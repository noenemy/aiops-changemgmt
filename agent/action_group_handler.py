"""Action Group Lambda — tools that the Bedrock Agent can call.

Tools:
  [PR]             get_pr_diff, get_pr_files, detect_change_type
  [DDB]            get_review_history, get_developer_profile, get_team_stats
  [Agent-as-Tool]  invoke_devops_agent, invoke_security_agent
  [Output]         post_github_comment, post_github_fix_suggestion, post_slack_report

Agent Memory and queryKnowledgeBase are exposed automatically by Bedrock Agent runtime.
"""

import json
import logging
import os
import urllib.request
import uuid
from datetime import datetime, timezone

import boto3
from boto3.dynamodb.conditions import Attr, Key

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# --- Clients ---
secrets_client = boto3.client("secretsmanager")
dynamodb = boto3.resource("dynamodb")
bedrock_agent_rt_local = boto3.client("bedrock-agent-runtime")

# --- Env ---
GITHUB_TOKEN_SECRET_ARN = os.environ["GITHUB_TOKEN_SECRET_ARN"]
SLACK_TOKEN_SECRET_ARN = os.environ["SLACK_TOKEN_SECRET_ARN"]
SLACK_CHANNEL_ID = os.environ["SLACK_CHANNEL_ID"]
GITHUB_REPO = os.environ["GITHUB_REPO"]

REVIEW_HISTORY_TABLE = os.environ.get("REVIEW_HISTORY_TABLE", "")
DEVELOPER_PROFILES_TABLE = os.environ.get("DEVELOPER_PROFILES_TABLE", "")
TEAM_STATS_TABLE = os.environ.get("TEAM_STATS_TABLE", "")

# DevOps/Security Agent stub config (empty = stub mode)
DEVOPS_AGENT_ID = os.environ.get("DEVOPS_AGENT_ID", "")
DEVOPS_AGENT_ALIAS_ID = os.environ.get("DEVOPS_AGENT_ALIAS_ID", "")
DEVOPS_AGENT_REGION = os.environ.get("DEVOPS_AGENT_REGION", "us-east-1")
SECURITY_AGENT_ID = os.environ.get("SECURITY_AGENT_ID", "")
SECURITY_AGENT_ALIAS_ID = os.environ.get("SECURITY_AGENT_ALIAS_ID", "")
SECURITY_AGENT_REGION = os.environ.get("SECURITY_AGENT_REGION", "us-east-1")

# --- Caches ---
_secrets_cache = {}
_templates_cache = {}

# --- Constants ---
IAC_EXTS = (".yaml", ".yml", ".tf", ".tfvars")
IAC_PATH_HINTS = ("infra/", "terraform/", "cdk/", "k8s/", "kubernetes/", "helm/", "chart.yaml", "kustomization.yaml")


def get_secret(arn: str) -> str:
    if arn not in _secrets_cache:
        resp = secrets_client.get_secret_value(SecretId=arn)
        _secrets_cache[arn] = resp["SecretString"]
    return _secrets_cache[arn]


def github_api(path: str, method: str = "GET", data: bytes = None,
               accept: str = "application/vnd.github.v3+json") -> str:
    token = get_secret(GITHUB_TOKEN_SECRET_ARN)
    url = f"https://api.github.com{path}"
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {token}",
        "Accept": accept,
        "Content-Type": "application/json",
        "User-Agent": "AIOps-ChangeManagement",
    })
    with urllib.request.urlopen(req) as resp:
        return resp.read().decode()


# ============================================================
# PR tools
# ============================================================

def get_pr_diff(pr_number: int) -> str:
    diff = github_api(
        f"/repos/{GITHUB_REPO}/pulls/{pr_number}",
        accept="application/vnd.github.v3.diff",
    )
    if len(diff) > 15000:
        diff = diff[:15000] + "\n... (truncated)"
    return diff


def get_pr_files(pr_number: int) -> str:
    resp = github_api(f"/repos/{GITHUB_REPO}/pulls/{pr_number}/files")
    files = json.loads(resp)
    summary = [
        {
            "filename": f["filename"],
            "additions": f["additions"],
            "deletions": f["deletions"],
            "status": f["status"],
        }
        for f in files
    ]
    return json.dumps(summary, ensure_ascii=False)


