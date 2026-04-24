# AIOps Change Management Demo

AI 기반 변경 관리 데모 — 코드 및 인프라 변경이 프로덕션에 배포되기 전에 리스크를 자동으로 감지하고 장애를 예방합니다.

이 데모는 AWS Seoul Summit 2026 컨퍼런스에서 AI-Powered Cloud Ops 부스의 데모를 위해 제작된 것입니다.

## 개요

개발자가 Pull Request를 생성하면 Bedrock AgentCore 기반 오케스트레이터가 변경 내용을 자동 분석하여 보안 취약점, 성능 저하, 데이터 손실 위험 등을 사전에 감지합니다. 결과는 GitHub PR 코멘트와 Slack 채널에 전달되며, 팀은 Slack 슬래시 커맨드(`/analysis`, `/reject`, `/fix`)로 추가 작업을 요청할 수 있습니다.

## 아키텍처

```
[개발자] ──PR──► GitHub
                   │
                   ▼
         Webhook → API Gateway → Webhook Lambda
                                    │ (async invoke)
         Slack /commands ─► Slack Command Lambda ──┐
                                                    ▼
                                          Analysis Lambda
                                                    │
                                                    ▼
          ┌─────────────── Bedrock Agent (단일, 3 Persona) ───────────────┐
          │                                                              │
          │  CodeReviewer ─┐                                              │
          │                ├─► RiskJudge ─► post_github_comment           │
          │  InfraReviewer ┘                post_slack_report             │
          │                                                               │
          │  Tools:                                                       │
          │    PR:       get_pr_diff, get_pr_files, detect_change_type    │
          │    DDB:      get_review_history, get_developer_profile,       │
          │              get_team_stats                                   │
          │    Sub-Agent: invoke_devops_agent, invoke_security_agent      │
          │               (Stub, 환경변수로 실체 연결)                    │
          │    Output:   post_github_comment, post_github_fix_suggestion, │
          │              post_slack_report (외부 템플릿 기반)             │
          │                                                               │
          │  Knowledge Base (자동): queryKnowledgeBase                    │
          │    ← S3(incidents/ runbooks/ policies/) via S3 Vectors        │
          │                                                               │
          │  Memory: SESSION_SUMMARY (365일, 레포 단위 memoryId)          │
          └───────────────────────────────────────────────────────────────┘
```

## 단일 Agent · 3 Persona

하나의 Bedrock Agent가 PR 유형(`code` / `iac` / `mixed`)에 따라 역할을 전환합니다.

| Persona | 활성 조건 | 분석 축 | 주요 도구 |
|---------|----------|---------|-----------|
| **CodeReviewer** | 코드 변경 | 보안 / 성능 / 안정성 / 호환성 | KB, get_review_history, get_developer_profile, invoke_security_agent |
| **InfraReviewer** | IaC 변경 (`*.yaml/yml/tf/tfvars`, `infra/**`, `terraform/**` 등) | 리소스 영향 / IAM / 데이터 보존 / 비용 / Drift | KB, invoke_devops_agent, invoke_security_agent |
| **RiskJudge** | 항상 마지막 | Code/Infra 결과 종합, 최종 Risk Score & Verdict | Memory(이전 세션 요약), post_*_comment, post_slack_report |

**Agent-as-Tool 패턴**: DevOps/Security 서브 에이전트는 도구로 래핑됨. 환경변수 `DEVOPS_AGENT_ID` / `SECURITY_AGENT_ID`가 비어있으면 Stub 응답, 설정되면 cross-region(Virginia 등)의 실제 Bedrock Agent를 invoke.

## 데이터 관리

