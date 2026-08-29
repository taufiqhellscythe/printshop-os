"""Payment gateway tests — signature verification + settle→auto-print flow.

Runs fully offline: no real Midtrans API calls. We stub the HTTP charge by
inserting a payment row directly, then drive the webhook settle path.
"""
from __future__ import annotations

import hashlib
import importlib
import os
import tempfile
from pathlib import Path

import pytest


@pytest.fixture()
def app_env(monkeypatch):
    # Isolated DB + payment enabled with a fake server key.
    tmp = tempfile.mkdtemp()
    db_path = str(Path(tmp) / "test.db")
    monkeypatch.setenv("DATABASE_PATH", db_path)
    monkeypatch.setenv("UPLOAD_DIR", str(Path(tmp) / "uploads"))
    monkeypatch.setenv("PAYMENT_PROVIDER", "midtrans")
    monkeypatch.setenv("MIDTRANS_SERVER_KEY", "SB-Mid-server-TESTKEY123")
    monkeypatch.setenv("MIDTRANS_IS_PRODUCTION", "false")
    monkeypatch.setenv("AUTO_PRINT_ON_STATUS", "antrian,proses")
    monkeypatch.setenv("AUTO_PRINT_LOCAL", "false")  # no CUPS on CI; stay queued
    monkeypatch.setenv("PAYMENT_PAID_STATUS", "antrian")

    # Reload the whole dependency chain in order so every module rebinds to the
    # fresh DB instance (each holds its own `from app.db import db` reference).
    import app.config as config
    importlib.reload(config)
    import app.db as db_mod
    importlib.reload(db_mod)
    import app.services.print_bridge as pb
    importlib.reload(pb)
    import app.services.print_jobs as pj
    importlib.reload(pj)
    import app.services.payment as pay
    importlib.reload(pay)
    import app.routers.payment as payment_router
    importlib.reload(payment_router)

    return config, db_mod, pay, payment_router


def _make_order(db, total_qty=10):
    quote = db.calc_quote([{"service_key": "print_bw_a4", "qty": total_qty}], [])
    order = db.create_order(
        {
            "customer_name": "Test Buyer",
            "customer_phone": "0811",
            "notes": "",
            "source": "web",
            "quote": quote,
            "actor": "test",
        }
    )
    return db.get_order(order["id"])


def test_signature_roundtrip(app_env):
    config, db_mod, pay, payment_router = app_env
    oid, sc, gross = "PS-250101-1-1700000000", "200", "5000.00"
    raw = f"{oid}{sc}{gross}{config.MIDTRANS_SERVER_KEY}"
    good = hashlib.sha512(raw.encode()).hexdigest()
    assert pay.verify_signature(oid, sc, gross, good) is True
    assert pay.verify_signature(oid, sc, gross, "deadbeef") is False


def test_is_settled_logic(app_env):
    _, _, pay, _pr = app_env
    assert pay.is_settled("settlement") is True
    assert pay.is_settled("capture", "accept") is True
    assert pay.is_settled("capture", "challenge") is False
    assert pay.is_settled("pending") is False
    assert pay.is_settled("expire") is False


def test_code_recovery(app_env):
    _, _, pay, _pr = app_env
    assert pay.code_from_midtrans_order_id("PS-250101-1-1700000000") == "PS-250101-1"


def test_settle_flow_triggers_autoprint(app_env):
    config, db_mod, pay, payment_router = app_env
    db = db_mod.db
    order = _make_order(db)
    assert order["payment_status"] == "belum"

    # Attach a dummy printable file so a print job can be enqueued.
    updir = Path(os.environ["UPLOAD_DIR"])
    updir.mkdir(parents=True, exist_ok=True)
    f = updir / f"{order['code']}_test.pdf"
    f.write_bytes(b"%PDF-1.4 fake pdf body\n")
    db.add_order_file(order["id"], "test.pdf", str(f), "application/pdf", f.stat().st_size)

    # Simulate a created QRIS charge (skip real HTTP).
    provider_oid = f"{order['code']}-1700000000"
    payment = db.create_payment(
        order["id"],
        provider="midtrans",
        provider_order_id=provider_oid,
        transaction_id="txn-abc",
        amount=int(order["total"]),
        qr_string="00020101...",
        qr_image_url="https://api.sandbox.midtrans.com/v2/qris/txn-abc/qr-code",
        raw={},
    )
    assert payment["status"] == "pending"

    # Build a valid settlement webhook payload.
    gross = f"{int(order['total'])}.00"
    sc = "200"
    raw = f"{provider_oid}{sc}{gross}{config.MIDTRANS_SERVER_KEY}"
    sig = hashlib.sha512(raw.encode()).hexdigest()

    # Drive the settle logic directly (router calls this).
    _settle_order = payment_router._settle_order
    assert pay.verify_signature(provider_oid, sc, gross, sig)
    body = {
        "order_id": provider_oid,
        "status_code": sc,
        "gross_amount": gross,
        "signature_key": sig,
        "transaction_status": "settlement",
        "transaction_id": "txn-abc",
    }
    _settle_order(order, payment, "txn-abc", body)

    # Assertions: order advanced, payment paid, print job queued.
    fresh = db.get_order(order["id"])
    assert fresh["payment_status"] == "lunas"
    assert fresh["status"] == "antrian"
    p = db.latest_payment_for_order(order["id"])
    assert p["status"] == "paid"
    jobs = db.list_print_jobs(limit=10)
    assert any(j["order_id"] == order["id"] for j in jobs), "print job should be enqueued after payment"


def test_settle_is_idempotent(app_env):
    config, db_mod, pay, payment_router = app_env
    db = db_mod.db
    order = _make_order(db, total_qty=5)
    provider_oid = f"{order['code']}-1700000001"
    payment = db.create_payment(
        order["id"], provider="midtrans", provider_order_id=provider_oid,
        transaction_id=None, amount=int(order["total"]), raw={},
    )
    _settle_order = payment_router._settle_order
    body = {"transaction_status": "settlement"}
    _settle_order(order, payment, "txn-1", body)
    _settle_order(order, payment, "txn-1", body)  # duplicate webhook
    # paid_amount must not double; status stays lunas/antrian.
    fresh = db.get_order(order["id"])
    assert fresh["payment_status"] == "lunas"
    assert fresh["paid_amount"] == int(order["total"])
