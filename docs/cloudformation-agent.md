# Bedrock Agent CloudFormation 템플릿

Agent, Action Group Lambda, Agent IAM Role, Agent Alias는 `infra/agent-template.yaml`로 관리된다.

## 주요 변경점 (v1 → v2)

- Agent 이름: `code-reviewer` → `orchestrator` (3 Persona)
- Action Group: 4개 → **11개** (PR/DDB/SubAgent/Output)
- **KnowledgeBase 연결** 추가: queryKnowledgeBase가 자동 도구로 노출됨
- **DevOps/Security Agent Stub**: 환경변수(`DEVOPS_AGENT_*`, `SECURITY_AGENT_*`) 파라미터 추가
- Memory: 기존과 동일 (SESSION_SUMMARY, 365일)

## 스택 파라미터

| 파라미터 | 설명 |
|---------|------|
| GitHubTokenSecretArn | 메인 스택 Output에서 참조 |
| SlackBotTokenSecretArn | 메인 스택 Output에서 참조 |
| SlackChannelId | Slack 채널 ID |
| GitHubRepo | `noenemy/aiops-changemgmt` |
| AgentModelId | 기본 `apac.anthropic.claude-sonnet-4-20250514-v1:0` |
| KnowledgeBaseId | **메인 스택에서 생성된 KB ID** |
| ReviewHistoryTableName | 메인 스택 Output |
| DeveloperProfilesTableName | 메인 스택 Output |
| TeamStatsTableName | 메인 스택 Output |
| DevopsAgentId, DevopsAgentAliasId, DevopsAgentRegion | 비어있으면 Stub |
| SecurityAgentId, SecurityAgentAliasId, SecurityAgentRegion | 비어있으면 Stub |

## 배포

메인 스택을 먼저 배포한 뒤, Output을 인자로 Agent 스택 배포:

```bash
MAIN_STACK=aiops-changemgmt-infra

KB_ID=$(aws cloudformation describe-stacks --stack-name $MAIN_STACK \
  --query "Stacks[0].Outputs[?OutputKey=='KnowledgeBaseId'].OutputValue" --output text \
  --region ap-northeast-2)
RH=$(aws cloudformation describe-stacks --stack-name $MAIN_STACK \
  --query "Stacks[0].Outputs[?OutputKey=='ReviewHistoryTableName'].OutputValue" --output text \
  --region ap-northeast-2)
DP=$(aws cloudformation describe-stacks --stack-name $MAIN_STACK \
  --query "Stacks[0].Outputs[?OutputKey=='DeveloperProfilesTableName'].OutputValue" --output text \
  --region ap-northeast-2)
TS=$(aws cloudformation describe-stacks --stack-name $MAIN_STACK \
  --query "Stacks[0].Outputs[?OutputKey=='TeamStatsTableName'].OutputValue" --output text \
  --region ap-northeast-2)

cd infra
sam build -t agent-template.yaml
sam deploy -t agent-template.yaml --stack-name aiops-changemgmt-agent \
  --region ap-northeast-2 --capabilities CAPABILITY_NAMED_IAM --resolve-s3 \
  --parameter-overrides \
    KnowledgeBaseId=$KB_ID \
    ReviewHistoryTableName=$RH \
    DeveloperProfilesTableName=$DP \
    TeamStatsTableName=$TS \
    GitHubTokenSecretArn=arn:aws:secretsmanager:... \
    SlackBotTokenSecretArn=arn:aws:secretsmanager:... \
    SlackChannelId=C0ASW5X99E1
```

## DevOps/Security Agent 연결 (나중에)

실체가 확보되면:
```bash
sam deploy -t agent-template.yaml --stack-name aiops-changemgmt-agent \
  --parameter-overrides \
    DevopsAgentId=XXXXXXXXXX DevopsAgentAliasId=YYYYY DevopsAgentRegion=us-east-1 \
    SecurityAgentId=AAAAAAAAAA SecurityAgentAliasId=BBBBB SecurityAgentRegion=us-east-1 \
    ...(기타 파라미터)
```

Stub 모드와 live 모드의 전환은 **환경변수만 바뀌므로 프롬프트/코드 변경 없이** 가능하다.
