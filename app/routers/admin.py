"""Admin / staff routes."""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware  # type hint only

from app.config import (
    KANBAN_COLUMNS,
    SECRET_KEY,
    SHOP_ADDRESS,
    SHOP_NAME,
    SHOP_PHONE,
    STATUS_COLORS,
    STATUS_FLOW,
    STATUS_LABELS,
    UPLOAD_DIR,
)
from app.db import db, today_wib
from app.services.print_bridge import list_printers, printer_status, resolve_print_settings
from app.services.print_jobs import enqueue_order_prints, maybe_auto_print_for_status, try_local_print_job
from app.utils import order_progress, rupiah, slug_filename, summarize_items

router = APIRouter(prefix="/admin", tags=["admin"])
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))
templates.env.globals.update(
    rupiah=rupiah,
    shop_name=SHOP_NAME,
    shop_phone=SHOP_PHONE,
    shop_address=SHOP_ADDRESS,
    status_labels=STATUS_LABELS,
    status_colors=STATUS_COLORS,
    status_flow=STATUS_FLOW,
    kanban_columns=KANBAN_COLUMNS,
    order_progress=order_progress,
    summarize_items=summarize_items,
)


def current_user(request: Request) -> dict | None:
    uid = request.session.get("user_id")
    if not uid:
        return None
    return db.get_user(int(uid))


def require_user(request: Request) -> dict:
    user = current_user(request)
    if not user:
        raise HTTPException(status_code=303, headers={"Location": "/admin/login"})
    return user


def login_required(request: Request):
    user = current_user(request)
    if not user:
        return None
    return user


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if current_user(request):
        return RedirectResponse("/admin", status_code=303)
    return templates.TemplateResponse(
        "admin/login.html", {"request": request, "error": None}
    )


@router.post("/login", response_class=HTMLResponse)
async def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
):
    user = db.verify_user(username.strip(), password)
    if not user:
        return templates.TemplateResponse(
            "admin/login.html",
            {"request": request, "error": "Username atau password salah."},
            status_code=401,
        )
    request.session["user_id"] = user["id"]
    request.session["username"] = user["username"]
    return RedirectResponse("/admin", status_code=303)


@router.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/admin/login", status_code=303)


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    user = current_user(request)
    if not user:
        return RedirectResponse("/admin/login", status_code=303)
    stats = db.dashboard_stats()
    recent = db.list_orders(active_only=True, limit=8)
    return templates.TemplateResponse(
        "admin/dashboard.html",
        {"request": request, "user": user, "stats": stats, "recent": recent},
    )


@router.get("/orders", response_class=HTMLResponse)
async def orders_list(request: Request, q: str = "", status: str = ""):
    user = current_user(request)
    if not user:
        return RedirectResponse("/admin/login", status_code=303)
    orders = db.list_orders(status=status or None, q=q or None, limit=100)
    return templates.TemplateResponse(
        "admin/orders.html",
        {
            "request": request,
            "user": user,
            "orders": orders,
            "q": q,
            "status": status,
        },
    )


@router.get("/kanban", response_class=HTMLResponse)
async def kanban(request: Request):
    user = current_user(request)
    if not user:
        return RedirectResponse("/admin/login", status_code=303)
    board = {col: db.list_orders(status=col, limit=50) for col in KANBAN_COLUMNS}
    return templates.TemplateResponse(
        "admin/kanban.html",
        {"request": request, "user": user, "board": board},
    )


@router.get("/orders/{order_id}", response_class=HTMLResponse)
async def order_detail(request: Request, order_id: int):
    user = current_user(request)
    if not user:
        return RedirectResponse("/admin/login", status_code=303)
    order = db.get_order(order_id)
    if not order:
        raise HTTPException(404, "Order tidak ditemukan")
    return templates.TemplateResponse(
        "admin/order_detail.html",
        {
            "request": request,
            "user": user,
            "order": order,
            "printers": list_printers(),
        },
    )


@router.post("/orders/{order_id}/status")
async def order_set_status(
    request: Request,
    order_id: int,
    status: str = Form(...),
    payment_status: str = Form(""),
    payment_method: str = Form(""),
    paid_amount: int = Form(0),
    internal_notes: str = Form(""),
    priority: int = Form(0),
):
    user = current_user(request)
    if not user:
        return RedirectResponse("/admin/login", status_code=303)
    kwargs = {
        "actor": user["username"],
        "priority": priority,
        "internal_notes": internal_notes or None,
    }
    if payment_status:
        kwargs["payment_status"] = payment_status
    if payment_method:
        kwargs["payment_method"] = payment_method
    if paid_amount:
        kwargs["paid_amount"] = paid_amount
    db.update_order_status(order_id, status, **kwargs)
    maybe_auto_print_for_status(order_id, status, actor=user["username"])
    return RedirectResponse(f"/admin/orders/{order_id}", status_code=303)


