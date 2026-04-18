"""slack_tools Lambda — Slack report posting.

Tools:
  post_slack_report(report_json) -> ack string

Template files are packaged under ./slack_templates/ at build time.
"""

import json
import os
import urllib.request
from datetime import datetime, timezone

from common import claim_dedup, err, get_secret, ok, parse_event
from slack_templates._renderer import render_template

SLACK_TOKEN_SECRET_ARN = os.environ["SLACK_TOKEN_SECRET_ARN"]
SLACK_CHANNEL_ID = os.environ["SLACK_CHANNEL_ID"]


def _risk_emoji(level: str) -> str:
    return {"LOW": "🟢", "MEDIUM": "🟡", "HIGH": "🔴", "CRITICAL": "🔴"}.get(level, "⚪")


def _change_type_label(ct: str) -> str:
    return {"code": "코드 리뷰", "iac": "인프라 변경", "mixed": "코드 + 인프라"}.get(ct, "변경")


_KNOWN_TEMPLATES = {"code_review", "infra_review", "command_analysis",
                    "command_reject", "command_fix"}


def post_slack_report(report_json: str) -> str:
    ctx = json.loads(report_json) if isinstance(report_json, str) else report_json

    template = ctx.get("template")
    if template not in _KNOWN_TEMPLATES:
        ct = ctx.get("change_type", "code")
        template = "infra_review" if ct in ("iac", "mixed") else "code_review"

    ctx.setdefault("risk_emoji", _risk_emoji(ctx.get("risk_level", "LOW")))
    ctx.setdefault("verdict_label",
                   "✅ CI/CD 자동 실행" if ctx.get("verdict") == "APPROVE" else "🚫 CI/CD 파이프라인 스킵")
    ctx.setdefault("change_type_label", _change_type_label(ctx.get("change_type", "code")))
    ctx.setdefault("timestamp", datetime.now(timezone.utc).isoformat(timespec="seconds"))

    blocks = render_template(template, ctx)
    slack_token = get_secret(SLACK_TOKEN_SECRET_ARN)
    payload = json.dumps({
        "channel": SLACK_CHANNEL_ID,
        "blocks": blocks,
        "text": f"PR #{ctx.get('pr_number')} 분석 완료 — Risk {ctx.get('risk_score')}/100",
    }).encode()

    req = urllib.request.Request(
        "https://slack.com/api/chat.postMessage",
        data=payload, method="POST",
        headers={
            "Authorization": f"Bearer {slack_token}",
            "Content-Type": "application/json; charset=utf-8",
        },
    )
    resp = urllib.request.urlopen(req)
    result = json.loads(resp.read())
    if not result.get("ok"):
        raise RuntimeError(f"Slack API error: {result.get('error')}")
    return f"Slack report posted (ts={result.get('ts')})"


TOOLS = {
    "post_slack_report": lambda a: post_slack_report(a["report_json"]),
}


def handler(event, context):
    print(f"slack-tools event={json.dumps(event, default=str)[:800]}")
    try:
        cc = getattr(context, "client_context", None)
        print(f"slack-tools client_context.custom={getattr(cc, 'custom', None)}")
    except Exception as exc:
        print(f"slack-tools ctx read err: {exc}")
    tool, args, session_id = parse_event(event, context)
    print(f"slack-tools parsed tool={tool!r} session={session_id!r} args_keys={list(args.keys()) if isinstance(args, dict) else type(args)}")
    fn = TOOLS.get(tool)
    if fn is None:
        return err(f"Unknown tool: {tool}")
    if tool == "post_slack_report":
        # Derive a fallback dedup key from the PR number in the report payload
        # (Gateway doesn't pass the Runtime sessionId through).
        pr_num = ""
        try:
            import json as _json
            pr_num = str(_json.loads(args.get("report_json", "{}")).get("pr_number", ""))
        except Exception:
            pass
        dedup_key = session_id or f"pr{pr_num or '?'}"
        if not claim_dedup(dedup_key, tool):
            return ok("Slack report already posted (dedup skip)")
    try:
        return ok(fn(args))
    except KeyError as e:
        return err(f"Missing arg: {e}")
    except Exception as e:
        import traceback
        print(f"slack-tools error: {e}\n{traceback.format_exc()[:1500]}")
        return err(f"Tool error: {e}", code=500)
