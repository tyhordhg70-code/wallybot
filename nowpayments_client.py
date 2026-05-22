import logging
import requests
from config import NOWPAYMENTS_API_KEY

logger = logging.getLogger(__name__)

BASE_URL = "https://api.nowpayments.io/v1"


def _headers():
    return {
        "x-api-key": NOWPAYMENTS_API_KEY,
        "Content-Type": "application/json",
    }


def create_invoice(amount, order_id, description):
    """
    Create a NOWPayments hosted invoice.
    Returns the full response dict, or None on failure.

    The invoice URL is at https://nowpayments.io/payment/?iid={id}
    and lets the user pick any supported crypto.
    """
    payload = {
        "price_amount": float(amount),
        "price_currency": "usd",
        "order_id": str(order_id),
        "order_description": description,
    }
    try:
        resp = requests.post(
            f"{BASE_URL}/invoice",
            headers=_headers(),
            json=payload,
            timeout=15,
        )
        data = resp.json()
        logger.info(f"NOWPayments create_invoice → {resp.status_code}: {data}")
        if resp.status_code in (200, 201):
            return data
        logger.error(f"NOWPayments invoice error: {data}")
    except Exception as e:
        logger.exception(f"NOWPayments create_invoice exception: {e}")
    return None


def get_payments_for_invoice(invoice_id):
    """
    Return the list of payment objects linked to an invoice.
    NOWPayments: GET /v1/payment/?invoiceId={id}
    """
    try:
        resp = requests.get(
            f"{BASE_URL}/payment/",
            headers=_headers(),
            params={"invoiceId": str(invoice_id)},
            timeout=15,
        )
        data = resp.json()
        logger.info(f"NOWPayments get_payments → {resp.status_code}: {data}")
        if resp.status_code == 200:
            # Response shape: { "data": [ ...payments... ] }
            if isinstance(data, dict) and "data" in data:
                return data["data"]
            if isinstance(data, list):
                return data
    except Exception as e:
        logger.exception(f"NOWPayments get_payments_for_invoice exception: {e}")
    return []


def extract_invoice_id(invoice_response):
    """Extract the invoice ID from a create_invoice response."""
    if not invoice_response:
        return None
    return str(invoice_response.get("id", "")) or None


def extract_checkout_url(invoice_response):
    """Build the hosted checkout URL from an invoice response."""
    invoice_id = extract_invoice_id(invoice_response)
    if invoice_id:
        return f"https://nowpayments.io/payment/?iid={invoice_id}"
    return None


def get_invoice_status(invoice_id):
    """
    Return the overall status string for an invoice by inspecting its payments.
    Returns one of: 'finished', 'confirmed', 'partially_paid', 'waiting',
    'confirming', 'sending', 'failed', 'expired', 'refunded', or None.
    """
    payments = get_payments_for_invoice(invoice_id)
    if not payments:
        return None
    # Return the status of the most recent payment
    latest = sorted(payments, key=lambda p: p.get("created_at", ""), reverse=True)[0]
    return str(latest.get("payment_status", "")).lower() or None


def is_payment_completed(status):
    """True when the user has fully paid."""
    if not status:
        return False
    return status.lower() in ("finished", "confirmed", "sending")


def is_payment_failed(status):
    """True when the payment cannot be recovered."""
    if not status:
        return False
    return status.lower() in ("failed", "expired", "refunded")
