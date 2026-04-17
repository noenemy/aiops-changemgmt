# 인프라 리소스 맵 (v2)

## 배포 위치

| 항목 | 값 |
|------|-----|
| Account ID | `528757824852` |
| Region | `ap-northeast-2` (Seoul) |
| Main Stack | `aiops-changemgmt-infra` |
| Agent Stack | `aiops-changemgmt-agent` |
| Sub-Agent Region (선택) | `us-east-1` (Virginia) — DevOps/Security Agent가 실재할 때만 사용 |

## 리소스 맵

### Lambda

| 함수명 | 역할 | Memory | Timeout |
|--------|------|--------|---------|
| `${Stack}-webhook` | GitHub Webhook 수신 + 검증 | 256MB | 30s |
| `${Stack}-analysis` | Agent 호출 브리지 + Fallback | 1024MB | 300s |
| `${Stack}-slack-command` | Slack Slash Command 서명 검증 + 비동기 라우팅 | 256MB | 10s |
| `${Stack}-kb-reindex` | S3 Event → StartIngestionJob | 256MB | 30s |
| `${AgentStack}-action-group` | Agent의 11개 Tool 실행기 | 512MB | 120s |

### API Gateway

| Path | Method | Lambda |
|------|--------|--------|
| `/prod/webhook` | POST | webhook Lambda |
| `/prod/slack/commands` | POST | slack-command Lambda |

### Bedrock

| 리소스 | 설명 |
|--------|------|
| `ChangeManagementAgent` | 단일 오케스트레이터 Agent (Claude Sonnet 4 APAC profile) |
| `AgentAlias (prod)` | 프로덕션 별칭 |
| `KnowledgeBase` | `incidents`, `runbooks`, `policies` 시맨틱 검색 |
| `KB DataSource (S3)` | InclusionPrefixes: `incidents/`, `runbooks/`, `policies/` |
| `Memory` | SESSION_SUMMARY, 365일, memoryId = repo slug |

### Storage

| 리소스 | PK/SK / 용도 |
|--------|--------------|
| DynamoDB `review-history` | PK: prKey, SK: reviewedAt. Agent 자동 쓰기 |
| DynamoDB `developer-profiles` | PK: author. 운영자 수동/배치 관리 |
| DynamoDB `team-stats` | PK: teamId, SK: period. 분기별 집계 |
| S3 `kb-data-${AccountId}` | Markdown 원본 (Versioning + ObjectCreated/Removed → Lambda) |
| S3 Vectors `vectors-${AccountId}` | KB 벡터 저장소 (Index: `aiops-kb-index`, dim=1024, cosine) |

### Secrets Manager

| Secret | 내용 |
|--------|------|
| `${Stack}/github-token` | GitHub Personal Access Token (repo scope) |
| `${Stack}/slack-bot-token` | Slack Bot User OAuth Token |
| `${Stack}/slack-signing-secret` | Slack App Signing Secret (Slash Command 서명 검증) |

### IAM Roles

| Role | 용도 |
|------|------|
| `${Stack}-kb-role` | KB 서비스 역할 (S3 read, S3 Vectors write, embedding model invoke) |
| `${Stack}-kb-reindex-role` | Reindex Lambda 실행 (StartIngestionJob) |
| `${AgentStack}-agent-role` | Bedrock Agent 실행 (모델 호출, KB retrieve) |
| `${AgentStack}-action-group-role` | Action Group Lambda (Secrets, DDB read, cross-region InvokeAgent) |

## Agent Tools (11개)

| 도구 | 종류 | 대상 |
|------|------|------|
| get_pr_diff | PR | GitHub API |
| get_pr_files | PR | GitHub API |
| detect_change_type | PR | GitHub API (파일 분류) |
| get_review_history | DDB | review-history |
| get_developer_profile | DDB | developer-profiles |
| get_team_stats | DDB | team-stats |
| invoke_devops_agent | Sub-Agent | Stub 또는 Virginia Agent |
| invoke_security_agent | Sub-Agent | Stub 또는 Virginia Agent |
| post_github_comment | Output | GitHub API |
| post_github_fix_suggestion | Output | GitHub API |
| post_slack_report | Output | Slack API (템플릿 기반) |
| (자동) queryKnowledgeBase | KB | Bedrock KB |

