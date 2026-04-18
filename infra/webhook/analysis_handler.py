"""Analysis orchestrator.

Routes:
  - GitHub Webhook (PR opened/synchronized) → AgentCore Runtime full pipeline
  - Slack Slash Commands:
      command=analysis → AgentCore Runtime full pipeline (same as webhook)
      command=reject   → skip Agent, post GitHub comment + Slack msg directly
      command=fix      → AgentCore Runtime Fix pipeline

All tools / KB / Memory run inside the AgentCore Runtime (see agent/runtime/).
This Lambda only bridges transport and handles lightweight command branches.

Fallback: if AGENT_RUNTIME_ARN == "none" or InvokeAgentRuntime fails, a direct
Bedrock model call with a simple prompt is used (no KB/DDB lookup).
"""

import json
import logging
import os
import urllib.request
from datetime import datetime, timezone

import boto3
from botocore.config import Config

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Runtime invocations take 80-120s on a full pipeline. Raise read timeout
# well above that so boto3 doesn't retry mid-flight and trigger duplicate
# same-sessionId executions.
_long_cfg = Config(read_timeout=295, connect_timeout=10, retries={"max_attempts": 1})

secrets_client = boto3.client("secretsmanager")
bedrock_agentcore = boto3.client("bedrock-agentcore", config=_long_cfg)
bedrock_runtime = boto3.client("bedrock-runtime")

GITHUB_TOKEN_SECRET_ARN = os.environ["GITHUB_TOKEN_SECRET_ARN"]
SLACK_TOKEN_SECRET_ARN = os.environ["SLACK_TOKEN_SECRET_ARN"]
SLACK_CHANNEL_ID = os.environ["SLACK_CHANNEL_ID"]
GITHUB_REPO = os.environ["GITHUB_REPO"]
AGENT_RUNTIME_ARN = os.environ["AGENT_RUNTIME_ARN"]
BEDROCK_MODEL_ID = os.environ["BEDROCK_MODEL_ID"]

_secrets_cache = {}


def get_secret(arn: str) -> str:
    if arn not in _secrets_cache:
        _secrets_cache[arn] = secrets_client.get_secret_value(SecretId=arn)["SecretString"]
    return _secrets_cache[arn]


# ============================================================
# AgentCore Runtime invocation
# ============================================================

def _session_id(pr_number: int) -> str:
    repo_tag = GITHUB_REPO.replace("/", "-")
    return f"pr-{repo_tag}-{pr_number}-{datetime.now().strftime('%Y%m%d%H%M%S')}"


def invoke_runtime_for_analysis(pr_data: dict) -> str:
    payload = {
        "command": "analysis",
        "pr_number": pr_data["pr_number"],
        "repo": GITHUB_REPO,
        "pr_title": pr_data.get("pr_title", ""),
        "pr_author": pr_data.get("pr_author", ""),
        "pr_url": pr_data.get("pr_url", ""),
        "head_branch": pr_data.get("head_branch", ""),
        "base_branch": pr_data.get("base_branch", ""),
    }
    return _invoke_runtime(payload, _session_id(pr_data["pr_number"]))


def invoke_runtime_for_fix(pr_data: dict) -> str:
    payload = {
        "command": "fix",
        "pr_number": pr_data["pr_number"],
        "repo": GITHUB_REPO,
        "pr_title": pr_data.get("pr_title", ""),
        "pr_author": pr_data.get("pr_author", ""),
        "pr_url": pr_data.get("pr_url", ""),
        "actor": pr_data.get("actor", ""),
    }
    return _invoke_runtime(payload, _session_id(pr_data["pr_number"]))


def _invoke_runtime(payload: dict, session_id: str) -> str:
    logger.info(f"Invoking AgentCore Runtime: session={session_id}, arn={AGENT_RUNTIME_ARN}")
    resp = bedrock_agentcore.invoke_agent_runtime(
        agentRuntimeArn=AGENT_RUNTIME_ARN,
        runtimeSessionId=session_id,
        payload=json.dumps(payload).encode(),
    )
    body = resp.get("response")
    if hasattr(body, "read"):
        body = body.read()
    if isinstance(body, (bytes, bytearray)):
        body = body.decode()
    logger.info(f"Runtime response: {str(body)[:500]}")
    return str(body)


# ============================================================
# /reject (no Agent — direct posting)
# ============================================================

def handle_reject(pr_data: dict) -> dict:
    pr_number = pr_data["pr_number"]
    reason = pr_data.get("reason", "") or "수동 거부 (사유 미기재)"
    actor = pr_data.get("actor", "unknown")

    github_token = get_secret(GITHUB_TOKEN_SECRET_ARN)
    slack_token = get_secret(SLACK_TOKEN_SECRET_ARN)

    # GitHub comment
    comment = (
        f"## 🚫 수동 REJECT\n\n"
        f"이 PR은 `@{actor}`에 의해 수동으로 거부되었습니다.\n\n"
        f"### 사유\n{reason}\n\n"
        f"---\n*Issued via `/reject` Slack command*"
    )
    _post_github_comment(pr_number, comment, github_token)

    # Slack notification (command_reject template rendered by Action Group Lambda)
    # We POST directly here to avoid invoking Agent just for a notice.
    blocks = [
        {"type": "header", "text": {"type": "plain_text",
                                    "text": f"🚫 수동 REJECT — PR #{pr_number}"}},
        {"type": "section", "fields": [
            {"type": "mrkdwn", "text": f"*PR:* <{pr_data['pr_url']}|{pr_data['pr_title']}>"},
            {"type": "mrkdwn", "text": f"*Rejected by:* {actor}"},
        ]},
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*사유:*\n{reason}"}},
        {"type": "divider"},
        {"type": "context", "elements": [
            {"type": "mrkdwn",
             "text": f"🤖 RiskJudge · {datetime.now(timezone.utc).isoformat(timespec='seconds')}"}
        ]},
    ]
    _post_slack(blocks, f"PR #{pr_number} REJECT by {actor}", slack_token)

    return {"pr_number": pr_number, "status": "rejected", "actor": actor}


