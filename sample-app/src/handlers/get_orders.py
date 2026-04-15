import json
import logging
import os
import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

dynamodb = boto3.resource("dynamodb")
orders_table = dynamodb.Table(os.environ["ORDERS_TABLE"])


def handler(event, context):
    request_id = event.get("requestContext", {}).get("requestId", "unknown")
    logger.info(json.dumps({
        "event": "fetch_orders_start",
        "request_id": request_id,
    }))

    try:
        response = orders_table.scan()
        orders = response["Items"]

        logger.info(json.dumps({
            "event": "fetch_orders_complete",
            "request_id": request_id,
            "order_count": len(orders),
        }))

        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps(orders, default=str),
        }
    except Exception as e:
        logger.error(json.dumps({
            "event": "fetch_orders_error",
            "request_id": request_id,
            "error": str(e),
        }))
        return {
            "statusCode": 500,
            "body": json.dumps({"error": "Internal server error"}),
        }