def detect_change_type(pr_number: int) -> str:
    """Classify PR as code / iac / mixed based on file paths."""
    resp = github_api(f"/repos/{GITHUB_REPO}/pulls/{pr_number}/files")
    files = json.loads(resp)

    has_iac = False
    has_code = False
    iac_files = []
    code_files = []

    for f in files:
        fn = f["filename"].lower()
        is_iac = fn.endswith(IAC_EXTS) or any(h in fn for h in IAC_PATH_HINTS)
        if is_iac:
            has_iac = True
            iac_files.append(f["filename"])
        else:
            has_code = True
            code_files.append(f["filename"])

    if has_iac and has_code:
        change_type = "mixed"
    elif has_iac:
        change_type = "iac"
    else:
        change_type = "code"

    return json.dumps({
        "change_type": change_type,
        "iac_files": iac_files[:10],
        "code_files": code_files[:10],
    }, ensure_ascii=False)


# ============================================================
# DDB tools
# ============================================================

def get_review_history(author: str = "", files: str = "", limit: int = 5) -> str:
    """Query review-history DDB.

    Args:
      author: filter by prAuthor (optional)
      files: comma-separated file basenames to match (optional)
      limit: max results (default 5)
    """
    if not REVIEW_HISTORY_TABLE:
        return json.dumps({"error": "REVIEW_HISTORY_TABLE not configured"})

    try:
        table = dynamodb.Table(REVIEW_HISTORY_TABLE)
        filter_expr = None
        if author:
            filter_expr = Attr("prAuthor").eq(author)

        scan_kwargs = {"Limit": 50}
        if filter_expr is not None:
            scan_kwargs["FilterExpression"] = filter_expr

        resp = table.scan(**scan_kwargs)
        items = resp.get("Items", [])

        # File filter (client-side)
        if files:
            wanted = [f.strip().split("/")[-1].lower() for f in files.split(",") if f.strip()]
            items = [
                i for i in items
                if any(w in str(i.get("changedFiles", "")).lower() for w in wanted)
            ]

        items.sort(key=lambda x: x.get("reviewedAt", ""), reverse=True)
        items = items[:limit]

        # Convert Decimal → int for JSON
        cleaned = []
        for i in items:
            cleaned.append({
                "prKey": i.get("prKey"),
                "prTitle": i.get("prTitle"),
                "prAuthor": i.get("prAuthor"),
                "reviewedAt": i.get("reviewedAt", "")[:19],
                "riskScore": int(i.get("riskScore", 0)) if i.get("riskScore") is not None else None,
                "riskLevel": i.get("riskLevel"),
                "verdict": i.get("verdict"),
                "summary": (i.get("summary") or "")[:200],
            })
        return json.dumps({"count": len(cleaned), "reviews": cleaned}, ensure_ascii=False)
    except Exception as e:
        logger.error(f"get_review_history failed: {e}")
        return json.dumps({"error": str(e)})


def get_developer_profile(author: str) -> str:
    """Lookup developer profile by author key."""
    if not DEVELOPER_PROFILES_TABLE:
        return json.dumps({"error": "DEVELOPER_PROFILES_TABLE not configured"})
    try:
        table = dynamodb.Table(DEVELOPER_PROFILES_TABLE)
        resp = table.get_item(Key={"author": author})
        item = resp.get("Item")
        if not item:
            return json.dumps({"found": False, "author": author})
        return json.dumps({"found": True, "profile": _ddb_item_to_json(item)}, ensure_ascii=False)
    except Exception as e:
        logger.error(f"get_developer_profile failed: {e}")
        return json.dumps({"error": str(e)})


def get_team_stats(team_id: str, period: str = "") -> str:
    """Fetch team stats. If period is empty, returns latest."""
    if not TEAM_STATS_TABLE:
        return json.dumps({"error": "TEAM_STATS_TABLE not configured"})
    try:
        table = dynamodb.Table(TEAM_STATS_TABLE)
        if period:
            resp = table.get_item(Key={"teamId": team_id, "period": period})
            item = resp.get("Item")
            if not item:
                return json.dumps({"found": False})
            return json.dumps({"found": True, "stats": _ddb_item_to_json(item)}, ensure_ascii=False)
        # latest: Query with ScanIndexForward=False
        resp = table.query(
            KeyConditionExpression=Key("teamId").eq(team_id),
            ScanIndexForward=False,
            Limit=1,
        )
        items = resp.get("Items", [])
        if not items:
            return json.dumps({"found": False})
        return json.dumps({"found": True, "stats": _ddb_item_to_json(items[0])}, ensure_ascii=False)
    except Exception as e:
        logger.error(f"get_team_stats failed: {e}")
        return json.dumps({"error": str(e)})


