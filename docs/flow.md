# 전체 동작 플로우

## E2E 플로우 (시간순)

```
[T+0.0s]  개발자가 PR 생성
          $ ./demo.sh run h4
          → GitHub API: POST /repos/noenemy/aiops-changemgmt/pulls
          
[T+0.1s]  GitHub이 Webhook 발송
          → POST https://xrbg55j765.execute-api.ap-northeast-2.amazonaws.com/prod/webhook
          → Headers: X-GitHub-Event: pull_request, X-Hub-Signature-256: sha256=...
          → Body: { action: "opened", pull_request: {...}, repository: {...} }

[T+0.3s]  API Gateway → Webhook Lambda (aiops-changemgmt-infra-webhook)
          • X-Hub-Signature-256 검증 (HMAC-SHA256, secret: aiops-demo-webhook-2026)
          • event type 확인: pull_request + opened/synchronize만 처리
          • PR 메타데이터 추출: number, title, author, branch, diff_url
          • Analysis Lambda 비동기 호출 (InvocationType: Event)
          • 즉시 200 반환 → GitHub에 응답

[T+0.5s]  Analysis Lambda (aiops-changemgmt-infra-analysis)
          • PR 정보 수신
          • BEDROCK_AGENT_ID 확인 → "ARTT9KIKKA" (Agent 모드)
          
[T+1.0s]  Bedrock AgentCore InvokeAgent 호출
          • agentId: ARTT9KIKKA
          • agentAliasId: HSRHSRPWOW
          • sessionId: "pr-{number}-{timestamp}" (PR별 고유 세션)
          • memoryId: "noenemy-aiops-changemgmt" (레포 단위, 세션 간 기억 유지)
          • inputText: "PR #{number}을 분석해주세요. 제목: ... Author: ..."

[T+1.5s]  Agent Runtime 시작 (Claude Sonnet 4)
          • 시스템 프롬프트 로드 (코드 리뷰어 역할 + 과거 장애 이력 + Memory 참조 지시)
          • Memory에서 이전 세션 요약 자동 로드 (같은 memoryId의 과거 대화)
          
[T+2.0s]  Agent 자율 판단: "diff를 확인해야 한다"
          → Action Group 호출: get_pr_diff(pr_number=9)
          → Action Group Lambda (aiops-changemgmt-action-group) 실행
          → GitHub API: GET /repos/noenemy/aiops-changemgmt/pulls/9
            (Accept: application/vnd.github.v3.diff)
          → diff 내용 반환 (최대 15,000자)

[T+4.0s]  Agent 자율 판단: "파일 목록도 확인하자"
          → Action Group 호출: get_pr_files(pr_number=9)
          → Action Group Lambda 실행
          → GitHub API: GET /repos/noenemy/aiops-changemgmt/pulls/9/files
          → 변경 파일 목록 반환 (filename, additions, deletions)

[T+5.0s]  Agent 분석 수행
          • diff + 파일 목록을 바탕으로 코드 분석
          • 시스템 프롬프트의 분석 기준 적용:
            - 보안, 성능, 안정성, 호환성
          • 과거 장애 이력 매칭:
            - "이 패턴은 INC-0042와 동일한 Race Condition이다"
            - "당시 매출 손실 ₩12M, 다운타임 2시간"
          • Memory 참조:
            - "이전 세션에서 이 개발자는 보안 이슈로 REJECT된 적이 있다"
          • Risk Score 산출 + 판정

[T+15.0s] Agent 자율 판단: "결과를 GitHub에 남기자"
          → Action Group 호출: post_github_comment(pr_number=9, comment_body="## 🔴 AI Code Review...")
          → Action Group Lambda 실행
          → GitHub API: POST /repos/noenemy/aiops-changemgmt/issues/9/comments
          → PR에 마크다운 리뷰 코멘트 작성

[T+17.0s] Agent 자율 판단: "Slack에도 리포트를 보내자"
          → Action Group 호출: post_slack_report(report_json="{...}")
          → Action Group Lambda 실행
          → Slack API: POST chat.postMessage
            (channel: C0ASW5X99E1, blocks: [...])
          → #test-channel에 리포트 메시지 전송

[T+20.0s] Agent 응답 완료
          → Analysis Lambda에 "PR #9 분석을 완료했습니다" 반환

[T+21.0s] 세션 종료 → Memory 자동 요약
          • endSession=True 호출
          • Agent Memory가 이 세션을 자동 요약하여 저장:
            "PR #9: create_order.py Race Condition, Risk 92/100, CRITICAL, REJECT.
             INC-0042와 동일 패턴. 결제-재고 불일치, 보상 트랜잭션 없음."
          • 다음 PR 분석 시 이 요약이 Memory에서 자동으로 제공됨

[T+22.0s] Analysis Lambda 종료
```

