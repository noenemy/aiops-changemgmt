"""PR Analysis handler — fetches diff, invokes Bedrock AgentCore, posts to GitHub + Slack."""

import json
import logging
import os
from datetime import datetime

import boto3
import urllib.request

logger = logging.getLogger()
logger.setLevel(logging.INFO)

secrets_client = boto3.client("secretsmanager")
bedrock_agent_runtime = boto3.client("bedrock-agent-runtime")
bedrock_runtime = boto3.client("bedrock-runtime")
dynamodb = boto3.resource("dynamodb")

GITHUB_TOKEN_SECRET_ARN = os.environ["GITHUB_TOKEN_SECRET_ARN"]
SLACK_TOKEN_SECRET_ARN = os.environ["SLACK_TOKEN_SECRET_ARN"]
SLACK_CHANNEL_ID = os.environ["SLACK_CHANNEL_ID"]
GITHUB_REPO = os.environ["GITHUB_REPO"]
BEDROCK_AGENT_ID = os.environ["BEDROCK_AGENT_ID"]
BEDROCK_AGENT_ALIAS_ID = os.environ["BEDROCK_AGENT_ALIAS_ID"]
BEDROCK_MODEL_ID = os.environ["BEDROCK_MODEL_ID"]
REVIEW_HISTORY_TABLE = os.environ["REVIEW_HISTORY_TABLE"]

review_table = dynamodb.Table(REVIEW_HISTORY_TABLE)

_secrets_cache = {}


def get_secret(arn: str) -> str:
    if arn not in _secrets_cache:
        resp = secrets_client.get_secret_value(SecretId=arn)
        _secrets_cache[arn] = resp["SecretString"]
    return _secrets_cache[arn]


def github_api(path: str, github_token: str, accept: str = "application/vnd.github.v3+json") -> str:
    url = f"https://api.github.com{path}"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {github_token}",
        "Accept": accept,
        "User-Agent": "AIOps-ChangeManagement",
    })
    with urllib.request.urlopen(req) as resp:
        return resp.read().decode()


def get_pr_diff(pr_number: int, github_token: str) -> str:
    return github_api(
        f"/repos/{GITHUB_REPO}/pulls/{pr_number}",
        github_token,
        accept="application/vnd.github.v3.diff",
    )


def get_pr_files(pr_number: int, github_token: str) -> list:
    resp = github_api(f"/repos/{GITHUB_REPO}/pulls/{pr_number}/files", github_token)
    return json.loads(resp)


def invoke_agent(pr_data: dict, diff: str, files: list) -> dict:
    """Invoke Bedrock AgentCore with session memory.

    Uses the Agent's built-in KB (past incidents) and Memory (past reviews)
    so the agent has full context without us manually fetching it.
    """
    files_summary = "\n".join(
        f"  - {f['filename']} (+{f['additions']}, -{f['deletions']})" for f in files
    )

    input_text = f"""아래 Pull Request를 분석해주세요.

## PR 정보
- PR #{pr_data['pr_number']}: {pr_data['pr_title']}
- Author: {pr_data['pr_author']}
- Branch: {pr_data['head_branch']} → {pr_data['base_branch']}

## 변경 파일
{files_summary}

## Diff
```
{diff[:15000]}
```

Knowledge Base에서 과거 장애 이력을 검색하여 유사한 패턴이 있는지 반드시 확인하세요.
과거 리뷰 이력도 Memory에서 참조하세요.

JSON 형식으로 응답하세요."""

    # Use repo as memoryId so the agent remembers across PRs for this repo
    session_id = f"pr-{pr_data['pr_number']}-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    memory_id = GITHUB_REPO.replace("/", "-")

    logger.info(f"Invoking AgentCore: agent={BEDROCK_AGENT_ID}, session={session_id}, memory={memory_id}")

    response = bedrock_agent_runtime.invoke_agent(
        agentId=BEDROCK_AGENT_ID,
        agentAliasId=BEDROCK_AGENT_ALIAS_ID,
        sessionId=session_id,
        memoryId=memory_id,
        inputText=input_text,
    )

    # Read streaming response
    completion = ""
    for event in response["completion"]:
        if "chunk" in event:
            completion += event["chunk"]["bytes"].decode()

    logger.info(f"Agent response length: {len(completion)} chars")

    # End session to trigger memory summarization
    try:
        bedrock_agent_runtime.invoke_agent(
            agentId=BEDROCK_AGENT_ID,
            agentAliasId=BEDROCK_AGENT_ALIAS_ID,
            sessionId=session_id,
            memoryId=memory_id,
            inputText="세션을 종료합니다.",
            endSession=True,
        )
    except Exception:
        pass  # Session end is best-effort

    # Parse JSON from response
    text = completion
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0]
    elif "```" in text:
        text = text.split("```")[1].split("```")[0]

    return json.loads(text.strip())


