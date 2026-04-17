---
doc_type: incident
incident_id: INC-0041
date: 2025-12-20
severity: P1
affected_files: [list_orders.py]
keywords: [n-plus-1, dynamodb, throttling, scan, pagination, performance, for-loop, get_item]
---

# 장애 보고서: INC-0041

## 개요
- **일시**: 2025-12-20 19:45 KST
- **심각도**: P1 (Critical)
- **영향 시간**: 1시간 30분
- **매출 손실**: ₩8,200,000
- **추가 비용**: DynamoDB 온디맨드 과금 ₩2,100,000

## 제목
주문 목록 API에서 N+1 쿼리로 DynamoDB 쓰로틀링 발생 — 전체 서비스 연쇄 장애

## 증상
크리스마스 시즌 트래픽 증가 시 주문 목록 API 응답시간이 30초 이상으로 증가.
DynamoDB ReadCapacityUnits가 쓰로틀링 상태에 도달하여
동일 테이블을 사용하는 주문 생성, 결제 API까지 영향 받음.

## 근본 원인
`list_orders.py`에서 주문 목록을 scan() 후 각 주문마다 상품 테이블을 개별 get_item() 호출.
로컬 테스트 데이터 10건에서는 문제 없었으나, 프로덕션 50,000건에서 50,001회 DynamoDB 호출 발생.
페이지네이션도 없어 전체 테이블 스캔.

## 영향 받은 파일
- `src/handlers/list_orders.py`

## 코드 패턴 (문제)
```python
orders = orders_table.scan()['Items']  # 전체 스캔, 페이지네이션 없음
for order in orders:
    product = products_table.get_item(  # N+1 쿼리
        Key={'productId': order['productId']}
    )['Item']
```

## 수정 방법
- BatchGetItem으로 최대 100건씩 일괄 조회
- limit + LastEvaluatedKey 기반 페이지네이션 필수
- 목록 API에는 요약 정보만 포함 (상세는 개별 API로)

## 재발 방지
- DynamoDB 사용 가이드라인 문서화 (scan 금지, 페이지네이션 필수)
- CloudWatch 알람: RCU 사용률 70% 초과 시 알림
- 성능 테스트: 프로덕션 규모 데이터로 부하 테스트 필수

## 태그
n-plus-1, dynamodb, throttling, scan, pagination, list_orders, performance