def _ddb_item_to_json(item: dict) -> dict:
    """Convert DDB types (Decimal, Set) to JSON-serializable."""
    out = {}
    for k, v in item.items():
        if hasattr(v, "is_integer"):
            out[k] = int(v) if v == int(v) else float(v)
        elif isinstance(v, set):
            out[k] = list(v)
        else:
            out[k] = v
    return out


# ============================================================
# Agent-as-Tool stubs (DevOps / Security)
# ============================================================

def _invoke_remote_agent(agent_id: str, alias_id: str, region: str,
                         label: str, query: str, context: str) -> dict:
    """Invoke a remote Bedrock Agent in another region. Stub if not configured."""
    if not agent_id or not alias_id:
        logger.info(f"[{label}] stub mode (no agent_id configured)")
        return {
            "source": "stub",
            "agent": label,
            "answer": (
                f"[{label} 연동 예정] 실제 에이전트가 연결되면 이 질의를 처리합니다.\n"
                f"질의: {query[:200]}"
            ),
        }

    try:
        client = boto3.client("bedrock-agent-runtime", region_name=region)
        resp = client.invoke_agent(
            agentId=agent_id,
            agentAliasId=alias_id,
            sessionId=f"{label.lower()}-{uuid.uuid4().hex[:12]}",
            inputText=f"{query}\n\nContext:\n{context[:4000]}",
        )
        completion = ""
        for event in resp["completion"]:
            if "chunk" in event:
                completion += event["chunk"]["bytes"].decode()
        return {"source": "live", "agent": label, "answer": completion[:4000]}
    except Exception as e:
        logger.error(f"[{label}] invoke failed: {e}")
        return {"source": "error", "agent": label, "answer": f"호출 실패: {e}"}


def invoke_devops_agent(query: str, context: str = "") -> str:
    result = _invoke_remote_agent(
        DEVOPS_AGENT_ID, DEVOPS_AGENT_ALIAS_ID, DEVOPS_AGENT_REGION,
        "DevOps", query, context,
    )
    return json.dumps(result, ensure_ascii=False)


def invoke_security_agent(query: str, context: str = "") -> str:
    result = _invoke_remote_agent(
        SECURITY_AGENT_ID, SECURITY_AGENT_ALIAS_ID, SECURITY_AGENT_REGION,
        "Security", query, context,
    )
    return json.dumps(result, ensure_ascii=False)


# ============================================================
# GitHub output tools
# ============================================================

def post_github_comment(pr_number: int, comment_body: str) -> str:
    data = json.dumps({"body": comment_body}).encode()
    github_api(
        f"/repos/{GITHUB_REPO}/issues/{pr_number}/comments",
        method="POST",
        data=data,
    )
    return f"Comment posted on PR #{pr_number}"


# NOTE: post_github_fix_suggestion was merged into post_github_comment.
# For /fix command, the agent prepends "## 🔧 AI Fix Suggestion" itself.


# ============================================================
# Slack output (template-driven, see slack_templates/)
# ============================================================

from slack_templates._renderer import render_template  # noqa: E402


