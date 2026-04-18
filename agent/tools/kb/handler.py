"""kb_tools Lambda — Bedrock Knowledge Base retrieval.

Tools:
  query_knowledge_base(query, max_results=5) -> {matches: [...]}
"""

import os

import boto3

from common import err, ok, parse_event

KNOWLEDGE_BASE_ID = os.environ["KNOWLEDGE_BASE_ID"]
_bedrock = boto3.client("bedrock-agent-runtime")


def query_knowledge_base(query: str, max_results: int = 5) -> dict:
    resp = _bedrock.retrieve(
        knowledgeBaseId=KNOWLEDGE_BASE_ID,
        retrievalQuery={"text": query},
        retrievalConfiguration={
            "vectorSearchConfiguration": {"numberOfResults": int(max_results)}
        },
    )
    matches = []
    for r in resp.get("retrievalResults", []):
        matches.append({
            "text": (r.get("content", {}).get("text") or "")[:1500],
            "score": r.get("score"),
            "source": r.get("location", {}).get("s3Location", {}).get("uri"),
        })
    return {"matches": matches}


TOOLS = {
    "query_knowledge_base": lambda a: query_knowledge_base(
        query=a["query"], max_results=int(a.get("max_results", 5))
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
