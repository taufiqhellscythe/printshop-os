"""App configuration."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-me-printshop-os")
SHOP_NAME = os.getenv("SHOP_NAME", "PrintShop L3110")
SHOP_PHONE = os.getenv("SHOP_PHONE", "")
SHOP_ADDRESS = os.getenv("SHOP_ADDRESS", "")
ADMIN_USER = os.getenv("ADMIN_USER", "admin")
ADMIN_PASS = os.getenv("ADMIN_PASS", "admin123")
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8088"))
TIMEZONE = os.getenv("TIMEZONE", "Asia/Jakarta")
CUPS_PRINTER = os.getenv("CUPS_PRINTER", "").strip()
# auto|bw|color
PRINT_COLOR_MODE = os.getenv("PRINT_COLOR_MODE", "auto").strip()
# comma statuses that enqueue/auto-print, e.g. antrian,proses
AUTO_PRINT_ON_STATUS = os.getenv("AUTO_PRINT_ON_STATUS", "antrian,proses").strip()
# if true and local CUPS available, print immediately; else queue for agent
AUTO_PRINT_LOCAL = os.getenv("AUTO_PRINT_LOCAL", "true").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
PRINT_AGENT_TOKEN = os.getenv("PRINT_AGENT_TOKEN", "print-agent-change-me").strip()

# ---- Payment gateway (QRIS) ----
# provider: "midtrans" (default) | "" to disable (manual confirmation only)
PAYMENT_PROVIDER = os.getenv("PAYMENT_PROVIDER", "").strip().lower()
MIDTRANS_SERVER_KEY = os.getenv("MIDTRANS_SERVER_KEY", "").strip()
MIDTRANS_CLIENT_KEY = os.getenv("MIDTRANS_CLIENT_KEY", "").strip()
MIDTRANS_IS_PRODUCTION = os.getenv("MIDTRANS_IS_PRODUCTION", "false").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
# QRIS acquirer used by Core API charge (gopay|airpay shopee). gopay covers all QRIS.
MIDTRANS_QRIS_ACQUIRER = os.getenv("MIDTRANS_QRIS_ACQUIRER", "gopay").strip()
# Order status set automatically once payment settles (must be in AUTO_PRINT_ON_STATUS to auto-print)
PAYMENT_PAID_STATUS = os.getenv("PAYMENT_PAID_STATUS", "antrian").strip()


def payment_enabled() -> bool:
    return PAYMENT_PROVIDER == "midtrans" and bool(MIDTRANS_SERVER_KEY)

DATABASE_PATH = Path(os.getenv("DATABASE_PATH", ROOT / "data" / "printshop.db"))
if not DATABASE_PATH.is_absolute():
    DATABASE_PATH = ROOT / DATABASE_PATH

UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", ROOT / "data" / "uploads"))
if not UPLOAD_DIR.is_absolute():
    UPLOAD_DIR = ROOT / UPLOAD_DIR

STATUS_FLOW = [
    "baru",
    "dikonfirmasi",
    "prepress",
    "antrian",
    "proses",
    "finishing",
    "siap",
    "diambil",
]

STATUS_LABELS = {
    "baru": "Baru",
    "dikonfirmasi": "Dikonfirmasi",
    "prepress": "Prepress",
    "antrian": "Antrian",
    "proses": "Proses Print",
    "finishing": "Finishing",
    "siap": "Siap Diambil",
    "diambil": "Selesai/Diambil",
    "batal": "Batal",
}

STATUS_COLORS = {
    "baru": "bg-sky-100 text-sky-800",
    "dikonfirmasi": "bg-indigo-100 text-indigo-800",
    "prepress": "bg-violet-100 text-violet-800",
    "antrian": "bg-amber-100 text-amber-800",
    "proses": "bg-orange-100 text-orange-800",
    "finishing": "bg-fuchsia-100 text-fuchsia-800",
    "siap": "bg-emerald-100 text-emerald-800",
    "diambil": "bg-slate-100 text-slate-700",
    "batal": "bg-rose-100 text-rose-800",
}

KANBAN_COLUMNS = [
    "baru",
    "dikonfirmasi",
    "prepress",
    "antrian",
    "proses",
    "finishing",
    "siap",
]
