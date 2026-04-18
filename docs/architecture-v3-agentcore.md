# 아키텍처 v3 — AgentCore 기반 (DRAFT, 리뷰용)

> 클래식 Bedrock Agent(v1/v2)를 폐기하고 Amazon Bedrock AgentCore(2025 GA)로 전환.
> 이 문서는 구현 전 리뷰용 설계안이다.

## 확정 스택

| 항목 | 값 | 근거 |
|---|---|---|
| **전 리전 통일** | `us-east-1` (버지니아) | AgentCore GA + cross-region 복잡도 제거 |
| Runtime 배포 | Python ZIP (S3) | Docker 불필요, SAM/CFN만으로 배포 |
| Framework | Strands Agents | AgentCore 네이티브 통합 |
| Auth | Secrets Manager (현행 유지) | OAuth 플로우 구성 부담 회피 |
| Foundation Model | `us.anthropic.claude-sonnet-4-*` 또는 `global.*` | us-east-1에서 사용 가능한 프로파일 |
| Embedding Model | `amazon.titan-embed-text-v2:0` (us-east-1) | KB 임베딩용 |

## AgentCore 구성 요소 매핑

| AgentCore 서비스 | 이 시스템에서의 역할 |
|---|---|
| **Runtime** | Strands 에이전트 실행. 3 Persona(Code/Infra/Risk) 오케스트레이션 |
| **Gateway** | 외부 도구(Lambda 5종)를 MCP 프로토콜로 에이전트에 노출 |
| **Memory** | 세션(단기) + 장기 메모리(레포별 리뷰 요약) |
| **Identity** | WorkloadIdentity만 사용. OAuth Provider는 이번 버전 생략 |

## 상위 구성도 — 전부 us-east-1

```
┌─ us-east-1 (virginia) ────────────────────────────────────────┐
│                                                                │
│  External                                                      │
│   GitHub ─webhook─▶ │    ▲                                     │
│   Slack ─cmd─────▶  │    │ comments / reports                  │
│                     │    │                                     │
│  API Gateway        │    │                                     │
│    /webhook   /slack/commands                                  │
│        │             │                                         │
│        ▼             ▼                                         │
│   webhook Lambda   slack-command Lambda                        │
│        │             │                                         │
│        └──────┬──────┘ async invoke                            │
│               ▼                                                │
│        analysis Lambda (bridge)                                │
│               │                                                │
│               │ InvokeAgentRuntime                             │
│               ▼                                                │
│   ┌────────────────────────────────────────────────┐           │
│   │ AgentCore Runtime                              │           │
│   │  • Strands Agent (Claude Sonnet 4.x)           │           │
│   │  • Python ZIP 배포 (S3)                        │           │
│   │  • 3 Persona 오케스트레이션 (프롬프트 기반)     │           │
│   │  • MCP 클라이언트로 Gateway 도구 호출           │           │
│   └──────┬──────────────────┬──────────────────────┘           │
│          │ MCP              │ Memory SDK                       │
│          ▼                  ▼                                  │
│   ┌────────────┐    ┌──────────────────┐                       │
│   │ Gateway    │    │ Memory           │                       │
│   │ (MCP endpt)│    │ 단기+장기 (SUM)   │                       │
│   └─────┬──────┘    └──────────────────┘                       │
│         │                                                      │
│         │ 5 × GatewayTarget (Lambda)                           │
│         ▼                                                      │
│   ┌─────────────────────────────────────────────────────┐      │
│   │ pr_tools      — get_pr_diff / files / detect        │      │
│   │                 post_github_comment                 │      │
│   │ kb_tools      — query_knowledge_base                │      │
│   │ ddb_tools     — review_history / developer_profile  │      │
│   │ slack_tools   — post_slack_report                   │      │
│   │ subagent_tools— devops / security (stub)            │      │
│   └──────┬──────────────────┬────────────────┬──────────┘      │
│          │                  │                │                 │
│          ▼                  ▼                ▼                 │
│   ┌──────────────┐  ┌───────────────┐  ┌───────────────┐       │
│   │ DDB 3종       │  │ Bedrock KB    │  │ Secrets Mgr   │       │
│   │ review-hist   │  │ + S3 Vectors  │  │ gh/slack      │       │
│   │ dev-profiles  │  │               │  │               │       │
│   │ team-stats    │  └───────────────┘  └───────────────┘       │
│   └──────────────┘         ▲                                   │
│                            │ Retrieve                          │
│                     ┌──────┴──────┐                            │
│                     │ S3 kb-data  │─▶ kb-reindex Lambda        │
│                     │   bucket    │    (StartIngestionJob)     │
│                     └─────────────┘                            │
│                                                                │
│  Identity: WorkloadIdentity only (OAuth provider 미사용)         │
└────────────────────────────────────────────────────────────────┘
```

모든 호출이 리전 내부라 cross-region 지연/권한/비용 이슈 없음.

## Memory 설계