def _post_github_comment(pr_number: int, body: str, token: str):
    url = f"https://api.github.com/repos/{GITHUB_REPO}/issues/{pr_number}/comments"
    data = json.dumps({"body": body}).encode()
    req = urllib.request.Request(url, data=data, method="POST", headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github.v3+json",
        "Content-Type": "application/json",
        "User-Agent": "AIOps-ChangeManagement",
    })
    urllib.request.urlopen(req)


def _post_slack(blocks: list, fallback: str, token: str):
    payload = json.dumps({
        "channel": SLACK_CHANNEL_ID,
        "blocks": blocks,
        "text": fallback,
    }).encode()
    req = urllib.request.Request(
        "https://slack.com/api/chat.postMessage",
        data=payload, method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
        },
    )
    resp = urllib.request.urlopen(req)
    result = json.loads(resp.read())
    if not result.get("ok"):
        logger.error(f"Slack API error: {result.get('error')}")


# ============================================================
# Fallback (Agent unavailable) — minimal direct model call
# ============================================================

def fallback_direct(pr_data: dict) -> dict:
    logger.warning("Fallback path: direct Bedrock model call (no KB, no tools)")
    github_token = get_secret(GITHUB_TOKEN_SECRET_ARN)

    # Fetch diff minimally
    diff_url = f"https://api.github.com/repos/{GITHUB_REPO}/pulls/{pr_data['pr_number']}"
    req = urllib.request.Request(diff_url, headers={
        "Authorization": f"Bearer {github_token}",
        "Accept": "application/vnd.github.v3.diff",
        "User-Agent": "AIOps-ChangeManagement",
    })
    with urllib.request.urlopen(req) as resp:
        diff = resp.read().decode()[:10000]

    prompt = (
        f"PR #{pr_data['pr_number']}: {pr_data['pr_title']}\n"
        f"Author: {pr_data['pr_author']}\n\n"
        f"## Diff\n```\n{diff}\n```\n\n"
        f"JSON 형식으로 응답: "
        f'{{"risk_score": <0-100>, "risk_level": "LOW|MEDIUM|HIGH|CRITICAL", '
        f'"verdict": "APPROVE|REJECT", "summary": "<한국어>"}}'
    )
    body = json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 2048,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1,
    })
    resp = bedrock_runtime.invoke_model(
        modelId=BEDROCK_MODEL_ID,
        contentType="application/json",
        accept="application/json",
        body=body,
    )
    result = json.loads(resp["body"].read())
    text = result["content"][0]["text"]
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0]
    elif "```" in text:
        text = text.split("```")[1].split("```")[0]
    analysis = json.loads(text.strip())

    # Post minimal GitHub comment
    emoji = {"LOW": "🟢", "MEDIUM": "🟡", "HIGH": "🔴", "CRITICAL": "🔴"}.get(
        analysis["risk_level"], "⚪"
    )
    verdict_label = "✅ CI/CD 자동 실행" if analysis["verdict"] == "APPROVE" else "🚫 CI/CD 스킵"
    comment = (
        f"## {emoji} AI Code Review (Fallback) — Risk {analysis['risk_score']}/100 "
        f"({analysis['risk_level']})\n\n"
        f"{analysis['summary']}\n\n"
        f"### 판정: {verdict_label}\n\n"
        f"---\n*⚠️ Agent unavailable — fallback direct model call*"
    )
    _post_github_comment(pr_data["pr_number"], comment, github_token)
    return {"pr_number": pr_data["pr_number"], "status": "fallback_completed",
            "risk_score": analysis["risk_score"]}


# ============================================================
# Main handler
# ============================================================

def handler(event, context):
    command = event.get("command", "")
    pr_number = event.get("pr_number", "?")
    logger.info(f"Handler invoked: command={command!r}, PR #{pr_number}")

    # --- Slack /reject — skip Agent ---
    if command == "reject":
        return handle_reject(event)

    # --- Slack /fix — AgentCore Fix pipeline ---
    if command == "fix":
        if AGENT_RUNTIME_ARN == "none":
            return {"status": "error", "message": "Fix requires Runtime (AGENT_RUNTIME_ARN=none)"}
        try:
            invoke_runtime_for_fix(event)
            return {"pr_number": pr_number, "status": "fix_completed"}
        except Exception as e:
            logger.error(f"Fix pipeline failed: {e}", exc_info=True)
            return {"status": "error", "message": str(e)}

    # --- Webhook event OR /analysis — full analysis via AgentCore Runtime ---
    if AGENT_RUNTIME_ARN != "none":
        try:
            invoke_runtime_for_analysis(event)
            return {"pr_number": pr_number, "status": "agent_completed"}
        except Exception as e:
            logger.warning(f"Runtime path failed, falling back: {e}", exc_info=True)

    # Fallback
    try:
        return fallback_direct(event)
    except Exception as e:
        logger.error(f"Fallback failed: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}
