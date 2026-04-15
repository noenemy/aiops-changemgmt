import json
import logging
import os
import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

dynamodb = boto3.resource("dynamodb")
orders_table = dynamodb.Table(os.environ["ORDERS_TABLE"])


def handler(event, context):
    logger.info("Fetching orders")

    try:
        response = orders_table.scan()
        orders = response["Items"]

        logger.info(f"Found {len(orders)} orders")

        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps(orders, default=str),
        }
    except Exception as e:
        logger.error(f"Error fetching orders: {str(e)}")
        return {
            "statusCode": 500,
            "body": json.dumps({"error": "Internal server error"}),
        }
