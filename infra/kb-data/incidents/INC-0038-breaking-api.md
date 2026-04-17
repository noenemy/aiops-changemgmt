---
doc_type: incident
incident_id: INC-0038
date: 2025-11-22
severity: P2
affected_files: [get_order.py]
keywords: [breaking-change, api, mobile, backward-compatibility, field-rename, orderId, 필드명]
---

# 장애 보고서: INC-0038

## 개요
- **일시**: 2025-11-22 10:15 KST
- **심각도**: P2 (High)
- **영향 시간**: 45분
- **매출 손실**: ₩3,500,000

## 제목
API 응답 필드 변경으로 모바일 앱 크래시

## 증상
주문 조회 API의 응답 필드명이 변경된 후 모바일 앱(iOS/Android)에서
JSON 파싱 실패로 주문 화면이 로딩되지 않음.
앱 크래시율이 평소 0.1%에서 34%로 급증.

## 근본 원인
`get_order.py`에서 API 응답 필드명을 리팩토링하면서 Breaking Change 발생.
`orderId` → `id`, `totalPrice` → `total_price`, `orderItems` → `items` 등 5개 필드 변경.
서버 쪽 테스트는 같이 수정하여 100% 통과했지만, 모바일 앱은 기존 필드명을 사용 중이었음.

## 영향 받은 파일
- `src/handlers/get_order.py`

## 코드 패턴 (문제)
```python
# 필드명 변경 — 외부 소비자(모바일 앱) 영향 미고려
return {
    "id": order['orderId'],           # 기존: orderId
    "status": order['status'],         # 기존: order_status
    "total_price": order['totalPrice'],# 기존: totalPrice
}
```

## 수정 방법
- API 버저닝(v1, v2) 도입
- 또는 기존 필드를 유지하면서 새 필드를 추가 (하위 호환성)
- Deprecated 필드는 최소 2스프린트 유예 후 제거

## 재발 방지
- API 계약 테스트(Contract Test) 도입
- Breaking Change 감지 자동화 (OpenAPI 스펙 diff)
- 공개 API 필드 삭제/변경 시 반드시 소비자 영향도 분석

## 태그
breaking-change, api, mobile, backward-compatibility, get_order, field-rename
