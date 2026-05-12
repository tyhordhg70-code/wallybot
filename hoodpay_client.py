import logging
import requests
from config import HOODPAY_API_KEY, HOODPAY_BUSINESS_ID

logger = logging.getLogger(__name__)

BASE_URL = "https://api.hoodpay.io"


def _headers():
    return {
        "Authorization": f"Bearer {HOODPAY_API_KEY}",
        "Content-Type": "application/json",
    }


def create_payment(amount, currency="USD", name=None, description=None):
    """Create a HoodPay payment and return payment info with checkout URL."""
    try:
        from hoodpay.hoodpay import HoodPay
        client = HoodPay(api_key=HOODPAY_API_KEY, business_id=HOODPAY_BUSINESS_ID)
        result = client.create_payment(
            currency=currency,
            amount=float(amount),
            name=name,
            description=description,
        )
        logger.info(f"HoodPay create_payment response: {result}")
        return result
    except Exception as e:
        logger.error(f"HoodPay create_payment error: {e}")
        # Fallback to direct REST API call
        return _create_payment_rest(amount, currency, name, description)


def _create_payment_rest(amount, currency="USD", name=None, description=None):
    """Fallback REST API call for creating payments."""
    try:
        payload = {
            "currency": currency,
            "amount": float(amount),
        }
        if name:
            payload["name"] = name
        if description:
            payload["description"] = description

        resp = requests.post(
            f"{BASE_URL}/v1/businesses/{HOODPAY_BUSINESS_ID}/payments",
            headers=_headers(),
            json=payload,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        logger.info(f"HoodPay REST create_payment response: {data}")
        return data
    except Exception as e:
        logger.error(f"HoodPay REST create_payment error: {e}")
        return None


def get_payment(payment_id):
    """Get payment status by HoodPay payment ID."""
    try:
        from hoodpay.hoodpay import HoodPay
        client = HoodPay(api_key=HOODPAY_API_KEY, business_id=HOODPAY_BUSINESS_ID)
        result = client.get_payment(payment_id)
        logger.info(f"HoodPay get_payment response: {result}")
        return result
    except Exception as e:
        logger.error(f"HoodPay get_payment error: {e}")
        return _get_payment_rest(payment_id)


def _get_payment_rest(payment_id):
    """Fallback REST API call for getting payment."""
    try:
        resp = requests.get(
            f"{BASE_URL}/v1/businesses/{HOODPAY_BUSINESS_ID}/payments/{payment_id}",
            headers=_headers(),
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        logger.info(f"HoodPay REST get_payment response: {data}")
        return data
    except Exception as e:
        logger.error(f"HoodPay REST get_payment error: {e}")
        return None


def extract_checkout_url(payment_response):
    """Extract checkout URL from various response formats."""
    if not payment_response:
        return None
    if isinstance(payment_response, dict):
        for key in ["checkout_url", "checkoutUrl", "url", "payment_url", "paymentUrl"]:
            if key in payment_response:
                return payment_response[key]
        if "data" in payment_response:
            return extract_checkout_url(payment_response["data"])
    return None


def extract_payment_id(payment_response):
    """Extract payment ID from various response formats."""
    if not payment_response:
        return None
    if isinstance(payment_response, dict):
        for key in ["id", "payment_id", "paymentId"]:
            if key in payment_response:
                return str(payment_response[key])
        if "data" in payment_response:
            return extract_payment_id(payment_response["data"])
    return None


def extract_payment_status(payment_response):
    """Extract payment status from various response formats."""
    if not payment_response:
        return None
    if isinstance(payment_response, dict):
        for key in ["status", "paymentStatus", "payment_status"]:
            if key in payment_response:
                val = payment_response[key]
                if isinstance(val, str):
                    return val.lower()
                return str(val).lower()
        if "data" in payment_response:
            return extract_payment_status(payment_response["data"])
    return None