| 구분 | namespace/strategy | 키 | 용도 |
|---|---|---|---|
| 단기 (session events) | — | `sessionId = pr-{repo}-{number}-{ts}` | 현재 PR 분석의 원시 대화 로그 |
| 장기 (summary) | `namespace=repo/{owner}/{name}`, `strategy=SUMMARY` | `actorId = repo` | 같은 레포의 과거 PR 요약 누적 |
| 장기 (preferences) | `namespace=developer/{login}`, `strategy=USER_PREFERENCES` | `actorId = developer` | 개발자별 반복 패턴/약점 |

- `SESSION_SUMMARY` 대신 AgentCore의 built-in SUMMARY strategy 사용
- 레포 단위 memoryId → `actorId = repo`로 치환 (concept 동일, API 다름)

## Gateway Target 구조

각 target은 Lambda로 구현, Gateway가 MCP 도구 스키마로 변환해서 에이전트에 노출.

```yaml
GatewayTargets:
  - Name: pr_tools
    Type: lambda-function-arn
    Credential: IAM (SigV4)
    Schema:
      tools: [get_pr_diff, get_pr_files, detect_change_type, post_github_comment]

  - Name: ddb_tools
    Type: lambda-function-arn
    Schema:
      tools: [get_review_history, get_developer_profile]

  - Name: kb_tools
    Type: lambda-function-arn
    Schema:
      tools: [query_knowledge_base]

  - Name: slack_tools
    Type: lambda-function-arn
    Schema:
      tools: [post_slack_report]

  - Name: subagent_tools
    Type: lambda-function-arn
    Schema:
      tools: [invoke_devops_agent, invoke_security_agent]
```

**Tool Lambda는 모두 us-east-1** — 전 리소스 단일 리전 통일.

## InvokeAgent 흐름 (webhook 경로)

```
T+0.0  GitHub PR opened
T+0.1  webhook Lambda: HMAC 검증 → analysis Lambda 비동기 호출
T+0.5  analysis Lambda:
         payload = {pr_number, repo, author, command: "analysis"}
         client = boto3.client('bedrock-agentcore')  # us-east-1
         client.invoke_agent_runtime(
           agentRuntimeArn=RUNTIME_ARN,
           runtimeSessionId=f"pr-{repo}-{pr_number}-{ts}",
           payload=json.dumps(payload).encode(),
         )
T+1.0  Runtime: Strands Agent 시작
         • Memory.retrieve(actorId=repo) → 과거 PR 요약 로드
         • detect_change_type → pr_tools
         • persona 활성화
         • query_knowledge_base → Bedrock KB
         • get_review_history → DDB
         • post_github_comment + post_slack_report
         • Memory.record(events) → 단기 + 장기 요약
T+25   응답 반환, 세션 종료
```

## 변경/제거 컴포넌트

| 기존 (v2) | 상태 | 비고 |
|---|---|---|
| `AWS::Bedrock::Agent` | **제거** | AgentCore Runtime으로 대체 |
| `AWS::Bedrock::AgentAlias` | **제거** | RuntimeEndpoint(prod alias)로 대체 |
| Action Group Lambda (통합) | **제거** | 5개 Tool Lambda로 분리 |
| `AWS::Bedrock::KnowledgeBase` | **유지** | Runtime이 cross-region Retrieve 호출 |
| DDB 3종, Secrets Manager, S3 kb-data | **유지** | 서울 그대로 |
| webhook / slack-command / analysis Lambda | **유지** (코드 수정) | analysis가 InvokeAgentRuntime 호출로 변경 |

## 구현 단계 (제안)

1. **Runtime 프로토타입** — Strands "hello world" 에이전트를 us-east-1에 ZIP 배포 → InvokeAgentRuntime smoke test
2. **Memory 연결** — SUMMARY strategy 적용, 세션 간 요약 로드 확인
3. **Gateway + 첫 Tool** — pr_tools(get_pr_diff만) Lambda 서울 배포 + Gateway target 등록 → MCP 경유 호출 검증
4. **Tool 전체 이관** — ddb_tools, kb_tools, slack_tools, subagent_tools 순차 추가
5. **analysis Lambda 전환** — `InvokeAgent` → `InvokeAgentRuntime`으로 코드 변경
6. **E2E 검증** — demo 시나리오 6개 (l1,l2,h1~h4) 통과
7. **클래식 리소스 정리** — 기존 계정 v1/v2, 새 계정 aiops-changemgmt-agent 삭제

## 미해결 이슈 / 리뷰 포인트

1. **Memory 단위**: `actorId=repo` 전략이 실용적인지, 개발자 단위를 병렬로 쓸지
2. **서브 에이전트(DevOps/Security) 실체**: 현재도 stub 상태. 추후 실체 확보 시 별도 AgentCore Runtime 호출로 확장
3. **데모 콘솔(demo-console)**: 현재 어디로 호출하는지 확인 후 경로 조정 필요
4. **비용**: AgentCore Runtime은 managed serverless — 데모 규모라면 미미
5. **검증 완료**: `s3vectors` 및 `bedrock-agentcore-control` 모두 us-east-1에서 API 호출 성공 확인

## 이 문서의 상태

**DRAFT** — 위 리뷰 포인트 합의 후 구현 착수. 기존 `architecture.md`, `flow.md`는 v3 확정 시 교체.
