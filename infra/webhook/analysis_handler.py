"""Analysis orchestrator.

Routes:
  - GitHub Webhook (PR opened/synchronized) → AgentCore Runtime full pipeline
  - Slack Slash Commands:
      command=accept       → GitHub APPROVE review + auto-merge + Slack notice (no Agent)
      command=rollback     → open a revert PR against the target PR's merge commit + Slack notice
      command=investigate  → forward the free-form prompt to the DevOps webhook
                             (no PR lookup, no Runtime)

All tools / KB / Memory run inside the AgentCore Runtime (see agent/runtime/).
This Lambda only bridges transport and handles lightweight command branches.

Fallback: if AGENT_RUNTIME_ARN == "none" or InvokeAgentRuntime fails, a direct
Bedrock model call with a simple prompt is used (no KB/DDB lookup).
"""

import base64
import hashlib
import hmac
import json
import logging
import os
import time
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

# DevOps investigation webhook (fire-and-forget). "none" means unset.
_dv_url = os.environ.get("DEVOPS_WEBHOOK_URL", "")
_dv_sec = os.environ.get("DEVOPS_WEBHOOK_SECRET", "")
DEVOPS_WEBHOOK_URL = "" if _dv_url in ("", "none") else _dv_url
DEVOPS_WEBHOOK_SECRET = "" if _dv_sec in ("", "none") else _dv_sec

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


def _post_devops_webhook(prompt: str, actor: str) -> dict:
    """Fire-and-forget call to the AIOps Investigation Groups webhook.

    Schema (confirmed):
      - Headers:  x-amzn-event-timestamp (ISO-8601 UTC ...Z)
                  x-amzn-event-signature (base64 HMAC-SHA256(secret, "<ts>:<body>"))
      - Body:     eventType:"incident", incidentId, action:"created", priority,
                  title, description, service, timestamp
    The remote side queues an investigation and posts its own updates to the
    Slack channel this webhook is wired to — we never see the investigation
    output here, only the acceptance ack.
    """
    ts = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
    iid = f"slack-investigate-{int(time.time())}"
    short = prompt if len(prompt) <= 80 else prompt[:77] + "…"
    body = json.dumps({
        "eventType": "incident",
        "incidentId": iid,
        "action": "created",
        "priority": "HIGH",
        "title": f"/investigate from {actor or 'unknown'}: {short}",
        "description": prompt,
        "service": "aiops-changemgmt",
        "timestamp": ts,
    }).encode()
    sig = base64.b64encode(
        hmac.new(DEVOPS_WEBHOOK_SECRET.encode(),
                 f"{ts}:{body.decode()}".encode(), hashlib.sha256).digest()
    ).decode()
    req = urllib.request.Request(
        DEVOPS_WEBHOOK_URL, data=body, method="POST",
        headers={
            "Content-Type": "application/json",
            "x-amzn-event-timestamp": ts,
            "x-amzn-event-signature": sig,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return {"status": resp.status,
                    "body": resp.read().decode("utf8", errors="replace")[:500],
                    "incident_id": iid}
    except Exception as e:
        return {"status": 0, "body": f"{type(e).__name__}: {e}",
                "incident_id": iid}


def handle_investigate(event: dict) -> dict:
    """Hand the free-form prompt to the DevOps webhook. No PR, no Runtime."""
    prompt = (event.get("prompt") or "").strip()
    actor = event.get("actor", "unknown")
    slack_token = get_secret(SLACK_TOKEN_SECRET_ARN)

    if not DEVOPS_WEBHOOK_URL or not DEVOPS_WEBHOOK_SECRET:
        _post_slack(
            [
                {"type": "header", "text": {"type": "plain_text",
                                            "text": "🔍 DevOps 조사 요청"}},
                {"type": "section", "text": {"type": "mrkdwn",
                                             "text": f"*요청자:* {actor}\n*질문:*\n{prompt}"}},
                {"type": "section", "text": {"type": "mrkdwn",
                                             "text": "⚠️ DevOps webhook 미연결 — DEVOPS_WEBHOOK_URL 확인 필요"}},
            ],
            f"/investigate from {actor}",
            slack_token,
        )
        return {"status": "error", "message": "DEVOPS_WEBHOOK_URL not configured"}

    result = _post_devops_webhook(prompt, actor)
    ok = 200 <= result["status"] < 300
    blocks = [
        {"type": "header", "text": {"type": "plain_text",
                                    "text": "🔍 DevOps 조사 요청 접수"}},
        {"type": "section",
         "text": {"type": "mrkdwn", "text": f"*요청자*  `{actor}`"}},
        {"type": "section",
         "text": {"type": "mrkdwn", "text": f"*질문*\n> {prompt}"}},
    ]
    if not ok:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn",
                     "text": f"❌ 전송 실패 (HTTP {result['status']}): {result['body']}"},
        })
    blocks.append({"type": "context", "elements": [
        {"type": "mrkdwn",
         "text": "조사 결과는 AI Ops Investigation Groups가 별도로 채널에 게시합니다."}
    ]})
    _post_slack(blocks, f"/investigate from {actor}", slack_token)
    return {"status": "investigate_dispatched", "result": result}


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
# GitHub REST helpers
# ============================================================

