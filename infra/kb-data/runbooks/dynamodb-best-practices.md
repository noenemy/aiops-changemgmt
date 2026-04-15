# DynamoDB 사용 가이드라인

## 필수 규칙

### 1. scan()은 절대 프로덕션 API에서 사용 금지
- scan()은 전체 테이블을 읽는 연산. RCU를 대량 소비.
- 목록 조회는 반드시 Query + GSI 또는 페이지네이션 적용.

### 2. 페이지네이션 필수
- `Limit` + `LastEvaluatedKey` 기반 커서 페이지네이션.
- API Gateway 응답 크기 제한: 10MB. 초과 시 502 Bad Gateway.

### 3. N+1 쿼리 금지
- 루프 안에서 get_item() 개별 호출 금지.
- `BatchGetItem`으로 최대 100건씩 일괄 조회.
- 또는 데이터 모델링을 변경하여 단일 쿼리로 해결.

### 4. 낙관적 잠금 (Optimistic Locking)
- 재고, 포인트, 잔액 등 동시 변경이 가능한 필드는 반드시 ConditionExpression 사용.
```python
table.update_item(
    ConditionExpression='stockCount >= :qty',
    UpdateExpression='SET stockCount = stockCount - :qty',
)
```

### 5. 파티션 키 변경 금지
- 기존 테이블의 파티션 키를 변경하면 기존 데이터에 접근 불가.
- 새로운 접근 패턴이 필요하면 GSI를 추가할 것.

## 모니터링
- CloudWatch 알람: ConsumedReadCapacityUnits > ProvisionedReadCapacityUnits × 0.7
- ThrottledRequests > 0 시 즉시 알림