| 저장소 | 용도 | 편집 방식 |
|-------|------|----------|
| **DynamoDB `review-history`** | Agent가 PR마다 자동 기록 | 자동 (수동 편집 불필요) |
| **DynamoDB `developer-profiles`** | 개발자 강점/약점/반복 패턴 | 운영자 수동/배치 |
| **DynamoDB `team-stats`** | 팀 단위 분기 집계 | 운영자 수동/배치 |
| **S3 + Bedrock KB + S3 Vectors** | `incidents/`, `runbooks/`, `policies/` 서술형 지식 | `infra/kb-data/*.md` 편집 → S3 sync 후 자동 재인덱싱 |
| **Bedrock Agent Memory (SESSION_SUMMARY)** | 세션 간 단기 맥락 | 자동 요약, 365일 보관 |

KB 편집 가이드: [`infra/kb-data/README.md`](infra/kb-data/README.md)
Slack 템플릿 편집 가이드: [`agent/slack_templates/README.md`](agent/slack_templates/README.md)

## Slack Slash Commands

| Command | 사용법 | 동작 |
|---------|--------|------|
| `/analysis <PR>` | `/analysis 9` | 해당 PR 재분석 (Agent 전체 파이프라인) |
| `/reject <PR> [사유]` | `/reject 9 보안 이슈 재검토 필요` | 즉시 REJECT 코멘트 + Slack 알림 (Agent 건너뜀) |
| `/fix <PR>` | `/fix 9` | 기존 리뷰 이슈에 대한 구체적 수정 제안 생성 |

설정 가이드: [`docs/slack-setup.md`](docs/slack-setup.md)

## 프로젝트 구조

```
aiops-changemgmt/
├── sample-app/                  # 분석 대상 샘플 애플리케이션 (Orders API)
│   ├── template.yaml
│   └── src/handlers/
├── infra/                       # 배포 인프라
│   ├── template.yaml            #   메인 스택 (Webhook, Slack Cmd, DDB, KB, S3 Vectors)
│   ├── agent-template.yaml      #   Bedrock Agent + Action Group
│   ├── webhook/                 #   PR Webhook + Analysis Lambda
│   ├── slack-commands/          #   Slack Slash Command Handler Lambda
│   ├── kb-reindex/              #   S3 Event → KB StartIngestionJob Lambda
│   └── kb-data/                 #   KB 원본 데이터 (사용자 편집)
│       ├── incidents/           #     과거 장애 보고서
│       ├── runbooks/            #     운영 가이드
│       ├── policies/            #     리뷰 정책
│       └── deploy-history/      #     배포 통계 (KB 미인덱싱)
├── agent/                       # Bedrock Agent 구성
│   ├── action_group_handler.py  #   도구 실행기 (Lambda)
│   ├── action_group_schema.json #   OpenAPI 미러 (참고용)
│   ├── system_prompt.txt        #   Agent 시스템 프롬프트 (3 Persona)
│   └── slack_templates/         #   외부 Slack Block Kit 템플릿
├── demo-console/                # Next.js 데모 웹 콘솔
├── docs/                        # 상세 문서
└── demo.sh                      # 데모 시나리오 스크립트 (6개)
```

## 데모 시나리오 (`./demo.sh`)

| ID | 시나리오 | 예상 결과 |
|----|---------|----------|
| `l1` | i18n 메시지 한국어 지원 | 🟢 LOW, APPROVE |
| `l2` | 구조화 로깅 + request_id | 🟢 LOW, APPROVE |
| `h1` | 결제 API 키 하드코딩 | 🔴 CRITICAL, REJECT (INC-0045 매칭) |
| `h2` | API 필드명 Breaking Change | 🔴 HIGH, REJECT (INC-0038 매칭) |
| `h3` | 주문 목록 N+1 쿼리 | 🔴 HIGH, REJECT (INC-0041 매칭) |
| `h4` | 재고 차감 Race Condition | 🔴 CRITICAL, REJECT (INC-0042 매칭) |

```bash
./demo.sh list              # 시나리오 목록
./demo.sh run h4            # h4 실행 (PR 생성)
./demo.sh reset-all         # 모든 데모 PR 닫기
```

## 데모 콘솔 (`demo-console/`)

