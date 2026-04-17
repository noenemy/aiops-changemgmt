# 아키텍처 (v2)

## 설계 원칙

1. **단일 Bedrock Agent + 3 Persona**
   멀티 에이전트를 별도로 두지 않고, 하나의 세션 안에서 역할(CodeReviewer / InfraReviewer / RiskJudge)을 전환. 최신 연구(Anthropic "Building Effective Agents" 등)가 보여주듯, 단일 에이전트 쪽이 컨텍스트 연속성과 토큰 효율이 좋음.

2. **Agent-as-Tool 패턴**
   DevOps/Security 서브 에이전트는 **도구(Function)** 로 래핑. Bedrock native multi-agent collaboration을 쓰지 않는 이유:
   - 래핑하는 쪽이 비용/레이턴시 제어 용이
   - 실체가 Bedrock Agent가 아니어도(HTTP API 등) 동일 인터페이스로 추상화 가능
   - 현재 실체 미확정 → Stub으로 선행 구축 가능

3. **DDB + KB 역할 분리**
   - **DDB**: 구조화 데이터 (리뷰 이력, 개발자 프로파일, 팀 통계) — 정확 조회, 쓰기 빈번
   - **KB**: 서술형 지식 (장애 보고서, 정책, 런북) — 시맨틱 검색, 읽기 위주
   - **Agent Memory**: 세션 간 맥락 (자동 요약, 운영자 미개입)

---

## 상위 구성도

```
┌──────────────────────────────────────────────────────────────────────────┐
│  External (GitHub, Slack)                                                │
│                                                                          │
│   GitHub PR ─ Webhook ─┐          ┌─ Slack /analysis /reject /fix        │
└────────────────────────┼──────────┼──────────────────────────────────────┘
                         │          │
                         ▼          ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  AWS ap-northeast-2                                                      │
│                                                                          │
│  API Gateway  /webhook      /slack/commands                              │
│       │              │                │                                  │
│       ▼              ▼                ▼                                  │
│  ┌─────────────┐  ┌─────────────────────┐                                │
│  │ webhook     │  │ slack-command       │                                │
│  │ Lambda      │  │ Lambda              │                                │
│  │ (서명검증)   │  │ (서명검증 + 3초 ack) │                                │
│  └──────┬──────┘  └─────────┬───────────┘                                │
│         │ async invoke      │ async invoke                               │
│         └──────────┬────────┘                                            │
│                    ▼                                                     │
│         ┌────────────────────────┐                                       │
│         │ analysis Lambda        │  ◄─ command 분기                       │
│         │  • webhook → Agent 전체 │                                       │
│         │  • /analysis → Agent   │                                       │
│         │  • /reject → 직접 포스팅 │                                       │
│         │  • /fix → Agent Fix    │                                       │
│         │  • Fallback: 직접 모델  │                                       │
│         └──────────┬─────────────┘                                       │
│                    │ InvokeAgent                                         │
│                    ▼                                                     │
│    ┌─────────────────────────────────────────────────────────────┐       │
│    │ Bedrock Agent (단일, 3 Persona)                              │       │
│    │                                                             │       │
│    │  Instruction:                                               │       │
│    │   detect → [Persona: Code|Infra|Mixed] → RiskJudge → 출력    │       │
│    │                                                             │       │
│    │  Memory: SESSION_SUMMARY (365일)                             │       │
│    │  Knowledge Base: queryKnowledgeBase (자동)                   │       │
│    │  Action Group: 11개 Tools                                    │       │
│    │                    │                                        │       │
│    └────────────────────┼────────────────────────────────────────┘       │
│                         ▼                                                │
│    ┌─────────────────────────────────────────────────────────────┐       │
│    │ Action Group Lambda (11 tools)                              │       │
│    │                                                             │       │
│    │  PR:      get_pr_diff, get_pr_files, detect_change_type     │       │
│    │  DDB:     get_review_history, get_developer_profile,        │       │
│    │           get_team_stats                                    │       │
│    │  SubAgent:invoke_devops_agent, invoke_security_agent        │       │
│    │  Output:  post_github_comment, post_github_fix_suggestion,  │       │
│    │           post_slack_report (외부 템플릿 기반)               │       │
│    └──────┬─────────────┬────────────┬──────────────┬────────────┘       │
│           │             │            │              │                    │
│           ▼             ▼            ▼              ▼                    │
│    DynamoDB 3종    S3 (kb-data)   Secrets        [GitHub]                │
│     review-hist     │              Manager       [Slack]                 │
│     dev-profiles    ▼                                                    │
│     team-stats   Bedrock KB                                              │
│                    │                                                     │
│                    ▼                                                     │
│                 S3 Vectors                                               │
│                                                                          │
│  [S3 ObjectCreated/Removed] → kb-reindex Lambda → StartIngestionJob     │
└──────────────────────────────────────────────────────────────────────────┘

                         ┌──── (선택) us-east-1 ────┐
                         │  DevOps Agent (stub)     │
                         │  Security Agent (stub)   │
                         └──────────────────────────┘
```

