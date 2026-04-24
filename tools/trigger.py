"""Manually trigger the analysis Lambda for a real GitHub PR.

Simulates what the webhook Lambda (on PR opened/sync) or the slack-command
Lambda (on /accept /rollback /investigate) would send. Bypasses API Gateway
+ signature checks.

Usage:
  python tools/trigger.py <command> <target> [--reason "..."] [--actor name]
                          [--sync] [--region us-east-1] [--profile new-account]

  <target> = PR number for webhook/accept/rollback,
             free-form prompt text for investigate.

Examples:
  # Full webhook-equivalent pipeline (Agent + KB + Slack post)
  python tools/trigger.py webhook 12

  # Slack /accept — APPROVE review + auto-merge (no Agent)
  python tools/trigger.py accept 12 --reason "보안 체크 끝, 수동 승인" --actor ethan

  # Slack /rollback — open a revert PR against a merged PR
  python tools/trigger.py rollback 12 --reason "프로덕션 이슈 감지"

  # Slack /investigate — free-form prompt forwarded to DevOps webhook
  python tools/trigger.py investigate "최근 배포된 것 중 문제가 있는지 분석해줘"

  # Wait for and print the Lambda response body (useful for debugging)
  python tools/trigger.py investigate "Orders API p99 급등 원인" --sync
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import urllib.request

import boto3

FUNCTION_NAME = os.environ.get("ANALYSIS_FUNCTION_NAME", "aiops-changemgmt-infra-analysis")
DEFAULT_REPO = os.environ.get("GITHUB_REPO", "noenemy/aiops-changemgmt")


def fetch_pr_meta(session: boto3.Session, pr_number: int, repo: str) -> dict:
    """Read the PR metadata exactly like slack-command Lambda does."""
    secret_id = os.environ.get(
        "GITHUB_TOKEN_SECRET_ARN",
        "arn:aws:secretsmanager:us-east-1:336093158955:secret:aiops-changemgmt-infra/github-token-j7z4D5",
    )
    token = session.client("secretsmanager").get_secret_value(SecretId=secret_id)["SecretString"]
    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/pulls/{pr_number}",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "AIOps-ChangeManagement-Trigger",
        },
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        pr = json.loads(resp.read())
    return {
        "pr_number": pr["number"],
        "pr_title": pr["title"],
        "pr_author": pr["user"]["login"],
        "pr_url": pr["html_url"],
        "head_branch": pr["head"]["ref"],
        "base_branch": pr["base"]["ref"],
        "repo_full_name": pr["base"]["repo"]["full_name"],
        "merge_commit_sha": pr.get("merge_commit_sha") or "",
        "merged": bool(pr.get("merged")),
    }


def build_payload(command: str, pr_meta: dict, reason: str, actor: str) -> dict:
    """Match the shape slack-command / webhook Lambdas send."""
    # "webhook" is the same as Slack /analysis but with no explicit command field,
    # exactly like analysis_handler.handler treats an event with no `command` key.
    cmd_field = "" if command == "webhook" else command
    return {
        **pr_meta,
        "command": cmd_field,
        "reason": reason,
        "actor": actor,
    }


def invoke(session: boto3.Session, payload: dict, sync: bool) -> None:
    client = session.client("lambda")
    inv_type = "RequestResponse" if sync else "Event"
    resp = client.invoke(
        FunctionName=FUNCTION_NAME,
        InvocationType=inv_type,
        LogType="Tail" if sync else "None",
        Payload=json.dumps(payload).encode(),
    )
    print(f"Lambda invoked: status={resp['StatusCode']}")
    if sync:
        body = resp["Payload"].read().decode()
        print("--- Response body ---")
        print(body)
        if "LogResult" in resp:
            print("--- Tail logs ---")
            print(base64.b64decode(resp["LogResult"]).decode())
    else:
        print("Async invoke accepted. Agent pipeline runs in the background.")
        print("Tail logs with:")
        print(f"  aws logs tail /aws/lambda/{FUNCTION_NAME} --follow --profile {session.profile_name or 'default'} --region {session.region_name}")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("command",
                   choices=["webhook", "accept", "rollback", "investigate"],
                   help="webhook/accept/rollback = PR-scoped; investigate = free-form prompt")
    p.add_argument("target", nargs="?",
                   help="PR number (webhook/accept/rollback) or "
                        "free-form prompt (investigate)")
    p.add_argument("--reason", default="", help="Slack-command reason field")
    p.add_argument("--actor", default="trigger-script", help="Slack user substitute")
    p.add_argument("--repo", default=DEFAULT_REPO)
    p.add_argument("--sync", action="store_true", help="Wait for Lambda and print response")
    p.add_argument("--region", default="us-east-1")
    p.add_argument("--profile", default=os.environ.get("AWS_PROFILE", "new-account"))
    args = p.parse_args()

    session = boto3.Session(profile_name=args.profile, region_name=args.region)

    # /investigate doesn't reference a PR — the target arg is the prompt text.
    if args.command == "investigate":
        prompt = args.target or args.reason or ""
        if not prompt:
            p.error("investigate requires a prompt as the second argument")
        payload = {"command": "investigate", "prompt": prompt, "actor": args.actor}
        print(f"Invoking {FUNCTION_NAME} with command='investigate' ...")
        invoke(session, payload, args.sync)
        return 0

    if args.target is None:
        p.error(f"{args.command} requires a PR number")
    try:
        pr_number = int(args.target)
    except ValueError:
        p.error(f"PR number must be an int (got {args.target!r})")
    args.pr_number = pr_number

    print(f"Fetching PR metadata for {args.repo}#{args.pr_number} ...")
    pr_meta = fetch_pr_meta(session, args.pr_number, args.repo)
    print(f"  title  : {pr_meta['pr_title']}")
    print(f"  author : {pr_meta['pr_author']}")
    print(f"  branch : {pr_meta['head_branch']} -> {pr_meta['base_branch']}")

    payload = build_payload(args.command, pr_meta, args.reason, args.actor)
    print(f"\nInvoking {FUNCTION_NAME} with command={args.command!r} ...")
    invoke(session, payload, args.sync)
    return 0


if __name__ == "__main__":
    sys.exit(main())