def invoke_bedrock_direct(pr_data: dict, diff: str, files: list) -> dict:
    """Fallback: direct Bedrock model invocation if Agent is unavailable."""
    files_summary = "\n".join(
        f"  - {f['filename']} (+{f['additions']}, -{f['deletions']})" for f in files
    )

    prompt = f"""당신은 시니어 소프트웨어 엔지니어이자 보안/성능 전문 코드 리뷰어입니다.

## PR 정보
- PR #{pr_data['pr_number']}: {pr_data['pr_title']}
- Author: {pr_data['pr_author']}
- Branch: {pr_data['head_branch']} → {pr_data['base_branch']}

## 변경 파일
{files_summary}

## Diff
```
{diff[:15000]}
```

아래 JSON 형식으로 응답하세요:
{{"risk_score": <0-100>, "risk_level": "<LOW|MEDIUM|HIGH|CRITICAL>", "verdict": "<APPROVE|REJECT>", "summary": "<한국어 요약>", "issues": [{{"severity": "<critical|high|medium|low>", "title": "<제목>", "location": "<파일:라인>", "description": "<설명>", "impact": "<영향>", "fix": "<수정>"}}], "past_incident_match": null}}"""

    body = json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 4096,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1,
    })

    response = bedrock_runtime.invoke_model(
        modelId=BEDROCK_MODEL_ID,
        contentType="application/json",
        accept="application/json",
        body=body,
    )

    result = json.loads(response["body"].read())
    text = result["content"][0]["text"]

    if "```json" in text:
        text = text.split("```json")[1].split("```")[0]
    elif "```" in text:
        text = text.split("```")[1].split("```")[0]

    return json.loads(text.strip())


def post_github_comment(pr_number: int, analysis: dict, github_token: str):
    risk_emoji = {
        "LOW": "🟢", "MEDIUM": "🟡", "HIGH": "🔴", "CRITICAL": "🔴"
    }.get(analysis["risk_level"], "⚪")

    verdict_text = "✅ CI/CD 자동 실행" if analysis["verdict"] == "APPROVE" else "🚫 CI/CD 스킵"

    body = f"""## {risk_emoji} AI Code Review — Risk Score: {analysis['risk_score']}/100 ({analysis['risk_level']})

{analysis['summary']}

### 판정: {verdict_text}
"""

    if analysis.get("issues"):
        body += "\n### 발견된 이슈\n\n"
        severity_icons = {"critical": "🔴", "high": "🟡", "medium": "🔵", "low": "⚪"}
        for issue in analysis["issues"]:
            icon = severity_icons.get(issue["severity"], "⚪")
            body += f"""**{icon} [{issue['severity'].upper()}] {issue['title']}**
📍 `{issue['location']}`
{issue['description']}
- **영향**: {issue['impact']}
- **수정 제안**: {issue['fix']}

"""

    if analysis.get("past_incident_match"):
        body += f"\n### ⚠️ 과거 유사 장애 이력\n{analysis['past_incident_match']}\n"

    body += "\n---\n*🤖 Analyzed by AIOps ChangeManagement Agent (Bedrock AgentCore)*"

    data = json.dumps({"body": body}).encode()
    url = f"https://api.github.com/repos/{GITHUB_REPO}/issues/{pr_number}/comments"
    req = urllib.request.Request(url, data=data, method="POST", headers={
        "Authorization": f"Bearer {github_token}",
        "Accept": "application/vnd.github.v3+json",
        "Content-Type": "application/json",
        "User-Agent": "AIOps-ChangeManagement",
    })
    urllib.request.urlopen(req)
    logger.info(f"Posted GitHub comment on PR #{pr_number}")