---

## Persona 동작 예시 (H4: Race Condition PR)

```
1. detect_change_type(9)
   → {change_type: "code", code_files: ["src/handlers/create_order.py"]}

2. get_pr_diff(9) + get_pr_files(9)
   → 재고 확인 후 update_item 패턴 확인

[Persona = CodeReviewer 활성]
3. queryKnowledgeBase("재고 차감 race condition")
   → INC-0042 매칭 (2026-01-15, P1, 2시간 다운타임)

4. get_review_history(author="dev-ethan", files="create_order.py")
   → 지난 PR #5 "시크릿 이슈로 REJECT" 1건

5. get_developer_profile("dev-ethan")
   → {risk_profile: "medium", repeated_patterns: ["보안 미검토"]}

6. invoke_security_agent("Race Condition on payment flow", context)
   → [stub] 연동 예정

[Persona = RiskJudge 활성]
7. 종합:
   - CRITICAL 이슈 1건(Race Condition)
   - 과거 장애 매칭(INC-0042)
   - 개발자 반복 패턴(이전 REJECT 1건) → 가중치 +10
   → risk_score 92, CRITICAL, REJECT

8. post_github_comment(9, 마크다운)
9. post_slack_report(JSON) → infra_review 대신 code_review.json 선택
   Memory 자동 요약: "PR #9 Race Condition, CRITICAL, REJECT, INC-0042 패턴"
```

---

## 컴포넌트 책임

| 컴포넌트 | 역할 |
|---------|------|
| API Gateway | 외부 진입점 (GitHub Webhook + Slack Slash Command) |
| Webhook Lambda | HMAC 서명 검증, PR 메타 추출, Analysis 비동기 호출 |
| Slack Command Lambda | Slack 서명 검증, 3초 ack, 커맨드 파싱 → Analysis 비동기 호출 |
| Analysis Lambda | Agent 호출 브리지. 커맨드별 분기 (/analysis, /reject, /fix). Fallback 경로 포함 |
| Bedrock Agent | 3 Persona 오케스트레이션, 도구 선택, 결과 합성 |
| Action Group Lambda | 11개 도구 실행기 (DDB, GitHub, Slack, 서브 에이전트) |
| Bedrock KB + S3 Vectors | 장애/정책/런북 시맨틱 검색 |
| KB Reindex Lambda | S3 변경 이벤트 → StartIngestionJob |
| DynamoDB 3종 | review-history(Agent 자동), developer-profiles(운영자 관리), team-stats(운영자 관리) |
| Secrets Manager | GitHub PAT, Slack Bot Token, Slack Signing Secret |

## Fallback 경로

Agent 호출 실패 시:
1. GitHub API로 diff 직접 수집
2. Bedrock 모델 직접 호출(`claude-sonnet-4-6`), 간소화된 프롬프트
3. GitHub 코멘트만 포스팅 (Slack 없음, DDB 기록 없음)

이는 "최소 기능 유지" 경로이며, 정상 경로에서 얻는 KB/DDB/Memory 맥락은 포기한다.