## 환경변수

### Analysis Lambda (`${Stack}-analysis`)
| Var | 비고 |
|-----|-----|
| BEDROCK_AGENT_ID | 초기값 `"none"`, 배포 후 실제 ID로 업데이트 |
| BEDROCK_AGENT_ALIAS_ID | 초기값 `"none"` |
| BEDROCK_MODEL_ID | Fallback 모델 |
| GITHUB_TOKEN_SECRET_ARN, SLACK_TOKEN_SECRET_ARN, SLACK_CHANNEL_ID, GITHUB_REPO | — |

### Action Group Lambda (`${AgentStack}-action-group`)
| Var | 비고 |
|-----|-----|
| REVIEW_HISTORY_TABLE, DEVELOPER_PROFILES_TABLE, TEAM_STATS_TABLE | DDB 테이블 이름 |
| DEVOPS_AGENT_ID, DEVOPS_AGENT_ALIAS_ID, DEVOPS_AGENT_REGION | 비었으면 Stub |
| SECURITY_AGENT_ID, SECURITY_AGENT_ALIAS_ID, SECURITY_AGENT_REGION | 비었으면 Stub |
| GITHUB_TOKEN_SECRET_ARN, SLACK_TOKEN_SECRET_ARN, SLACK_CHANNEL_ID, GITHUB_REPO | — |

### Slack Command Lambda (`${Stack}-slack-command`)
| Var | 비고 |
|-----|-----|
| SLACK_SIGNING_SECRET_ARN | 서명 검증용 |
| ANALYSIS_FUNCTION_NAME | 비동기 호출 타겟 |
| GITHUB_TOKEN_SECRET_ARN, GITHUB_REPO | PR 메타 조회 |

## 배포

### 1. 메인 스택
```bash
cd infra
sam build && sam deploy --stack-name aiops-changemgmt-infra --region ap-northeast-2 \
  --capabilities CAPABILITY_NAMED_IAM --resolve-s3 \
  --parameter-overrides GitHubToken=... SlackBotToken=... SlackSigningSecret=... SlackChannelId=...
```

### 2. KB 데이터 업로드
```bash
aws s3 sync infra/kb-data/ s3://<KBDataBucketName>/ --region ap-northeast-2 --delete
```

### 3. Agent 스택
```bash
sam deploy -t infra/agent-template.yaml --stack-name aiops-changemgmt-agent \
  --region ap-northeast-2 --capabilities CAPABILITY_NAMED_IAM --resolve-s3 \
  --parameter-overrides \
      KnowledgeBaseId=... ReviewHistoryTableName=... \
      DeveloperProfilesTableName=... TeamStatsTableName=... \
      GitHubTokenSecretArn=... SlackBotTokenSecretArn=... SlackChannelId=...
```

### 4. Analysis Lambda 환경변수 업데이트
```bash
AGENT_ID=$(aws cloudformation describe-stacks --stack-name aiops-changemgmt-agent \
  --query "Stacks[0].Outputs[?OutputKey=='AgentId'].OutputValue" --output text)
ALIAS_ID=$(aws cloudformation describe-stacks --stack-name aiops-changemgmt-agent \
  --query "Stacks[0].Outputs[?OutputKey=='AgentAliasId'].OutputValue" --output text)

aws lambda update-function-configuration \
  --function-name aiops-changemgmt-infra-analysis \
  --environment "Variables={BEDROCK_AGENT_ID=$AGENT_ID,BEDROCK_AGENT_ALIAS_ID=$ALIAS_ID,...}"
```

## 로그 / 디버깅
```bash
aws logs tail /aws/lambda/aiops-changemgmt-infra-analysis --since 5m --region ap-northeast-2
aws logs tail /aws/lambda/aiops-changemgmt-infra-slack-command --since 5m --region ap-northeast-2
aws logs tail /aws/lambda/aiops-changemgmt-agent-action-group --since 5m --region ap-northeast-2
aws logs tail /aws/lambda/aiops-changemgmt-infra-kb-reindex --since 5m --region ap-northeast-2
```
