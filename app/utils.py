"""Helpers."""
from __future__ import annotations

import re
from typing import Any


def rupiah(amount: int | float | None) -> str:
    n = int(amount or 0)
    return f"Rp{n:,}".replace(",", ".")


def slug_filename(name: str) -> str:
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._")
    return base or "file.bin"


def order_progress(status: str) -> int:
    flow = [
        "baru",
        "dikonfirmasi",
        "prepress",
        "antrian",
        "proses",
        "finishing",
        "siap",
        "diambil",
    ]
    if status == "batal":
        return 0
    try:
        return int((flow.index(status) + 1) / len(flow) * 100)
    except ValueError:
        return 0


def summarize_items(order: dict[str, Any]) -> str:
    items = order.get("items") or []
    if not items:
        return "-"
    parts = [f"{i['service_name']} x{i['qty']}" for i in items[:3]]
    if len(items) > 3:
        parts.append(f"+{len(items)-3}")
    return ", ".join(parts)
