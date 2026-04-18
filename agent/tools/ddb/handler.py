"""ddb_tools Lambda — DynamoDB reads.

Tools:
  get_review_history(author?, files?, limit=5) -> {count, reviews}
  get_developer_profile(author) -> {found, profile}
"""

import json
import os
import boto3
from boto3.dynamodb.conditions import Attr

from common import err, ok, parse_event

REVIEW_HISTORY_TABLE = os.environ["REVIEW_HISTORY_TABLE"]
DEVELOPER_PROFILES_TABLE = os.environ["DEVELOPER_PROFILES_TABLE"]

_ddb = boto3.resource("dynamodb")


def _clean(item: dict) -> dict:
    out = {}
    for k, v in item.items():
        if hasattr(v, "is_integer"):
            out[k] = int(v) if v == int(v) else float(v)
        elif isinstance(v, set):
            out[k] = list(v)
        else:
            out[k] = v
    return out


def get_review_history(author: str = "", files: str = "", limit: int = 5) -> dict:
    table = _ddb.Table(REVIEW_HISTORY_TABLE)
    scan_kwargs = {"Limit": 50}
    if author:
        scan_kwargs["FilterExpression"] = Attr("prAuthor").eq(author)
    resp = table.scan(**scan_kwargs)
    items = resp.get("Items", [])

    if files:
        wanted = [f.strip().split("/")[-1].lower() for f in files.split(",") if f.strip()]
        items = [i for i in items
                 if any(w in str(i.get("changedFiles", "")).lower() for w in wanted)]

    items.sort(key=lambda x: x.get("reviewedAt", ""), reverse=True)
    items = items[:limit]

    reviews = [{
        "prKey": i.get("prKey"),
        "prTitle": i.get("prTitle"),
        "prAuthor": i.get("prAuthor"),
        "reviewedAt": (i.get("reviewedAt") or "")[:19],
        "riskScore": int(i["riskScore"]) if i.get("riskScore") is not None else None,
        "riskLevel": i.get("riskLevel"),
        "verdict": i.get("verdict"),
        "summary": (i.get("summary") or "")[:200],
    } for i in items]
    return {"count": len(reviews), "reviews": reviews}


def get_developer_profile(author: str) -> dict:
    table = _ddb.Table(DEVELOPER_PROFILES_TABLE)
    resp = table.get_item(Key={"author": author})
    item = resp.get("Item")
    if not item:
        return {"found": False, "author": author}
    return {"found": True, "profile": _clean(item)}


TOOLS = {
    "get_review_history": lambda a: get_review_history(
        author=a.get("author", ""),
        files=a.get("files", ""),
        limit=int(a.get("limit", 5)),
    ),
    "get_developer_profile": lambda a: get_developer_profile(a["author"]),
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