def post_slack_report(report_json: str) -> str:
    """Render a Slack template with given context and post to channel.

    Expected keys in report_json:
      template (str, optional): template name under slack_templates/ (default: auto by change_type)
      pr_number, pr_title, pr_author, pr_url
      change_type (code|iac|mixed)
      risk_score, risk_level, verdict
      summary
      issues_text, incident_match, developer_pattern, infra_impact (mrkdwn, optional)
      agent_persona (str)
    """
    try:
        ctx = json.loads(report_json)
    except Exception as e:
        return f"Invalid report_json: {e}"

    template = ctx.get("template")
    if not template:
        change_type = ctx.get("change_type", "code")
        template = "infra_review" if change_type in ("iac", "mixed") else "code_review"

    # Derive helper fields
    ctx.setdefault("risk_emoji", _risk_emoji(ctx.get("risk_level", "LOW")))
    ctx.setdefault("verdict_label",
                   "✅ CI/CD 자동 실행" if ctx.get("verdict") == "APPROVE" else "🚫 CI/CD 파이프라인 스킵")
    ctx.setdefault("change_type_label", _change_type_label(ctx.get("change_type", "code")))
    ctx.setdefault("timestamp", datetime.now(timezone.utc).isoformat(timespec="seconds"))

    try:
        blocks = render_template(template, ctx)
    except Exception as e:
        logger.error(f"Template render failed ({template}): {e}")
        return f"Template render error: {e}"

    return _post_slack_blocks(
        blocks,
        fallback_text=f"PR #{ctx.get('pr_number')} 분석 완료 — Risk {ctx.get('risk_score')}/100",
    )


def _risk_emoji(level: str) -> str:
    return {"LOW": "🟢", "MEDIUM": "🟡", "HIGH": "🔴", "CRITICAL": "🔴"}.get(level, "⚪")


def _change_type_label(change_type: str) -> str:
    return {"code": "코드 리뷰", "iac": "인프라 변경", "mixed": "코드 + 인프라"}.get(change_type, "변경")


def _post_slack_blocks(blocks: list, fallback_text: str) -> str:
    slack_token = get_secret(SLACK_TOKEN_SECRET_ARN)
    payload = json.dumps({
        "channel": SLACK_CHANNEL_ID,
        "blocks": blocks,
        "text": fallback_text,
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
        logger.error(f"Slack error: {result.get('error')}")
        return f"Slack API error: {result.get('error')}"
    return f"Slack report posted (ts={result.get('ts')})"


# ============================================================
# Bedrock Agent Action Group handler
# ============================================================

def get_param(params: list, name: str, default: str = "") -> str:
    for p in params:
        if p["name"] == name:
            return p.get("value", default)
    return default


TOOL_REGISTRY = {
    "get_pr_diff":              lambda p: get_pr_diff(int(get_param(p, "pr_number"))),
    "get_pr_files":             lambda p: get_pr_files(int(get_param(p, "pr_number"))),
    "detect_change_type":       lambda p: detect_change_type(int(get_param(p, "pr_number"))),
    "get_review_history":       lambda p: get_review_history(
                                    author=get_param(p, "author"),
                                    files=get_param(p, "files"),
                                    limit=int(get_param(p, "limit", "5")),
                                 ),
    "get_developer_profile":    lambda p: get_developer_profile(get_param(p, "author")),
    "get_team_stats":           lambda p: get_team_stats(
                                    team_id=get_param(p, "team_id"),
                                    period=get_param(p, "period"),
                                 ),
    "invoke_devops_agent":      lambda p: invoke_devops_agent(
                                    query=get_param(p, "query"),
                                    context=get_param(p, "context"),
                                 ),
    "invoke_security_agent":    lambda p: invoke_security_agent(
                                    query=get_param(p, "query"),
                                    context=get_param(p, "context"),
                                 ),
    "post_github_comment":      lambda p: post_github_comment(
                                    int(get_param(p, "pr_number")),
                                    get_param(p, "comment_body"),
                                 ),
    "post_slack_report":        lambda p: post_slack_report(get_param(p, "report_json")),
}


def handler(event, context):
    logger.info(f"Action group event: {json.dumps(event, default=str)[:500]}")
    action = event.get("actionGroup", "")
    function = event.get("function", "")
    params = event.get("parameters", [])
    logger.info(f"Function: {function}, Params: {[p['name'] for p in params]}")

    try:
        fn = TOOL_REGISTRY.get(function)
        if fn is None:
            result = f"Unknown function: {function}"
        else:
            result = fn(params)
    except Exception as e:
        logger.error(f"Error in {function}: {e}", exc_info=True)
        result = f"Error: {e}"

    logger.info(f"Result length: {len(str(result))}")
    return {
        "messageVersion": "1.0",
        "response": {
            "actionGroup": action,
            "function": function,
            "functionResponse": {
                "responseBody": {"TEXT": {"body": str(result)}}
            },
        },
    }
