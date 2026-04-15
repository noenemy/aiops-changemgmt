"""GitHub Webhook receiver — validates signature and triggers analysis."""

import hashlib
import hmac
import json
import logging
import os

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

lambda_client = boto3.client("lambda")

WEBHOOK_SECRET = os.environ.get("GITHUB_WEBHOOK_SECRET", "")
ANALYSIS_FUNCTION = os.environ["ANALYSIS_FUNCTION_NAME"]


def verify_signature(payload_body: str, signature_header: str) -> bool:
    """Verify GitHub webhook HMAC-SHA256 signature."""
    if not signature_header:
        return False
    expected = "sha256=" + hmac.new(
        WEBHOOK_SECRET.encode(), payload_body.encode(), hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature_header)


def handler(event, context):
    # Verify webhook signature
    signature = (event.get("headers") or {}).get("X-Hub-Signature-256", "")
    body = event.get("body", "")

    if WEBHOOK_SECRET and not verify_signature(body, signature):
        logger.warning("Invalid webhook signature")
        return {"statusCode": 401, "body": "Invalid signature"}

    payload = json.loads(body)
    action = payload.get("action", "")
    gh_event = (event.get("headers") or {}).get("X-GitHub-Event", "")

    logger.info(f"Received event: {gh_event}, action: {action}")

    # Only process PR opened or synchronized (new commits pushed)
    if gh_event != "pull_request" or action not in ("opened", "synchronize"):
        return {"statusCode": 200, "body": "Ignored"}

    pr = payload["pull_request"]
    pr_data = {
        "pr_number": pr["number"],
        "pr_title": pr["title"],
        "pr_author": pr["user"]["login"],
        "pr_url": pr["html_url"],
        "head_branch": pr["head"]["ref"],
        "base_branch": pr["base"]["ref"],
        "diff_url": pr["diff_url"],
        "repo_full_name": payload["repository"]["full_name"],
    }

    logger.info(f"Processing PR #{pr_data['pr_number']}: {pr_data['pr_title']}")

    # Invoke analysis Lambda asynchronously
    lambda_client.invoke(
        FunctionName=ANALYSIS_FUNCTION,
        InvocationType="Event",
        Payload=json.dumps(pr_data),
    )

    return {
        "statusCode": 200,
        "body": json.dumps({"message": f"Analysis triggered for PR #{pr_data['pr_number']}"}),
    }
