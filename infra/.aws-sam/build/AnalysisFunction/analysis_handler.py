"""PR Analysis handler — fetches diff, invokes Bedrock AgentCore, posts to GitHub + Slack.

Memory strategy:
  - Phase 1 (now): DynamoDB ReviewHistoryTable stores past reviews.
    On each analysis, we query past reviews by author + changed files
    and inject them into the prompt so the model has full context.
  - Phase 2 (AgentCore): Agent Memory automatically stores session summaries.
    Combined with DynamoDB history for richer context.
"""

import json
import logging
import os
from datetime import datetime
from decimal import Decimal

import boto3
import urllib.request
from boto3.dynamodb.conditions import Attr

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

# Known incident data (also in KB, but hardcoded for Phase 1 reliability)
KNOWN_INCIDENTS = [
    {
        "id": "INC-0042",
        "date": "2026-01-15",
        "severity": "P1",
        "title": "주문 폭주 시 재고 마이너스 발생 — Race Condition",
        "root_cause": "재고 확인-차감 간 TOCTOU 취약점",
        "affected_file": "create_order.py",
        "downtime": "2시간",
        "revenue_impact": "₩12,000,000",
        "pattern_keywords": ["race condition", "toctou", "get_item", "update_item", "stockcount", "inventory", "재고"],
    },
    {
        "id": "INC-0038",
        "date": "2025-11-22",
        "severity": "P2",
        "title": "API 응답 필드 변경으로 모바일 앱 크래시",
        "root_cause": "Breaking API Change without versioning",
        "affected_file": "get_order.py",
        "downtime": "45분",
        "revenue_impact": "₩3,500,000",
        "pattern_keywords": ["field", "rename", "breaking", "api", "response", "orderId", "필드명"],
    },
    {
        "id": "INC-0041",
        "date": "2025-12-20",
        "severity": "P1",
        "title": "N+1 쿼리로 DynamoDB 쓰로틀링 — 전체 서비스 연쇄 장애",
        "root_cause": "for 루프 내 개별 get_item 호출 (N+1 쿼리)",
        "affected_file": "list_orders.py",
        "downtime": "1시간 30분",
        "revenue_impact": "₩8,200,000 + DynamoDB 과금 ₩2,100,000",
        "pattern_keywords": ["n+1", "scan", "for", "get_item", "loop", "pagination", "페이지네이션"],
    },
    {
        "id": "INC-0045",
        "date": "2026-02-08",
        "severity": "P1",
        "title": "결제 API 라이브 키 소스코드 노출 — 보안 인시던트",
        "root_cause": "시크릿 하드코딩 + DEBUG 로그에 카드 토큰 평문 기록",
        "affected_file": "process_payment.py",
        "downtime": "4시간 (시크릿 로테이션)",
        "revenue_impact": "₩5,000,000 (보안 감사 비용)",
        "pattern_keywords": ["sk_live", "secret", "hardcode", "api_key", "card_token", "debug", "pci", "시크릿"],
    },
]

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


# ============================================================
# Memory: past review history from DynamoDB
# ============================================================

def get_past_reviews_by_author(author: str) -> list:
    """Get past review results for the same author."""
    try:
        resp = review_table.scan(
            FilterExpression=Attr("prAuthor").eq(author),
            Limit=50,
        )
        items = resp.get("Items", [])
        items.sort(key=lambda x: x.get("reviewedAt", ""), reverse=True)
        return items[:5]
    except Exception as e:
        logger.warning(f"Failed to query reviews by author: {e}")
        return []


def get_past_reviews_by_files(changed_files: list) -> list:
    """Get past reviews that touched the same files."""
    try:
        resp = review_table.scan(Limit=50)
        items = resp.get("Items", [])
        relevant = []
        for item in items:
            item_issues = item.get("issues", "[]")
            if isinstance(item_issues, str):
                for f in changed_files:
                    basename = f.split("/")[-1]
                    if basename in item_issues or basename in item.get("prTitle", ""):
                        relevant.append(item)
                        break
        relevant.sort(key=lambda x: x.get("reviewedAt", ""), reverse=True)
        return relevant[:5]
    except Exception as e:
        logger.warning(f"Failed to query reviews by files: {e}")
        return []


