import logging
import requests
from config import HOODPAY_API_KEY, HOODPAY_BUSINESS_ID

logger = logging.getLogger(__name__)

# Try multiple base URLs as HoodPay has had different endpoints
API_URLS = [
    "https://api.hoodpay.io/v1",
    "https://api.hoodpay.com/v1",
]


def _headers():
    return {
        "Authorization": f"Bearer {HOODPAY_API_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def create_payment(amount, currency="USD", name=None, description=None):
    """Create a HoodPay payment. Returns dict with payment info or None."""

    payload = {
        "currency": currency,
        "amount": float(amount),
    }
    if name:
        payload["name"] = name
    if description:
        payload["description"] = description

    # Try SDK first
    try:
        from hoodpay.hoodpay import HoodPay

        client = HoodPay(api_key=HOODPAY_API_KEY, business_id=HOODPAY_BUSINESS_ID)
        result = client.create_payment(
            currency=currency,
            amount=float(amount),
            name=name,
            description=description,
        )
        logger.info(f"HoodPay SDK response: {result}")
        if result and isinstance(result, dict) and "error" not in str(result).lower():
            return result
    except Exception as e:
        logger.warning(f"HoodPay SDK error: {e}")

    # Try REST API with multiple base URLs
    for base_url in API_URLS:
        try:
            url = f"{base_url}/businesses/{HOODPAY_BUSINESS_ID}/payments"
            resp = requests.post(url, headers=_headers(), json=payload, timeout=15)
            if resp.status_code in (200, 201):
                data = resp.json()
                logger.info(f"HoodPay REST response from {base_url}: {data}")
                return data
            else:
                logger.warning(f"HoodPay REST {base_url}: {resp.status_code} - {resp.text[:200]}")
        except Exception as e:
            logger.warning(f"HoodPay REST error ({base_url}): {e}")

    logger.error("All HoodPay payment creation methods failed")
    return None


def get_payment(payment_id):
    """Get payment status by HoodPay payment ID."""
    # Try SDK first
    try:
        from hoodpay.hoodpay import HoodPay

        client = HoodPay(api_key=HOODPAY_API_KEY, business_id=HOODPAY_BUSINESS_ID)
        result = client.get_payment(payment_id)
        if result:
            return result
    except Exception as e:
        logger.warning(f"HoodPay SDK get_payment error: {e}")

    # Try REST API
    for base_url in API_URLS:
        try:
            url = f"{base_url}/businesses/{HOODPAY_BUSINESS_ID}/payments/{payment_id}"
            resp = requests.get(url, headers=_headers(), timeout=15)
            if resp.status_code == 200:
                return resp.json()
        except Exception as e:
            logger.warning(f"HoodPay REST get_payment error ({base_url}): {e}")

    return None


def extract_checkout_url(payment_response):
    """Extract checkout URL from various response formats."""
    if not payment_response:
        return None
    if isinstance(payment_response, dict):
        # Direct fields
        for key in ["checkout_url", "checkoutUrl", "url", "payment_url", "paymentUrl"]:
            if key in payment_response:
                return payment_response[key]
        # Nested in data
        if "data" in payment_response and isinstance(payment_response["data"], dict):
            return extract_checkout_url(payment_response["data"])
        # Build from payment ID
        pid = extract_payment_id(payment_response)
        if pid:
            return f"https://checkout.hoodpay.io/{pid}"
    return None


def extract_payment_id(payment_response):
    """Extract payment ID from various response formats."""
    if not payment_response:
        return None
    if isinstance(payment_response, dict):
        for key in ["id", "payment_id", "paymentId"]:
            if key in payment_response:
                return str(payment_response[key])
        if "data" in payment_response and isinstance(payment_response["data"], dict):
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
                return str(val).lower() if val else None
        if "data" in payment_response and isinstance(payment_response["data"], dict):
            return extract_payment_status(payment_response["data"])
    return None


def is_payment_completed(status_str):
    """Check if a HoodPay payment status means completed/paid."""
    if not status_str:
        return False
    s = status_str.lower()
    return s in ("completed", "confirmed", "paid", "settled")


def is_payment_failed(status_str):
    """Check if a HoodPay payment status means failed/expired."""
    if not status_str:
        return False
    s = status_str.lower()
    return s in ("expired", "cancelled", "canceled", "failed", "refunded")