부스/영상 녹화용 Next.js 웹 콘솔. 시나리오 설명, 활성 경로가 하이라이트되는 아키텍처 다이어그램, 터미널 뷰, Slack 리포트 미리보기를 한 화면에 묶어 보여줍니다.

- **연출(scripted) 모드**: 미리 정의된 시나리오 출력을 타이핑 애니메이션으로 재생. 네트워크/AWS 크레덴셜 없이 동작.
- **실제(live) 모드**: 브라우저에서 `tools/demo_run.py`를 실제로 트리거하고 stdout을 SSE로 스트리밍. Python `boto3` + AWS 프로파일(`new-account` 기본, `AWS_PROFILE`로 변경 가능)이 필요합니다.

```bash
cd demo-console
npm install
npm run dev      # http://localhost:3001
```

세부 사용법, 녹화 전 체크리스트, 시나리오 편집 방법: [`demo-console/README.md`](demo-console/README.md)

## 시작하기

### 사전 요구사항
- AWS CLI + SAM CLI
- Python 3.13+
- GitHub PAT (`repo` scope)
- Slack App (Bot Token + Signing Secret + Slash Commands 활성화)
- Bedrock 모델 접근 권한 (Claude Sonnet 4+, Titan Embeddings v2)

### 1. 샘플 앱 배포
```bash
cd sample-app && sam build && sam deploy --guided --stack-name aiops-changemgmt-app
```

### 2. 메인 인프라 배포
```bash
cd infra && sam build && sam deploy --guided --stack-name aiops-changemgmt-infra \
    --region ap-northeast-2 --capabilities CAPABILITY_NAMED_IAM
```
생성된 Output에서 `KBDataBucketName`, `WebhookUrl`, `SlackCommandUrl` 확인.

### 3. KB 데이터 업로드
```bash
aws s3 sync infra/kb-data/ s3://<KBDataBucketName>/ --region ap-northeast-2 --delete
```
업로드 후 자동 재인덱싱 (`kb-reindex` Lambda).

### 4. Agent 배포
```bash
sam deploy -t infra/agent-template.yaml --stack-name aiops-changemgmt-agent \
    --region ap-northeast-2 --capabilities CAPABILITY_NAMED_IAM \
    --parameter-overrides \
        KnowledgeBaseId=<from main output> \
        ReviewHistoryTableName=<from main output> \
        DeveloperProfilesTableName=<from main output> \
        TeamStatsTableName=<from main output> \
        GitHubTokenSecretArn=<arn> SlackBotTokenSecretArn=<arn> \
        SlackChannelId=<id>
```

### 5. Analysis Lambda 환경변수에 Agent 연결
```bash
aws lambda update-function-configuration \
    --function-name aiops-changemgmt-infra-analysis \
    --environment "Variables={BEDROCK_AGENT_ID=<id>,BEDROCK_AGENT_ALIAS_ID=<alias>,...}"
```

### 6. GitHub Webhook 등록
`WebhookUrl` 을 GitHub Repo Settings → Webhooks에 등록.

### 7. Slack App 설정
Slash Commands 3개의 Request URL을 `SlackCommandUrl`로 설정. 자세한 내용은 [`docs/slack-setup.md`](docs/slack-setup.md).

## 문서

- [`docs/architecture.md`](docs/architecture.md) — 시스템 아키텍처 상세
- [`docs/flow.md`](docs/flow.md) — E2E 처리 흐름
- [`docs/infrastructure.md`](docs/infrastructure.md) — 리소스 맵
- [`docs/slack-setup.md`](docs/slack-setup.md) — Slack App 설정
- [`infra/kb-data/README.md`](infra/kb-data/README.md) — KB 데이터 편집
- [`agent/slack_templates/README.md`](agent/slack_templates/README.md) — Slack 템플릿 편집
- [`demo-console/README.md`](demo-console/README.md) — 데모 콘솔 실행 및 녹화 가이드

## 라이선스

MIT
