"""AgentCore Runtime entrypoint — Strands Agent with 3 Persona orchestration.

Invoked by analysis Lambda via bedrock-agentcore:InvokeAgentRuntime.

Payload shape:
  {
    "pr_number": int,
    "repo": str,          # "owner/name"
    "pr_title": str,
    "pr_author": str,
    "pr_url": str,
    "command": "analysis" | "fix"   # reject doesn't hit the agent
  }

Uses:
- Strands Agent (Claude on Bedrock)
- AgentCore Gateway via MCP client (tools are surfaced by Gateway targets)
- AgentCore Memory for session + long-term summaries
"""

import base64
import json
import logging
import os
import time
import urllib.parse
import urllib.request

import boto3
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from mcp.client.streamable_http import streamablehttp_client
from strands import Agent
from strands.models import BedrockModel
from strands.tools.mcp.mcp_client import MCPClient

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# --- Env ---
MODEL_ID = os.environ.get("BEDROCK_MODEL_ID", "global.anthropic.claude-sonnet-4-6")
GATEWAY_URL = os.environ["GATEWAY_URL"]          # MCP endpoint URL
MEMORY_ID = os.environ["MEMORY_ID"]              # AgentCore Memory resource id
REGION = os.environ.get("AWS_REGION", "us-east-1")
COGNITO_DOMAIN = os.environ.get("COGNITO_DOMAIN", "")
COGNITO_CLIENT_ID = os.environ.get("COGNITO_CLIENT_ID", "")
COGNITO_CLIENT_SECRET = os.environ.get("COGNITO_CLIENT_SECRET", "")
COGNITO_SCOPE = os.environ.get("COGNITO_SCOPE", "")

_token_cache = {"value": None, "expires_at": 0.0}

_memory_client = boto3.client("bedrock-agentcore", region_name=REGION)

# --- System prompt (3 Persona) ---
SYSTEM_PROMPT = """당신은 AIOps ChangeManagement 오케스트레이터입니다.
PR 유형에 따라 3개 Persona(CodeReviewer/InfraReviewer/RiskJudge)를 전환하며 분석합니다.

# 작업 순서
1. detect_change_type(pr_number) → code / iac / mixed 판별
2. get_pr_diff, get_pr_files 로 변경 내용 파악
3. 유형별 Persona 활성화
   - code: CodeReviewer / iac: InfraReviewer / mixed: 두 Persona 순차
4. 각 Persona는 query_knowledge_base 와 DDB 도구 활용
5. RiskJudge 가 종합해 Risk Score, Verdict 결정
6. post_github_comment + post_slack_report 로 결과 전달

# Persona
- CodeReviewer: 보안/성능/안정성/호환성. 도구: query_knowledge_base, get_review_history, get_developer_profile, invoke_security_agent. 의심 패턴은 KB 검색, 보안 HIGH/CRITICAL은 invoke_security_agent.
- InfraReviewer: *.yaml/*.tf, infra/**, terraform/**, cdk/**, k8s/**, helm/**. 분석축: 리소스 영향/IAM/데이터 보존/비용/Drift. 도구: query_knowledge_base, invoke_devops_agent, invoke_security_agent. IAM 변경은 반드시 invoke_security_agent, Replacement 유발은 경고.
- RiskJudge: 종합해 Risk Score 산출. 0-20 LOW APPROVE / 21-50 MEDIUM APPROVE / 51-80 HIGH REJECT / 81-100 CRITICAL REJECT. CRITICAL 1개↑ 또는 HIGH 2개↑ → REJECT. 이전 세션 요약에서 반복 패턴 확인 시 가중치 +10~20.

# 출력
- GitHub 코멘트: 마크다운(risk score + 판정 + 이슈 + 과거 장애 + 개발자 패턴)
- Slack: post_slack_report 에 **단일 JSON 문자열** 전달 (report_json 필드).

## Slack JSON 필수 필드
- pr_number, pr_title, pr_author, pr_url, change_type(code|iac|mixed)
- risk_score (정수 0-100), risk_level (LOW|MEDIUM|HIGH|CRITICAL), verdict (APPROVE|REJECT)
- summary: 한국어 2-3문장, 글머리기호 없이 짧게
- agent_persona: "CodeReviewer", "InfraReviewer", "RiskJudge" 중 하나 또는 조합

## Slack JSON 시각화 필드 (새 스키마 — 반드시 채울 것)
- code_block: 문자열. PR diff 에서 **위험 핵심 부분 30-50줄** 발췌.
  diff 기호(+/-) 포함. 변경 없는 맥락 줄은 최소 3줄 남김.
  불필요한 import, 공백 라인은 제거.
- issues: **JSON 배열**. 최대 5개. 각 항목 구조:
    {
      "severity": "CRITICAL"|"HIGH"|"MEDIUM"|"LOW",
      "title": "짧은 이슈 제목 (예: TOCTOU Race Condition)",
      "line_range": "L42-48" 또는 "create_order.py:42",
      "code": "문제가 되는 실제 코드 스니펫 (5-15줄)",
      "why": "왜 위험한지 1-2문장 (한국어)",
      "fix": "수정된 코드 스니펫 (선택, 없으면 빈 문자열)"
    }
- incident_match: "INC-0042 (2026-01-15, P1, ₩12M 손실)" 처럼 한 줄 요약.
  **엄격한 연관성 기준**: KB 에서 찾은 과거 장애가 본 PR 의 위험 패턴과
  동일한 취약점 유형(예: TOCTOU vs TOCTOU, Secrets leak vs Secrets leak,
  Breaking API vs Breaking API, N+1 vs N+1) 일 때만 포함한다.
  "참고용", "패턴 불일치", "유사하지만 다른 패턴" 같은 단서를 붙여야 한다면
  **반드시 빈 문자열로 둔다**. 억지 매칭 금지 — 없으면 없다고 답하는 게 정답.
- incident_code: KB 에서 찾은 과거 장애 재현 코드 스니펫 (5-10줄)
  incident_match 가 빈 문자열이면 incident_code 도 반드시 빈 문자열
- developer_pattern: 한국어 1-2문장. 최근 리뷰 이력 기반
- infra_impact: iac/mixed 일 때만. code 타입이면 빈 문자열

## 주의
- code_block / code / fix 내부에 백틱(```) 포함 금지 (Slack 렌더 깨짐)
- issues 배열은 빈 배열 [] 가능. 이슈 없으면 verdict=APPROVE
- incident_code 에는 실제 KB 검색에서 얻은 코드 스니펫만 포함. 추측 금지

# 원칙
- 하드코딩 금지: 장애/정책은 query_knowledge_base
- 한국어 응답, 근거 필수
- Stub 서브 에이전트("source":"stub")는 부분 반영

# 출력 도구 호출 규칙 (엄격)
- post_github_comment 는 세션 전체에서 정확히 1번만 호출한다. 한 번 호출했으면 절대 재호출하지 않는다.
- post_slack_report 도 세션 전체에서 정확히 1번만 호출한다.
- 위 두 도구가 에러를 리턴해도 재시도하지 말고 바로 종료한다.
- 두 도구 호출이 끝나면 더 이상 도구를 호출하지 말고 한국어 최종 요약만 리턴한다.
"""