def post_slack_report(pr_data: dict, analysis: dict, slack_token: str):
    risk_emoji = {
        "LOW": "🟢", "MEDIUM": "🟡", "HIGH": "🔴", "CRITICAL": "🔴"
    }.get(analysis["risk_level"], "⚪")

    verdict_text = "✅ CI/CD 자동 실행" if analysis["verdict"] == "APPROVE" else "🚫 CI/CD 파이프라인 스킵"

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"PR #{pr_data['pr_number']} 변경 분석 리포트"}
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*PR:* {pr_data['pr_title']}"},
                {"type": "mrkdwn", "text": f"*Author:* {pr_data['pr_author']}"},
                {"type": "mrkdwn", "text": f"*Branch:* `{pr_data['head_branch']}`"},
                {"type": "mrkdwn", "text": f"*Risk:* {risk_emoji} {analysis['risk_score']}/100 ({analysis['risk_level']})"},
            ]
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*요약:* {analysis['summary']}"}
        },
    ]

    if analysis.get("issues"):
        issue_text = "*발견된 이슈:*\n"
        severity_icons = {"critical": "🔴", "high": "🟡", "medium": "🔵", "low": "⚪"}
        for issue in analysis["issues"]:
            icon = severity_icons.get(issue["severity"], "⚪")
            issue_text += f"{icon} *[{issue['severity'].upper()}]* {issue['title']}\n"
            issue_text += f"     `{issue['location']}` — {issue['description'][:100]}\n"
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": issue_text}
        })

    if analysis.get("past_incident_match"):
        blocks.append({"type": "divider"})
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"⚠️ *과거 유사 장애:* {analysis['past_incident_match']}"}
        })

    blocks.append({"type": "divider"})
    blocks.append({
        "type": "section",
        "text": {"type": "mrkdwn", "text": f"*판정:* {verdict_text}"}
    })
    blocks.append({
        "type": "context",
        "elements": [
            {"type": "mrkdwn", "text": f"<{pr_data['pr_url']}|GitHub PR 보기> | 🤖 AIOps ChangeManagement Agent (Bedrock AgentCore)"}
        ]
    })

    payload = json.dumps({
        "channel": SLACK_CHANNEL_ID,
        "blocks": blocks,
        "text": f"PR #{pr_data['pr_number']} 분석 완료 — Risk {analysis['risk_score']}/100",
    }).encode()

    req = urllib.request.Request(
        "https://slack.com/api/chat.postMessage",
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Bearer {slack_token}",
            "Content-Type": "application/json; charset=utf-8",
        },
    )
    resp = urllib.request.urlopen(req)
    result = json.loads(resp.read())

    if not result.get("ok"):
        logger.error(f"Slack API error: {result.get('error')}")
    else:
        logger.info(f"Posted Slack report for PR #{pr_data['pr_number']}")


def save_review_history(pr_data: dict, analysis: dict):
    try:
        review_table.put_item(Item={
            "prKey": f"{GITHUB_REPO}#{pr_data['pr_number']}",
            "reviewedAt": datetime.now().isoformat(),
            "prTitle": pr_data["pr_title"],
            "prAuthor": pr_data["pr_author"],
            "riskScore": analysis["risk_score"],
            "riskLevel": analysis["risk_level"],
            "verdict": analysis["verdict"],
            "summary": analysis["summary"],
            "issueCount": len(analysis.get("issues", [])),
            "issues": json.dumps(analysis.get("issues", []), ensure_ascii=False),
            "severity": analysis["issues"][0]["severity"] if analysis.get("issues") else "none",
            "rootCause": analysis["issues"][0]["title"] if analysis.get("issues") else None,
            "title": f"PR #{pr_data['pr_number']}: {pr_data['pr_title']}",
        })
        logger.info(f"Saved review history for PR #{pr_data['pr_number']}")
    except Exception as e:
        logger.error(f"Failed to save review history: {e}")


def handler(event, context):
    logger.info(f"Analyzing PR #{event['pr_number']}: {event['pr_title']}")

    github_token = get_secret(GITHUB_TOKEN_SECRET_ARN)
    slack_token = get_secret(SLACK_TOKEN_SECRET_ARN)

    diff = get_pr_diff(event["pr_number"], github_token)
    files = get_pr_files(event["pr_number"], github_token)
    logger.info(f"Fetched diff ({len(diff)} chars) and {len(files)} files")

    # Try AgentCore first, fallback to direct model invocation
    try:
        logger.info("Invoking Bedrock AgentCore...")
        analysis = invoke_agent(event, diff, files)
    except Exception as e:
        logger.warning(f"AgentCore invocation failed, falling back to direct model: {e}")
        analysis = invoke_bedrock_direct(event, diff, files)

    logger.info(f"Analysis complete: Risk {analysis['risk_score']}/100 ({analysis['risk_level']})")

    post_github_comment(event["pr_number"], analysis, github_token)
    post_slack_report(event, analysis, slack_token)
    save_review_history(event, analysis)

    return {
        "pr_number": event["pr_number"],
        "risk_score": analysis["risk_score"],
        "verdict": analysis["verdict"],
    }
