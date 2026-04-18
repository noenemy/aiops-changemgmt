"""Render a Slack template locally with sample data, optionally post it.

Goal: iterate on slack_templates/*.json + sections/*.json without redeploying
the slack-tools Lambda every time. `make slack-preview TEMPLATE=code_review`
prints the rendered blocks JSON; `make slack-post` actually posts it to Slack.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "agent"))
from slack_templates._renderer import render_template  # noqa: E402

SAMPLE = {
    "pr_number": 9,
    "pr_title": "feat: 주문 생성 시 재고 차감 및 결제 처리",
    "pr_author": "sk88ee",
    "pr_url": "https://github.com/noenemy/aiops-changemgmt/pull/9",
    "change_type": "code",
    "risk_score": 85,
    "risk_level": "CRITICAL",
    "verdict": "REJECT",
    "summary": "TOCTOU race condition이 감지되었습니다. INC-0042와 동일 패턴. 프로덕션 배포 차단 권장.",
    "issues_text": "🔴 *CRITICAL*: `get_item` 후 `update_item` 사이 race condition\n🟡 *MEDIUM*: 보상 트랜잭션 없음",
    "incident_match": "INC-0042 (2026-01-15, P1, 2시간 다운타임, ₩12M 매출 손실)",
    "developer_pattern": "dev-ethan: 최근 3 PR 중 2건 REJECT (보안·안정성)",
    "infra_impact": "",
    "agent_persona": "CodeReviewer → RiskJudge",
}

VERDICT_LABELS = {
    "APPROVE": "✅ CI/CD 자동 실행",
    "REJECT":  "🚫 CI/CD 파이프라인 스킵",
}
RISK_EMOJI = {"LOW": "🟢", "MEDIUM": "🟡", "HIGH": "🔴", "CRITICAL": "🔴"}
CHANGE_TYPE_LABEL = {"code": "코드 리뷰", "iac": "인프라 변경", "mixed": "코드 + 인프라"}


def build_ctx(overrides: dict) -> dict:
    ctx = {**SAMPLE, **overrides}
    ctx.setdefault("risk_emoji", RISK_EMOJI.get(ctx["risk_level"], "⚪"))
    ctx.setdefault("verdict_label", VERDICT_LABELS.get(ctx["verdict"], "—"))
    ctx.setdefault("change_type_label", CHANGE_TYPE_LABEL.get(ctx["change_type"], "변경"))
    ctx.setdefault("timestamp", datetime.now(timezone.utc).isoformat(timespec="seconds"))
    return ctx


def post_to_slack(blocks: list, fallback_text: str, channel: str,
                  profile: str, region: str) -> None:
    import boto3
    session = boto3.Session(profile_name=profile, region_name=region)
    cfn = session.client("cloudformation")
    outs = cfn.describe_stacks(StackName="aiops-changemgmt-infra")["Stacks"][0]["Outputs"]
    out_map = {o["OutputKey"]: o["OutputValue"] for o in outs}
    secret_arn = out_map["SlackBotTokenSecretArn"]
    token = session.client("secretsmanager").get_secret_value(SecretId=secret_arn)["SecretString"]
    if token == "placeholder":
        raise SystemExit("Slack bot token not injected. Put the real value into the secret.")

    req = urllib.request.Request(
        "https://slack.com/api/chat.postMessage",
        data=json.dumps({"channel": channel, "blocks": blocks, "text": fallback_text}).encode(),
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
        },
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        result = json.loads(resp.read())
    if not result.get("ok"):
        raise SystemExit(f"Slack API error: {result}")
    print(f"Posted: ts={result['ts']}")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--template", default="code_review",
                   help="code_review | infra_review | command_analysis | command_reject | command_fix")
    p.add_argument("--overrides", help='JSON of extra context, e.g. \'{"risk_score":10,"risk_level":"LOW","verdict":"APPROVE"}\'')
    p.add_argument("--post", action="store_true", help="Send to the Slack channel instead of just printing")
    p.add_argument("--channel", default="C0ASW5X99E1")
    p.add_argument("--profile", default=os.environ.get("AWS_PROFILE", "new-account"))
    p.add_argument("--region", default="us-east-1")
    args = p.parse_args()

    overrides = json.loads(args.overrides) if args.overrides else {}
    ctx = build_ctx(overrides)
    blocks = render_template(args.template, ctx)

    if args.post:
        post_to_slack(blocks, f"[preview] PR #{ctx['pr_number']} {ctx['risk_level']}",
                      args.channel, args.profile, args.region)
    else:
        print(json.dumps(blocks, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