def _gh(path: str, token: str, method: str = "GET", body: dict | None = None,
        media_type: str = "application/vnd.github.v3+json") -> dict | list | str:
    url = f"https://api.github.com{path}"
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode() if body else None,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": media_type,
            "Content-Type": "application/json",
            "User-Agent": "AIOps-ChangeManagement",
        },
    )
    with urllib.request.urlopen(req) as resp:
        raw = resp.read()
    if media_type == "application/vnd.github.v3.diff":
        return raw.decode()
    return json.loads(raw) if raw else {}


def _post_github_comment(pr_number: int, body: str, token: str):
    _gh(f"/repos/{GITHUB_REPO}/issues/{pr_number}/comments",
        token, method="POST", body={"body": body})


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
# /accept — human override of an AI REJECT (no Agent)
# ============================================================

def handle_accept(pr_data: dict) -> dict:
    """Post APPROVE review, merge the PR, and notify Slack.

    Best-effort merge: if GitHub refuses (branch protection, conflicts, draft),
    we still keep the APPROVE review and leave a Slack note explaining why.
    """
    pr_number = pr_data["pr_number"]
    note = pr_data.get("reason", "").strip()
    actor = pr_data.get("actor", "unknown")
    github_token = get_secret(GITHUB_TOKEN_SECRET_ARN)
    slack_token = get_secret(SLACK_TOKEN_SECRET_ARN)

    review_body = (
        f"## ✅ 사람 승인 (AI REJECT 덮어쓰기)\n\n"
        f"`@{actor}` 님이 AI 판정과 별개로 이 PR을 직접 승인했습니다.\n\n"
        + (f"### 메모\n{note}\n\n" if note else "")
        + f"---\n*Issued via `/accept` Slack command*"
    )
    # APPROVE review
    try:
        _gh(f"/repos/{GITHUB_REPO}/pulls/{pr_number}/reviews",
            github_token, method="POST",
            body={"event": "APPROVE", "body": review_body})
    except Exception as e:
        logger.warning(f"APPROVE review failed: {e}")

    # Attempt auto-merge
    merge_note = ""
    try:
        _gh(f"/repos/{GITHUB_REPO}/pulls/{pr_number}/merge",
            github_token, method="PUT",
            body={"merge_method": "squash",
                  "commit_title": f"[human-approve] {pr_data.get('pr_title', '')} (#{pr_number})"})
        merge_note = "자동 머지 완료 — CI/CD가 곧 실행됩니다."
    except Exception as e:
        merge_note = f"자동 머지 실패 ({type(e).__name__}) — 브랜치 보호 설정 확인이 필요합니다."
        logger.warning(f"auto-merge failed: {e}")

    blocks = [
        {"type": "header", "text": {"type": "plain_text",
                                    "text": f"✅ 사람 승인 — PR #{pr_number}"}},
        {"type": "section", "fields": [
            {"type": "mrkdwn", "text": f"*PR:* <{pr_data['pr_url']}|{pr_data['pr_title']}>"},
            {"type": "mrkdwn", "text": f"*Approved by:* {actor}"},
        ]},
        {"type": "section", "text": {"type": "mrkdwn",
                                     "text": f"*머지 상태:* {merge_note}"}},
    ]
    if note:
        blocks.append({"type": "section",
                       "text": {"type": "mrkdwn", "text": f"*메모:*\n{note}"}})
    blocks.append({"type": "divider"})
    blocks.append({"type": "context", "elements": [
        {"type": "mrkdwn",
         "text": f"🤖 RiskJudge · {datetime.now(timezone.utc).isoformat(timespec='seconds')}"}
    ]})
    _post_slack(blocks, f"PR #{pr_number} human-approved by {actor}", slack_token)

    return {"pr_number": pr_number, "status": "accepted", "actor": actor}


# ============================================================
# /rollback — open a revert PR against a previously-merged change
# ============================================================

