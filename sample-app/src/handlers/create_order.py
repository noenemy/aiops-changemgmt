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
    try:
        body = json.loads(event["body"])
        product_id = body["product_id"]
        quantity = body["quantity"]
        user_id = body["user_id"]
    except (json.JSONDecodeError, KeyError) as e:
        return {
            "statusCode": 400,
            "body": json.dumps({"error": "Invalid request body"}),
        }

    logger.info(f"Creating order for user {user_id}, product {product_id}")

    try:
        # Atomic inventory decrement with condition
        inventory_table.update_item(
            Key={"productId": product_id},
            UpdateExpression="SET stockCount = stockCount - :qty",
            ConditionExpression="stockCount >= :qty",
            ExpressionAttributeValues={":qty": quantity},
        )
    except dynamodb.meta.client.exceptions.ConditionalCheckFailedException:
        return {
            "statusCode": 400,
            "body": json.dumps({"error": "Insufficient stock"}),
        }

    order_id = str(uuid.uuid4())
    order = {
        "orderId": order_id,
        "userId": user_id,
        "productId": product_id,
        "quantity": quantity,
        "status": "CONFIRMED",
        "totalPrice": quantity * 29900,
        "createdAt": datetime.now().isoformat(),
    }

    orders_table.put_item(Item=order)
    logger.info(f"Order created: {order_id}")

    return {
        "statusCode": 201,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps({"orderId": order_id}),
    }
