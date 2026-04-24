"""subagent_tools Lambda — DevOps / Security sub-agent stubs.

Tools:
  invoke_devops_agent(query, context?) -> {source, agent, answer}
  invoke_security_agent(query, context?) -> {source, agent, answer}

Connection priority for each sub-agent:
  1. <AGENT>_WEBHOOK_URL (+ optional <AGENT>_WEBHOOK_SECRET) — external agent
     exposed via a generic webhook (e.g. AWS AI Ops investigation endpoint).
     The exact payload schema is provider-specific; we try a couple of common
     shapes and return whatever the service replies.
  2. <AGENT>_RUNTIME_ARN — another Bedrock AgentCore Runtime.
  3. Otherwise return a stub so the main agent can still produce a reply.
"""

import json
import os
import urllib.request
import uuid

import boto3

from common import err, ok, parse_event

def _env(name: str) -> str:
    # CloudFormation can't pass an empty string, so we use "none" as a
    # sentinel for "unset" across DevOps/Security env vars.
    v = os.environ.get(name, "")
    return "" if v in ("", "none") else v


DEVOPS_RUNTIME_ARN = _env("DEVOPS_RUNTIME_ARN")
SECURITY_RUNTIME_ARN = _env("SECURITY_RUNTIME_ARN")
DEVOPS_WEBHOOK_URL = _env("DEVOPS_WEBHOOK_URL")
DEVOPS_WEBHOOK_SECRET = _env("DEVOPS_WEBHOOK_SECRET")
SECURITY_WEBHOOK_URL = _env("SECURITY_WEBHOOK_URL")
SECURITY_WEBHOOK_SECRET = _env("SECURITY_WEBHOOK_SECRET")

_rt = None


def _runtime():
    global _rt
    if _rt is None:
        _rt = boto3.client("bedrock-agentcore")
    return _rt


def _call_webhook(url: str, secret: str, label: str, query: str,
                  context_text: str) -> dict:
    """Call an external agent webhook. Provider schemas vary — we send our
    canonical payload and return the raw reply for the main agent to summarize.
    """
    body = json.dumps({
        "agent": label,
        "query": query,
        "context": context_text[:4000],
    }).encode()
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {secret}" if secret else "",
            "X-Webhook-Secret": secret or "",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf8", errors="replace")[:4000]
        return {"source": "webhook", "agent": label, "answer": raw}
    except Exception as e:
        # Fall through to stub so the agent still has *something* to cite.
        return {
            "source": "webhook_error",
            "agent": label,
            "answer": f"[{label} webhook 호출 실패: {e}] 질의: {query[:200]}",
        }


def _call_runtime(runtime_arn: str, label: str, query: str,
                  context_text: str) -> dict:
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


def _invoke(label: str, webhook_url: str, webhook_secret: str,
            runtime_arn: str, query: str, context_text: str) -> dict:
    if webhook_url:
        return _call_webhook(webhook_url, webhook_secret, label, query, context_text)
    if runtime_arn:
        return _call_runtime(runtime_arn, label, query, context_text)
    return {
        "source": "stub",
        "agent": label,
        "answer": f"[{label} 연동 예정] 실제 에이전트 연결 시 처리. 질의: {query[:200]}",
    }


TOOLS = {
    "invoke_devops_agent": lambda a: _invoke(
        "DevOps", DEVOPS_WEBHOOK_URL, DEVOPS_WEBHOOK_SECRET,
        DEVOPS_RUNTIME_ARN, a["query"], a.get("context", ""),
    ),
    "invoke_security_agent": lambda a: _invoke(
        "Security", SECURITY_WEBHOOK_URL, SECURITY_WEBHOOK_SECRET,
        SECURITY_RUNTIME_ARN, a["query"], a.get("context", ""),
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
