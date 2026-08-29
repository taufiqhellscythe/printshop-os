"""Public customer portal routes."""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.config import (
    SHOP_ADDRESS,
    SHOP_NAME,
    SHOP_PHONE,
    STATUS_COLORS,
    STATUS_LABELS,
    UPLOAD_DIR,
    payment_enabled,
)
from app.db import db
from app.utils import order_progress, rupiah, slug_filename

router = APIRouter(tags=["public"])
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))
templates.env.globals.update(
    rupiah=rupiah,
    shop_name=SHOP_NAME,
    shop_phone=SHOP_PHONE,
    shop_address=SHOP_ADDRESS,
    status_labels=STATUS_LABELS,
    status_colors=STATUS_COLORS,
    order_progress=order_progress,
)


@router.get("/", response_class=HTMLResponse)
async def home(request: Request):
    services = db.list_services()
    addons = db.list_addons()
    discounts = db.list_discounts()
    return templates.TemplateResponse(
        "public/home.html",
        {
            "request": request,
            "services": services,
            "addons": addons,
            "discounts": discounts,
        },
    )


@router.get("/harga", response_class=HTMLResponse)
async def harga(request: Request):
    return templates.TemplateResponse(
        "public/harga.html",
        {
            "request": request,
            "services": db.list_services(),
            "addons": db.list_addons(),
            "discounts": db.list_discounts(),
        },
    )


@router.get("/order", response_class=HTMLResponse)
async def order_form(request: Request):
    return templates.TemplateResponse(
        "public/order.html",
        {
            "request": request,
            "services": db.list_services(),
            "addons": db.list_addons(),
            "error": None,
            "form": {},
        },
    )


@router.post("/order", response_class=HTMLResponse)
async def order_submit(
    request: Request,
    customer_name: str = Form(...),
    customer_phone: str = Form(""),
    customer_email: str = Form(""),
    service_key: str = Form(...),
    qty: int = Form(...),
    notes: str = Form(""),
    addon_keys: List[str] = Form(default=[]),
    files: List[UploadFile] = File(default=[]),
):
    form = {
        "customer_name": customer_name,
        "customer_phone": customer_phone,
        "customer_email": customer_email,
        "service_key": service_key,
        "qty": qty,
        "notes": notes,
        "addon_keys": addon_keys,
    }
    try:
        quote = db.calc_quote(
            [{"service_key": service_key, "qty": qty}],
            addon_keys,
        )
        order = db.create_order(
            {
                "customer_name": customer_name.strip(),
                "customer_phone": customer_phone.strip() or None,
                "customer_email": customer_email.strip() or None,
                "notes": notes.strip(),
                "source": "web",
                "priority": 1 if "rush" in addon_keys else 0,
                "quote": quote,
                "actor": "customer-web",
            }
        )
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        for f in files:
            if not f.filename:
                continue
            safe = slug_filename(f.filename)
            dest = UPLOAD_DIR / f"{order['code']}_{uuid.uuid4().hex[:8]}_{safe}"
            content = await f.read()
            dest.write_bytes(content)
            db.add_order_file(
                order["id"],
                f.filename,
                str(dest),
                f.content_type,
                len(content),
            )
        order = db.get_order(order["id"])
        # If online payment is enabled, send customer to QRIS checkout first.
        if payment_enabled() and int(order["total"]) > 0:
            return RedirectResponse(f"/pay/{order['track_token']}", status_code=303)
        return RedirectResponse(f"/track/{order['track_token']}?new=1", status_code=303)
    except Exception as e:
        return templates.TemplateResponse(
            "public/order.html",
            {
                "request": request,
                "services": db.list_services(),
                "addons": db.list_addons(),
                "error": str(e),
                "form": form,
            },
            status_code=400,
        )


@router.get("/track", response_class=HTMLResponse)
async def track_form(request: Request, code: str = ""):
    return templates.TemplateResponse(
        "public/track.html",
        {"request": request, "code": code, "error": None, "order": None},
    )


@router.post("/track", response_class=HTMLResponse)
async def track_lookup(request: Request, code: str = Form(...), phone: str = Form("")):
    order = db.get_order(code=code.strip().upper())
    if not order:
        return templates.TemplateResponse(
            "public/track.html",
            {
                "request": request,
                "code": code,
                "error": "Order tidak ditemukan. Cek kode order.",
                "order": None,
            },
            status_code=404,
        )
    if phone and order.get("customer_phone") and phone.strip() not in (order["customer_phone"] or ""):
        # soft check — allow if phone empty on order
        pass
    return RedirectResponse(f"/track/{order['track_token']}", status_code=303)


@router.get("/track/{token}", response_class=HTMLResponse)
async def track_token(request: Request, token: str, new: Optional[int] = None):
    order = db.get_order(track_token=token)
    if not order:
        return templates.TemplateResponse(
            "public/track.html",
            {
                "request": request,
                "code": "",
                "error": "Link lacak tidak valid.",
                "order": None,
            },
            status_code=404,
        )
    return templates.TemplateResponse(
        "public/track_detail.html",
        {"request": request, "order": order, "is_new": bool(new)},
    )


@router.get("/receipt/{token}", response_class=HTMLResponse)
async def receipt_public(request: Request, token: str):
    """Customer-facing digital receipt. Reachable with the track token only."""
    order = db.get_order(track_token=token)
    if not order:
        return templates.TemplateResponse(
            "public/track.html",
            {
                "request": request,
                "code": "",
                "error": "Link struk tidak valid.",
                "order": None,
            },
            status_code=404,
        )

    payment = db.latest_payment_for_order(order["id"])

    # Settlement timestamp: prefer the gateway's, fall back to the webhook event.
    settled_at = None
    if payment and payment.get("raw_json"):
        try:
            raw = json.loads(payment["raw_json"])
            settled_at = raw.get("settlement_time") or raw.get("transaction_time")
        except (ValueError, TypeError):
            settled_at = None
    if not settled_at:
        for ev in order.get("events") or []:
            if ev.get("actor") == "payment-webhook":
                settled_at = (ev.get("created_at") or "")[:16].replace("T", " ")
                break

    return templates.TemplateResponse(
        "public/receipt.html",
        {
            "request": request,
            "order": order,
            "payment": payment,
            "settled_at": settled_at,
            "track_url": f"{str(request.base_url).rstrip('/')}/track/{token}",
        },
    )


@router.get("/api/quote")
async def api_quote(service_key: str, qty: int = 1, addons: str = ""):
    addon_keys = [a for a in addons.split(",") if a]
    try:
        q = db.calc_quote([{"service_key": service_key, "qty": qty}], addon_keys)
        return {
            "ok": True,
            "total": q["total"],
            "total_fmt": rupiah(q["total"]),
            "subtotal": q["subtotal"],
            "discount": q["discount"],
            "addons_total": q["addons_total"],
            "lines": q["lines"],
            "addons": q["addons"],
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}
