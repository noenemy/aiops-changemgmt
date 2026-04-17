---
doc_type: policy
topic: code-review-checklist
keywords: [code-review, checklist, security, performance, reliability, compatibility]
---

# 코드 리뷰 체크리스트

모든 PR 리뷰는 아래 4축을 반드시 점검한다.

## 1. 보안
- 시크릿/API 키가 하드코딩되어 있지 않은가? (Secrets Manager 또는 Parameter Store 사용)
- SQL/NoSQL Injection 가능성 — 사용자 입력이 파라미터화되어 있는가?
- PII(이름, 이메일, 전화번호, 카드번호 등)가 로그에 기록되지 않는가?
- 인증/인가 우회 — 인증 미들웨어를 건너뛰는 경로가 있는가?
- IAM 권한 — 최소 권한 원칙을 지키는가? `*` 리소스 금지.

## 2. 성능
- N+1 쿼리 — for 루프 내 개별 DB 호출 금지
- DynamoDB scan 금지 (프로덕션 API)
- 페이지네이션 — 목록 API는 반드시 Limit + Cursor
- 외부 API 호출에 timeout 설정
- Lambda 메모리/실행 시간 — 불필요한 대용량 페이로드 처리 피하기

## 3. 안정성
- Race Condition — 동시성 이슈가 있는 필드는 낙관적 잠금 또는 ConditionExpression
- 에러 핸들링 — try/except가 예외를 무시하지 않는가?
- 보상 트랜잭션 — 멀티스텝 작업의 실패 복구 경로가 있는가?
- 멱등성 — 같은 요청이 두 번 와도 안전한가?

## 4. 호환성
- Breaking API Change — 기존 필드명/타입 변경 금지, 삭제는 Deprecated 후 2스프린트
- 데이터 마이그레이션 — 기존 데이터 호환되는가?
- 소비자(모바일 앱, 외부 API) 영향 분석

## 판정 기준
- 4축 중 하나라도 CRITICAL 이슈 발견 시 REJECT
- HIGH 이슈 2개 이상 시 REJECT
- 그 외는 MEDIUM/LOW 판정 후 개별 수정 요청