@router.post("/orders/{order_id}/quick-status")
async def order_quick_status(request: Request, order_id: int, status: str = Form(...)):
    user = current_user(request)
    if not user:
        return RedirectResponse("/admin/login", status_code=303)
    db.update_order_status(order_id, status, actor=user["username"])
    maybe_auto_print_for_status(order_id, status, actor=user["username"])
    referer = request.headers.get("referer") or "/admin/kanban"
    return RedirectResponse(referer, status_code=303)


@router.post("/orders/{order_id}/pay")
async def order_pay(
    request: Request,
    order_id: int,
    payment_method: str = Form("Tunai"),
    mark_siap: Optional[str] = Form(None),
):
    user = current_user(request)
    if not user:
        return RedirectResponse("/admin/login", status_code=303)
    order = db.get_order(order_id)
    if not order:
        raise HTTPException(404)
    new_status = order["status"]
    if mark_siap and order["status"] not in ("diambil", "batal"):
        new_status = "siap"
    db.update_order_status(
        order_id,
        new_status,
        actor=user["username"],
        payment_status="lunas",
        payment_method=payment_method,
        paid_amount=int(order["total"]),
        message=f"Pembayaran lunas via {payment_method}",
    )
    return RedirectResponse(f"/admin/orders/{order_id}", status_code=303)


@router.post("/orders/{order_id}/print")
async def order_print(
    request: Request,
    order_id: int,
    file_id: int = Form(...),
    copies: int = Form(0),
):
    user = current_user(request)
    if not user:
        return RedirectResponse("/admin/login", status_code=303)
    order = db.get_order(order_id)
    if not order:
        raise HTTPException(404)
    f = next((x for x in order.get("files") or [] if x["id"] == file_id), None)
    if not f:
        raise HTTPException(400, "File tidak ada")
    settings = resolve_print_settings(order, f)
    if copies and int(copies) > 0:
        settings["copies"] = int(copies)
    job = db.enqueue_print_job(
        order_id,
        f["id"],
        copies=settings["copies"],
        color_mode=settings["color_mode"],
        duplex=settings["duplex"],
        media=settings["media"],
    )
    result = try_local_print_job(job["id"], actor=user["username"])
    flag = "ok" if result.get("ok") else ("queued" if result.get("queued") else "fail")
    return RedirectResponse(f"/admin/orders/{order_id}?print={flag}", status_code=303)


@router.post("/orders/{order_id}/print-all")
async def order_print_all(request: Request, order_id: int):
    user = current_user(request)
    if not user:
        return RedirectResponse("/admin/login", status_code=303)
    jobs = enqueue_order_prints(order_id, actor=user["username"], force=True)
    flag = "ok" if any(j and j.get("status") == "done" for j in jobs) else "queued"
    if not jobs:
        flag = "nofile"
    return RedirectResponse(f"/admin/orders/{order_id}?print={flag}", status_code=303)


@router.post("/print-jobs/{job_id}/retry")
async def print_job_retry(request: Request, job_id: int):
    user = current_user(request)
    if not user:
        return RedirectResponse("/admin/login", status_code=303)
    job = db.requeue_print_job(job_id)
    if job:
        try_local_print_job(job_id, actor=user["username"])
        return RedirectResponse(f"/admin/orders/{job['order_id']}", status_code=303)
    return RedirectResponse("/admin/print-jobs", status_code=303)


@router.get("/print-jobs", response_class=HTMLResponse)
async def print_jobs_page(request: Request, status: str = ""):
    user = current_user(request)
    if not user:
        return RedirectResponse("/admin/login", status_code=303)
    jobs = db.list_print_jobs(status=status or None, limit=100)
    return templates.TemplateResponse(
        "admin/print_jobs.html",
        {
            "request": request,
            "user": user,
            "jobs": jobs,
            "status": status,
            "printer": printer_status(),
        },
    )


@router.get("/pos", response_class=HTMLResponse)
async def pos_page(request: Request):
    user = current_user(request)
    if not user:
        return RedirectResponse("/admin/login", status_code=303)
    return templates.TemplateResponse(
        "admin/pos.html",
        {
            "request": request,
            "user": user,
            "services": db.list_services(),
            "addons": db.list_addons(),
            "error": None,
            "success": None,
        },
    )


