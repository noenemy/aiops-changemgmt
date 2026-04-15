#!/usr/bin/env python3
"""Seed sample data into DynamoDB tables."""

import argparse
import boto3
import json

def get_stack_outputs(stack_name, region):
    cf = boto3.client("cloudformation", region_name=region)
    response = cf.describe_stacks(StackName=stack_name)
    outputs = response["Stacks"][0]["Outputs"]
    return {o["OutputKey"]: o["OutputValue"] for o in outputs}


def seed_products(table_name, region):
    dynamodb = boto3.resource("dynamodb", region_name=region)
    table = dynamodb.Table(table_name)

    products = [
        {
            "productId": "prod-001",
            "name": "무선 블루투스 이어폰",
            "description": "노이즈 캔슬링 지원 고음질 블루투스 이어폰",
            "price": 89000,
            "imageUrl": "/images/earbuds.png",
            "category": "electronics",
            "specifications": {"battery": "8시간", "bluetooth": "5.3", "weight": "5.2g"},
            "reviews": [
                {"user": "user-101", "rating": 5, "comment": "음질 최고"},
                {"user": "user-102", "rating": 4, "comment": "가성비 좋음"},
            ],
        },
        {
            "productId": "prod-002",
            "name": "스마트 워치 Pro",
            "description": "건강 모니터링 + GPS 지원 스마트 워치",
            "price": 299000,
            "imageUrl": "/images/watch.png",
            "category": "electronics",
            "specifications": {"battery": "48시간", "display": "1.4인치 AMOLED", "waterproof": "5ATM"},
            "reviews": [],
        },
        {
            "productId": "prod-003",
            "name": "프리미엄 백팩",
            "description": "노트북 수납 가능 비즈니스 백팩",
            "price": 129000,
            "imageUrl": "/images/backpack.png",
            "category": "fashion",
            "specifications": {"material": "방수 나일론", "capacity": "25L", "laptop": "16인치"},
            "reviews": [
                {"user": "user-103", "rating": 5, "comment": "출장 필수템"},
            ],
        },
    ]

    for product in products:
        table.put_item(Item=product)
    print(f"  Seeded {len(products)} products into {table_name}")


def seed_inventory(table_name, region):
    dynamodb = boto3.resource("dynamodb", region_name=region)
    table = dynamodb.Table(table_name)

    inventory = [
        {"productId": "prod-001", "stockCount": 150, "price": 89000},
        {"productId": "prod-002", "stockCount": 50, "price": 299000},
        {"productId": "prod-003", "stockCount": 200, "price": 129000},
    ]

    for item in inventory:
        table.put_item(Item=item)
    print(f"  Seeded {len(inventory)} inventory items into {table_name}")


def seed_orders(table_name, region):
    dynamodb = boto3.resource("dynamodb", region_name=region)
    table = dynamodb.Table(table_name)

    orders = [
        {
            "orderId": "order-001",
            "userId": "user-101",
            "productId": "prod-001",
            "quantity": 1,
            "status": "CONFIRMED",
            "totalPrice": 89000,
            "createdAt": "2026-04-10T09:30:00",
            "items": [{"productId": "prod-001", "name": "무선 블루투스 이어폰", "quantity": 1}],
        },
        {
            "orderId": "order-002",
            "userId": "user-102",
            "productId": "prod-002",
            "quantity": 1,
            "status": "CONFIRMED",
            "totalPrice": 299000,
            "createdAt": "2026-04-11T14:20:00",
            "items": [{"productId": "prod-002", "name": "스마트 워치 Pro", "quantity": 1}],
        },
        {
            "orderId": "order-003",
            "userId": "user-103",
            "productId": "prod-003",
            "quantity": 2,
            "status": "SHIPPED",
            "totalPrice": 258000,
            "createdAt": "2026-04-12T11:00:00",
            "items": [{"productId": "prod-003", "name": "프리미엄 백팩", "quantity": 2}],
        },
    ]

    for order in orders:
        table.put_item(Item=order)
    print(f"  Seeded {len(orders)} orders into {table_name}")


def main():
    parser = argparse.ArgumentParser(description="Seed sample data")
    parser.add_argument("--stack-name", default="aiops-changemgmt-app")
    parser.add_argument("--region", default="ap-northeast-2")
    args = parser.parse_args()

    print(f"Getting stack outputs for {args.stack_name}...")
    outputs = get_stack_outputs(args.stack_name, args.region)

    print("Seeding data...")
    seed_products(outputs["ProductsTableName"], args.region)
    seed_inventory(outputs["InventoryTableName"], args.region)
    seed_orders(outputs["OrdersTableName"], args.region)

    print("Done!")
    print(f"API URL: {outputs['ApiUrl']}")


if __name__ == "__main__":
    main()
