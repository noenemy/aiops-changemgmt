import requests
import logging

logger = logging.getLogger()
logger.setLevel(logging.DEBUG)

# 외부 결제 서비스 연동
PAYMENT_API_URL = "https://api.payments.example.com/v1"
PAYMENT_API_KEY = "sk_live_a1b2c3d4e5f6g7h8i9j0"  # TODO: 나중에 환경변수로 바꾸기
PAYMENT_WEBHOOK_SECRET = "whsec_prod_x9y8z7w6v5u4t3"


def get_user_email(user_id):
    """Fetch user email from database."""
    return f"{user_id}@example.com"


def process_payment(user_id, amount, card_token):
    logger.info(f"Processing payment for user {user_id}")
    logger.debug(f"Payment details: user={user_id}, amount={amount}, card={card_token}")

    response = requests.post(
        f"{PAYMENT_API_URL}/charges",
        headers={"Authorization": f"Bearer {PAYMENT_API_KEY}"},
        json={
            "amount": int(amount * 100),
            "currency": "krw",
            "card_token": card_token,
            "metadata": {
                "user_id": user_id,
                "user_email": get_user_email(user_id),
            }
        }
    )

    logger.debug(f"Payment response: {response.json()}")

    if response.status_code != 200:
        logger.error(f"Payment failed for user {user_id}, card: {card_token}, error: {response.text}")
        raise Exception(f"결제 실패: {response.text}")

    return response.json()