## 시나리오별 플로우 차이

### Low Risk (L1, L2) — 자동 승인

```
PR 생성 → Webhook → Agent 분석
  → "문자열 상수만 변경, 로직 없음"
  → Risk 12/100, LOW, APPROVE
  → GitHub 코멘트: "🟢 Risk 12/100 (LOW) — CI/CD 자동 실행"
  → Slack: "✅ CI/CD 자동 실행"
  → Memory: "PR #7: messages.py 한국어화, Low Risk, APPROVE"
```

### High Risk (H1~H4) — 배포 차단

```
PR 생성 → Webhook → Agent 분석
  → 이슈 발견 (Critical/High)
  → 과거 장애 매칭 (INC-0042 등)
  → Memory에서 개발자 패턴 확인
  → Risk 82-95/100, HIGH/CRITICAL, REJECT
  → GitHub 코멘트: "🔴 Risk 92/100 (CRITICAL) — CI/CD 스킵" + 상세 이슈
  → Slack: "🚫 CI/CD 파이프라인 스킵" + 이슈 목록 + 과거 장애 연결
  → Memory: "PR #9: Race Condition, CRITICAL, REJECT, INC-0042 패턴"
```

## Memory가 누적되는 플로우 (데모 순서)

```
[1차 시연] L1: 메시지 한국어화
  Memory: (비어있음 — 첫 리뷰)
  결과: LOW, APPROVE
  Memory 저장: "L1: 안전한 변경, APPROVE"

[2차 시연] H1: 시크릿 하드코딩
  Memory: "이전에 L1 APPROVE"
  결과: CRITICAL, REJECT
  Memory 저장: "H1: 시크릿 노출+PCI DSS 위반, CRITICAL, REJECT"

[3차 시연] H4: Race Condition (같은 개발자)
  Memory: "이전에 L1 APPROVE, H1 CRITICAL REJECT"
  Agent: "이 개발자는 이전 PR에서 보안 이슈로 REJECT 판정을 받았습니다.
          이번 PR에서도 에러 핸들링과 보안 관점의 주의가 필요합니다."
  결과: CRITICAL, REJECT (과거 장애 INC-0042 매칭)
  Memory 저장: "H4: Race Condition, INC-0042 패턴, CRITICAL, REJECT"

[4차 시연] H3: N+1 쿼리
  Memory: "L1 APPROVE, H1 REJECT, H4 REJECT"
  Agent: "이 레포에서 최근 REJECT 비율이 증가 추세입니다.
          이전 리뷰에서 보안(H1)과 안정성(H4) 이슈가 연속으로 발견되었고,
          이번에는 성능 이슈까지 추가되었습니다."
  결과: HIGH, REJECT (과거 장애 INC-0041 매칭)
```

## Fallback 플로우 (Agent 실패 시)

```
Analysis Lambda
  │
  ├── Agent 호출 시도 → 성공 → Agent가 모든 것 처리 (정상 경로)
  │
  └── Agent 호출 실패 → Fallback 경로
        │
        ├── GitHub API로 diff 직접 수집
        ├── DynamoDB에서 과거 리뷰 이력 조회
        ├── 장애 패턴 하드코딩 매칭
        ├── 프롬프트 수동 구성
        ├── Bedrock InvokeModel 직접 호출 (Claude Sonnet 4.6)
        ├── JSON 파싱
        ├── GitHub 코멘트 직접 작성
        ├── Slack 리포트 직접 전송
        └── DynamoDB에 이력 저장
```

## 데모 운영 플로우

```bash
# 시나리오 목록 확인
$ ./demo.sh list

# PR 생성 (시나리오 시작)
$ ./demo.sh run h4
  → PR 생성됨 → Webhook → Agent 분석 → GitHub 코멘트 + Slack 리포트

# PR 닫기 (재시연 준비)
$ ./demo.sh reset h4

# 전체 초기화
$ ./demo.sh reset-all
```
