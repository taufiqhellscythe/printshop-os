"""CUPS print bridge + job queue for remote print agent."""
from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path
from typing import Any

from app.config import AUTO_PRINT_ON_STATUS, CUPS_PRINTER, PRINT_COLOR_MODE

logger = logging.getLogger(__name__)


def cups_available() -> bool:
    return bool(shutil.which("lp"))


def list_printers() -> list[str]:
    if not cups_available():
        return []
    try:
        out = subprocess.check_output(["lpstat", "-a"], text=True, timeout=5)
        return [line.split()[0] for line in out.splitlines() if line.strip()]
    except Exception as e:
        logger.warning("lpstat failed: %s", e)
        return []


def printer_status(printer: str | None = None) -> dict[str, Any]:
    target = printer or CUPS_PRINTER
    if not cups_available():
        return {"ok": False, "error": "CUPS/lp belum terpasang di mesin ini"}
    if not target:
        printers = list_printers()
        return {
            "ok": bool(printers),
            "printer": None,
            "printers": printers,
            "error": None if printers else "Belum ada printer queue",
        }
    try:
        out = subprocess.check_output(["lpstat", "-p", target], text=True, timeout=5)
        return {"ok": True, "printer": target, "raw": out.strip(), "printers": list_printers()}
    except Exception as e:
        return {"ok": False, "printer": target, "error": str(e), "printers": list_printers()}


def _guess_color(order: dict[str, Any] | None, filename: str) -> str:
    mode = (PRINT_COLOR_MODE or "auto").lower()
    if mode in {"color", "colour", "warna"}:
        return "color"
    if mode in {"bw", "mono", "grayscale", "hitam-putih", "hitamputih"}:
        return "bw"
    # auto
    text = " ".join(
        [
            filename.lower(),
            " ".join(i.get("service_key", "") for i in (order or {}).get("items") or []),
            " ".join(i.get("service_name", "") for i in (order or {}).get("items") or []),
        ]
    )
    if any(k in text for k in ("color", "warna", "photo", "foto")):
        return "color"
    return "bw"


def build_lp_options(
    *,
    color_mode: str = "bw",
    duplex: bool = False,
    media: str = "A4",
    extra: list[str] | None = None,
) -> list[str]:
    opts = [f"media={media}"]
    if color_mode == "bw":
        opts.append("print-color-mode=monochrome")
        opts.append("ColorModel=Gray")
    else:
        opts.append("print-color-mode=color")
    if duplex:
        opts.append("sides=two-sided-long-edge")
    else:
        opts.append("sides=one-sided")
    if extra:
        opts.extend(extra)
    return opts


def submit_print_job(
    file_path: str | Path,
    *,
    copies: int = 1,
    title: str | None = None,
    printer: str | None = None,
    color_mode: str = "bw",
    duplex: bool = False,
    media: str = "A4",
) -> dict[str, Any]:
    """Submit file to local CUPS. Safe no-op if printer not configured."""
    path = Path(file_path)
    if not path.exists():
        return {"ok": False, "error": "file not found", "path": str(path)}
    if not cups_available():
        return {
            "ok": False,
            "error": "CUPS/lp not installed on this machine",
            "hint": "Install di PC toko yang USB-nya ke L3110, atau jalankan print agent",
        }
    target = printer or CUPS_PRINTER
    if not target:
        printers = list_printers()
        if len(printers) == 1:
            target = printers[0]
        else:
            return {
                "ok": False,
                "error": "CUPS_PRINTER belum di-set di .env",
                "printers": printers,
                "manual_path": str(path),
            }

    cmd = ["lp", "-d", target, "-n", str(max(1, int(copies or 1)))]
    if title:
        cmd.extend(["-t", title[:80]])
    for opt in build_lp_options(color_mode=color_mode, duplex=duplex, media=media):
        cmd.extend(["-o", opt])
    cmd.append(path.as_posix())
    try:
        out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True, timeout=60)
        return {
            "ok": True,
            "output": out.strip(),
            "printer": target,
            "color_mode": color_mode,
            "copies": copies,
            "cmd": " ".join(cmd[:-1] + [path.name]),
        }
    except subprocess.CalledProcessError as e:
        return {"ok": False, "error": (e.output or str(e)).strip(), "printer": target}
    except Exception as e:
        return {"ok": False, "error": str(e), "printer": target}


def should_auto_print_status(status: str) -> bool:
    targets = {s.strip() for s in (AUTO_PRINT_ON_STATUS or "").split(",") if s.strip()}
    return status in targets


def resolve_print_settings(order: dict[str, Any], file_row: dict[str, Any] | None = None) -> dict[str, Any]:
    filename = (file_row or {}).get("filename") or ""
    color_mode = _guess_color(order, filename)
    duplex = False
    for a in order.get("addons") or []:
        key = (a.get("addon_key") or a.get("key") or "").lower()
        name = (a.get("addon_name") or a.get("name") or "").lower()
        if key == "duplex" or "bolak" in name:
            duplex = True
    # qty from first matching print item, else 1
    copies = 1
    for it in order.get("items") or []:
        sk = it.get("service_key") or ""
        if sk.startswith("print_") or sk.startswith("copy_"):
            copies = max(1, int(it.get("qty") or 1))
            break
    media = "A4"
    joined = " ".join(i.get("service_key", "") for i in order.get("items") or []).lower()
    if "f4" in joined or "legal" in joined:
        media = "Legal"
    return {
        "color_mode": color_mode,
        "duplex": duplex,
        "copies": copies,
        "media": media,
    }
