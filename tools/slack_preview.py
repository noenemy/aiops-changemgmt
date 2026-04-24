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
    "summary": "재고 차감 로직에서 TOCTOU race condition이 감지됨. INC-0042와 동일 패턴으로 프로덕션 배포 차단 권장.",
    "code_block": (
        "# sample-app/src/handlers/create_order.py\n"
        "    inventory = table.get_item(Key={'productId': product_id})\n"
        "    stock = inventory['Item']['stockCount']\n"
        "    if stock < quantity:\n"
        "        return {'error': 'out of stock'}\n"
        "-   table.update_item(\n"
        "-       Key={'productId': product_id},\n"
        "-       UpdateExpression='SET stockCount = stockCount - :q',\n"
        "-       ConditionExpression='stockCount >= :q',\n"
        "-       ExpressionAttributeValues={':q': quantity},\n"
        "-   )\n"
        "+   table.update_item(\n"
        "+       Key={'productId': product_id},\n"
        "+       UpdateExpression='SET stockCount = stockCount - :q',\n"
        "+       ExpressionAttributeValues={':q': quantity},\n"
        "+   )\n"
        "    process_payment(order)  # TODO: implement"
    ),
    "issues": [
        {
            "severity": "CRITICAL",
            "title": "TOCTOU Race Condition",
            "line_range": "create_order.py L42-48",
            "code": (
                "table.update_item(\n"
                "    Key={'productId': product_id},\n"
                "    UpdateExpression='SET stockCount = stockCount - :q',\n"
                "    ExpressionAttributeValues={':q': quantity},\n"
                ")  # ConditionExpression 제거됨"
            ),
            "why": "get_item 후 update_item 사이 동시 요청이 들어오면 stockCount가 음수가 됨. Overselling 유발.",
            "fix": "ConditionExpression='stockCount >= :q' 를 복원하고 ConditionalCheckFailedException을 잡아 재시도.",
        },
        {
            "severity": "HIGH",
            "title": "결제 실패 보상 트랜잭션 없음",
            "line_range": "create_order.py L61",
            "code": "process_payment(order)  # TODO: implement",
            "why": "order 생성 후 결제 실패 시 재고가 복구되지 않고 주문이 CONFIRMED로 남음.",
            "fix": "",
        },
    ],
    "incident_match": "INC-0042 (2026-01-15, P1, 2시간 다운타임, ₩12M 매출 손실)",
    "incident_code": (
        "# INC-0042 당시 동일 패턴\n"
        "table.update_item(\n"
        "    Key={'productId': pid},\n"
        "    UpdateExpression='SET stockCount = stockCount - :q',\n"
        "    ExpressionAttributeValues={':q': qty},\n"
        ")"
    ),
    "developer_pattern": "sk88ee: 최근 3 PR 중 2건 REJECT (보안/안정성 반복).",
    "infra_impact": "",
    "agent_persona": "CodeReviewer → RiskJudge",
}

VERDICT_LABELS = {
    "APPROVE": "✅ CI/CD 자동 실행",
    "REJECT":  "🚫 CI/CD 파이프라인 스킵",
}
RISK_EMOJI = {"LOW": "🟢", "MEDIUM": "🟡", "HIGH": "🔴", "CRITICAL": "🔴"}
CHANGE_TYPE_LABEL = {"code": "코드 리뷰", "iac": "인프라 변경", "mixed": "코드 + 인프라"}
SEVERITY_EMOJI = {"CRITICAL": "🔴", "HIGH": "🟠", "MEDIUM": "🟡", "LOW": "🟢"}


def _risk_bar(score: int) -> str:
    s = int(score or 0)
    filled = max(0, min(10, round(s / 10)))
    if s >= 81:
        box = "🟥"
    elif s >= 51:
        box = "🟧"
    elif s >= 21:
        box = "🟨"
    else:
        box = "🟩"
    return box * filled + "⬜" * (10 - filled)


def build_ctx(overrides: dict) -> dict:
    ctx = {**SAMPLE, **overrides}
    ctx.setdefault("risk_emoji", RISK_EMOJI.get(ctx["risk_level"], "⚪"))
    ctx.setdefault("risk_bar", _risk_bar(ctx.get("risk_score", 0)))
    ctx.setdefault("verdict_label", VERDICT_LABELS.get(ctx["verdict"], "—"))
    ctx.setdefault("change_type_label", CHANGE_TYPE_LABEL.get(ctx["change_type"], "변경"))
    ctx.setdefault("timestamp", datetime.now(timezone.utc).isoformat(timespec="seconds"))
    # Enrich issues with severity_emoji
    issues = ctx.get("issues") or []
    if isinstance(issues, str):
        try:
            issues = json.loads(issues)
        except Exception:
            issues = []
    for it in issues:
        if isinstance(it, dict):
            it.setdefault("severity_emoji", SEVERITY_EMOJI.get((it.get("severity") or "").upper(), "⚪"))
    ctx["issues"] = issues
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
