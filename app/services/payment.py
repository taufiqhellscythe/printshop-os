"""Payment gateway integration (Midtrans QRIS via Core API).

Design notes
------------
* QRIS dynamic per order: each order gets its own QR string with the exact amount,
  so settlement can be detected automatically via webhook (unlike a static personal QRIS).
* Core API `/v2/charge` with payment_type=qris returns a `qr_string` and an action URL
  to the QR image, which we render on our own /pay page (no external redirect).
* Webhook (`/api/payment/webhook`) is verified with SHA512 signature:
      signature = sha512(order_id + status_code + gross_amount + server_key)
* Provider is abstracted behind a thin layer so Xendit can be added later without
  touching the routers.
"""
from __future__ import annotations

import hashlib
import logging
from typing import Any

import httpx

from app.config import (
    MIDTRANS_IS_PRODUCTION,
    MIDTRANS_QRIS_ACQUIRER,
    MIDTRANS_SERVER_KEY,
    payment_enabled,
)

logger = logging.getLogger(__name__)

CORE_BASE_PROD = "https://api.midtrans.com"
CORE_BASE_SANDBOX = "https://api.sandbox.midtrans.com"


def _base_url() -> str:
    return CORE_BASE_PROD if MIDTRANS_IS_PRODUCTION else CORE_BASE_SANDBOX


def _auth_header() -> dict[str, str]:
    # Midtrans uses HTTP Basic with server key as username and empty password.
    import base64

    token = base64.b64encode(f"{MIDTRANS_SERVER_KEY}:".encode()).decode()
    return {
        "Authorization": f"Basic {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


class PaymentError(Exception):
    pass


def create_qris_charge(order: dict[str, Any]) -> dict[str, Any]:
    """Create a QRIS charge for an order. Returns dict with qr_string + qr_image_url.

    The Midtrans order_id must be unique per charge attempt. We use the order code
    plus a short suffix so re-charging a still-pending order works. The internal
    order code is recoverable by splitting on '-'.
    """
    if not payment_enabled():
        raise PaymentError("Payment gateway belum dikonfigurasi")

    gross = int(order["total"])
    if gross <= 0:
        raise PaymentError("Total order tidak valid untuk pembayaran online")

    # midtrans_order_id must be unique; embed order code for traceability.
    import time

    midtrans_order_id = f"{order['code']}-{int(time.time())}"

    payload = {
        "payment_type": "qris",
        "transaction_details": {
            "order_id": midtrans_order_id,
            "gross_amount": gross,
        },
        "qris": {"acquirer": MIDTRANS_QRIS_ACQUIRER},
        "customer_details": {
            "first_name": order.get("customer_name") or "Pelanggan",
            "phone": order.get("customer_phone") or "",
            "email": order.get("customer_email") or "",
        },
        "item_details": [
            {
                "id": order["code"],
                "price": gross,
                "quantity": 1,
                "name": f"Order {order['code']}"[:50],
            }
        ],
    }

    try:
        # trust_env=False: ignore *_PROXY env vars. The host exports a SOCKS5
        # proxy which httpx cannot use without the optional `socksio` package,
        # and Midtrans is reachable directly anyway.
        with httpx.Client(timeout=20, trust_env=False) as client:
            resp = client.post(
                f"{_base_url()}/v2/charge",
                headers=_auth_header(),
                json=payload,
            )
        data = resp.json()
    except Exception as e:  # network / decode
        logger.exception("Midtrans charge failed")
        raise PaymentError(f"Gagal menghubungi payment gateway: {e}") from e

    status_code = str(data.get("status_code", ""))
    # 201 = created & pending (expected for QRIS)
    if status_code not in ("201", "200"):
        msgs = data.get("status_message") or data.get("error_messages") or data
        raise PaymentError(f"Charge ditolak gateway: {msgs}")

    qr_string = data.get("qr_string")
    qr_image_url = None
    for action in data.get("actions", []) or []:
        if action.get("name") == "generate-qr-code":
            qr_image_url = action.get("url")
            break

    return {
        "midtrans_order_id": midtrans_order_id,
        "transaction_id": data.get("transaction_id"),
        "gross_amount": gross,
        "qr_string": qr_string,
        "qr_image_url": qr_image_url,
        "transaction_status": data.get("transaction_status"),
        "expiry_time": data.get("expiry_time"),
        "raw": data,
    }


def verify_signature(midtrans_order_id: str, status_code: str, gross_amount: str, signature_key: str) -> bool:
    """Validate Midtrans webhook signature (SHA512).

    signature = sha512(order_id + status_code + gross_amount + server_key)
    gross_amount arrives as a string like "5000.00" — must be used verbatim.
    """
    raw = f"{midtrans_order_id}{status_code}{gross_amount}{MIDTRANS_SERVER_KEY}"
    computed = hashlib.sha512(raw.encode()).hexdigest()
    # constant-time compare
    import hmac

    return hmac.compare_digest(computed, (signature_key or "").lower())


def is_settled(transaction_status: str, fraud_status: str | None = None) -> bool:
    """True when funds are captured and the order should proceed."""
    ts = (transaction_status or "").lower()
    if ts == "settlement":
        return True
    if ts == "capture" and (fraud_status or "accept").lower() == "accept":
        return True
    return False


def code_from_midtrans_order_id(midtrans_order_id: str) -> str:
    """Recover internal order code from the unique midtrans order id."""
    return (midtrans_order_id or "").rsplit("-", 1)[0]
