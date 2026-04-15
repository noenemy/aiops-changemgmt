# 아키텍처 구성도

## 전체 아키텍처

```
┌──────────────┐
│  Developer   │
│  (PR 생성)   │
└──────┬───────┘
       │ git push + PR create
       ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    GitHub (noenemy/aiops-changemgmt)                  │
│                                                                      │
│  PR opened/sync ──→ Webhook POST (pull_request event)                │
│                                                                      │
│  ◀── Agent가 post_github_comment 도구로 PR 코멘트 작성               │
└──────────────────────────┬───────────────────────────────────────────┘
                           │ HTTPS POST
                           ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    AWS (ap-northeast-2)                               │
│                                                                      │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │ API Gateway                                                   │  │
│  │ POST /prod/webhook                                            │  │
│  └────────────────────────────┬──────────────────────────────────┘  │
│                               │                                      │
│                               ▼                                      │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │ Lambda: webhook-handler (트리거 전용, 얇은 레이어)              │  │
│  │                                                               │  │
│  │ • GitHub Webhook 서명 검증 (HMAC-SHA256)                      │  │
│  │ • PR event 파싱 (opened/synchronize만 처리)                   │  │
│  │ • Analysis Lambda 비동기 호출                                 │  │
│  └────────────────────────────┬──────────────────────────────────┘  │
│                               │ Async Invoke                         │
│                               ▼                                      │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │ Lambda: analysis-handler                                      │  │
│  │                                                               │  │
│  │ • PR 정보 추출                                                │  │
│  │ • Bedrock AgentCore InvokeAgent 호출                          │  │
│  │   (sessionId + memoryId 전달)                                 │  │
│  │ • Fallback: Agent 실패 시 Bedrock 직접 모델 호출              │  │
│  └────────────────────────────┬──────────────────────────────────┘  │
│                               │ InvokeAgent API                      │
│                               ▼                                      │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │                                                               │  │
│  │                 Bedrock AgentCore                              │  │
│  │                 (ChangeManagement Agent)                       │  │
│  │                                                               │  │
│  │  ┌────────────────────────────────────────────────────────┐   │  │
│  │  │                Agent Runtime                           │   │  │
│  │  │                                                        │   │  │
│  │  │  Foundation Model: Claude Sonnet 4                     │   │  │
│  │  │  시스템 프롬프트: 코드 리뷰어 + 과거 장애 이력 참조      │   │  │
│  │  │                                                        │   │  │
│  │  │  Agent가 자율적으로 도구를 선택하고 호출:                 │   │  │
│  │  │  1. get_pr_diff → diff 수집                            │   │  │
│  │  │  2. get_pr_files → 파일 목록 수집                       │   │  │
│  │  │  3. 코드 분석 + 리스크 평가                             │   │  │
│  │  │  4. Memory 참조 (과거 리뷰 이력)                        │   │  │
│  │  │  5. post_github_comment → PR 코멘트 작성                │   │  │
│  │  │  6. post_slack_report → Slack 리포트 전송               │   │  │
│  │  │                                                        │   │  │
│  │  └──────────┬────────────────────┬────────────────────────┘   │  │
│  │             │                    │                             │  │
│  │             ▼                    ▼                             │  │
│  │  ┌──────────────────┐ ┌──────────────────────────────────┐   │  │
│  │  │     Memory       │ │     Action Group Lambda          │   │  │
│  │  │                  │ │     (GitHubSlackTools)            │   │  │
│  │  │ SESSION_SUMMARY  │ │                                  │   │  │
│  │  │ 365일 유지       │ │  get_pr_diff()                   │   │  │
│  │  │ per memoryId     │ │    → GitHub API: diff 수집       │   │  │
│  │  │ (레포 단위)      │ │                                  │   │  │
│  │  │                  │ │  get_pr_files()                   │   │  │
│  │  │ 자동 세션 요약:  │ │    → GitHub API: 파일 목록 수집   │   │  │
│  │  │ "PR #9: Race     │ │                                  │   │  │
│  │  │  Condition 감지, │ │  post_github_comment()            │   │  │
│  │  │  CRITICAL,       │ │    → GitHub API: 코멘트 작성      │   │  │
│  │  │  REJECT"         │ │                                  │   │  │
│  │  │                  │ │  post_slack_report()              │   │  │
│  │  │                  │ │    → Slack API: 리포트 전송       │   │  │
│  │  └──────────────────┘ └──────────────────────────────────┘   │  │
│  │                                                               │  │
│  └───────────────────────────────────────────────────────────────┘  │
│                                                                      │
│  ┌────────────────┐  ┌──────────────────┐  ┌──────────────────────┐ │
│  │ Secrets Manager│  │ DynamoDB         │  │ S3                   │ │
│  │                │  │ (review-history) │  │ (kb-data)            │ │
│  │ • GitHub PAT   │  │                  │  │                      │ │
│  │ • Slack Token  │  │ 리뷰 이력 저장   │  │ Phase 2:             │ │
│  │                │  │ (fallback용)     │  │ KB 데이터 저장        │ │
│  └────────────────┘  └──────────────────┘  └──────────────────────┘ │
└─────────────────────────────────────────────────────────────────────┘
                           │                        │
                           ▼                        ▼
                 ┌──────────────┐          ┌──────────────┐
                 │   GitHub     │          │    Slack      │
                 │  PR Comment  │          │ #test-channel │
                 │  (리뷰 결과) │          │  (리포트)     │
                 └──────────────┘          └──────────────┘
```

## 컴포넌트 역할

| 컴포넌트 | 역할 | 핵심 포인트 |
|----------|------|------------|
| **API Gateway** | GitHub Webhook 수신 | 외부 진입점 |
| **Webhook Lambda** | 이벤트 검증 + 라우팅 | 서명 검증, 비동기 호출 |
| **Analysis Lambda** | Agent 호출 오케스트레이터 | Agent 호출 + fallback |
| **Bedrock Agent** | 코드 분석 두뇌 | 자율적 도구 선택 + 분석 |
| **Agent Memory** | 세션 간 기억 유지 | 개발자/파일 패턴 추적 |
| **Action Group Lambda** | Agent의 도구 실행기 | GitHub/Slack API 호출 |
| **Secrets Manager** | 시크릿 관리 | PAT, Slack Token |
| **DynamoDB** | 리뷰 이력 (fallback) | Phase 1 Memory 대체 |
| **S3** | KB 데이터 저장 | Phase 2 대기 |

## Phase 1 vs Phase 2

| 기능 | Phase 1 (현재) | Phase 2 (예정) |
|------|---------------|---------------|
| 코드 분석 | AgentCore (Claude Sonnet 4) | 동일 |
| Memory | Agent Memory (SESSION_SUMMARY) | 동일 + KB RAG |
| 도구 | Action Group (GitHub/Slack) | 동일 |
| 과거 장애 참조 | 시스템 프롬프트에 하드코딩 | Knowledge Base (S3 → OpenSearch → RAG) |
| Fallback | DynamoDB + 직접 모델 호출 | 유지 |
