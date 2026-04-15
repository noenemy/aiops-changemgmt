import json
import logging
import os
import boto3
from messages import MESSAGES

logger = logging.getLogger()
logger.setLevel(logging.INFO)

dynamodb = boto3.resource("dynamodb")
orders_table = dynamodb.Table(os.environ["ORDERS_TABLE"])


def handler(event, context):
    order_id = event["pathParameters"]["orderId"]
    logger.info(f"Fetching order: {order_id}")

    try:
        response = orders_table.get_item(Key={"orderId": order_id})
        order = response.get("Item")

        if not order:
            return {
                "statusCode": 404,
                "body": json.dumps({"error": MESSAGES["order_not_found"]}),
            }

        # Refactored: snake_case 통일, 불필요 필드 제거
        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({
                "id": order["orderId"],
                "status": order["status"],
                "total_price": order["totalPrice"],
                "created_at": order["createdAt"],
                "items": order.get("items", []),
                # userId 제거 — 프론트에서 사용하지 않음
            }, default=str),
        }
    except Exception as e:
        logger.error(f"Error fetching order {order_id}: {str(e)}")
        return {
            "statusCode": 500,
            "body": json.dumps({"error": "Internal server error"}),
        }
