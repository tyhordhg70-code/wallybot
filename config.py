import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
DATABASE_URL = os.environ.get("NEON_DATABASE_URL") or os.environ["DATABASE_URL"]
HOODPAY_API_KEY = os.environ["HOODPAY_API_KEY"]
HOODPAY_BUSINESS_ID = int(os.environ.get("HOODPAY_BUSINESS_ID", "0"))
SALES_GROUP_CHAT_ID = os.environ.get("SALES_GROUP_CHAT_ID", "")

PLANS = {
    "1day_1item": {
        "duration_label": "1 Day",
        "duration_days": 1,
        "items": 1,
        "price": 25,
        "label": "1 Day - 1 Item (Unlimited Use) - $25",
        "button_text": "1 Item (Unlimited Use) - $25",
    },
    "1day_3items": {
        "duration_label": "1 Day",
        "duration_days": 1,
        "items": 3,
        "price": 55,
        "label": "1 Day - 3 Items (Unlimited Use) - $55",
        "button_text": "3 Items (Unlimited Use) - $55",
    },
    "3day_1item": {
        "duration_label": "3 Days",
        "duration_days": 3,
        "items": 1,
        "price": 65,
        "label": "3 Days - 1 Item (Unlimited Use) - $65",
        "button_text": "1 Item (Unlimited Use) - $65",
    },
    "3day_3items": {
        "duration_label": "3 Days",
        "duration_days": 3,
        "items": 3,
        "price": 85,
        "label": "3 Days - 3 Items (Unlimited Use) - $85",
        "button_text": "3 Items (Unlimited Use) - $85",
    },
    "1week_1item": {
        "duration_label": "1 Week",
        "duration_days": 7,
        "items": 1,
        "price": 150,
        "label": "1 Week - 1 Item (Unlimited Use) - $150",
        "button_text": "1 Item (Unlimited Use) - $150",
    },
    "1week_3items": {
        "duration_label": "1 Week",
        "duration_days": 7,
        "items": 3,
        "price": 200,
        "label": "1 Week - 3 Items (Unlimited Use) - $200",
        "button_text": "3 Items (Unlimited Use) - $200",
    },
}
