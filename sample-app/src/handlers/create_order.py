import json
import logging
import os
import uuid
from datetime import datetime

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

dynamodb = boto3.resource("dynamodb")
orders_table = dynamodb.Table(os.environ["ORDERS_TABLE"])
inventory_table = dynamodb.Table(os.environ["INVENTORY_TABLE"])


def handler(event, context):
    body = json.loads(event["body"])
    product_id = body["product_id"]
    quantity = body["quantity"]
    user_id = body["user_id"]

    logger.info(f"Creating order for user {user_id}, product {product_id}")

    # Step 1: 재고 확인
    inventory = inventory_table.get_item(Key={"productId": product_id})["Item"]
    available = inventory["stockCount"]

    if available < quantity:
        return {"statusCode": 400, "body": "재고가 부족합니다"}

    # Step 2: 재고 차감
    inventory_table.update_item(
        Key={"productId": product_id},
        UpdateExpression="SET stockCount = stockCount - :qty",
        ExpressionAttributeValues={":qty": quantity},
    )

    # Step 3: 주문 생성
    order_id = str(uuid.uuid4())
    orders_table.put_item(Item={
        "orderId": order_id,
        "userId": user_id,
        "productId": product_id,
        "quantity": quantity,
        "status": "CONFIRMED",
        "totalPrice": inventory["price"] * quantity,
        "createdAt": datetime.now().isoformat(),
    })

    # Step 4: 결제 처리
    payment_result = process_payment(user_id, inventory["price"] * quantity)

    return {"statusCode": 201, "body": json.dumps({"orderId": order_id})}


def process_payment(user_id, amount):
    """Process payment via external service."""
    logger.info(f"Processing payment: user={user_id}, amount={amount}")
    # TODO: 외부 결제 API 연동
    return {"status": "success"}
