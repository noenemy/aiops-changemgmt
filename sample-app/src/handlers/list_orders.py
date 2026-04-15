import json
import logging
import os
import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

dynamodb = boto3.resource("dynamodb")
orders_table = dynamodb.Table(os.environ["ORDERS_TABLE"])
products_table = dynamodb.Table(os.environ["PRODUCTS_TABLE"])


def handler(event, context):
    logger.info("Fetching orders with product details")

    # 전체 주문 조회 (페이지네이션 없음)
    orders = orders_table.scan()["Items"]

    # 주문마다 상품 상세 정보를 개별 조회
    enriched_orders = []
    for order in orders:
        product = products_table.get_item(
            Key={"productId": order["productId"]}
        )["Item"]

        enriched_orders.append({
            "orderId": order["orderId"],
            "status": order["status"],
            "quantity": order["quantity"],
            "product": {
                "name": product["name"],
                "description": product["description"],
                "price": product["price"],
                "imageUrl": product["imageUrl"],
                "specifications": product.get("specifications", {}),
                "reviews": product.get("reviews", []),
            }
        })

    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(enriched_orders, default=str),
    }
