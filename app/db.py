"""SQLite database layer for PrintShop OS."""
from __future__ import annotations

import json
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

from passlib.context import CryptContext

from app.config import ADMIN_PASS, ADMIN_USER, DATABASE_PATH, UPLOAD_DIR

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
WIB = timezone(timedelta(hours=7))


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def today_wib() -> str:
    return datetime.now(WIB).strftime("%Y-%m-%d")


def local_day(iso_ts: str | None) -> str:
    if not iso_ts:
        return ""
    try:
        ts = iso_ts.replace("Z", "+00:00")
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(WIB).strftime("%Y-%m-%d")
    except Exception:
        return iso_ts[:10]


class DB:
    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path or DATABASE_PATH)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        self.init_schema()
        self.seed_if_empty()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def init_schema(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    full_name TEXT,
                    role TEXT NOT NULL DEFAULT 'admin',
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS customers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    phone TEXT,
                    email TEXT,
                    notes TEXT DEFAULT '',
                    total_orders INTEGER DEFAULT 0,
                    total_spent INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS services (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    key TEXT UNIQUE NOT NULL,
                    name TEXT NOT NULL,
                    category TEXT NOT NULL DEFAULT 'print',
                    unit TEXT NOT NULL DEFAULT 'lembar',
                    price INTEGER NOT NULL,
                    min_charge INTEGER NOT NULL DEFAULT 0,
                    cost_estimate INTEGER NOT NULL DEFAULT 0,
                    active INTEGER NOT NULL DEFAULT 1,
                    sort_order INTEGER NOT NULL DEFAULT 0,
                    description TEXT DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS addons (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    key TEXT UNIQUE NOT NULL,
                    name TEXT NOT NULL,
                    price INTEGER NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1
                );

                CREATE TABLE IF NOT EXISTS discount_rules (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    min_qty INTEGER NOT NULL,
                    percent INTEGER NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1
                );

                CREATE TABLE IF NOT EXISTS inventory_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sku TEXT UNIQUE NOT NULL,
                    name TEXT NOT NULL,
                    category TEXT NOT NULL,
                    unit TEXT NOT NULL DEFAULT 'pcs',
                    qty REAL NOT NULL DEFAULT 0,
                    reorder_level REAL NOT NULL DEFAULT 0,
                    unit_cost INTEGER NOT NULL DEFAULT 0,
                    notes TEXT DEFAULT '',
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS inventory_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    item_id INTEGER NOT NULL,
                    delta REAL NOT NULL,
                    reason TEXT,
                    ref_type TEXT,
                    ref_id INTEGER,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(item_id) REFERENCES inventory_items(id)
                );

                CREATE TABLE IF NOT EXISTS orders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    code TEXT UNIQUE NOT NULL,
                    track_token TEXT UNIQUE NOT NULL,
                    customer_id INTEGER,
                    customer_name TEXT NOT NULL,
                    customer_phone TEXT,
                    customer_email TEXT,
                    source TEXT NOT NULL DEFAULT 'web',
                    priority INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'baru',
                    payment_status TEXT NOT NULL DEFAULT 'belum',
                    payment_method TEXT,
                    paid_amount INTEGER NOT NULL DEFAULT 0,
                    subtotal INTEGER NOT NULL DEFAULT 0,
                    discount INTEGER NOT NULL DEFAULT 0,
                    addons_total INTEGER NOT NULL DEFAULT 0,
                    tax INTEGER NOT NULL DEFAULT 0,
                    total INTEGER NOT NULL DEFAULT 0,
                    notes TEXT DEFAULT '',
                    internal_notes TEXT DEFAULT '',
                    due_at TEXT,
                    eta_minutes INTEGER,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    completed_at TEXT,
                    FOREIGN KEY(customer_id) REFERENCES customers(id)
                );

                CREATE TABLE IF NOT EXISTS order_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id INTEGER NOT NULL,
                    service_key TEXT NOT NULL,
                    service_name TEXT NOT NULL,
                    qty INTEGER NOT NULL,
                    unit_price INTEGER NOT NULL,
                    line_subtotal INTEGER NOT NULL,
                    line_discount INTEGER NOT NULL DEFAULT 0,
                    line_total INTEGER NOT NULL,
                    options_json TEXT DEFAULT '{}',
                    notes TEXT DEFAULT '',
                    FOREIGN KEY(order_id) REFERENCES orders(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS order_addons (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id INTEGER NOT NULL,
                    addon_key TEXT NOT NULL,
                    addon_name TEXT NOT NULL,
                    price INTEGER NOT NULL,
                    FOREIGN KEY(order_id) REFERENCES orders(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS order_files (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id INTEGER NOT NULL,
                    filename TEXT NOT NULL,
                    stored_path TEXT NOT NULL,
                    mime TEXT,
                    size_bytes INTEGER,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(order_id) REFERENCES orders(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS print_jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id INTEGER NOT NULL,
                    file_id INTEGER,
                    status TEXT NOT NULL DEFAULT 'queued',
                    copies INTEGER NOT NULL DEFAULT 1,
                    color_mode TEXT NOT NULL DEFAULT 'bw',
                    duplex INTEGER NOT NULL DEFAULT 0,
                    media TEXT NOT NULL DEFAULT 'A4',
                    printer_name TEXT,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT,
                    result_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT,
                    claimed_by TEXT,
                    FOREIGN KEY(order_id) REFERENCES orders(id) ON DELETE CASCADE,
                    FOREIGN KEY(file_id) REFERENCES order_files(id) ON DELETE SET NULL
                );

                CREATE TABLE IF NOT EXISTS order_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id INTEGER NOT NULL,
                    status TEXT,
                    message TEXT NOT NULL,
                    actor TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(order_id) REFERENCES orders(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS expenses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    category TEXT NOT NULL,
                    amount INTEGER NOT NULL,
                    note TEXT DEFAULT '',
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS payments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id INTEGER NOT NULL,
                    provider TEXT NOT NULL DEFAULT 'midtrans',
                    provider_order_id TEXT UNIQUE,
                    transaction_id TEXT,
                    method TEXT NOT NULL DEFAULT 'qris',
                    amount INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'pending',
                    qr_string TEXT,
                    qr_image_url TEXT,
                    expiry_time TEXT,
                    raw_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    paid_at TEXT,
                    FOREIGN KEY(order_id) REFERENCES orders(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_payments_order ON payments(order_id);
                CREATE INDEX IF NOT EXISTS idx_payments_provider_oid ON payments(provider_order_id);
                CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
                CREATE INDEX IF NOT EXISTS idx_orders_created ON orders(created_at);
                CREATE INDEX IF NOT EXISTS idx_orders_code ON orders(code);
                CREATE INDEX IF NOT EXISTS idx_customers_phone ON customers(phone);
                CREATE INDEX IF NOT EXISTS idx_print_jobs_status ON print_jobs(status);
                """
            )

    def seed_if_empty(self) -> None:
        with self.connect() as conn:
            user_count = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]
            if user_count == 0:
                conn.execute(
                    "INSERT INTO users (username, password_hash, full_name, role, created_at) VALUES (?,?,?,?,?)",
                    (
                        ADMIN_USER,
                        pwd_context.hash(ADMIN_PASS),
                        "Owner",
                        "owner",
                        now_iso(),
                    ),
                )

            svc_count = conn.execute("SELECT COUNT(*) AS c FROM services").fetchone()["c"]
            if svc_count == 0:
                services = [
                    ("print_bw_a4", "Print Hitam-Putih A4", "print", "lembar", 500, 1000, 150, 1, 10, "Dokumen BW A4"),
                    ("print_color_a4", "Print Warna A4", "print", "lembar", 1500, 2000, 400, 1, 20, "Dokumen warna A4"),
                    ("print_bw_f4", "Print BW F4/Legal", "print", "lembar", 700, 1000, 200, 1, 30, "Dokumen BW F4"),
                    ("print_color_f4", "Print Warna F4", "print", "lembar", 2000, 2000, 500, 1, 40, "Dokumen warna F4"),
                    ("print_photo_a4", "Print Foto A4", "print", "lembar", 5000, 5000, 1200, 1, 50, "Foto A4"),
                    ("scan_a4", "Scan Dokumen A4", "scan", "lembar", 1000, 1000, 50, 1, 60, "Scan ke PDF/JPG"),
                    ("copy_bw", "Fotocopy BW", "copy", "lembar", 300, 500, 80, 1, 70, "Fotocopy hitam putih"),
                    ("copy_color", "Fotocopy Warna", "copy", "lembar", 1500, 1500, 400, 1, 80, "Fotocopy warna"),
                    ("jilid_dokumen", "Jasa Jilid Dokumen", "finishing", "eksemplar", 5000, 5000, 1000, 1, 90, "Jilid sederhana"),
                ]
                conn.executemany(
                    """INSERT INTO services
                    (key, name, category, unit, price, min_charge, cost_estimate, active, sort_order, description)
                    VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    services,
                )
                addons = [
                    ("rush", "Prioritas / Kilat", 5000),
                    ("jilid_steples", "Jilid Steples", 1000),
                    ("jilid_spiral", "Jilid Spiral", 10000),
                    ("laminating_a4", "Laminating A4", 5000),
                    ("duplex", "Bolak-balik (duplex)", 0),
                ]
                conn.executemany(
                    "INSERT INTO addons (key, name, price, active) VALUES (?,?,?,1)",
                    addons,
                )
                discounts = [
                    ("Diskon 5% (≥50 lembar)", 50, 5),
                    ("Diskon 10% (≥100 lembar)", 100, 10),
                    ("Diskon 15% (≥250 lembar)", 250, 15),
                ]
                conn.executemany(
                    "INSERT INTO discount_rules (name, min_qty, percent, active) VALUES (?,?,?,1)",
                    discounts,
                )

            inv_count = conn.execute("SELECT COUNT(*) AS c FROM inventory_items").fetchone()["c"]
            if inv_count == 0:
                now = now_iso()
                items = [
                    ("KERTAS-A4-70", "Kertas A4 70gsm", "kertas", "rim", 10, 2, 45000, "1 rim ≈ 500 lembar"),
                    ("KERTAS-A4-80", "Kertas A4 80gsm", "kertas", "rim", 5, 1, 55000, ""),
                    ("KERTAS-F4", "Kertas F4/Legal", "kertas", "rim", 3, 1, 50000, ""),
                    ("TINTA-C", "Tinta Cyan L3110", "tinta", "ml", 70, 20, 35000, "Estimasi level"),
                    ("TINTA-M", "Tinta Magenta L3110", "tinta", "ml", 70, 20, 35000, ""),
                    ("TINTA-Y", "Tinta Yellow L3110", "tinta", "ml", 70, 20, 35000, ""),
                    ("TINTA-K", "Tinta Black L3110", "tinta", "ml", 100, 30, 35000, "BW lebih boros K"),
                    ("SPIRAL-A4", "Spiral Jilid A4", "finishing", "pcs", 20, 5, 2000, ""),
                    ("LAMINATE-A4", "Kantung Laminating A4", "finishing", "pcs", 30, 10, 1500, ""),
                ]
                for it in items:
                    conn.execute(
                        """INSERT INTO inventory_items
                        (sku, name, category, unit, qty, reorder_level, unit_cost, notes, updated_at)
                        VALUES (?,?,?,?,?,?,?,?,?)""",
                        (*it, now),
                    )

    # ---- auth ----
    def verify_user(self, username: str, password: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        if not row:
            return None
        if not pwd_context.verify(password, row["password_hash"]):
            return None
        return dict(row)

    def get_user(self, user_id: int) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return dict(row) if row else None

    # ---- catalog ----
    def list_services(self, active_only: bool = True) -> list[dict[str, Any]]:
        q = "SELECT * FROM services"
        if active_only:
            q += " WHERE active = 1"
        q += " ORDER BY sort_order, name"
        with self.connect() as conn:
            return [dict(r) for r in conn.execute(q).fetchall()]

    def get_service(self, key: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM services WHERE key = ?", (key,)).fetchone()
        return dict(row) if row else None

    def update_service_price(self, key: str, price: int) -> None:
        with self.connect() as conn:
            conn.execute("UPDATE services SET price = ? WHERE key = ?", (price, key))

    def list_addons(self, active_only: bool = True) -> list[dict[str, Any]]:
        q = "SELECT * FROM addons"
        if active_only:
            q += " WHERE active = 1"
        q += " ORDER BY name"
        with self.connect() as conn:
            return [dict(r) for r in conn.execute(q).fetchall()]

    def list_discounts(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            return [
                dict(r)
                for r in conn.execute(
                    "SELECT * FROM discount_rules WHERE active = 1 ORDER BY min_qty"
                ).fetchall()
            ]

    # ---- pricing ----
    def calc_line(self, service_key: str, qty: int) -> dict[str, Any]:
        if qty < 1:
            raise ValueError("Qty minimal 1")
        svc = self.get_service(service_key)
        if not svc or not svc["active"]:
            raise KeyError(f"Layanan tidak ditemukan: {service_key}")
        unit = int(svc["price"])
        subtotal = unit * qty
        min_charge = int(svc["min_charge"] or 0)
        if subtotal < min_charge:
            subtotal = min_charge
        discount_percent = 0
        discount_name = ""
        for rule in sorted(self.list_discounts(), key=lambda r: r["min_qty"], reverse=True):
            if qty >= int(rule["min_qty"]):
                discount_percent = int(rule["percent"])
                discount_name = rule["name"]
                break
        discount = int(subtotal * discount_percent / 100)
        return {
            "service_key": service_key,
            "service_name": svc["name"],
            "category": svc["category"],
            "unit": svc["unit"],
            "qty": qty,
            "unit_price": unit,
            "line_subtotal": subtotal,
            "line_discount": discount,
            "discount_percent": discount_percent,
            "discount_name": discount_name,
            "line_total": subtotal - discount,
            "cost_estimate": int(svc["cost_estimate"] or 0) * qty,
        }

    def calc_quote(
        self,
        items: list[dict[str, Any]],
        addon_keys: list[str] | None = None,
    ) -> dict[str, Any]:
        lines = []
        for it in items:
            lines.append(self.calc_line(it["service_key"], int(it["qty"])))
        addons = []
        addons_total = 0
        addon_map = {a["key"]: a for a in self.list_addons()}
        for key in addon_keys or []:
            a = addon_map.get(key)
            if not a:
                continue
            addons.append({"key": a["key"], "name": a["name"], "price": int(a["price"])})
            addons_total += int(a["price"])
        subtotal = sum(l["line_subtotal"] for l in lines)
        discount = sum(l["line_discount"] for l in lines)
        total = sum(l["line_total"] for l in lines) + addons_total
        return {
            "lines": lines,
            "addons": addons,
            "subtotal": subtotal,
            "discount": discount,
            "addons_total": addons_total,
            "tax": 0,
            "total": total,
            "cost_estimate": sum(l["cost_estimate"] for l in lines),
            "margin_estimate": total - sum(l["cost_estimate"] for l in lines),
        }

    # ---- customers ----
    def upsert_customer(
        self,
        name: str,
        phone: str | None = None,
        email: str | None = None,
    ) -> int:
        now = now_iso()
        with self.connect() as conn:
            row = None
            if phone:
                row = conn.execute(
                    "SELECT id FROM customers WHERE phone = ?", (phone,)
                ).fetchone()
            if row:
                conn.execute(
                    "UPDATE customers SET name = ?, email = COALESCE(?, email), updated_at = ? WHERE id = ?",
                    (name, email, now, row["id"]),
                )
                return int(row["id"])
            cur = conn.execute(
                """INSERT INTO customers (name, phone, email, notes, created_at, updated_at)
                   VALUES (?,?,?,?,?,?)""",
                (name, phone, email, "", now, now),
            )
            return int(cur.lastrowid)

    def list_customers(self, q: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        sql = "SELECT * FROM customers"
        params: list[Any] = []
        if q:
            sql += " WHERE name LIKE ? OR phone LIKE ? OR email LIKE ?"
            like = f"%{q}%"
            params.extend([like, like, like])
        sql += " ORDER BY updated_at DESC LIMIT ?"
        params.append(limit)
        with self.connect() as conn:
            return [dict(r) for r in conn.execute(sql, params).fetchall()]

    def get_customer(self, customer_id: int) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM customers WHERE id = ?", (customer_id,)).fetchone()
        return dict(row) if row else None

    # ---- orders ----
    def next_code(self) -> str:
        day = datetime.now(WIB).strftime("%y%m%d")
        prefix = f"PS{day}"
        with self.connect() as conn:
            row = conn.execute(
                "SELECT code FROM orders WHERE code LIKE ? ORDER BY id DESC LIMIT 1",
                (f"{prefix}%",),
            ).fetchone()
        if not row:
            return f"{prefix}-001"
        try:
            n = int(row["code"].split("-")[-1]) + 1
        except ValueError:
            n = 1
        return f"{prefix}-{n:03d}"

    def create_order(self, payload: dict[str, Any]) -> dict[str, Any]:
        now = now_iso()
        code = payload.get("code") or self.next_code()
        track_token = secrets.token_urlsafe(12)
        quote = payload["quote"]
        customer_id = payload.get("customer_id")
        if not customer_id and payload.get("customer_name"):
            customer_id = self.upsert_customer(
                payload["customer_name"],
                payload.get("customer_phone"),
                payload.get("customer_email"),
            )
        with self.connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO orders (
                    code, track_token, customer_id, customer_name, customer_phone, customer_email,
                    source, priority, status, payment_status, payment_method, paid_amount,
                    subtotal, discount, addons_total, tax, total, notes, internal_notes,
                    due_at, eta_minutes, created_at, updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    code,
                    track_token,
                    customer_id,
                    payload["customer_name"],
                    payload.get("customer_phone"),
                    payload.get("customer_email"),
                    payload.get("source") or "web",
                    int(payload.get("priority") or 0),
                    payload.get("status") or "baru",
                    payload.get("payment_status") or "belum",
                    payload.get("payment_method"),
                    int(payload.get("paid_amount") or 0),
                    quote["subtotal"],
                    quote["discount"],
                    quote["addons_total"],
                    quote.get("tax") or 0,
                    quote["total"],
                    payload.get("notes") or "",
                    payload.get("internal_notes") or "",
                    payload.get("due_at"),
                    payload.get("eta_minutes"),
                    now,
                    now,
                ),
            )
            order_id = int(cur.lastrowid)
            for line in quote["lines"]:
                conn.execute(
                    """
                    INSERT INTO order_items (
                        order_id, service_key, service_name, qty, unit_price,
                        line_subtotal, line_discount, line_total, options_json, notes
                    ) VALUES (?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        order_id,
                        line["service_key"],
                        line["service_name"],
                        line["qty"],
                        line["unit_price"],
                        line["line_subtotal"],
                        line["line_discount"],
                        line["line_total"],
                        json.dumps(line.get("options") or {}),
                        line.get("notes") or "",
                    ),
                )
            for addon in quote.get("addons") or []:
                conn.execute(
                    "INSERT INTO order_addons (order_id, addon_key, addon_name, price) VALUES (?,?,?,?)",
                    (order_id, addon["key"], addon["name"], addon["price"]),
                )
            conn.execute(
                "INSERT INTO order_events (order_id, status, message, actor, created_at) VALUES (?,?,?,?,?)",
                (
                    order_id,
                    payload.get("status") or "baru",
                    "Order dibuat",
                    payload.get("actor") or "system",
                    now,
                ),
            )
            if customer_id:
                conn.execute(
                    "UPDATE customers SET total_orders = total_orders + 1, updated_at = ? WHERE id = ?",
                    (now, customer_id),
                )
        return self.get_order(order_id)  # type: ignore

    def add_order_file(
        self,
        order_id: int,
        filename: str,
        stored_path: str,
        mime: str | None,
        size_bytes: int | None,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO order_files (order_id, filename, stored_path, mime, size_bytes, created_at)
                   VALUES (?,?,?,?,?,?)""",
                (order_id, filename, stored_path, mime, size_bytes, now_iso()),
            )

    def get_order(
        self,
        order_id: int | None = None,
        code: str | None = None,
        track_token: str | None = None,
    ) -> dict[str, Any] | None:
        with self.connect() as conn:
            if order_id is not None:
                row = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
            elif code:
                row = conn.execute(
                    "SELECT * FROM orders WHERE code = ?", (code.upper(),)
                ).fetchone()
            elif track_token:
                row = conn.execute(
                    "SELECT * FROM orders WHERE track_token = ?", (track_token,)
                ).fetchone()
            else:
                return None
            if not row:
                return None
            order = dict(row)
            oid = order["id"]
            order["items"] = [
                dict(r)
                for r in conn.execute(
                    "SELECT * FROM order_items WHERE order_id = ?", (oid,)
                ).fetchall()
            ]
            order["addons"] = [
                dict(r)
                for r in conn.execute(
                    "SELECT * FROM order_addons WHERE order_id = ?", (oid,)
                ).fetchall()
            ]
            order["files"] = [
                dict(r)
                for r in conn.execute(
                    "SELECT * FROM order_files WHERE order_id = ?", (oid,)
                ).fetchall()
            ]
            order["events"] = [
                dict(r)
                for r in conn.execute(
                    "SELECT * FROM order_events WHERE order_id = ? ORDER BY id DESC",
                    (oid,),
                ).fetchall()
            ]
            order["print_jobs"] = [
                dict(r)
                for r in conn.execute(
                    "SELECT * FROM print_jobs WHERE order_id = ? ORDER BY id DESC",
                    (oid,),
                ).fetchall()
            ]
            return order

    def list_orders(
        self,
        status: str | None = None,
        q: str | None = None,
        active_only: bool = False,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM orders WHERE 1=1"
        params: list[Any] = []
        if status:
            sql += " AND status = ?"
            params.append(status)
        if active_only:
            sql += " AND status NOT IN ('diambil','batal')"
        if q:
            sql += " AND (code LIKE ? OR customer_name LIKE ? OR customer_phone LIKE ?)"
            like = f"%{q}%"
            params.extend([like, like, like])
        sql += " ORDER BY priority DESC, id DESC LIMIT ?"
        params.append(limit)
        with self.connect() as conn:
            orders = [dict(r) for r in conn.execute(sql, params).fetchall()]
            for o in orders:
                o["items"] = [
                    dict(r)
                    for r in conn.execute(
                        "SELECT * FROM order_items WHERE order_id = ?", (o["id"],)
                    ).fetchall()
                ]
                o["addons"] = [
                    dict(r)
                    for r in conn.execute(
                        "SELECT * FROM order_addons WHERE order_id = ?", (o["id"],)
                    ).fetchall()
                ]
        return orders

    def update_order_status(
        self,
        order_id: int,
        status: str,
        *,
        actor: str = "admin",
        message: str | None = None,
        payment_status: str | None = None,
        payment_method: str | None = None,
        paid_amount: int | None = None,
        priority: int | None = None,
        internal_notes: str | None = None,
    ) -> dict[str, Any] | None:
        now = now_iso()
        with self.connect() as conn:
            prev = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
            if not prev:
                return None
            fields = ["status = ?", "updated_at = ?"]
            params: list[Any] = [status, now]
            if payment_status is not None:
                fields.append("payment_status = ?")
                params.append(payment_status)
            if payment_method is not None:
                fields.append("payment_method = ?")
                params.append(payment_method)
            if paid_amount is not None:
                fields.append("paid_amount = ?")
                params.append(paid_amount)
            if priority is not None:
                fields.append("priority = ?")
                params.append(priority)
            if internal_notes is not None:
                fields.append("internal_notes = ?")
                params.append(internal_notes)
            if status in ("siap", "diambil"):
                fields.append("completed_at = COALESCE(completed_at, ?)")
                params.append(now)
            params.append(order_id)
            conn.execute(f"UPDATE orders SET {', '.join(fields)} WHERE id = ?", params)
            conn.execute(
                "INSERT INTO order_events (order_id, status, message, actor, created_at) VALUES (?,?,?,?,?)",
                (
                    order_id,
                    status,
                    message or f"Status diubah ke {status}",
                    actor,
                    now,
                ),
            )
            becoming_lunas = payment_status == "lunas" and prev["payment_status"] != "lunas"
            if becoming_lunas and prev["customer_id"]:
                conn.execute(
                    """UPDATE customers SET total_spent = total_spent + ?, updated_at = ?
                       WHERE id = ?""",
                    (int(prev["total"]), now, prev["customer_id"]),
                )
        # inventory consume on proses once
        if status == "proses":
            self._consume_inventory_for_order(order_id)
        return self.get_order(order_id)

    def _consume_inventory_for_order(self, order_id: int) -> None:
        order = self.get_order(order_id)
        if not order:
            return
        # avoid double consume
        with self.connect() as conn:
            exists = conn.execute(
                "SELECT 1 FROM inventory_logs WHERE ref_type='order' AND ref_id=? AND reason LIKE 'consume%'",
                (order_id,),
            ).fetchone()
            if exists:
                return
        for item in order.get("items") or []:
            qty = int(item["qty"])
            key = item["service_key"]
            # rough consumption model for L3110 shop
            if "bw" in key or key.startswith("copy_bw") or key.startswith("print_bw"):
                self.adjust_inventory_sku("KERTAS-A4-70", -qty / 500.0, f"consume order {order['code']}", "order", order_id)
                self.adjust_inventory_sku("TINTA-K", -qty * 0.05, f"consume order {order['code']}", "order", order_id)
            elif "color" in key or "photo" in key:
                paper = "KERTAS-A4-80" if "photo" in key else "KERTAS-A4-70"
                self.adjust_inventory_sku(paper, -qty / 500.0, f"consume order {order['code']}", "order", order_id)
                for sku in ("TINTA-C", "TINTA-M", "TINTA-Y", "TINTA-K"):
                    self.adjust_inventory_sku(sku, -qty * 0.03, f"consume order {order['code']}", "order", order_id)
        for addon in order.get("addons") or []:
            if addon["addon_key"] == "jilid_spiral":
                self.adjust_inventory_sku("SPIRAL-A4", -1, f"consume order {order['code']}", "order", order_id)
            if addon["addon_key"] == "laminating_a4":
                self.adjust_inventory_sku("LAMINATE-A4", -1, f"consume order {order['code']}", "order", order_id)

    # ---- inventory ----
    def list_inventory(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = [dict(r) for r in conn.execute("SELECT * FROM inventory_items ORDER BY category, name").fetchall()]
        for r in rows:
            r["low"] = float(r["qty"]) <= float(r["reorder_level"])
        return rows

    def adjust_inventory_sku(
        self,
        sku: str,
        delta: float,
        reason: str,
        ref_type: str | None = None,
        ref_id: int | None = None,
    ) -> None:
        with self.connect() as conn:
            row = conn.execute("SELECT id, qty FROM inventory_items WHERE sku = ?", (sku,)).fetchone()
            if not row:
                return
            new_qty = float(row["qty"]) + float(delta)
            conn.execute(
                "UPDATE inventory_items SET qty = ?, updated_at = ? WHERE id = ?",
                (new_qty, now_iso(), row["id"]),
            )
            conn.execute(
                """INSERT INTO inventory_logs (item_id, delta, reason, ref_type, ref_id, created_at)
                   VALUES (?,?,?,?,?,?)""",
                (row["id"], delta, reason, ref_type, ref_id, now_iso()),
            )

    def adjust_inventory_id(self, item_id: int, delta: float, reason: str) -> None:
        with self.connect() as conn:
            row = conn.execute("SELECT id, qty FROM inventory_items WHERE id = ?", (item_id,)).fetchone()
            if not row:
                raise KeyError("item not found")
            new_qty = float(row["qty"]) + float(delta)
            conn.execute(
                "UPDATE inventory_items SET qty = ?, updated_at = ? WHERE id = ?",
                (new_qty, now_iso(), item_id),
            )
            conn.execute(
                """INSERT INTO inventory_logs (item_id, delta, reason, ref_type, ref_id, created_at)
                   VALUES (?,?,?,?,?,?)""",
                (item_id, delta, reason, "manual", None, now_iso()),
            )

    # ---- expenses / reports ----
    def add_expense(self, category: str, amount: int, note: str = "") -> int:
        with self.connect() as conn:
            cur = conn.execute(
                "INSERT INTO expenses (category, amount, note, created_at) VALUES (?,?,?,?)",
                (category, amount, note, now_iso()),
            )
            return int(cur.lastrowid)

    def list_expenses(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.connect() as conn:
            return [
                dict(r)
                for r in conn.execute(
                    "SELECT * FROM expenses ORDER BY id DESC LIMIT ?", (limit,)
                ).fetchall()
            ]

    def dashboard_stats(self, day: str | None = None) -> dict[str, Any]:
        day = day or today_wib()
        orders = self.list_orders(limit=5000)
        day_orders = [o for o in orders if local_day(o["created_at"]) == day]
        active = [o for o in orders if o["status"] not in ("diambil", "batal")]
        paid_today = [o for o in day_orders if o["payment_status"] == "lunas"]
        revenue = sum(int(o["total"]) for o in paid_today)
        potential = sum(int(o["total"]) for o in day_orders if o["status"] != "batal")
        expenses = [e for e in self.list_expenses(500) if local_day(e["created_at"]) == day]
        expense_total = sum(int(e["amount"]) for e in expenses)
        by_status: dict[str, int] = {}
        for o in active:
            by_status[o["status"]] = by_status.get(o["status"], 0) + 1
        low_stock = [i for i in self.list_inventory() if i["low"]]
        # last 7 days revenue series
        series = []
        for i in range(6, -1, -1):
            d = (datetime.now(WIB) - timedelta(days=i)).strftime("%Y-%m-%d")
            rev = sum(
                int(o["total"])
                for o in orders
                if local_day(o["created_at"]) == d and o["payment_status"] == "lunas"
            )
            series.append({"day": d[5:], "revenue": rev, "count": sum(1 for o in orders if local_day(o["created_at"]) == d)})
        top_services: dict[str, int] = {}
        for o in day_orders:
            for it in o.get("items") or []:
                top_services[it["service_name"]] = top_services.get(it["service_name"], 0) + int(it["qty"])
        top = sorted(top_services.items(), key=lambda x: x[1], reverse=True)[:5]
        return {
            "day": day,
            "orders_today": len(day_orders),
            "active_orders": len(active),
            "revenue_today": revenue,
            "potential_today": potential,
            "expense_today": expense_total,
            "profit_today": revenue - expense_total,
            "by_status": by_status,
            "low_stock": low_stock,
            "series": series,
            "top_services": top,
            "unpaid": sum(1 for o in active if o["payment_status"] != "lunas"),
        }

    def report_range(self, start: str, end: str) -> dict[str, Any]:
        orders = self.list_orders(limit=10000)
        filtered = [
            o
            for o in orders
            if start <= local_day(o["created_at"]) <= end and o["status"] != "batal"
        ]
        paid = [o for o in filtered if o["payment_status"] == "lunas"]
        expenses = [
            e
            for e in self.list_expenses(5000)
            if start <= local_day(e["created_at"]) <= end
        ]
        return {
            "start": start,
            "end": end,
            "order_count": len(filtered),
            "paid_count": len(paid),
            "revenue": sum(int(o["total"]) for o in paid),
            "potential": sum(int(o["total"]) for o in filtered),
            "expense_total": sum(int(e["amount"]) for e in expenses),
            "orders": filtered,
            "expenses": expenses,
        }

    # ---- payments ----
    def create_payment(
        self,
        order_id: int,
        *,
        provider: str,
        provider_order_id: str,
        transaction_id: str | None,
        amount: int,
        method: str = "qris",
        qr_string: str | None = None,
        qr_image_url: str | None = None,
        expiry_time: str | None = None,
        raw: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = now_iso()
        with self.connect() as conn:
            cur = conn.execute(
                """INSERT INTO payments (
                    order_id, provider, provider_order_id, transaction_id, method,
                    amount, status, qr_string, qr_image_url, expiry_time, raw_json,
                    created_at, updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    order_id,
                    provider,
                    provider_order_id,
                    transaction_id,
                    method,
                    int(amount),
                    "pending",
                    qr_string,
                    qr_image_url,
                    expiry_time,
                    json.dumps(raw or {}),
                    now,
                    now,
                ),
            )
            pid = int(cur.lastrowid)
        return self.get_payment(pid)  # type: ignore

    def get_payment(self, payment_id: int) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM payments WHERE id = ?", (payment_id,)).fetchone()
        return dict(row) if row else None

    def get_payment_by_provider_oid(self, provider_order_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM payments WHERE provider_order_id = ?", (provider_order_id,)
            ).fetchone()
        return dict(row) if row else None

    def latest_payment_for_order(self, order_id: int) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM payments WHERE order_id = ? ORDER BY id DESC LIMIT 1",
                (order_id,),
            ).fetchone()
        return dict(row) if row else None

    def mark_payment_status(
        self,
        payment_id: int,
        status: str,
        *,
        transaction_id: str | None = None,
        raw: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        now = now_iso()
        with self.connect() as conn:
            fields = ["status = ?", "updated_at = ?"]
            params: list[Any] = [status, now]
            if transaction_id is not None:
                fields.append("transaction_id = ?")
                params.append(transaction_id)
            if raw is not None:
                fields.append("raw_json = ?")
                params.append(json.dumps(raw))
            if status == "paid":
                fields.append("paid_at = COALESCE(paid_at, ?)")
                params.append(now)
            params.append(payment_id)
            conn.execute(f"UPDATE payments SET {', '.join(fields)} WHERE id = ?", params)
        return self.get_payment(payment_id)

    # ---- print jobs ----
    def enqueue_print_job(
        self,
        order_id: int,
        file_id: int | None,
        *,
        copies: int = 1,
        color_mode: str = "bw",
        duplex: bool = False,
        media: str = "A4",
        printer_name: str | None = None,
    ) -> dict[str, Any]:
        now = now_iso()
        with self.connect() as conn:
            # avoid duplicate queued job for same file
            if file_id is not None:
                existing = conn.execute(
                    """SELECT * FROM print_jobs
                       WHERE order_id = ? AND file_id = ? AND status IN ('queued','printing')
                       ORDER BY id DESC LIMIT 1""",
                    (order_id, file_id),
                ).fetchone()
                if existing:
                    return dict(existing)
            cur = conn.execute(
                """
                INSERT INTO print_jobs (
                    order_id, file_id, status, copies, color_mode, duplex, media,
                    printer_name, attempts, created_at, updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    order_id,
                    file_id,
                    "queued",
                    int(copies or 1),
                    color_mode or "bw",
                    1 if duplex else 0,
                    media or "A4",
                    printer_name,
                    0,
                    now,
                    now,
                ),
            )
            job_id = int(cur.lastrowid)
            conn.execute(
                "INSERT INTO order_events (order_id, status, message, actor, created_at) VALUES (?,?,?,?,?)",
                (
                    order_id,
                    None,
                    f"Print job #{job_id} masuk antrian ({color_mode}, x{copies})",
                    "print-queue",
                    now,
                ),
            )
        return self.get_print_job(job_id)  # type: ignore

    def get_print_job(self, job_id: int) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM print_jobs WHERE id = ?", (job_id,)).fetchone()
            if not row:
                return None
            job = dict(row)
            if job.get("file_id"):
                f = conn.execute(
                    "SELECT * FROM order_files WHERE id = ?", (job["file_id"],)
                ).fetchone()
                job["file"] = dict(f) if f else None
            else:
                job["file"] = None
            o = conn.execute("SELECT code, customer_name, status FROM orders WHERE id = ?", (job["order_id"],)).fetchone()
            job["order"] = dict(o) if o else None
            return job

    def list_print_jobs(
        self,
        status: str | None = None,
        order_id: int | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM print_jobs WHERE 1=1"
        params: list[Any] = []
        if status:
            sql += " AND status = ?"
            params.append(status)
        if order_id is not None:
            sql += " AND order_id = ?"
            params.append(order_id)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        with self.connect() as conn:
            jobs = [dict(r) for r in conn.execute(sql, params).fetchall()]
            for job in jobs:
                if job.get("file_id"):
                    f = conn.execute(
                        "SELECT id, filename, stored_path, mime, size_bytes FROM order_files WHERE id = ?",
                        (job["file_id"],),
                    ).fetchone()
                    job["file"] = dict(f) if f else None
                else:
                    job["file"] = None
                o = conn.execute(
                    "SELECT id, code, customer_name, status FROM orders WHERE id = ?",
                    (job["order_id"],),
                ).fetchone()
                job["order"] = dict(o) if o else None
        return jobs

    def claim_next_print_job(self, worker: str) -> dict[str, Any] | None:
        now = now_iso()
        with self.connect() as conn:
            row = conn.execute(
                """SELECT * FROM print_jobs
                   WHERE status = 'queued'
                   ORDER BY id ASC LIMIT 1"""
            ).fetchone()
            if not row:
                return None
            conn.execute(
                """UPDATE print_jobs
                   SET status = 'printing', claimed_by = ?, started_at = ?, updated_at = ?,
                       attempts = attempts + 1
                   WHERE id = ? AND status = 'queued'""",
                (worker, now, now, row["id"]),
            )
            job_id = int(row["id"])
        return self.get_print_job(job_id)

    def finish_print_job(
        self,
        job_id: int,
        *,
        ok: bool,
        message: str = "",
        result: dict[str, Any] | None = None,
        printer_name: str | None = None,
    ) -> dict[str, Any] | None:
        import json as _json

        now = now_iso()
        status = "done" if ok else "failed"
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM print_jobs WHERE id = ?", (job_id,)).fetchone()
            if not row:
                return None
            conn.execute(
                """UPDATE print_jobs
                   SET status = ?, last_error = ?, result_json = ?, printer_name = COALESCE(?, printer_name),
                       finished_at = ?, updated_at = ?
                   WHERE id = ?""",
                (
                    status,
                    None if ok else message,
                    _json.dumps(result or {}, ensure_ascii=False),
                    printer_name,
                    now,
                    now,
                    job_id,
                ),
            )
            conn.execute(
                "INSERT INTO order_events (order_id, status, message, actor, created_at) VALUES (?,?,?,?,?)",
                (
                    row["order_id"],
                    None,
                    f"Print job #{job_id} {'berhasil' if ok else 'gagal'}: {message or status}",
                    row["claimed_by"] or "print-agent",
                    now,
                ),
            )
        return self.get_print_job(job_id)

    def requeue_print_job(self, job_id: int) -> dict[str, Any] | None:
        now = now_iso()
        with self.connect() as conn:
            conn.execute(
                """UPDATE print_jobs
                   SET status = 'queued', claimed_by = NULL, started_at = NULL, finished_at = NULL,
                       last_error = NULL, updated_at = ?
                   WHERE id = ?""",
                (now, job_id),
            )
        return self.get_print_job(job_id)


db = DB()