@router.post("/pos", response_class=HTMLResponse)
async def pos_submit(
    request: Request,
    customer_name: str = Form("Walk-in"),
    customer_phone: str = Form(""),
    service_key: str = Form(...),
    qty: int = Form(...),
    notes: str = Form(""),
    payment_method: str = Form("Tunai"),
    pay_now: str = Form("yes"),
    addon_keys: List[str] = Form(default=[]),
):
    user = current_user(request)
    if not user:
        return RedirectResponse("/admin/login", status_code=303)
    try:
        quote = db.calc_quote([{"service_key": service_key, "qty": qty}], addon_keys)
        order = db.create_order(
            {
                "customer_name": customer_name.strip() or "Walk-in",
                "customer_phone": customer_phone.strip() or None,
                "notes": notes,
                "source": "pos",
                "status": "dikonfirmasi",
                "priority": 1 if "rush" in addon_keys else 0,
                "payment_status": "lunas" if pay_now == "yes" else "belum",
                "payment_method": payment_method if pay_now == "yes" else None,
                "paid_amount": quote["total"] if pay_now == "yes" else 0,
                "quote": quote,
                "actor": user["username"],
            }
        )
        if pay_now == "yes":
            # ensure customer spent updated
            db.update_order_status(
                order["id"],
                "dikonfirmasi",
                actor=user["username"],
                payment_status="lunas",
                payment_method=payment_method,
                paid_amount=quote["total"],
                message="POS payment",
            )
            order = db.get_order(order["id"])
        return RedirectResponse(f"/admin/orders/{order['id']}?pos=1", status_code=303)
    except Exception as e:
        return templates.TemplateResponse(
            "admin/pos.html",
            {
                "request": request,
                "user": user,
                "services": db.list_services(),
                "addons": db.list_addons(),
                "error": str(e),
                "success": None,
            },
            status_code=400,
        )


@router.get("/customers", response_class=HTMLResponse)
async def customers(request: Request, q: str = ""):
    user = current_user(request)
    if not user:
        return RedirectResponse("/admin/login", status_code=303)
    return templates.TemplateResponse(
        "admin/customers.html",
        {
            "request": request,
            "user": user,
            "customers": db.list_customers(q=q or None),
            "q": q,
        },
    )


@router.get("/inventory", response_class=HTMLResponse)
async def inventory(request: Request):
    user = current_user(request)
    if not user:
        return RedirectResponse("/admin/login", status_code=303)
    return templates.TemplateResponse(
        "admin/inventory.html",
        {"request": request, "user": user, "items": db.list_inventory()},
    )


@router.post("/inventory/adjust")
async def inventory_adjust(
    request: Request,
    item_id: int = Form(...),
    delta: float = Form(...),
    reason: str = Form("penyesuaian"),
):
    user = current_user(request)
    if not user:
        return RedirectResponse("/admin/login", status_code=303)
    db.adjust_inventory_id(item_id, delta, f"{reason} by {user['username']}")
    return RedirectResponse("/admin/inventory", status_code=303)


@router.get("/services", response_class=HTMLResponse)
async def services_page(request: Request):
    user = current_user(request)
    if not user:
        return RedirectResponse("/admin/login", status_code=303)
    return templates.TemplateResponse(
        "admin/services.html",
        {
            "request": request,
            "user": user,
            "services": db.list_services(active_only=False),
            "addons": db.list_addons(active_only=False),
            "discounts": db.list_discounts(),
        },
    )


@router.post("/services/price")
async def services_price(request: Request, key: str = Form(...), price: int = Form(...)):
    user = current_user(request)
    if not user:
        return RedirectResponse("/admin/login", status_code=303)
    db.update_service_price(key, price)
    return RedirectResponse("/admin/services", status_code=303)


@router.get("/reports", response_class=HTMLResponse)
async def reports(request: Request, start: str = "", end: str = ""):
    user = current_user(request)
    if not user:
        return RedirectResponse("/admin/login", status_code=303)
    if not start:
        start = today_wib()
    if not end:
        end = today_wib()
    report = db.report_range(start, end)
    stats = db.dashboard_stats(end)
    return templates.TemplateResponse(
        "admin/reports.html",
        {
            "request": request,
            "user": user,
            "report": report,
            "stats": stats,
            "start": start,
            "end": end,
        },
    )


@router.get("/expenses", response_class=HTMLResponse)
async def expenses_page(request: Request):
    user = current_user(request)
    if not user:
        return RedirectResponse("/admin/login", status_code=303)
    return templates.TemplateResponse(
        "admin/expenses.html",
        {
            "request": request,
            "user": user,
            "expenses": db.list_expenses(100),
        },
    )


@router.post("/expenses")
async def expenses_add(
    request: Request,
    category: str = Form(...),
    amount: int = Form(...),
    note: str = Form(""),
):
    user = current_user(request)
    if not user:
        return RedirectResponse("/admin/login", status_code=303)
    db.add_expense(category, amount, note)
    return RedirectResponse("/admin/expenses", status_code=303)


@router.get("/orders/{order_id}/receipt", response_class=HTMLResponse)
async def receipt(request: Request, order_id: int):
    user = current_user(request)
    if not user:
        return RedirectResponse("/admin/login", status_code=303)
    order = db.get_order(order_id)
    if not order:
        raise HTTPException(404)
    return templates.TemplateResponse(
        "admin/receipt.html",
        {"request": request, "order": order, "user": user},
    )


@router.get("/api/stats")
async def api_stats(request: Request):
    if not current_user(request):
        raise HTTPException(401)
    return db.dashboard_stats()
