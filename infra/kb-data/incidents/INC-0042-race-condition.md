# 장애 보고서: INC-0042

## 개요
- **일시**: 2026-01-15 14:30 KST
- **심각도**: P1 (Critical)
- **영향 시간**: 2시간
- **매출 손실**: ₩12,000,000

## 제목
주문 폭주 시 재고 마이너스 발생 — Race Condition

## 증상
설 연휴 프로모션 트래픽 폭증 시 동일 상품에 대해 재고보다 많은 주문이 생성됨.
재고가 -23까지 떨어졌으며, 이미 결제 완료된 주문 23건에 대해 환불 처리 필요.

## 근본 원인
`create_order.py`에서 재고 확인(get_item)과 재고 차감(update_item) 사이에 Race Condition 발생.
동시 요청이 같은 재고 값을 읽은 뒤 각각 차감하여 overselling 발생. (TOCTOU 취약점)

## 영향 받은 파일
- `src/handlers/create_order.py` (L17-L28)

## 코드 패턴 (문제)
```python
# Step 1: 재고 확인 (읽기)
inventory = inventory_table.get_item(Key={'productId': product_id})['Item']
available = inventory['stockCount']
if available < quantity:
    return error

# Step 2: 재고 차감 (쓰기) — 이 사이에 다른 요청이 끼어들 수 있음
inventory_table.update_item(
    UpdateExpression='SET stockCount = stockCount - :qty',
    ExpressionAttributeValues={':qty': quantity}
)
```

## 수정 방법
```python
# ConditionExpression으로 원자적 차감
inventory_table.update_item(
    Key={'productId': product_id},
    UpdateExpression='SET stockCount = stockCount - :qty',
    ConditionExpression='stockCount >= :qty',
    ExpressionAttributeValues={':qty': quantity}
)
```

## 재발 방지
- DynamoDB의 ConditionExpression을 활용한 낙관적 잠금 적용
- 동시성 테스트 추가 (locust 부하 테스트)

## 태그
race-condition, toctou, dynamodb, inventory, overselling, create_order
