# Local Trigger Scripts

Bypass API Gateway / Webhook signature checks and feed events directly to the
Lambda chain. Use while iterating on the agent prompt, tools, or Slack templates.

## Prerequisites

- Real GitHub PR must exist (the agent calls `get_pr_diff`/`get_pr_files`).
- Secrets injected in AWS Secrets Manager: `github-token`, `slack-bot-token`.
- AWS profile with access to the Lambda + Secrets (defaults to `new-account`).

## Scenarios

```bash
# Full webhook-style run (what happens when a PR is opened)
python tools/trigger.py webhook 12 --sync

# Slack /analysis (same flow but command field populated)
python tools/trigger.py analysis 12

# Slack /reject — no agent, just posts a rejection to GitHub + Slack
python tools/trigger.py reject 12 --reason "보안 재검토 필요" --actor ethan

# Slack /fix — AgentCore Runtime Fix pipeline
python tools/trigger.py fix 12
```

`--sync` makes the Lambda run synchronously and prints its response body + log tail
(~4KB). Without it the invocation is async (production mode); tail logs yourself.

## What each command exercises

| Command | Runtime? | Tools exercised | Output |
|---|---|---|---|
| `webhook` | yes | all 5 lambdas via Gateway, Memory | GitHub PR comment + Slack |
| `analysis` | yes | same as webhook | same |
| `reject` | no | pr_tools(post_github_comment), Slack direct | GitHub + Slack |
| `fix` | yes | ddb(get_review_history) + pr + slack | GitHub(🔧 header) + Slack |

## Tail all involved logs at once (handy)

```bash
P=new-account; R=us-east-1
for fn in aiops-changemgmt-infra-analysis \
          aiops-changemgmt-agentcore-pr-tools \
          aiops-changemgmt-agentcore-kb-tools \
          aiops-changemgmt-agentcore-ddb-tools \
          aiops-changemgmt-agentcore-slack-tools; do
  echo ">>> $fn"
  aws logs tail "/aws/lambda/$fn" --since 5m --profile $P --region $R --format short
done
```

Runtime logs live under `/aws/bedrock-agentcore/runtimes/<runtime-id>-DEFAULT`.
