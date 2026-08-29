#!/usr/bin/env python3
"""Smoke tests for PrintShop OS core."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
tmp = tempfile.mkdtemp(prefix="psos_")
os.environ["DATABASE_PATH"] = str(Path(tmp) / "t.db")
os.environ["ADMIN_PASS"] = "admin123"

from app.db import DB

db = DB(Path(tmp) / "t.db")


def test_seed():
    assert db.verify_user("admin", "admin123")
    assert len(db.list_services()) >= 5
    assert len(db.list_inventory()) >= 5
    print("OK seed")


def test_quote_and_order():
    q = db.calc_quote([{"service_key": "print_bw_a4", "qty": 100}], ["rush"])
    assert q["discount"] == 5000
    assert q["addons_total"] == 5000
    assert q["total"] == 50000
    order = db.create_order(
        {
            "customer_name": "Siti",
            "customer_phone": "0812",
            "source": "web",
            "quote": q,
            "actor": "test",
        }
    )
    assert order["code"].startswith("PS")
    assert order["track_token"]
    assert len(order["items"]) == 1
    updated = db.update_order_status(order["id"], "proses", actor="test")
    assert updated["status"] == "proses"
    # inventory consumed
    inv = {i["sku"]: i for i in db.list_inventory()}
    assert inv["TINTA-K"]["qty"] < 100
    paid = db.update_order_status(
        order["id"], "siap", payment_status="lunas", payment_method="QRIS", actor="test"
    )
    assert paid["payment_status"] == "lunas"
    cust = db.list_customers(q="Siti")[0]
    assert cust["total_spent"] == order["total"]
    stats = db.dashboard_stats()
    assert stats["orders_today"] >= 1
    print("OK quote/order/inventory/pay", order["code"])


def test_multi_line_quote():
    q = db.calc_quote(
        [
            {"service_key": "print_color_a4", "qty": 5},
            {"service_key": "scan_a4", "qty": 3},
        ],
        ["jilid_steples"],
    )
    assert q["total"] == 5 * 1500 + 3 * 1000 + 1000
    print("OK multi-line")


if __name__ == "__main__":
    test_seed()
    test_quote_and_order()
    test_multi_line_quote()
    print("\nALL PASSED")
