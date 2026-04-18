"""Register 5 Lambda targets on the AgentCore MCP Gateway.

Run after the agentcore CFN stack + gateway are created.
Idempotent-ish: will skip a target if the name already exists.
"""

import json
import sys

import boto3

GATEWAY_ID = "aiops-changemgmt-gateway-c30ktnjtfk"
REGION = "us-east-1"

# From agentcore-template.yaml outputs
TOOLS = {
    "pr-tools": {
        "lambda_arn": "arn:aws:lambda:us-east-1:336093158955:function:aiops-changemgmt-agentcore-pr-tools",
        "schema": [
            {
                "name": "get_pr_diff",
                "description": "Fetch the diff of a GitHub Pull Request.",
                "inputSchema": {
                    "type": "object",
                    "properties": {"pr_number": {"type": "integer", "description": "PR number"}},
                    "required": ["pr_number"],
                },
            },
            {
                "name": "get_pr_files",
                "description": "Return the list of files changed in a PR (filename, additions, deletions, status).",
                "inputSchema": {
                    "type": "object",
                    "properties": {"pr_number": {"type": "integer"}},
                    "required": ["pr_number"],
                },
            },
            {
                "name": "detect_change_type",
                "description": "Classify a PR as code / iac / mixed based on file paths.",
                "inputSchema": {
                    "type": "object",
                    "properties": {"pr_number": {"type": "integer"}},
                    "required": ["pr_number"],
                },
            },
            {
                "name": "post_github_comment",
                "description": "Post a markdown comment to the PR. For /fix use, the agent prepends '## 🔧 AI Fix Suggestion'.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "pr_number": {"type": "integer"},
                        "comment_body": {"type": "string", "description": "Markdown comment body"},
                    },
                    "required": ["pr_number", "comment_body"],
                },
            },
        ],
    },
    "ddb-tools": {
        "lambda_arn": "arn:aws:lambda:us-east-1:336093158955:function:aiops-changemgmt-agentcore-ddb-tools",
        "schema": [
            {
                "name": "get_review_history",
                "description": "Query past review history. Filter by author or comma-separated file basenames.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "author": {"type": "string"},
                        "files": {"type": "string"},
                        "limit": {"type": "integer", "description": "default 5"},
                    },
                },
            },
            {
                "name": "get_developer_profile",
                "description": "Look up a developer profile by GitHub login. Contains strengths/weaknesses/repeated patterns.",
                "inputSchema": {
                    "type": "object",
                    "properties": {"author": {"type": "string"}},
                    "required": ["author"],
                },
            },
        ],
    },
    "kb-tools": {
        "lambda_arn": "arn:aws:lambda:us-east-1:336093158955:function:aiops-changemgmt-agentcore-kb-tools",
        "schema": [
            {
                "name": "query_knowledge_base",
                "description": "Semantic search over past incidents, runbooks, and policies.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "max_results": {"type": "integer", "description": "default 5"},
                    },
                    "required": ["query"],
                },
            },
        ],
    },
    "slack-tools": {
        "lambda_arn": "arn:aws:lambda:us-east-1:336093158955:function:aiops-changemgmt-agentcore-slack-tools",
        "schema": [
            {
                "name": "post_slack_report",
                "description": "Post an analysis report to Slack. Provide a JSON string with pr_number, pr_title, pr_author, pr_url, change_type, risk_score, risk_level, verdict, summary, issues_text, incident_match, developer_pattern, infra_impact, agent_persona, template.",
                "inputSchema": {
                    "type": "object",
                    "properties": {"report_json": {"type": "string", "description": "JSON payload"}},
                    "required": ["report_json"],
                },
            },
        ],
    },
    "subagent-tools": {
        "lambda_arn": "arn:aws:lambda:us-east-1:336093158955:function:aiops-changemgmt-agentcore-subagent-tools",
        "schema": [
            {
                "name": "invoke_devops_agent",
                "description": "Call the DevOps expert sub-agent (stub if not connected).",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "context": {"type": "string"},
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "invoke_security_agent",
                "description": "Call the Security expert sub-agent (stub if not connected).",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "context": {"type": "string"},
                    },
                    "required": ["query"],
                },
            },
        ],
    },
}


def main():
    session = boto3.Session(region_name=REGION)
    control = session.client("bedrock-agentcore-control")

    existing = {t["name"] for t in control.list_gateway_targets(
        gatewayIdentifier=GATEWAY_ID).get("items", [])}
    print(f"Existing targets: {existing or '(none)'}")

    for name, cfg in TOOLS.items():
        if name in existing:
            print(f"[skip] {name} already exists")
            continue
        print(f"[create] {name} ...")
        resp = control.create_gateway_target(
            gatewayIdentifier=GATEWAY_ID,
            name=name,
            targetConfiguration={
                "mcp": {
                    "lambda": {
                        "lambdaArn": cfg["lambda_arn"],
                        "toolSchema": {"inlinePayload": cfg["schema"]},
                    }
                }
            },
            credentialProviderConfigurations=[
                {"credentialProviderType": "GATEWAY_IAM_ROLE"}
            ],
        )
        print(f"  -> {resp.get('targetId')} status={resp.get('status')}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise
