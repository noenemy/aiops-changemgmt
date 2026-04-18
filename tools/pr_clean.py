"""Delete all bot-authored comments from a PR (repeatable demo cleanup)."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request

import boto3

BOT_MARKERS = ("🤖 AIOps", "🔧 AI Fix", "🚫 수동 REJECT", "AIOps Change", "AIOps ChangeManagement")


def github_req(token: str, path: str, method: str = "GET", body: bytes | None = None) -> bytes:
    req = urllib.request.Request(
        f"https://api.github.com{path}",
        data=body, method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "aiops-cleaner",
        },
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.read()


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("pr_number", type=int)
    p.add_argument("--repo", default="noenemy/aiops-changemgmt")
    p.add_argument("--profile", default=os.environ.get("AWS_PROFILE", "new-account"))
    p.add_argument("--region", default="us-east-1")
    p.add_argument("--all", action="store_true", help="Delete every comment, not just bot ones")
    args = p.parse_args()

    session = boto3.Session(profile_name=args.profile, region_name=args.region)
    cfn = session.client("cloudformation")
    outs = cfn.describe_stacks(StackName="aiops-changemgmt-infra")["Stacks"][0]["Outputs"]
    secret_arn = next(o["OutputValue"] for o in outs if o["OutputKey"] == "GitHubTokenSecretArn")
    token = session.client("secretsmanager").get_secret_value(SecretId=secret_arn)["SecretString"]
    if token == "placeholder":
        raise SystemExit("GitHub token not injected")

    comments = json.loads(github_req(token, f"/repos/{args.repo}/issues/{args.pr_number}/comments"))
    print(f"PR #{args.pr_number} — {len(comments)} comments total")
    to_delete = [c for c in comments
                 if args.all or any(m in c["body"] for m in BOT_MARKERS)]
    print(f"Matching bot comments to delete: {len(to_delete)}")
    for c in to_delete:
        github_req(token, f"/repos/{args.repo}/issues/comments/{c['id']}", method="DELETE")
        print(f"  deleted id={c['id']} ({c['created_at']})")
    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
