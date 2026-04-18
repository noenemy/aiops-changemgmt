SHELL := /usr/bin/env bash
PROFILE ?= new-account
REGION  ?= us-east-1
PR      ?= 9
REPO    ?= noenemy/aiops-changemgmt

# ------------------------------------------------------------
# Deployment IDs. Non-sensitive values live here; secrets come
# from env or .env.local (gitignored). Sourcing .env.local lets
# us commit this file safely.
# ------------------------------------------------------------
-include .env.local

GATEWAY_URL      ?= https://aiops-changemgmt-gateway-c30ktnjtfk.gateway.bedrock-agentcore.us-east-1.amazonaws.com/mcp
MEMORY_ID        ?= aiops_changemgmt_memory-8yOyma7ILl
COGNITO_DOMAIN   ?= agentcore-c92b6d96
COGNITO_CLIENT   ?= 2ulgdak6e1t5dctbehtd8h1o52
COGNITO_SCOPE    ?= aiops-changemgmt-gateway/invoke
BEDROCK_MODEL    ?= global.anthropic.claude-sonnet-4-6
# COGNITO_SECRET must be set via .env.local or exported in the shell.
# Example .env.local (do not commit):
#   COGNITO_SECRET=...
ifndef COGNITO_SECRET
COGNITO_SECRET = $(shell aws secretsmanager get-secret-value --secret-id aiops-changemgmt-cognito-client-secret --region $(REGION) --profile $(PROFILE) --query SecretString --output text 2>/dev/null)
endif

PY  := AWS_PROFILE=$(PROFILE) python3
AWS := aws --profile $(PROFILE) --region $(REGION)

.PHONY: help
help:
	@awk 'BEGIN{FS=":.*?## "} /^[a-zA-Z_-]+:.*?## /{printf "  %-22s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

# ------------------------------------------------------------
# Agent runtime (app.py / prompt changes)
# ------------------------------------------------------------
.PHONY: dev-agent
dev-agent: ## Redeploy the AgentCore Runtime (app.py, prompt, deps)
	cd agent/runtime && AWS_PROFILE=$(PROFILE) agentcore deploy --auto-update-on-conflict \
	  --env GATEWAY_URL=$(GATEWAY_URL) \
	  --env MEMORY_ID=$(MEMORY_ID) \
	  --env BEDROCK_MODEL_ID=$(BEDROCK_MODEL) \
	  --env COGNITO_DOMAIN=$(COGNITO_DOMAIN) \
	  --env COGNITO_CLIENT_ID=$(COGNITO_CLIENT) \
	  --env COGNITO_CLIENT_SECRET=$(COGNITO_SECRET) \
	  --env COGNITO_SCOPE=$(COGNITO_SCOPE)

.PHONY: agent-status
agent-status: ## Show current Runtime status
	@cd agent/runtime && AWS_PROFILE=$(PROFILE) agentcore status 2>&1 | grep -E "agent_arn|status|endpoint" | head -20

.PHONY: agent-logs
agent-logs: ## Tail Runtime logs (last 5 min)
	$(AWS) logs tail /aws/bedrock-agentcore/runtimes/aiops_changemgmt_runtime-jj5rG36Uk4-DEFAULT \
	  --since 5m --format short | tail -80

# ------------------------------------------------------------
# Tool Lambdas (any tools/*/handler.py change)
# ------------------------------------------------------------
.PHONY: sync-common
sync-common:
	@for t in pr ddb kb slack subagent; do \
	  cp agent/tools/common.py agent/tools/$$t/common.py; \
	done
	@rm -rf agent/tools/slack/slack_templates
	@cp -r agent/slack_templates agent/tools/slack/slack_templates
	@echo "Synced common.py + slack_templates"

.PHONY: dev-tools
dev-tools: sync-common ## Rebuild + redeploy all 5 Tool Lambdas
	cd infra && sam build -t agentcore-template.yaml >/dev/null
	cd infra && sam deploy -t agentcore-template.yaml \
	  --stack-name aiops-changemgmt-agentcore --region $(REGION) --profile $(PROFILE) \
	  --capabilities CAPABILITY_NAMED_IAM --resolve-s3 \
	  --no-confirm-changeset --no-fail-on-empty-changeset \
	  --parameter-overrides \
	    GitHubTokenSecretArn=$$($(AWS) cloudformation describe-stacks --stack-name aiops-changemgmt-infra --query "Stacks[0].Outputs[?OutputKey=='GitHubTokenSecretArn'].OutputValue" --output text) \
	    SlackBotTokenSecretArn=$$($(AWS) cloudformation describe-stacks --stack-name aiops-changemgmt-infra --query "Stacks[0].Outputs[?OutputKey=='SlackBotTokenSecretArn'].OutputValue" --output text) \
	    SlackChannelId=C0ASW5X99E1 \
	    GitHubRepo=$(REPO) \
	    KnowledgeBaseId=$$($(AWS) cloudformation describe-stacks --stack-name aiops-changemgmt-infra --query "Stacks[0].Outputs[?OutputKey=='KnowledgeBaseId'].OutputValue" --output text) \
	    ReviewHistoryTableName=$$($(AWS) cloudformation describe-stacks --stack-name aiops-changemgmt-infra --query "Stacks[0].Outputs[?OutputKey=='ReviewHistoryTableName'].OutputValue" --output text) \
	    DeveloperProfilesTableName=$$($(AWS) cloudformation describe-stacks --stack-name aiops-changemgmt-infra --query "Stacks[0].Outputs[?OutputKey=='DeveloperProfilesTableName'].OutputValue" --output text)