INVESTIGATE_PROMPT_SUFFIX = """

# 이번 호출은 /investigate 명령 — DevOpsInvestigator 페르소나 활성화
- 이 호출의 목적은 새 PR 리뷰가 아니라, 운영 중 관측된 증상(장애·레이턴시·오류율 등)과
  지정된 PR 변경이 인과관계가 있는지 조사하는 것이다.
- 작업 순서:
  1) get_pr_diff / get_pr_files 로 변경 요약 확보
  2) query_knowledge_base 로 관련 runbook·incident 조회
  3) invoke_devops_agent 를 반드시 호출하여 외부 DevOps Agent 의견 수렴
     (실제 DevOps Agent 미연결 시 stub 응답이 오며, stub임을 리포트에 명시)
  4) RiskJudge 대신 DevOpsInvestigator 관점으로 가설·증거·권고 액션을 기술
- 출력 도구:
  - post_github_comment 본문 앞에 '## 🔍 AI Investigation' 헤더
  - post_slack_report 에 template="command_investigate" 포함.
    Slack JSON 필수 필드 중 verdict 는 APPROVE/REJECT 대신 "INVESTIGATE" 허용.
  - incident_match / incident_code 는 실제 관련성이 확인된 경우에만 채움.
- DevOps Agent 응답이 stub 인 경우 summary 에 "(DevOps Agent 연결 대기 중 — stub 기반 추정)" 문구를 포함한다.
"""

# --- Memory helpers ---

def _actor_for_repo(repo: str) -> str:
    return f"repo:{repo}"


def _load_repo_memory(repo: str, limit: int = 5) -> str:
    """Return a short text summary of past sessions for this repo.

    list_sessions returns entries in sessionId order, not chronological order,
    so we pull a larger page and sort by createdAt before taking the top N.
    Older-but-relevant review summaries (e.g. manually seeded history for
    demo authors) stay visible even after many recent sessions accumulate.
    """
    try:
        actor = _actor_for_repo(repo)
        sess_resp = _memory_client.list_sessions(
            memoryId=MEMORY_ID, actorId=actor, maxResults=100,
        )
        summaries = sess_resp.get("sessionSummaries", [])
        if not summaries:
            return ""
        summaries.sort(key=lambda s: s.get("createdAt") or 0, reverse=True)
        lines = []
        for s in summaries[:limit]:
            sid = s.get("sessionId")
            if not sid:
                continue
            ev_resp = _memory_client.list_events(
                memoryId=MEMORY_ID, actorId=actor, sessionId=sid, maxResults=2,
            )
            for e in ev_resp.get("events", []):
                ts = e.get("eventTimestamp", "")
                for p in e.get("payload", []):
                    text = (p.get("conversational", {}) or {}).get("content", {}).get("text", "")
                    if text:
                        lines.append(f"- [{ts}] {text[:500]}")
        return "\n".join(lines[:limit])
    except Exception as exc:
        logger.warning(f"Memory load skipped: {exc}")
        return ""


