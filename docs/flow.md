# E2E 플로우 (v2)

## 1. GitHub Webhook 경로 (PR opened/synchronize)

```
T+0.0s  개발자 PR 생성 (gh pr create 또는 웹 UI)
T+0.1s  GitHub → POST /webhook (API Gateway)
T+0.3s  webhook Lambda
         • HMAC-SHA256 서명 검증
         • event filter: pull_request + opened|synchronize
         • Analysis Lambda 비동기 invoke → 200 OK 반환

T+0.5s  analysis Lambda
         • command 필드 없음 → webhook 경로로 판정
         • invoke_agent_for_analysis(pr_data)

T+1.0s  Bedrock Agent (session_id = analysis-pr9-..., memoryId = repo 단위)
         • SESSION_SUMMARY(이전 세션 요약) 자동 주입
         • detect_change_type → get_pr_diff → get_pr_files
         • Persona 활성화(code/iac/mixed)
         • queryKnowledgeBase 검색 (incidents/runbooks/policies)
         • DDB 도구 호출 (get_review_history, get_developer_profile)
         • (필요 시) invoke_security_agent / invoke_devops_agent
         • RiskJudge 종합 → post_github_comment + post_slack_report

T+~20s  endSession=True → Memory 요약 저장
         다음 세션부터 이 PR의 요약이 자동 참조됨
```

## 2. `/analysis <PR>` 경로

```
Slack → POST /slack/commands (API Gateway)
slack-command Lambda
  • Slack X-Slack-Signature 검증
  • /analysis, /reject, /fix 중 하나만 허용
  • PR 메타 조회 (GitHub API)
  • Analysis Lambda 비동기 invoke with {command: "analysis", ...}
  • 3초 내 ephemeral ack: "🔍 PR #9 재분석을 시작했습니다"

analysis Lambda
  • command == "analysis" → webhook 경로와 동일하게 invoke_agent_for_analysis
```

## 3. `/reject <PR> [사유]` 경로

```
slack-command Lambda
  • 파싱: "9 보안 이슈 재검토" → {pr_number: 9, reason: "..."}
  • Analysis Lambda 비동기 invoke with {command: "reject", ...}

analysis Lambda
  • command == "reject" → Agent 건너뛰고 직접 처리
  • _post_github_comment: "🚫 수동 REJECT ... 사유: ..."
  • _post_slack: header + pr + reason + footer (직접 조립)
  • Agent 호출 없음 → 비용/레이턴시 최소
```

## 4. `/fix <PR>` 경로

```
slack-command Lambda → Analysis Lambda with {command: "fix"}

analysis Lambda
  • invoke_agent_for_fix(pr_data)

Bedrock Agent (session_id = fix-pr9-...)
  • get_review_history(files=...) → 기존 이슈 파악
  • get_pr_diff → 현재 코드 재확인
  • 이슈별 구체적 수정 제안 작성
  • post_github_fix_suggestion (일반 코멘트와 별도 헤더)
  • post_slack_report(template="command_fix", ...)
```

## 5. Fallback 경로 (Agent 실패 시)

```
analysis Lambda
  try:
    invoke_agent_for_analysis → 예외 발생 (timeout, 권한 등)
  except:
    fallback_direct()
      • GitHub API로 diff 직접 수집
      • Bedrock invoke_model (claude-sonnet-4-6) 직접 호출
      • 간단한 프롬프트로 risk_score/verdict/summary JSON 받음
      • GitHub 코멘트만 포스팅 (Slack, DDB, KB 없음)
```

## 6. KB 재인덱싱 흐름

```
운영자: vi infra/kb-data/incidents/INC-0046.md
        aws s3 sync infra/kb-data/ s3://<kb-bucket>/ --delete

S3: ObjectCreated:* or ObjectRemoved:* 이벤트 발생
  → kb-reindex Lambda
      • 20초 debounce (다중 파일 업로드 시 1회만 실행)
      • bedrock-agent:StartIngestionJob 호출

Bedrock KB: 비동기 인덱싱 (수분)
  → 이후 queryKnowledgeBase에서 검색 가능
```

## 7. Memory 누적 예시 (같은 레포 세션 흐름)

```
[1] PR #5 L1 (i18n) → LOW APPROVE
    Memory 저장: "PR#5 dev-ethan i18n LOW APPROVE"

[2] PR #6 H1 (secret) → CRITICAL REJECT
    Memory 로드: "PR#5 LOW"
    Memory 저장: "PR#6 dev-ethan 시크릿 하드코딩 CRITICAL REJECT"

[3] PR #7 H4 (race) → CRITICAL REJECT (같은 dev-ethan)
    Memory 로드: "PR#5 LOW, PR#6 CRITICAL (시크릿)"
    Agent: "dev-ethan은 이전 PR#6에서 보안 이슈로 REJECT, 이번에 안정성 이슈 추가"
    Memory 저장: "PR#7 Race Condition CRITICAL REJECT INC-0042 패턴"

[4] PR #8 (다른 개발자) 
    Memory 로드: 위 3개 요약 전부 (레포 단위 memoryId)
    Agent: "최근 REJECT 비율 67%, 보안/안정성 이슈 누적"
```