def handle_rollback(pr_data: dict) -> dict:
    """Create a branch that reverts the merge commit of the given PR, then open
    a new PR. The real CD pipeline re-deploys once the revert PR is merged;
    we just set the scaffolding up.
    """
    pr_number = pr_data["pr_number"]
    note = pr_data.get("reason", "").strip()
    actor = pr_data.get("actor", "unknown")
    github_token = get_secret(GITHUB_TOKEN_SECRET_ARN)
    slack_token = get_secret(SLACK_TOKEN_SECRET_ARN)

    revert_url = ""
    revert_note = ""

    merge_sha = pr_data.get("merge_commit_sha") or ""
    if not merge_sha or not pr_data.get("merged"):
        revert_note = (
            f"이 PR은 아직 머지되지 않아 롤백할 커밋이 없습니다. "
            f"머지된 이후 `/rollback {pr_number}` 를 다시 실행하세요."
        )
    else:
        try:
            # 1) Look up the parent commit of the merge so the revert branches
            #    off the same base. Shallow: we just need `parents[0].sha`.
            commit = _gh(f"/repos/{GITHUB_REPO}/commits/{merge_sha}", github_token)
            parent_sha = commit["parents"][0]["sha"]

            # 2) Create a branch from the parent. Any write will follow.
            branch = f"rollback/pr-{pr_number}-{datetime.now().strftime('%Y%m%d%H%M%S')}"
            _gh(f"/repos/{GITHUB_REPO}/git/refs", github_token, method="POST",
                body={"ref": f"refs/heads/{branch}", "sha": parent_sha})

            # 3) Open a PR from branch → main. The branch is already the
            #    pre-merge state, so merging the PR reverses the change.
            pr = _gh(f"/repos/{GITHUB_REPO}/pulls", github_token, method="POST",
                     body={
                         "title": f"Revert: {pr_data.get('pr_title', '')} (#{pr_number})",
                         "head": branch, "base": "main",
                         "body": (
                             f"## ⏪ Rollback of #{pr_number}\n\n"
                             f"요청자: `@{actor}`\n\n"
                             + (f"### 메모\n{note}\n\n" if note else "")
                             + f"---\n"
                             f"이 PR은 `/rollback` Slack 명령으로 자동 생성되었습니다. "
                             f"머지하면 CD 파이프라인이 원상복구 배포를 수행합니다."
                         ),
                     })
            revert_url = pr.get("html_url", "")
            revert_note = f"롤백 PR 생성 완료 — {revert_url} 머지 시 CD가 재배포합니다."
        except Exception as e:
            logger.warning(f"rollback failed: {e}")
            revert_note = f"롤백 PR 생성 실패 ({type(e).__name__}) — 수동 대응 필요."

    blocks = [
        {"type": "header", "text": {"type": "plain_text",
                                    "text": f"⏪ 롤백 요청 — PR #{pr_number}"}},
        {"type": "section", "fields": [
            {"type": "mrkdwn", "text": f"*PR:* <{pr_data['pr_url']}|{pr_data['pr_title']}>"},
            {"type": "mrkdwn", "text": f"*Requested by:* {actor}"},
        ]},
        {"type": "section", "text": {"type": "mrkdwn",
                                     "text": f"*상태:* {revert_note}"}},
    ]
    if revert_url:
        blocks.append({"type": "section",
                       "text": {"type": "mrkdwn",
                                "text": f"*롤백 PR:* <{revert_url}|바로가기>"}})
    if note:
        blocks.append({"type": "section",
                       "text": {"type": "mrkdwn", "text": f"*메모:*\n{note}"}})
    blocks.append({"type": "divider"})
    blocks.append({"type": "context", "elements": [
        {"type": "mrkdwn",
         "text": f"🤖 DevOpsInvestigator · {datetime.now(timezone.utc).isoformat(timespec='seconds')}"}
    ]})
    _post_slack(blocks, f"PR #{pr_number} rollback requested by {actor}", slack_token)

    # Also leave a comment on the original PR so the history is complete.
    try:
        comment = (
            f"## ⏪ Rollback 요청\n\n"
            f"`@{actor}` 님이 `/rollback` 명령으로 롤백 PR 생성을 요청했습니다.\n\n"
            + (f"### 메모\n{note}\n\n" if note else "")
            + (f"롤백 PR: {revert_url}\n\n" if revert_url else "")
            + f"---\n*Issued via `/rollback` Slack command*"
        )
        _post_github_comment(pr_number, comment, github_token)
    except Exception as e:
        logger.warning(f"original-PR comment failed: {e}")

    return {"pr_number": pr_number, "status": "rollback_opened",
            "revert_pr_url": revert_url, "actor": actor}


# ============================================================
# Fallback (Agent unavailable) — minimal direct model call
# ============================================================

def fallback_direct(pr_data: dict) -> dict:
    logger.warning("Fallback path: direct Bedrock model call (no KB, no tools)")
    github_token = get_secret(GITHUB_TOKEN_SECRET_ARN)

    # Fetch diff minimally
    diff = _gh(f"/repos/{GITHUB_REPO}/pulls/{pr_data['pr_number']}",
               github_token, media_type="application/vnd.github.v3.diff")
    if isinstance(diff, str):
        diff = diff[:10000]
    else:
        diff = ""

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

    # --- Slack /accept — human override, no Agent ---
    if command == "accept":
        return handle_accept(event)

    # --- Slack /rollback — revert PR, no Agent ---
    if command == "rollback":
        return handle_rollback(event)

    # --- Slack /investigate — free-form prompt, forward to DevOps webhook ---
    if command == "investigate":
        try:
            return handle_investigate(event)
        except Exception as e:
            logger.error(f"investigate failed: {e}", exc_info=True)
            return {"status": "error", "message": str(e)}

    # --- Webhook event (no command) — full analysis via AgentCore Runtime ---
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