def _record_session(repo: str, session_id: str, summary: str):
    """Write the final response into Memory under the repo actor."""
    try:
        _memory_client.create_event(
            memoryId=MEMORY_ID,
            actorId=_actor_for_repo(repo),
            sessionId=session_id,
            eventTimestamp=int(time.time()),
            payload=[{
                "conversational": {
                    "role": "ASSISTANT",
                    "content": {"text": summary[:2000]},
                }
            }],
        )
    except Exception as exc:
        logger.warning(f"Memory write skipped: {exc}")


# --- MCP + Strands Agent ---

def _bearer_token() -> str:
    """Fetch a JWT from Cognito (client_credentials) for the Gateway MCP endpoint.

    Cached until ~60s before expiry.
    """
    now = time.time()
    if _token_cache["value"] and _token_cache["expires_at"] > now + 60:
        return _token_cache["value"]
    if not (COGNITO_DOMAIN and COGNITO_CLIENT_ID and COGNITO_CLIENT_SECRET):
        return os.environ.get("GATEWAY_BEARER_TOKEN", "")

    token_url = f"https://{COGNITO_DOMAIN}.auth.{REGION}.amazoncognito.com/oauth2/token"
    auth = base64.b64encode(f"{COGNITO_CLIENT_ID}:{COGNITO_CLIENT_SECRET}".encode()).decode()
    form = {"grant_type": "client_credentials"}
    if COGNITO_SCOPE:
        form["scope"] = COGNITO_SCOPE
    data = urllib.parse.urlencode(form).encode()

    req = urllib.request.Request(
        token_url, data=data, method="POST",
        headers={
            "Authorization": f"Basic {auth}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        payload = json.loads(resp.read())
    token = payload["access_token"]
    _token_cache["value"] = token
    _token_cache["expires_at"] = now + int(payload.get("expires_in", 3600))
    logger.info(f"Fetched Cognito JWT, expires in {payload.get('expires_in')}s")
    return token


def _build_mcp_client() -> MCPClient:
    token = _bearer_token()
    headers = {"Authorization": f"Bearer {token}"} if token else {}

    def _transport():
        return streamablehttp_client(GATEWAY_URL, headers=headers)

    return MCPClient(_transport)


app = BedrockAgentCoreApp()


@app.entrypoint
def invoke(payload, context=None):
    """AgentCore Runtime entrypoint.

    payload: dict with pr_number/repo/... as above (or {"prompt": "..."} for smoke tests)
    """
    logger.info(f"Runtime invoked: {json.dumps(payload, default=str)[:500]}")

    if isinstance(payload, (bytes, bytearray)):
        payload = json.loads(payload.decode())
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except Exception:
            payload = {"prompt": payload}

    # Smoke test path
    if "prompt" in payload and "pr_number" not in payload:
        return _run_agent(payload["prompt"], repo=None, session_id=None,
                          is_investigate=False)

    pr_number = payload["pr_number"]
    repo = payload["repo"]
    command = payload.get("command", "analysis")
    is_investigate = command == "investigate"

    # Session id derived from the gateway's runtime session if present
    session_id = (context or {}).get("session_id") if isinstance(context, dict) else None
    session_id = session_id or f"pr-{repo.replace('/', '-')}-{pr_number}-{int(time.time())}"

    past = _load_repo_memory(repo)
    header = f"""# 분석 요청
- PR: #{pr_number} ({payload.get('pr_title','')})
- Author: {payload.get('pr_author','')}
- URL: {payload.get('pr_url','')}
- Command: {command}

# 과거 이 레포의 세션 요약 (최근 {5}건, 비어있을 수 있음)
{past or '(없음)'}

위 정보를 바탕으로 System Prompt 의 작업 순서를 따라 PR을 분석하세요.
"""

    answer = _run_agent(header, repo=repo, session_id=session_id,
                        is_investigate=is_investigate)
    _record_session(repo, session_id, answer)
    return {"session_id": session_id, "answer": answer}


def _run_agent(user_text: str, repo: str | None, session_id: str | None,
               is_investigate: bool) -> str:
    model = BedrockModel(model_id=MODEL_ID, region_name=REGION)
    system = SYSTEM_PROMPT + (INVESTIGATE_PROMPT_SUFFIX if is_investigate else "")

    mcp_client = _build_mcp_client()
    with mcp_client:
        tools = mcp_client.list_tools_sync()
        logger.info(f"Loaded {len(tools)} MCP tools from gateway")
        agent = Agent(model=model, system_prompt=system, tools=tools)
        result = agent(user_text)
        return str(result)


if __name__ == "__main__":
    app.run()