.PHONY: dev-slack-tools
dev-slack-tools: sync-common ## Redeploy only the slack_tools Lambda (faster)
	zip -qr /tmp/slack-tools.zip -j agent/tools/slack/handler.py agent/tools/slack/common.py
	cd /tmp && zip -qr /tmp/slack-tools.zip slack_templates || true
	cd agent/tools/slack && zip -qr /tmp/slack-tools.zip slack_templates
	$(AWS) lambda update-function-code \
	  --function-name aiops-changemgmt-agentcore-slack-tools \
	  --zip-file fileb:///tmp/slack-tools.zip --output text --query LastModified
	@rm -f /tmp/slack-tools.zip

.PHONY: dev-pr-tools
dev-pr-tools: sync-common ## Redeploy only the pr_tools Lambda
	zip -qr /tmp/pr-tools.zip -j agent/tools/pr/handler.py agent/tools/pr/common.py
	$(AWS) lambda update-function-code \
	  --function-name aiops-changemgmt-agentcore-pr-tools \
	  --zip-file fileb:///tmp/pr-tools.zip --output text --query LastModified
	@rm -f /tmp/pr-tools.zip

# ------------------------------------------------------------
# KB / Memory maintenance
# ------------------------------------------------------------
.PHONY: kb-sync
kb-sync: ## Upload infra/kb-data/ to S3 and trigger re-ingest
	@KB_BUCKET=$$($(AWS) cloudformation describe-stacks --stack-name aiops-changemgmt-infra --query "Stacks[0].Outputs[?OutputKey=='KBDataBucketName'].OutputValue" --output text); \
	KB_ID=$$($(AWS) cloudformation describe-stacks --stack-name aiops-changemgmt-infra --query "Stacks[0].Outputs[?OutputKey=='KnowledgeBaseId'].OutputValue" --output text); \
	DS_ID=$$($(AWS) bedrock-agent list-data-sources --knowledge-base-id $$KB_ID --query "dataSourceSummaries[0].dataSourceId" --output text); \
	$(AWS) s3 sync infra/kb-data/ s3://$$KB_BUCKET/ --exclude "deploy-history/*" --delete; \
	$(AWS) bedrock-agent start-ingestion-job --knowledge-base-id $$KB_ID --data-source-id $$DS_ID --query "ingestionJob.ingestionJobId" --output text

.PHONY: memory-clear
memory-clear: ## Clear long-term summaries for this repo from Memory
	$(PY) tools/memory_ops.py clear --repo $(REPO)

.PHONY: memory-show
memory-show: ## Print current Memory events for this repo
	$(PY) tools/memory_ops.py show --repo $(REPO)

.PHONY: dedup-clear
dedup-clear: ## Purge the tool-dedup table (run between test runs)
	@TABLE=$$($(AWS) cloudformation describe-stack-resource --stack-name aiops-changemgmt-agentcore --logical-resource-id ToolDedupTable --query "StackResourceDetail.PhysicalResourceId" --output text); \
	echo "Clearing $$TABLE..."; \
	$(AWS) dynamodb scan --table-name $$TABLE --projection-expression "dedupKey" --query "Items[].dedupKey.S" --output text | tr '\t' '\n' | while read k; do \
	  [ -n "$$k" ] && $(AWS) dynamodb delete-item --table-name $$TABLE --key "{\"dedupKey\":{\"S\":\"$$k\"}}" > /dev/null; \
	done; \
	echo "Done"

# ------------------------------------------------------------
# Trigger
# ------------------------------------------------------------
.PHONY: trigger
trigger: ## Run the webhook-style trigger (make trigger PR=9)
	$(PY) tools/trigger.py webhook $(PR) --profile $(PROFILE) --region $(REGION)

.PHONY: trigger-analysis
trigger-analysis: ## /analysis command
	$(PY) tools/trigger.py analysis $(PR) --profile $(PROFILE) --region $(REGION)

.PHONY: trigger-reject
trigger-reject: ## /reject command (pass REASON=... ACTOR=...)
	$(PY) tools/trigger.py reject $(PR) --reason "$${REASON:-수동 REJECT}" --actor $${ACTOR:-ethan} --profile $(PROFILE) --region $(REGION)

.PHONY: trigger-fix
trigger-fix: ## /fix command
	$(PY) tools/trigger.py fix $(PR) --profile $(PROFILE) --region $(REGION)

# ------------------------------------------------------------
# Slack template preview (local render, optional post)
# ------------------------------------------------------------
.PHONY: slack-preview
slack-preview: ## Render a Slack template locally (TEMPLATE=code_review)
	$(PY) tools/slack_preview.py --template $${TEMPLATE:-code_review}

.PHONY: slack-post
slack-post: ## Render + post to real Slack channel (TEMPLATE=code_review)
	$(PY) tools/slack_preview.py --template $${TEMPLATE:-code_review} --post --profile $(PROFILE) --region $(REGION)

# ------------------------------------------------------------
# Cleanup
# ------------------------------------------------------------
.PHONY: pr-clean
pr-clean: ## Delete all bot comments from a PR (make pr-clean PR=9)
	$(PY) tools/pr_clean.py $(PR) --repo $(REPO) --profile $(PROFILE) --region $(REGION)
