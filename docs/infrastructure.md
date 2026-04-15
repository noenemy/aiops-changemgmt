# 인프라 배포 및 리소스 맵

## AWS 계정 정보

| 항목 | 값 |
|------|-----|
| Account ID | `528757824852` |
| Region | `ap-northeast-2` (Seoul) |
| IAM User | `ethan.choi` |
| CloudFormation Stack | `aiops-changemgmt-infra` |

## 리소스 맵

### Bedrock AgentCore

| 리소스 | ID / ARN | 설명 |
|--------|----------|------|
| **Agent** | `ARTT9KIKKA` | ChangeManagement 코드 리뷰 에이전트 |
| **Agent Alias (prod)** | `HSRHSRPWOW` | 프로덕션 별칭 |
| **Foundation Model** | `apac.anthropic.claude-sonnet-4-20250514-v1:0` | Claude Sonnet 4 (APAC inference profile) |
| **Action Group** | `AP27THHAQZ` (`GitHubSlackTools`) | GitHub/Slack 도구 4개 |
| **Memory** | `SESSION_SUMMARY`, 365일 | memoryId: `noenemy-aiops-changemgmt` (레포 단위) |
| **Agent Role** | `arn:aws:iam::528757824852:role/aiops-changemgmt-agent-role` | Bedrock 모델 호출 권한 |

### Lambda Functions

| 함수명 | ARN | 역할 | Runtime | Memory | Timeout |
|--------|-----|------|---------|--------|---------|
| `aiops-changemgmt-infra-webhook` | `arn:aws:lambda:ap-northeast-2:528757824852:function:aiops-changemgmt-infra-webhook` | Webhook 수신 + 검증 | python3.13 | 256MB | 30s |
| `aiops-changemgmt-infra-analysis` | `arn:aws:lambda:ap-northeast-2:528757824852:function:aiops-changemgmt-infra-analysis` | Agent 호출 오케스트레이터 | python3.13 | 1024MB | 300s |
| `aiops-changemgmt-action-group` | `arn:aws:lambda:ap-northeast-2:528757824852:function:aiops-changemgmt-action-group` | Agent Action Group (GitHub/Slack 도구) | python3.13 | 512MB | 120s |

### API Gateway

| 항목 | 값 |
|------|-----|
| API ID | `xrbg55j765` |
| Stage | `prod` |
| Webhook URL | `https://xrbg55j765.execute-api.ap-northeast-2.amazonaws.com/prod/webhook` |
| Method | `POST /webhook` |

### DynamoDB

| 테이블명 | PK | SK | 용도 |
|----------|-----|-----|------|
| `aiops-changemgmt-infra-review-history` | `prKey` (S) | `reviewedAt` (S) | 리뷰 이력 저장 (fallback Memory) |

### Secrets Manager

| Secret 이름 | ARN | 내용 |
|-------------|-----|------|
| `aiops-changemgmt-infra/github-token` | `arn:aws:secretsmanager:ap-northeast-2:528757824852:secret:aiops-changemgmt-infra/github-token-ART1FB` | GitHub Classic PAT |
| `aiops-changemgmt-infra/slack-bot-token` | `arn:aws:secretsmanager:ap-northeast-2:528757824852:secret:aiops-changemgmt-infra/slack-bot-token-hmZxAm` | Slack Bot Token |

### S3

| Bucket | 용도 |
|--------|------|
| `aiops-changemgmt-infra-kb-data-528757824852` | KB 데이터 + Agent 스키마 저장 |

### IAM Roles

| Role | 용도 |
|------|------|
| `aiops-changemgmt-agent-role` | Bedrock Agent 실행 (모델 호출) |
| `aiops-changemgmt-action-group-role` | Action Group Lambda 실행 (Secrets + CloudWatch) |
| `aiops-changemgmt-infra-WebhookFunctionRole-*` | Webhook Lambda (SAM 관리) |
| `aiops-changemgmt-infra-AnalysisFunctionRole-*` | Analysis Lambda (SAM 관리) |

## GitHub 연동

| 항목 | 값 |
|------|-----|
| Repository | `noenemy/aiops-changemgmt` |
| Webhook URL | `https://xrbg55j765.execute-api.ap-northeast-2.amazonaws.com/prod/webhook` |
| Webhook Secret | `aiops-demo-webhook-2026` |
| Webhook Events | `pull_request` (opened, synchronize) |

## Slack 연동

| 항목 | 값 |
|------|-----|
| Channel ID | `C0ASW5X99E1` |
| Channel Name | `#test-channel` |
| Bot Token Type | `xoxb-*` (Bot User OAuth Token) |

## 데모 브랜치

| ID | 브랜치 | 시나리오 | Risk 예상 |
|----|--------|---------|----------|
| L1 | `demo/i18n-messages` | 응답 메시지 한국어화 | LOW |
| L2 | `demo/structured-logging` | 구조화 로깅 + request_id | LOW |
| H1 | `demo/payment-integration` | 시크릿 하드코딩 + PII 로깅 | CRITICAL |
| H2 | `demo/api-cleanup` | API 필드명 변경 (Breaking Change) | HIGH |
| H3 | `demo/order-enrichment` | N+1 쿼리 + 무제한 페이로드 | HIGH |
| H4 | `demo/checkout-feature` | Race Condition + 결제 불일치 | CRITICAL |

## 배포 명령어

```bash
# SAM 스택 배포
cd infra
sam build && sam deploy --stack-name aiops-changemgmt-infra --region ap-northeast-2 --capabilities CAPABILITY_NAMED_IAM --resolve-s3

# Agent 상태 확인
aws bedrock-agent get-agent --agent-id ARTT9KIKKA --region ap-northeast-2

# Lambda 로그 확인
aws logs tail /aws/lambda/aiops-changemgmt-infra-analysis --since 5m --region ap-northeast-2
aws logs tail /aws/lambda/aiops-changemgmt-action-group --since 5m --region ap-northeast-2
```