def get_repo_review_stats() -> dict:
    """Get aggregate review stats for this repo."""
    try:
        resp = review_table.scan(Limit=100)
        items = resp.get("Items", [])
        if not items:
            return {}

        total = len(items)
        rejected = sum(1 for i in items if i.get("verdict") == "REJECT")
        avg_score = sum(int(i.get("riskScore", 0)) for i in items) / total

        # Recent trend
        items.sort(key=lambda x: x.get("reviewedAt", ""), reverse=True)
        recent_5 = items[:5]
        recent_avg = sum(int(i.get("riskScore", 0)) for i in recent_5) / len(recent_5) if recent_5 else 0

        return {
            "total_reviews": total,
            "rejected_count": rejected,
            "reject_rate": f"{rejected/total*100:.0f}%",
            "avg_risk_score": f"{avg_score:.0f}",
            "recent_5_avg_score": f"{recent_avg:.0f}",
            "trend": "상승" if recent_avg > avg_score else "하락" if recent_avg < avg_score else "유지",
        }
    except Exception as e:
        logger.warning(f"Failed to get review stats: {e}")
        return {}


def match_known_incidents(diff: str, files: list) -> list:
    """Match PR changes against known incident patterns."""
    diff_lower = diff.lower()
    file_names = [f["filename"].split("/")[-1].lower() for f in files]
    matched = []

    for inc in KNOWN_INCIDENTS:
        score = 0
        # Check file match
        if inc["affected_file"].lower() in file_names:
            score += 3
        # Check keyword match
        for kw in inc["pattern_keywords"]:
            if kw.lower() in diff_lower:
                score += 1
        if score >= 2:
            matched.append({**inc, "match_score": score})

    matched.sort(key=lambda x: x["match_score"], reverse=True)
    return matched


# ============================================================
# Prompt builder with full memory context
# ============================================================

def build_analysis_prompt(pr_data: dict, diff: str, files: list,
                          author_history: list, file_history: list,
                          repo_stats: dict, matched_incidents: list) -> str:
    files_summary = "\n".join(
        f"  - {f['filename']} (+{f['additions']}, -{f['deletions']})" for f in files
    )

    # Build memory context
    memory_sections = []

    # 1. Author history
    if author_history:
        lines = [f"\n## 개발자 리뷰 이력 ({pr_data['pr_author']})"]
        for rev in author_history:
            lines.append(
                f"- PR {rev.get('prTitle', 'N/A')} | Risk {rev.get('riskScore', '?')}/100 "
                f"({rev.get('riskLevel', '?')}) | {rev.get('verdict', '?')} | "
                f"{rev.get('reviewedAt', '?')[:10]}"
            )
            if rev.get("rootCause"):
                lines.append(f"  주요 이슈: {rev['rootCause']}")
        memory_sections.append("\n".join(lines))

    # 2. File history
    if file_history:
        lines = ["\n## 동일 파일 변경 이력"]
        for rev in file_history:
            lines.append(
                f"- {rev.get('prTitle', 'N/A')} | Risk {rev.get('riskScore', '?')}/100 "
                f"({rev.get('verdict', '?')}) | {rev.get('reviewedAt', '?')[:10]}"
            )
        memory_sections.append("\n".join(lines))

    # 3. Repo stats
    if repo_stats:
        lines = ["\n## 레포 리뷰 통계"]
        lines.append(f"- 총 리뷰: {repo_stats.get('total_reviews', 0)}건")
        lines.append(f"- REJECT 비율: {repo_stats.get('reject_rate', 'N/A')}")
        lines.append(f"- 평균 Risk Score: {repo_stats.get('avg_risk_score', 'N/A')}/100")
        lines.append(f"- 최근 5건 평균: {repo_stats.get('recent_5_avg_score', 'N/A')}/100 (추세: {repo_stats.get('trend', 'N/A')})")
        memory_sections.append("\n".join(lines))

    # 4. Known incident matches
    if matched_incidents:
        lines = ["\n## ⚠️ 과거 장애 이력 매칭"]
        for inc in matched_incidents:
            lines.append(f"- **{inc['id']}** ({inc['date']}, {inc['severity']}): {inc['title']}")
            lines.append(f"  근본 원인: {inc['root_cause']}")
            lines.append(f"  영향: 다운타임 {inc['downtime']}, 매출 손실 {inc['revenue_impact']}")
            lines.append(f"  관련 파일: {inc['affected_file']}")
        memory_sections.append("\n".join(lines))

    memory_context = "\n".join(memory_sections) if memory_sections else "\n(이 PR은 이 레포의 첫 번째 리뷰입니다)"

    return f"""당신은 시니어 소프트웨어 엔지니어이자 보안/성능 전문 코드 리뷰어입니다.
아래 Pull Request의 변경 내용을 분석하고, 리스크를 평가해주세요.

**중요: 아래 "과거 컨텍스트" 섹션의 정보를 반드시 분석에 반영하세요.**
- 개발자의 과거 리뷰 이력이 있다면, 반복되는 패턴이 있는지 확인하세요.
- 동일 파일의 변경 이력이 있다면, 이전에 발생한 이슈가 재현되는지 확인하세요.
- 과거 장애와 유사한 패턴이 매칭되었다면, 해당 장애의 영향도를 반드시 언급하세요.

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

## 과거 컨텍스트 (Memory + Knowledge Base)
{memory_context}

## 응답 형식
반드시 아래 JSON 형식으로 응답하세요:

{{
  "risk_score": <0-100 정수>,
  "risk_level": "<LOW|MEDIUM|HIGH|CRITICAL>",
  "verdict": "<APPROVE|REJECT>",
  "summary": "<한국어 1-2문장 요약>",
  "issues": [
    {{
      "severity": "<critical|high|medium|low>",
      "title": "<이슈 제목>",
      "location": "<파일명:라인>",
      "description": "<상세 설명>",
      "impact": "<영향도>",
      "fix": "<수정 제안>"
    }}
  ],
  "past_incident_match": "<과거 유사 장애가 있으면 장애 ID, 날짜, 영향도를 포함한 상세 설명. 없으면 null>",
  "author_pattern_note": "<이 개발자의 과거 리뷰에서 반복되는 패턴이 있으면 설명. 없으면 null>",
  "memory_context_used": "<분석에 활용한 과거 컨텍스트 요약. 첫 리뷰면 null>"
}}

분석 기준:
1. 보안: 시크릿 노출, Injection, PII 로깅, 인증/인가 우회
2. 성능: N+1 쿼리, 페이지네이션 부재, 타임아웃 위험
3. 안정성: Race Condition, 보상 트랜잭션 부재, 에러 핸들링 누락
4. 호환성: Breaking API Change, 하위 호환성 파괴
5. 과거 장애 연관성: Memory/KB의 장애 이력과 유사한 패턴인지
6. 개발자 패턴: 이 개발자가 과거에 유사한 실수를 한 적이 있는지

risk_score 기준:
- 0-20: LOW (안전한 변경, 자동 승인 가능)
- 21-50: MEDIUM (주의 필요, 사람 리뷰 권장)
- 51-80: HIGH (위험, 배포 차단 권장)
- 81-100: CRITICAL (긴급, 즉시 차단)
"""


