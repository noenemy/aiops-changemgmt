"""subagent_tools Lambda — DevOps / Security sub-agent stubs.

Tools:
  invoke_devops_agent(query, context?) -> {source, agent, answer}
  invoke_security_agent(query, context?) -> {source, agent, answer}

Real sub-agents are not yet connected. If <AGENT>_RUNTIME_ARN env var is set,
calls out to Bedrock AgentCore InvokeAgentRuntime; otherwise stubbed.
"""

import json
import os
import uuid

import boto3

from common import err, ok, parse_event

DEVOPS_RUNTIME_ARN = os.environ.get("DEVOPS_RUNTIME_ARN", "")
SECURITY_RUNTIME_ARN = os.environ.get("SECURITY_RUNTIME_ARN", "")

_rt = None


def _runtime():
    global _rt
    if _rt is None:
        _rt = boto3.client("bedrock-agentcore")
    return _rt


def _invoke(runtime_arn: str, label: str, query: str, context_text: str) -> dict:
    if not runtime_arn:
        return {
            "source": "stub",
            "agent": label,
            "answer": f"[{label} 연동 예정] 실제 에이전트 연결 시 처리. 질의: {query[:200]}",
        }
    try:
        payload = json.dumps({"query": query, "context": context_text[:4000]}).encode()
        resp = _runtime().invoke_agent_runtime(
            agentRuntimeArn=runtime_arn,
            runtimeSessionId=f"{label.lower()}-{uuid.uuid4().hex[:12]}",
            payload=payload,
        )
        body = resp.get("response", b"")
        if hasattr(body, "read"):
            body = body.read()
        return {"source": "live", "agent": label, "answer": body.decode()[:4000]}
    except Exception as e:
        return {"source": "error", "agent": label, "answer": f"호출 실패: {e}"}


TOOLS = {
    "invoke_devops_agent": lambda a: _invoke(
        DEVOPS_RUNTIME_ARN, "DevOps", a["query"], a.get("context", "")
    ),
    "invoke_security_agent": lambda a: _invoke(
        SECURITY_RUNTIME_ARN, "Security", a["query"], a.get("context", "")
    ),
}


def handler(event, context):
    tool, args, _ = parse_event(event, context)
    fn = TOOLS.get(tool)
    if fn is None:
        return err(f"Unknown tool: {tool}")
    try:
        return ok(fn(args))
    except KeyError as e:
        return err(f"Missing arg: {e}")
    except Exception as e:
        return err(f"Tool error: {e}", code=500)
