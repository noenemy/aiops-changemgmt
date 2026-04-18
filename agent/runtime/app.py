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
- Slack: post_slack_report 에 JSON 문자열 전달. 필드: pr_number, pr_title, pr_author, pr_url, change_type, risk_score, risk_level, verdict, summary(한국어), issues_text, incident_match, developer_pattern, infra_impact, agent_persona. 없으면 빈 문자열.

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

FIX_PROMPT_SUFFIX = """

# 이번 호출은 /fix 명령
- 기존 리뷰 이슈를 참조하여 구체적 수정안 제시
- post_github_comment 시 본문 앞에 '## 🔧 AI Fix Suggestion' 헤더 추가
- post_slack_report 시 template="command_fix" 필드 포함
"""

# --- Memory helpers ---

def _actor_for_repo(repo: str) -> str:
    return f"repo:{repo}"


def _load_repo_memory(repo: str, limit: int = 5) -> str:
    """Return a short text summary of past sessions for this repo.

    list_events requires a sessionId, so we list the most recent sessions for
    the repo actor first, then pull a few events from each.
    """
    try:
        actor = _actor_for_repo(repo)
        sess_resp = _memory_client.list_sessions(
            memoryId=MEMORY_ID, actorId=actor, maxResults=limit,
        )
        summaries = sess_resp.get("sessionSummaries", [])
        if not summaries:
            return ""
        lines = []
        for s in summaries:
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
                        lines.append(f"- [{ts}] {text[:300]}")
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
        return _run_agent(payload["prompt"], repo=None, session_id=None, is_fix=False)

    pr_number = payload["pr_number"]
    repo = payload["repo"]
    command = payload.get("command", "analysis")
    is_fix = command == "fix"

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

    answer = _run_agent(header, repo=repo, session_id=session_id, is_fix=is_fix)
    _record_session(repo, session_id, answer)
    return {"session_id": session_id, "answer": answer}


def _run_agent(user_text: str, repo: str | None, session_id: str | None, is_fix: bool) -> str:
    model = BedrockModel(model_id=MODEL_ID, region_name=REGION)
    system = SYSTEM_PROMPT + (FIX_PROMPT_SUFFIX if is_fix else "")

    mcp_client = _build_mcp_client()
    with mcp_client:
        tools = mcp_client.list_tools_sync()
        logger.info(f"Loaded {len(tools)} MCP tools from gateway")
        agent = Agent(model=model, system_prompt=system, tools=tools)
        result = agent(user_text)
        return str(result)


if __name__ == "__main__":
    app.run()
