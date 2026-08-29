"""Payment routes: QRIS checkout page, webhook, and status polling.

Flow
----
1. Customer submits order -> redirected to /pay/{token}
2. /pay/{token} creates (or reuses) a QRIS charge and renders the QR.
3. Customer scans & pays with any QRIS-capable app.
4. Midtrans calls POST /api/payment/webhook on settlement.
   -> signature verified -> payment marked paid
   -> order set payment_status=lunas + status=PAYMENT_PAID_STATUS (default 'antrian')
   -> maybe_auto_print_for_status() enqueues prints automatically.
5. The /pay page polls /api/payment/status/{token} and redirects to tracking once paid.
"""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.config import (
    PAYMENT_PAID_STATUS,
    PAYMENT_PROVIDER,
    SHOP_ADDRESS,
    SHOP_NAME,
    SHOP_PHONE,
    payment_enabled,
)
from app.db import db
from app.services import payment as pay
from app.services.print_jobs import maybe_auto_print_for_status
from app.utils import rupiah

logger = logging.getLogger("printshop-os.payment")

router = APIRouter(tags=["payment"])
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))
templates.env.globals.update(
    rupiah=rupiah,
    shop_name=SHOP_NAME,
    shop_phone=SHOP_PHONE,
    shop_address=SHOP_ADDRESS,
)


def _settle_order(order: dict, payment_row: dict, provider_txn_id: str | None, raw: dict) -> None:
    """Mark payment paid, advance order, trigger auto-print. Idempotent."""
    if payment_row and payment_row.get("status") != "paid":
        db.mark_payment_status(
            payment_row["id"], "paid", transaction_id=provider_txn_id, raw=raw
        )
    # Only advance if not already lunas (idempotency for duplicate webhooks).
    fresh = db.get_order(order["id"])
    if fresh and fresh.get("payment_status") != "lunas":
        db.update_order_status(
            order["id"],
            PAYMENT_PAID_STATUS,
            actor="payment-webhook",
            payment_status="lunas",
            payment_method="QRIS",
            paid_amount=int(fresh["total"]),
            message="Pembayaran QRIS lunas (otomatis) → masuk antrian",
        )
        # Auto-enqueue prints for the new status (antrian/proses -> auto-print).
        try:
            maybe_auto_print_for_status(order["id"], PAYMENT_PAID_STATUS, actor="payment-webhook")
        except Exception:
            logger.exception("Auto-print after payment failed for order %s", order["code"])


@router.get("/pay/{token}", response_class=HTMLResponse)
async def pay_page(request: Request, token: str):
    order = db.get_order(track_token=token)
    if not order:
        return HTMLResponse("Link pembayaran tidak valid.", status_code=404)

    # If already paid, go straight to tracking.
    if order.get("payment_status") == "lunas":
        return RedirectResponse(f"/track/{token}", status_code=303)

    if not payment_enabled():
        # Gateway off: fall back to tracking (manual confirmation).
        return RedirectResponse(f"/track/{token}?pay=manual", status_code=303)

    # Reuse an existing pending charge if present, else create a new one.
    payment = db.latest_payment_for_order(order["id"])
    if not payment or payment.get("status") not in ("pending",) or not payment.get("qr_image_url"):
        try:
            charge = pay.create_qris_charge(order)
        except pay.PaymentError as e:
            return templates.TemplateResponse(
                "public/pay.html",
                {"request": request, "order": order, "payment": None, "error": str(e)},
                status_code=502,
            )
        payment = db.create_payment(
            order["id"],
            provider=PAYMENT_PROVIDER or "midtrans",
            provider_order_id=charge["midtrans_order_id"],
            transaction_id=charge.get("transaction_id"),
            amount=charge["gross_amount"],
            qr_string=charge.get("qr_string"),
            qr_image_url=charge.get("qr_image_url"),
            expiry_time=charge.get("expiry_time"),
            raw=charge.get("raw"),
        )

    return templates.TemplateResponse(
        "public/pay.html",
        {"request": request, "order": order, "payment": payment, "error": None},
    )


@router.get("/api/payment/status/{token}")
async def payment_status(token: str):
    order = db.get_order(track_token=token)
    if not order:
        return JSONResponse({"ok": False, "error": "not found"}, status_code=404)
    paid = order.get("payment_status") == "lunas"
    return {
        "ok": True,
        "paid": paid,
        "status": order.get("status"),
        "payment_status": order.get("payment_status"),
        "redirect": f"/track/{token}" if paid else None,
    }


@router.post("/api/payment/webhook")
async def payment_webhook(request: Request):
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "invalid json"}, status_code=400)

    provider_order_id = str(body.get("order_id", ""))
    status_code = str(body.get("status_code", ""))
    gross_amount = str(body.get("gross_amount", ""))
    signature_key = str(body.get("signature_key", ""))
    transaction_status = str(body.get("transaction_status", ""))
    fraud_status = body.get("fraud_status")
    transaction_id = body.get("transaction_id")

    # 1. Verify signature — reject forgeries.
    if not pay.verify_signature(provider_order_id, status_code, gross_amount, signature_key):
        logger.warning("Webhook signature mismatch for %s", provider_order_id)
        return JSONResponse({"ok": False, "error": "invalid signature"}, status_code=403)

    # 2. Locate our payment + order.
    payment = db.get_payment_by_provider_oid(provider_order_id)
    if not payment:
        # Fall back to recovering the order code from the composite id.
        code = pay.code_from_midtrans_order_id(provider_order_id)
        order = db.get_order(code=code)
        if not order:
            logger.warning("Webhook for unknown order %s", provider_order_id)
            return JSONResponse({"ok": True, "note": "unknown order, ignored"})
    else:
        order = db.get_order(payment["order_id"])

    if not order:
        return JSONResponse({"ok": True, "note": "order gone, ignored"})

    # 3. Act on transaction status.
    if pay.is_settled(transaction_status, fraud_status):
        _settle_order(order, payment, transaction_id, body)
        return {"ok": True, "settled": True}

    if transaction_status in ("expire", "cancel", "deny"):
        if payment and payment.get("status") == "pending":
            db.mark_payment_status(payment["id"], transaction_status, raw=body)
        return {"ok": True, "settled": False, "status": transaction_status}

    # pending / other — acknowledge so Midtrans stops retrying.
    return {"ok": True, "settled": False, "status": transaction_status}
