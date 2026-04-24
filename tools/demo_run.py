"""Create the demo PR for a given scenario via GitHub REST API.

`demo.sh run <id>` relies on the `gh` CLI. This script does the same thing
(check for an existing open PR on the scenario branch, open a new one if not)
without `gh`, so the demo-console live-mode stream works in any environment
that has AWS creds for the `new-account` profile — the GitHub token is pulled
from Secrets Manager just like the other backend tools.

Usage:
  python3 tools/demo_run.py run <scenario_id>
  python3 tools/demo_run.py reset <scenario_id>
  python3 tools/demo_run.py list

Output is line-based plain text so the Next.js SSE stream can render each line
incrementally. No colour codes — the frontend classifies tone from text.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from typing import Optional

import boto3

REPO = os.environ.get("GITHUB_REPO", "noenemy/aiops-changemgmt")
SECRET_ID = os.environ.get(
    "GITHUB_TOKEN_SECRET_ARN",
    "arn:aws:secretsmanager:us-east-1:336093158955:secret:aiops-changemgmt-infra/github-token-j7z4D5",
)

# Mirror of demo.sh SCENARIOS — keep ids/branches in sync.
SCENARIOS = {
    "l1": ("demo/i18n-messages",        "feat: API 응답 메시지 한국어 지원"),
    "l2": ("demo/structured-logging",   "refactor: 구조화 로깅 적용 및 request_id 추가"),
    "h1": ("demo/payment-integration",  "feat: 외부 결제 서비스 연동"),
    "h2": ("demo/api-cleanup",          "refactor: API 응답 필드명 컨벤션 통일"),
    "h3": ("demo/order-enrichment",     "feat: 주문 목록에 상품 상세 정보 포함"),
    "h4": ("demo/checkout-feature",     "feat: 주문 생성 시 재고 차감 및 결제 처리"),
    "i1": ("demo/infra-tagging",        "chore(infra): 거버넌스 태그 + 로그 보존 90일"),
    "i2": ("demo/sg-egress-tightening", "feat(infra): Lambda 보안그룹 egress를 내부 CIDR로 제한"),
}


def _log(msg: str) -> None:
    # Flush immediately so the SSE stream sees each line without buffering.
    print(msg, flush=True)


def _gh_token() -> str:
    profile = os.environ.get("AWS_PROFILE", "new-account")
    region = os.environ.get("AWS_REGION", "us-east-1")
    session = boto3.Session(profile_name=profile, region_name=region)
    value = session.client("secretsmanager").get_secret_value(SecretId=SECRET_ID)["SecretString"]
    if value == "placeholder" or not value:
        raise SystemExit("GitHub token not injected into Secrets Manager.")
    return value


def _gh(path: str, token: str, method: str = "GET",
        body: Optional[dict] = None) -> dict | list:
    req = urllib.request.Request(
        f"https://api.github.com{path}",
        data=json.dumps(body).encode() if body else None,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github.v3+json",
            "Content-Type": "application/json",
            "User-Agent": "AIOps-DemoConsole-Runner",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read() or b"null")
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf8", errors="replace")
        raise SystemExit(f"GitHub API {e.code} on {method} {path}: {detail}") from e


def _open_pr_for_branch(branch: str, token: str) -> Optional[dict]:
    items = _gh(f"/repos/{REPO}/pulls?head={REPO.split('/')[0]}:{branch}&state=open",
                token)
    if isinstance(items, list) and items:
        return items[0]
    return None


def _trigger_analysis(pr_number: int) -> None:
    """Invoke the analysis Lambda directly, same payload as the webhook would.

    Mirrors `make trigger PR=<n>` — we don't rely on GitHub actually firing
    the webhook because repo-level hooks are outside our control in the demo
    environment. This is the path that consistently reaches AgentCore.
    """
    profile = os.environ.get("AWS_PROFILE", "new-account")
    region = os.environ.get("AWS_REGION", "us-east-1")
    session = boto3.Session(profile_name=profile, region_name=region)

    token = _gh_token()
    pr_raw = _gh(f"/repos/{REPO}/pulls/{pr_number}", token)
    assert isinstance(pr_raw, dict)
    payload = {
        "pr_number": pr_raw["number"],
        "pr_title": pr_raw["title"],
        "pr_author": pr_raw["user"]["login"],
        "pr_url": pr_raw["html_url"],
        "head_branch": pr_raw["head"]["ref"],
        "base_branch": pr_raw["base"]["ref"],
        "repo_full_name": pr_raw["base"]["repo"]["full_name"],
        "command": "",
        "reason": "",
        "actor": "demo-console",
    }
    fn = os.environ.get("ANALYSIS_FUNCTION_NAME", "aiops-changemgmt-infra-analysis")
    session.client("lambda").invoke(
        FunctionName=fn,
        InvocationType="Event",
        Payload=json.dumps(payload).encode(),
    )


def cmd_run(scenario_id: str) -> int:
    if scenario_id not in SCENARIOS:
        _log(f"✗ Unknown scenario: {scenario_id}")
        return 2
    branch, title = SCENARIOS[scenario_id]

    _log(f"Creating PR for scenario: {scenario_id}")
    _log(f"  Branch: {branch}")
    _log(f"  Title:  {title}")

    token = _gh_token()

    existing = _open_pr_for_branch(branch, token)
    if existing:
        _log(f"⚠ PR #{existing['number']} already open for {branch}. Reset first.")
        _log(f"  {existing['html_url']}")
        return 1

    body_md = (
        "## 변경 사항\n"
        f"데모 시나리오 {scenario_id}에 해당하는 코드 변경입니다.\n\n"
        "> 이 PR은 AI Agent가 자동으로 분석합니다."
    )
    created = _gh(
        f"/repos/{REPO}/pulls",
        token,
        method="POST",
        body={"title": title, "head": branch, "base": "main", "body": body_md},
    )
    if not isinstance(created, dict):
        _log("✗ PR 생성 실패: 예상치 못한 응답 형식")
        return 1
    pr_number = created["number"]
    _log(f"✓ PR #{pr_number} 생성")
    _log(f"  {created['html_url']}")
    _log("")
    _log("→ Analysis Lambda 트리거 (make trigger 경로와 동일)...")
    try:
        _trigger_analysis(pr_number)
        _log("✓ AgentCore Runtime 호출 시작 (async)")
    except Exception as e:
        _log(f"⚠ analysis 트리거 실패: {e}")
        return 1
    _log("  (CloudWatch logs: /aws/lambda/aiops-changemgmt-infra-analysis)")
    _log("  분석에는 약 90~120초가 걸립니다. Slack 채널에서 결과를 확인하세요.")
    return 0


def cmd_reset(scenario_id: str) -> int:
    if scenario_id not in SCENARIOS:
        _log(f"✗ Unknown scenario: {scenario_id}")
        return 2
    branch, _ = SCENARIOS[scenario_id]
    token = _gh_token()
    pr = _open_pr_for_branch(branch, token)
    if not pr:
        _log(f"No open PR for {branch}. Already clean.")
        return 0
    _gh(
        f"/repos/{REPO}/pulls/{pr['number']}",
        token,
        method="PATCH",
        body={"state": "closed"},
    )
    _log(f"✓ PR #{pr['number']} 닫힘. 시나리오 {scenario_id} 재시연 가능.")
    return 0


def cmd_list() -> int:
    token = _gh_token()
    for sid, (branch, title) in SCENARIOS.items():
        pr = _open_pr_for_branch(branch, token)
        if pr:
            _log(f"  {sid:<4} {branch:<30} PR #{pr['number']} open — {title}")
        else:
            _log(f"  {sid:<4} {branch:<30} ready              — {title}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)

    p_run = sub.add_parser("run")
    p_run.add_argument("scenario_id")

    p_reset = sub.add_parser("reset")
    p_reset.add_argument("scenario_id")

    sub.add_parser("list")

    args = p.parse_args()
    if args.cmd == "run":
        return cmd_run(args.scenario_id)
    if args.cmd == "reset":
        return cmd_reset(args.scenario_id)
    if args.cmd == "list":
        return cmd_list()
    return 0


if __name__ == "__main__":
    sys.exit(main())