# ============================================================
# Bedrock invocation
# ============================================================

def invoke_agent(pr_data: dict, diff: str, files: list) -> dict:
    """Invoke Bedrock AgentCore with session memory."""
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

    completion = ""
    for event in response["completion"]:
        if "chunk" in event:
            completion += event["chunk"]["bytes"].decode()

    logger.info(f"Agent response length: {len(completion)} chars")

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
        pass

    text = completion
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0]
    elif "```" in text:
        text = text.split("```")[1].split("```")[0]

    return json.loads(text.strip())


def invoke_bedrock_direct(prompt: str) -> dict:
    """Direct Bedrock model invocation with full memory-enriched prompt."""
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


# ============================================================
# GitHub + Slack posting
# ============================================================

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

    if analysis.get("author_pattern_note"):
        body += f"\n### 👤 개발자 패턴 분석\n{analysis['author_pattern_note']}\n"

    if analysis.get("memory_context_used"):
        body += f"\n### 🧠 참조된 컨텍스트\n{analysis['memory_context_used']}\n"

    body += "\n---\n*🤖 Analyzed by AIOps ChangeManagement Agent (Bedrock AgentCore + Memory)*"

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

    if analysis.get("author_pattern_note"):
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"👤 *개발자 패턴:* {analysis['author_pattern_note']}"}
        })

    if analysis.get("memory_context_used"):
        blocks.append({
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": f"🧠 *Memory:* {analysis['memory_context_used'][:200]}"}
            ]
        })

    blocks.append({"type": "divider"})
    blocks.append({
        "type": "section",
        "text": {"type": "mrkdwn", "text": f"*판정:* {verdict_text}"}
    })
    blocks.append({
        "type": "context",
        "elements": [
            {"type": "mrkdwn", "text": f"<{pr_data['pr_url']}|GitHub PR 보기> | 🤖 AIOps ChangeManagement Agent (Bedrock AgentCore + Memory)"}
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


# ============================================================
# Review history persistence
# ============================================================

def save_review_history(pr_data: dict, analysis: dict, changed_files: list):
    try:
        review_table.put_item(Item={
            "prKey": f"{GITHUB_REPO}#{pr_data['pr_number']}",
            "reviewedAt": datetime.now().isoformat(),
            "prTitle": pr_data["pr_title"],
            "prAuthor": pr_data["pr_author"],
            "headBranch": pr_data["head_branch"],
            "riskScore": analysis["risk_score"],
            "riskLevel": analysis["risk_level"],
            "verdict": analysis["verdict"],
            "summary": analysis["summary"],
            "issueCount": len(analysis.get("issues", [])),
            "issues": json.dumps(analysis.get("issues", []), ensure_ascii=False),
            "changedFiles": json.dumps(changed_files, ensure_ascii=False),
            "severity": analysis["issues"][0]["severity"] if analysis.get("issues") else "none",
            "rootCause": analysis["issues"][0]["title"] if analysis.get("issues") else None,
            "title": f"PR #{pr_data['pr_number']}: {pr_data['pr_title']}",
            "pastIncidentMatch": analysis.get("past_incident_match"),
            "authorPatternNote": analysis.get("author_pattern_note"),
        })
        logger.info(f"Saved review history for PR #{pr_data['pr_number']}")
    except Exception as e:
        logger.error(f"Failed to save review history: {e}")


# ============================================================
# Main handler
# ============================================================

def invoke_agent_simple(pr_data: dict) -> str:
    """Invoke Agent with just PR info — Agent handles everything via tools."""
    session_id = f"pr-{pr_data['pr_number']}-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    memory_id = GITHUB_REPO.replace("/", "-")

    input_text = (
        f"PR #{pr_data['pr_number']}을 분석해주세요.\n"
        f"제목: {pr_data['pr_title']}\n"
        f"Author: {pr_data['pr_author']}\n"
        f"Branch: {pr_data['head_branch']} → {pr_data['base_branch']}\n\n"
        f"get_pr_diff와 get_pr_files 도구로 변경 내용을 확인하고, "
        f"분석 후 post_github_comment로 PR에 리뷰를 작성하고, "
        f"post_slack_report로 Slack에 리포트를 전송해주세요."
    )

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

    # End session to trigger memory summarization
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


def handler(event, context):
    logger.info(f"Analyzing PR #{event['pr_number']}: {event['pr_title']}")

    if BEDROCK_AGENT_ID != "none":
        # ============================================
        # AgentCore 경로: Agent가 모든 것을 자율 처리
        # ============================================
        logger.info("Using Bedrock AgentCore (Agent handles tools autonomously)")
        try:
            result = invoke_agent_simple(event)
            logger.info("Agent completed successfully")
            return {"pr_number": event["pr_number"], "status": "agent_completed"}
        except Exception as e:
            logger.warning(f"AgentCore failed, falling back to direct: {e}")

    # ============================================
    # Fallback: 직접 모델 호출 (Phase 1 방식)
    # ============================================
    logger.info("Using direct Bedrock model (fallback)")

    github_token = get_secret(GITHUB_TOKEN_SECRET_ARN)
    slack_token = get_secret(SLACK_TOKEN_SECRET_ARN)

    diff = get_pr_diff(event["pr_number"], github_token)
    files = get_pr_files(event["pr_number"], github_token)
    changed_filenames = [f["filename"] for f in files]
    logger.info(f"Fetched diff ({len(diff)} chars) and {len(files)} files")

    author_history = get_past_reviews_by_author(event["pr_author"])
    file_history = get_past_reviews_by_files(changed_filenames)
    repo_stats = get_repo_review_stats()
    matched_incidents = match_known_incidents(diff, files)

    logger.info(
        f"Memory context: {len(author_history)} author reviews, "
        f"{len(file_history)} file reviews, "
        f"{len(matched_incidents)} incident matches"
    )

    prompt = build_analysis_prompt(
        event, diff, files,
        author_history, file_history,
        repo_stats, matched_incidents,
    )

    analysis = invoke_bedrock_direct(prompt)
    logger.info(f"Analysis complete: Risk {analysis['risk_score']}/100 ({analysis['risk_level']})")

    post_github_comment(event["pr_number"], analysis, github_token)
    post_slack_report(event, analysis, slack_token)
    save_review_history(event, analysis, changed_filenames)

    return {
        "pr_number": event["pr_number"],
        "risk_score": analysis["risk_score"],
        "verdict": analysis["verdict"],
    }
