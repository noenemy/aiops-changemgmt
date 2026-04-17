---
doc_type: runbook
topic: api-change-policy
keywords: [api, breaking-change, versioning, backward-compatibility, deprecation, 호환성]
---

# API 변경 정책

## 공개 API 필드 변경 규칙

### 절대 금지
- 기존 필드 이름 변경 (Breaking Change)
- 기존 필드 삭제 (소비자 영향 미확인 상태)
- 기존 필드의 타입 변경 (string → number 등)

### 허용 (단, 주의)
- 새 필드 추가 (하위 호환성 유지)
- 기존 필드를 Deprecated로 표시 (최소 2스프린트 유예)

### Breaking Change가 불가피한 경우
1. API 버저닝 적용 (v1 → v2)
2. v1은 최소 6개월 유지
3. 모든 알려진 소비자(모바일 앱, 파트너 API)에 사전 공지
4. API 계약 테스트(Contract Test)로 하위 호환성 검증

## 소비자 목록 (알려진 API 클라이언트)
- iOS 앱 (v3.2+)
- Android 앱 (v3.1+)
- 파트너 정산 시스템 (partner-billing-api)
- 내부 대시보드 (admin-dashboard)
- 마케팅 분석 시스템 (analytics-pipeline)
