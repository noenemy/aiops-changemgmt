"""Shared helpers for AgentCore Gateway target Lambdas.

Gateway target Lambdas receive events in one of two shapes:

1) Direct invocation from Runtime (MCP-passthrough):
   {"tool": "<name>", "arguments": {...}}

2) Smithy/OpenAPI spec via Gateway (operation in context):
   - event body carries `arguments`
   - tool/operation name in `context.client_context.custom["bedrockAgentCoreToolName"]`

We normalize both into `(tool_name, args_dict)` and return a plain JSON-serializable
dict / string so Gateway can wrap it into the MCP response envelope.
"""

import json
import logging
import os
import time

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

_secrets_client = None
_secrets_cache = {}
_ddb = None

DEDUP_TABLE = os.environ.get("DEDUP_TABLE", "")
DEDUP_TTL_SECONDS = int(os.environ.get("DEDUP_TTL_SECONDS", "86400"))  # 24h


def _ddb_resource():
    global _ddb
    if _ddb is None:
        _ddb = boto3.resource("dynamodb")
    return _ddb


def claim_dedup(session_id: str, tool_name: str) -> bool:
    """Return True if this (session, tool) claim is new; False if already taken.

    Used by post-output tools to prevent duplicate GitHub comments / Slack posts
    when the Runtime retries inside the same session.
    """
    if not DEDUP_TABLE or not session_id or not tool_name:
        return True
    key = f"{session_id}#{tool_name}"
    try:
        _ddb_resource().Table(DEDUP_TABLE).put_item(
            Item={"dedupKey": key, "ttl": int(time.time()) + DEDUP_TTL_SECONDS,
                  "claimedAt": int(time.time())},
            ConditionExpression="attribute_not_exists(dedupKey)",
        )
        return True
    except _ddb_resource().meta.client.exceptions.ConditionalCheckFailedException:
        logger.info(f"dedup: skip duplicate {key}")
        return False
    except Exception as exc:
        logger.warning(f"dedup check skipped on error: {exc}")
        return True  # fail-open — better to duplicate than block


def secrets():
    global _secrets_client
    if _secrets_client is None:
        _secrets_client = boto3.client("secretsmanager")
    return _secrets_client


def get_secret(arn: str) -> str:
    if arn not in _secrets_cache:
        resp = secrets().get_secret_value(SecretId=arn)
        _secrets_cache[arn] = resp["SecretString"]
    return _secrets_cache[arn]


def parse_event(event, context):
    """Return (tool_name, args_dict, session_id) regardless of invocation style.

    Gateway forwards MCP tool names as `{target}___{tool}` and passes the
    Runtime session id via context.client_context.custom.bedrockAgentCoreSessionId.
    """
    tool_name = None
    session_id = ""
    args = {}

    if context is not None:
        try:
            cc = getattr(context, "client_context", None)
            if cc and hasattr(cc, "custom"):
                tool_name = cc.custom.get("bedrockAgentCoreToolName")
                session_id = cc.custom.get("bedrockAgentCoreSessionId", "")
        except Exception:
            pass

    if isinstance(event, dict):
        if not tool_name:
            tool_name = event.get("tool") or event.get("tool_name") or event.get("name")
        if not session_id:
            session_id = event.get("session_id", "")
        args = event.get("arguments") or event.get("args") or {}
        if not args and isinstance(event.get("body"), str):
            try:
                body = json.loads(event["body"])
                args = body.get("arguments") or body
            except Exception:
                pass
        if not args:
            non_meta = {k: v for k, v in event.items()
                        if k not in ("tool", "tool_name", "name", "arguments",
                                     "args", "body", "session_id")}
            if non_meta:
                args = non_meta

    if tool_name and "___" in tool_name:
        tool_name = tool_name.split("___", 1)[1]

    return tool_name, args or {}, session_id


def ok(payload) -> dict:
    if isinstance(payload, (dict, list)):
        body = json.dumps(payload, ensure_ascii=False)
    else:
        body = str(payload)
    return {"statusCode": 200, "body": body}


def err(message: str, code: int = 400) -> dict:
    return {"statusCode": code, "body": json.dumps({"error": message}, ensure_ascii=False)}
