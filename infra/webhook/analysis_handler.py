"""Analysis orchestrator.

Routes:
  - GitHub Webhook (PR opened/synchronized) → Agent full pipeline
  - Slack Slash Commands:
      command=analysis → Agent full pipeline (same as webhook)
      command=reject   → skip Agent, post GitHub comment + Slack msg directly
      command=fix      → Agent Fix pipeline (get history + diff → fix suggestion)

Full KB + Memory + tool-based analysis runs inside the Bedrock Agent (see agent/).
This Lambda only bridges transport and handles lightweight command branches.

Fallback: if BEDROCK_AGENT_ID == "none" or invoke_agent fails, a direct Bedrock
model call with a simple prompt is used (minimal, no DDB/KB lookup here — those
are the Agent's job).
"""

import json
import logging
import os
import urllib.request
from datetime import datetime, timezone

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

secrets_client = boto3.client("secretsmanager")
bedrock_agent_runtime = boto3.client("bedrock-agent-runtime")
bedrock_runtime = boto3.client("bedrock-runtime")

GITHUB_TOKEN_SECRET_ARN = os.environ["GITHUB_TOKEN_SECRET_ARN"]
SLACK_TOKEN_SECRET_ARN = os.environ["SLACK_TOKEN_SECRET_ARN"]
SLACK_CHANNEL_ID = os.environ["SLACK_CHANNEL_ID"]
GITHUB_REPO = os.environ["GITHUB_REPO"]
BEDROCK_AGENT_ID = os.environ["BEDROCK_AGENT_ID"]
BEDROCK_AGENT_ALIAS_ID = os.environ["BEDROCK_AGENT_ALIAS_ID"]
BEDROCK_MODEL_ID = os.environ["BEDROCK_MODEL_ID"]

_secrets_cache = {}


def get_secret(arn: str) -> str:
    if arn not in _secrets_cache:
        _secrets_cache[arn] = secrets_client.get_secret_value(SecretId=arn)["SecretString"]
    return _secrets_cache[arn]


# ============================================================
# Agent invocation
# ============================================================

def _memory_id() -> str:
    return GITHUB_REPO.replace("/", "-")


def _session_id(prefix: str, pr_number: int) -> str:
    return f"{prefix}-pr{pr_number}-{datetime.now().strftime('%Y%m%d%H%M%S')}"


def invoke_agent_for_analysis(pr_data: dict) -> str:
    """Full PR analysis via Agent. Agent handles all tools, KB, Memory."""
    input_text = (
        f"PR #{pr_data['pr_number']}을 분석해주세요.\n"
        f"제목: {pr_data['pr_title']}\n"
        f"Author: {pr_data['pr_author']}\n"
        f"Branch: {pr_data['head_branch']} → {pr_data['base_branch']}\n"
        f"URL: {pr_data['pr_url']}\n\n"
        f"시스템 프롬프트에 정의된 오케스트레이션 순서(detect_change_type → "
        f"get_pr_diff/get_pr_files → Persona 분석 → queryKnowledgeBase → "
        f"RiskJudge 종합 → post_github_comment → post_slack_report)를 따라주세요.\n\n"
        f"Slack report_json에는 pr_url로 {pr_data['pr_url']}을 반드시 포함하세요."
    )
    return _invoke_agent(input_text, _session_id("analysis", pr_data["pr_number"]))


def invoke_agent_for_fix(pr_data: dict) -> str:
    """Generate a fix suggestion for an existing PR."""
    input_text = (
        f"PR #{pr_data['pr_number']}의 기존 리뷰 이슈에 대해 구체적인 수정 제안을 생성해주세요.\n"
        f"제목: {pr_data['pr_title']}\n"
        f"Author: {pr_data['pr_author']}\n\n"
        f"절차:\n"
        f"1. get_review_history(files=...)로 이 PR에 대한 과거 리뷰 결과 조회\n"
        f"2. get_pr_diff로 현재 diff 재확인\n"
        f"3. 이슈별로 구체적 수정 코드 또는 단계를 한국어 마크다운으로 작성\n"
        f"4. post_github_comment로 PR에 제안 게시 — 본문 시작에 반드시 "
        f"'## 🔧 AI Fix Suggestion' 헤더를 붙여 일반 리뷰와 구분\n"
        f"5. post_slack_report에 template='command_fix', summary=수정 제안 요약, "
        f"pr_url={pr_data['pr_url']}, actor={pr_data.get('actor','')} 로 Slack 알림\n"
    )
    return _invoke_agent(input_text, _session_id("fix", pr_data["pr_number"]))


def _invoke_agent(input_text: str, session_id: str) -> str:
    memory_id = _memory_id()
    logger.info(f"Invoking Agent: session={session_id}, memory={memory_id}")

    response = bedrock_agent_runtime.invoke_agent(
        agentId=BEDROCK_AGENT_ID,
        agentAliasId=BEDROCK_AGENT_ALIAS_ID,
        sessionId=session_id,
        memoryId=memory_id,
        inputText=input_text,
    )
    completion = ""
    for event in response["completion"]:
        if "chunk" in event:
            completion += event["chunk"]["bytes"].decode()
    logger.info(f"Agent response: {completion[:500]}")

    # Close session → triggers SESSION_SUMMARY
    try:
        bedrock_agent_runtime.invoke_agent(
            agentId=BEDROCK_AGENT_ID,
            agentAliasId=BEDROCK_AGENT_ALIAS_ID,
            sessionId=session_id,
            memoryId=memory_id,
            inputText="세션 종료",
            endSession=True,
        )
    except Exception:
        pass

    return completion


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

    # --- Slack /fix — Agent Fix pipeline ---
    if command == "fix":
        if BEDROCK_AGENT_ID == "none":
            return {"status": "error", "message": "Fix requires Agent (BEDROCK_AGENT_ID=none)"}
        try:
            invoke_agent_for_fix(event)
            return {"pr_number": pr_number, "status": "fix_completed"}
        except Exception as e:
            logger.error(f"Fix pipeline failed: {e}", exc_info=True)
            return {"status": "error", "message": str(e)}

    # --- Webhook event OR /analysis — full analysis via Agent ---
    if BEDROCK_AGENT_ID != "none":
        try:
            invoke_agent_for_analysis(event)
            return {"pr_number": pr_number, "status": "agent_completed"}
        except Exception as e:
            logger.warning(f"Agent path failed, falling back: {e}", exc_info=True)

    # Fallback
    try:
        return fallback_direct(event)
    except Exception as e:
        logger.error(f"Fallback failed: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}
