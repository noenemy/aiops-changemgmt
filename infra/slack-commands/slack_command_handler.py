"""Slack Slash Command receiver.

Verifies Slack signature, parses command (/analysis, /reject, /fix),
acks within 3s, and invokes Analysis Lambda asynchronously.

Expected Slash Commands:
  /analysis <PR_NUMBER>
  /reject   <PR_NUMBER> [reason]
  /fix      <PR_NUMBER>

The Slash Command URL should point to this Lambda's API Gateway endpoint.
"""

import base64
import hashlib
import hmac
import json
import logging
import os
import time
import urllib.parse
import urllib.request

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

secrets_client = boto3.client("secretsmanager")
lambda_client = boto3.client("lambda")

SLACK_SIGNING_SECRET_ARN = os.environ["SLACK_SIGNING_SECRET_ARN"]
ANALYSIS_FUNCTION_NAME = os.environ["ANALYSIS_FUNCTION_NAME"]
GITHUB_REPO = os.environ["GITHUB_REPO"]
GITHUB_TOKEN_SECRET_ARN = os.environ["GITHUB_TOKEN_SECRET_ARN"]

_secrets_cache = {}

ALLOWED_COMMANDS = {"/analysis", "/reject", "/fix"}


def get_secret(arn: str) -> str:
    if arn not in _secrets_cache:
        _secrets_cache[arn] = secrets_client.get_secret_value(SecretId=arn)["SecretString"]
    return _secrets_cache[arn]


def verify_slack_signature(headers: dict, body: str) -> bool:
    """Verify X-Slack-Signature using HMAC-SHA256."""
    ts = headers.get("x-slack-request-timestamp") or headers.get("X-Slack-Request-Timestamp", "")
    sig = headers.get("x-slack-signature") or headers.get("X-Slack-Signature", "")
    if not ts or not sig:
        return False
    # Replay protection — reject > 5min old
    try:
        if abs(time.time() - int(ts)) > 300:
            return False
    except ValueError:
        return False

    secret = get_secret(SLACK_SIGNING_SECRET_ARN)
    basestring = f"v0:{ts}:{body}"
    expected = "v0=" + hmac.new(
        secret.encode(), basestring.encode(), hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, sig)


def fetch_pr_meta(pr_number: int) -> dict:
    """Fetch basic PR metadata for command processing."""
    token = get_secret(GITHUB_TOKEN_SECRET_ARN)
    url = f"https://api.github.com/repos/{GITHUB_REPO}/pulls/{pr_number}"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "AIOps-ChangeManagement",
    })
    with urllib.request.urlopen(req) as resp:
        pr = json.loads(resp.read())
    return {
        "pr_number": pr["number"],
        "pr_title": pr["title"],
        "pr_author": pr["user"]["login"],
        "pr_url": pr["html_url"],
        "head_branch": pr["head"]["ref"],
        "base_branch": pr["base"]["ref"],
        "repo_full_name": pr["base"]["repo"]["full_name"],
    }


def parse_text(text: str) -> tuple:
    """Parse '123 some reason' → (123, 'some reason')."""
    parts = (text or "").strip().split(maxsplit=1)
    if not parts:
        return None, ""
    try:
        pr_num = int(parts[0].lstrip("#"))
    except ValueError:
        return None, ""
    reason = parts[1] if len(parts) > 1 else ""
    return pr_num, reason


def ephemeral_response(text: str) -> dict:
    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps({"response_type": "ephemeral", "text": text}),
    }


def handler(event, context):
    # API Gateway passes body as string, possibly base64 if binary support
    raw_body = event.get("body", "") or ""
    if event.get("isBase64Encoded"):
        raw_body = base64.b64decode(raw_body).decode()

    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}

    if not verify_slack_signature(headers, raw_body):
        logger.warning("Invalid Slack signature")
        return {"statusCode": 401, "body": "Invalid signature"}

    form = dict(urllib.parse.parse_qsl(raw_body))
    command = form.get("command", "")
    text = form.get("text", "")
    user_id = form.get("user_id", "")
    user_name = form.get("user_name", "")

    logger.info(f"Slack command: {command}, text: {text!r}, user: {user_name}")

    if command not in ALLOWED_COMMANDS:
        return ephemeral_response(f"Unsupported command: {command}")

    pr_number, reason = parse_text(text)
    if pr_number is None:
        return ephemeral_response(
            f"사용법: `{command} <PR번호>`" + (" [사유]" if command == "/reject" else "")
        )

    # Fetch PR metadata
    try:
        pr_meta = fetch_pr_meta(pr_number)
    except Exception as e:
        logger.error(f"Failed to fetch PR #{pr_number}: {e}")
        return ephemeral_response(f"PR #{pr_number} 조회 실패: {e}")

    # Invoke Analysis Lambda async with command flag
    payload = {
        **pr_meta,
        "command": command.lstrip("/"),  # "analysis" / "reject" / "fix"
        "reason": reason,
        "actor": user_name or user_id,
    }

    try:
        lambda_client.invoke(
            FunctionName=ANALYSIS_FUNCTION_NAME,
            InvocationType="Event",
            Payload=json.dumps(payload),
        )
    except Exception as e:
        logger.error(f"Failed to invoke analysis: {e}")
        return ephemeral_response(f"분석 요청 실패: {e}")

    # 3초 내 ack
    labels = {
        "/analysis": f"🔍 PR #{pr_number} 재분석을 시작했습니다. 결과는 곧 채널에 게시됩니다.",
        "/reject":   f"🚫 PR #{pr_number}에 REJECT 코멘트를 게시 중입니다.",
        "/fix":      f"🔧 PR #{pr_number}에 대한 Fix 제안을 생성 중입니다.",
    }
    return ephemeral_response(labels[command])
