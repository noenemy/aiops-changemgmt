"""Action Group Lambda — tools that the Bedrock Agent can call."""

import json
import logging
import os
import urllib.request

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

secrets_client = boto3.client("secretsmanager")

GITHUB_TOKEN_SECRET_ARN = os.environ["GITHUB_TOKEN_SECRET_ARN"]
SLACK_TOKEN_SECRET_ARN = os.environ["SLACK_TOKEN_SECRET_ARN"]
SLACK_CHANNEL_ID = os.environ["SLACK_CHANNEL_ID"]
GITHUB_REPO = os.environ["GITHUB_REPO"]

_secrets_cache = {}


def get_secret(arn: str) -> str:
    if arn not in _secrets_cache:
        resp = secrets_client.get_secret_value(SecretId=arn)
        _secrets_cache[arn] = resp["SecretString"]
    return _secrets_cache[arn]


def github_api(path: str, method: str = "GET", data: bytes = None,
               accept: str = "application/vnd.github.v3+json") -> str:
    github_token = get_secret(GITHUB_TOKEN_SECRET_ARN)
    url = f"https://api.github.com{path}"
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {github_token}",
        "Accept": accept,
        "Content-Type": "application/json",
        "User-Agent": "AIOps-ChangeManagement",
    })
    with urllib.request.urlopen(req) as resp:
        return resp.read().decode()


# ============================================================
# Tool implementations
# ============================================================

def get_pr_diff(pr_number: int) -> str:
    """Fetch PR diff from GitHub."""
    diff = github_api(
        f"/repos/{GITHUB_REPO}/pulls/{pr_number}",
        accept="application/vnd.github.v3.diff",
    )
    # Truncate if too long for agent context
    if len(diff) > 15000:
        diff = diff[:15000] + "\n... (truncated)"
    return diff


def get_pr_files(pr_number: int) -> str:
    """Fetch list of changed files."""
    resp = github_api(f"/repos/{GITHUB_REPO}/pulls/{pr_number}/files")
    files = json.loads(resp)
    summary = []
    for f in files:
        summary.append({
            "filename": f["filename"],
            "additions": f["additions"],
            "deletions": f["deletions"],
            "status": f["status"],
        })
    return json.dumps(summary, ensure_ascii=False)


def post_github_comment(pr_number: int, comment_body: str) -> str:
    """Post a comment on the PR."""
    data = json.dumps({"body": comment_body}).encode()
    github_api(
        f"/repos/{GITHUB_REPO}/issues/{pr_number}/comments",
        method="POST",
        data=data,
    )
    return f"Comment posted on PR #{pr_number}"


def post_slack_report(pr_number: int, pr_title: str, pr_author: str,
                      risk_score: int, risk_level: str, verdict: str,
                      summary: str, issues_text: str) -> str:
    """Post analysis report to Slack."""
    slack_token = get_secret(SLACK_TOKEN_SECRET_ARN)

    risk_emoji = {"LOW": "🟢", "MEDIUM": "🟡", "HIGH": "🔴", "CRITICAL": "🔴"}.get(risk_level, "⚪")
    verdict_text = "✅ CI/CD 자동 실행" if verdict == "APPROVE" else "🚫 CI/CD 파이프라인 스킵"

    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": f"PR #{pr_number} 변경 분석 리포트"}},
        {"type": "section", "fields": [
            {"type": "mrkdwn", "text": f"*PR:* {pr_title}"},
            {"type": "mrkdwn", "text": f"*Author:* {pr_author}"},
            {"type": "mrkdwn", "text": f"*Risk:* {risk_emoji} {risk_score}/100 ({risk_level})"},
        ]},
        {"type": "divider"},
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*요약:* {summary}"}},
    ]

    if issues_text:
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"*발견된 이슈:*\n{issues_text}"}})

    blocks.append({"type": "divider"})
    blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"*판정:* {verdict_text}"}})
    blocks.append({"type": "context", "elements": [
        {"type": "mrkdwn", "text": f"🤖 AIOps ChangeManagement Agent (Bedrock AgentCore + Memory)"}
    ]})

    payload = json.dumps({
        "channel": SLACK_CHANNEL_ID,
        "blocks": blocks,
        "text": f"PR #{pr_number} 분석 완료 — Risk {risk_score}/100",
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
        return f"Slack error: {result.get('error')}"
    return f"Slack report posted for PR #{pr_number}"


# ============================================================
# Bedrock Agent Action Group handler
# ============================================================

def get_param(params: list, name: str) -> str:
    """Extract parameter value from action group event."""
    for p in params:
        if p["name"] == name:
            return p["value"]
    return ""


def handler(event, context):
    logger.info(f"Action group event: {json.dumps(event, default=str)[:500]}")

    action = event.get("actionGroup", "")
    function = event.get("function", "")
    params = event.get("parameters", [])

    logger.info(f"Function: {function}, Params: {[p['name'] for p in params]}")

    try:
        if function == "get_pr_diff":
            pr_number = int(get_param(params, "pr_number"))
            result = get_pr_diff(pr_number)

        elif function == "get_pr_files":
            pr_number = int(get_param(params, "pr_number"))
            result = get_pr_files(pr_number)

        elif function == "post_github_comment":
            pr_number = int(get_param(params, "pr_number"))
            comment_body = get_param(params, "comment_body")
            result = post_github_comment(pr_number, comment_body)

        elif function == "post_slack_report":
            report_json_str = get_param(params, "report_json")
            report = json.loads(report_json_str)
            result = post_slack_report(
                pr_number=int(report.get("pr_number", 0)),
                pr_title=report.get("pr_title", ""),
                pr_author=report.get("pr_author", ""),
                risk_score=int(report.get("risk_score", 0)),
                risk_level=report.get("risk_level", "LOW"),
                verdict=report.get("verdict", "APPROVE"),
                summary=report.get("summary", ""),
                issues_text=report.get("issues_text", ""),
            )
        else:
            result = f"Unknown function: {function}"

    except Exception as e:
        logger.error(f"Error in {function}: {e}")
        result = f"Error: {str(e)}"

    logger.info(f"Result length: {len(result)}")

    return {
        "messageVersion": "1.0",
        "response": {
            "actionGroup": action,
            "function": function,
            "functionResponse": {
                "responseBody": {
                    "TEXT": {"body": result}
                }
            },
        },
    }
