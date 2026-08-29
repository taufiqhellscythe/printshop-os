#!/usr/bin/env python3
"""
PrintShop OS — Windows Print Agent (Epson L3110)

PC toko (USB → L3110) poll job dari server web, download file, print otomatis.

Jalankan via start.bat (paling gampang).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

APP_DIR = Path(__file__).resolve().parent
CONFIG_PATH = APP_DIR / "config.env"
LOG_PATH = APP_DIR / "agent.log"


def log(msg: str) -> None:
    line = time.strftime("%Y-%m-%d %H:%M:%S") + " " + msg
    print(line, flush=True)
    try:
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def load_config_file() -> dict[str, str]:
    cfg: dict[str, str] = {}
    if not CONFIG_PATH.exists():
        return cfg
    for raw in CONFIG_PATH.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        cfg[k.strip()] = v.strip().strip('"').strip("'")
    return cfg


FILE_CFG = load_config_file()


def cfg(name: str, default: str = "") -> str:
    return (os.getenv(name) or FILE_CFG.get(name) or default).strip()


def http_json(method: str, url: str, token: str, data: dict | None = None, timeout: int = 30) -> dict:
    body = None
    headers = {
        "X-Print-Token": token,
        "Accept": "application/json",
        "User-Agent": "PrintShopWindowsAgent/1.1",
    }
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = Request(url, data=body, headers=headers, method=method)
    with urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8")
        return json.loads(raw) if raw else {}


def download(url: str, token: str, dest: Path) -> None:
    req = Request(url, headers={"X-Print-Token": token, "User-Agent": "PrintShopWindowsAgent/1.1"})
    with urlopen(req, timeout=180) as resp, dest.open("wb") as f:
        while True:
            chunk = resp.read(1024 * 256)
            if not chunk:
                break
            f.write(chunk)


def run(cmd: list[str], timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        shell=False,
    )


def default_printer_name() -> str:
    if os.name != "nt":
        return ""
    ps = (
        "try { (Get-CimInstance Win32_Printer | Where-Object {$_.Default -eq $true}).Name }"
        " catch { (Get-WmiObject -Query \"SELECT * FROM Win32_Printer WHERE Default=$true\").Name }"
    )
    try:
        cp = run(["powershell", "-NoProfile", "-Command", ps], timeout=20)
        name = (cp.stdout or "").strip()
        return name
    except Exception:
        return ""


def list_printers() -> list[str]:
    if os.name != "nt":
        return []
    ps = (
        "Get-CimInstance Win32_Printer | Select-Object -ExpandProperty Name"
    )
    try:
        cp = run(["powershell", "-NoProfile", "-Command", ps], timeout=20)
        return [x.strip() for x in (cp.stdout or "").splitlines() if x.strip()]
    except Exception:
        return []


def find_sumatra() -> str | None:
    candidates = [
        cfg("SUMATRA_PATH"),
        r"C:\Program Files\SumatraPDF\SumatraPDF.exe",
        r"C:\Program Files (x86)\SumatraPDF\SumatraPDF.exe",
        str(APP_DIR / "SumatraPDF.exe"),
    ]
    for c in candidates:
        if c and Path(c).exists():
            return c
    return shutil.which("SumatraPDF") or shutil.which("SumatraPDF.exe")


def print_with_sumatra(path: Path, printer: str, copies: int) -> dict:
    exe = find_sumatra()
    if not exe:
        return {"ok": False, "error": "SumatraPDF not found"}
    # Sumatra: -print-to <printer> -print-settings "n copies" file
    settings = f"{max(1, copies)}x"
    cmd = [exe, "-silent", "-print-to", printer, "-print-settings", settings, str(path)]
    try:
        cp = run(cmd, timeout=180)
        if cp.returncode == 0:
            return {"ok": True, "output": "SumatraPDF print ok", "printer": printer, "engine": "sumatra"}
        return {
            "ok": False,
            "error": (cp.stderr or cp.stdout or f"sumatra exit {cp.returncode}").strip(),
            "engine": "sumatra",
        }
    except Exception as e:
        return {"ok": False, "error": str(e), "engine": "sumatra"}


def print_with_windows_verb(path: Path, copies: int) -> dict:
    """Uses default printer association (best-effort). Copies loop."""
    errors = []
    for i in range(max(1, copies)):
        ps = f'Start-Process -FilePath "{path}" -Verb Print -WindowStyle Hidden -ErrorAction Stop'
        try:
            cp = run(["powershell", "-NoProfile", "-Command", ps], timeout=90)
            if cp.returncode != 0:
                errors.append((cp.stderr or cp.stdout or f"exit {cp.returncode}").strip())
            else:
                # give spooler a moment between copies
                time.sleep(1.5)
        except Exception as e:
            errors.append(str(e))
    if errors and len(errors) == max(1, copies):
        return {"ok": False, "error": "; ".join(errors[:3]), "engine": "win-verb"}
    return {
        "ok": True,
        "output": f"Windows Print verb x{copies}",
        "printer": "default",
        "engine": "win-verb",
        "warnings": errors or None,
    }


def print_with_lp(path: Path, printer: str, copies: int, color_mode: str, duplex: bool, media: str, title: str) -> dict:
    if not shutil.which("lp"):
        return {"ok": False, "error": "lp not found"}
    cmd = ["lp", "-d", printer, "-n", str(max(1, copies)), "-t", title[:80]]
    cmd += ["-o", f"media={media}"]
    if color_mode == "bw":
        cmd += ["-o", "print-color-mode=monochrome", "-o", "ColorModel=Gray"]
    else:
        cmd += ["-o", "print-color-mode=color"]
    cmd += ["-o", "sides=two-sided-long-edge" if duplex else "sides=one-sided"]
    cmd.append(str(path))
    try:
        cp = run(cmd, timeout=90)
        if cp.returncode == 0:
            return {"ok": True, "output": (cp.stdout or "lp ok").strip(), "printer": printer, "engine": "lp"}
        return {"ok": False, "error": (cp.stderr or cp.stdout or "lp failed").strip(), "engine": "lp"}
    except Exception as e:
        return {"ok": False, "error": str(e), "engine": "lp"}


def local_print(
    path: Path,
    *,
    printer: str,
    copies: int,
    color_mode: str,
    duplex: bool,
    media: str,
    title: str,
) -> dict:
    target = printer or default_printer_name()
    if not target:
        printers = list_printers()
        if len(printers) == 1:
            target = printers[0]
        elif printers:
            return {
                "ok": False,
                "error": "Printer belum dipilih. Isi PRINTER_NAME di config.env",
                "printers": printers,
            }
        else:
            return {"ok": False, "error": "Tidak ada printer terdeteksi di Windows"}

    suffix = path.suffix.lower()
    # PDF/image: prefer Sumatra if available (more reliable silent print)
    if suffix in {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"} or True:
        if find_sumatra() and suffix in {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".gif"}:
            res = print_with_sumatra(path, target, copies)
            if res.get("ok"):
                return res
            log(f"sumatra failed: {res.get('error')}; fallback...")

    if shutil.which("lp"):
        res = print_with_lp(path, target, copies, color_mode, duplex, media, title)
        if res.get("ok"):
            return res
        log(f"lp failed: {res.get('error')}; fallback...")

    # Windows association print (default printer)
    res = print_with_windows_verb(path, copies if suffix not in {".pdf"} else copies)
    res["printer"] = target
    return res


def loop(base_url: str, token: str, printer: str, worker: str, interval: float) -> None:
    base = base_url.rstrip("/")
    log(f"START worker={worker} server={base}")
    log(f"printer config={printer or '(default Windows)'}")
    if os.name == "nt":
        dp = default_printer_name()
        log(f"default printer now: {dp or '-'}")
        printers = list_printers()
        if printers:
            log("printers: " + ", ".join(printers))
        if find_sumatra():
            log(f"SumatraPDF: {find_sumatra()}")
        else:
            log("SumatraPDF: not found (optional, recommended for PDF silent print)")

    while True:
        try:
            claimed = http_json("POST", f"{base}/api/print-agent/claim", token, {"worker": worker})
            job = claimed.get("job")
            if not job:
                time.sleep(interval)
                continue

            job_id = job["id"]
            file_meta = job.get("file") or {}
            order_code = (job.get("order") or {}).get("code") or str(job_id)
            log(f"CLAIM job=#{job_id} order={order_code} file={file_meta.get('filename')}")

            if not file_meta.get("id"):
                http_json(
                    "POST",
                    f"{base}/api/print-agent/jobs/{job_id}/complete",
                    token,
                    {"ok": False, "message": "job tanpa file", "printer_name": printer},
                )
                continue

            with tempfile.TemporaryDirectory(prefix="psprint_") as td:
                dest = Path(td) / (file_meta.get("filename") or f"job_{job_id}.bin")
                download(f"{base}/api/print-agent/jobs/{job_id}/file", token, dest)
                log(f"DOWNLOADED {dest.name} ({dest.stat().st_size} bytes)")
                result = local_print(
                    dest,
                    printer=printer or job.get("printer_name") or "",
                    copies=int(job.get("copies") or 1),
                    color_mode=job.get("color_mode") or "bw",
                    duplex=bool(job.get("duplex")),
                    media=job.get("media") or "A4",
                    title=f"{order_code} {file_meta.get('filename') or ''}".strip(),
                )
                http_json(
                    "POST",
                    f"{base}/api/print-agent/jobs/{job_id}/complete",
                    token,
                    {
                        "ok": bool(result.get("ok")),
                        "message": result.get("output") if result.get("ok") else result.get("error", "failed"),
                        "printer_name": result.get("printer") or printer,
                        "result": result,
                    },
                )
                log(f"DONE job=#{job_id} ok={result.get('ok')} engine={result.get('engine')} detail={result}")
        except HTTPError as e:
            body = e.read().decode("utf-8", errors="ignore")[:300]
            log(f"HTTP {e.code}: {body}")
            time.sleep(max(interval, 3))
        except URLError as e:
            log(f"koneksi gagal: {e}")
            time.sleep(max(interval, 5))
        except Exception as e:
            log(f"error: {e}")
            log(traceback.format_exc(limit=3))
            time.sleep(max(interval, 3))


def self_test() -> int:
    log("=== SELF TEST ===")
    log(f"config: {CONFIG_PATH} exists={CONFIG_PATH.exists()}")
    url = cfg("PRINTSHOP_URL", "http://127.0.0.1:8088")
    token = cfg("PRINT_AGENT_TOKEN", "print-agent-change-me")
    printer = cfg("PRINTER_NAME") or cfg("CUPS_PRINTER")
    log(f"URL={url}")
    log(f"printer={printer or default_printer_name() or '-'}")
    try:
        h = http_json("GET", f"{url.rstrip('/')}/api/print-agent/health", token)
        log(f"server health: {h}")
    except Exception as e:
        log(f"server health FAIL: {e}")
        return 1
    if os.name == "nt":
        log("printers: " + ", ".join(list_printers()) or "-")
        log("default: " + (default_printer_name() or "-"))
    log("SELF TEST OK")
    return 0


def main() -> None:
    p = argparse.ArgumentParser(description="PrintShop Windows Agent")
    p.add_argument("--url", default=cfg("PRINTSHOP_URL", "http://127.0.0.1:8088"))
    p.add_argument("--token", default=cfg("PRINT_AGENT_TOKEN", "print-agent-change-me"))
    p.add_argument("--printer", default=cfg("PRINTER_NAME") or cfg("CUPS_PRINTER", ""))
    p.add_argument(
        "--worker",
        default=cfg("PRINT_WORKER_NAME")
        or os.environ.get("COMPUTERNAME")
        or os.environ.get("HOSTNAME")
        or "windows-agent",
    )
    p.add_argument("--interval", type=float, default=float(cfg("PRINT_POLL_INTERVAL", "2") or 2))
    p.add_argument("--test", action="store_true", help="Test koneksi + printer lalu exit")
    args = p.parse_args()

    if args.test:
        raise SystemExit(self_test())

    if not args.token or args.token == "print-agent-change-me":
        log("WARNING: ganti PRINT_AGENT_TOKEN di config.env biar aman")
    if not args.url:
        log("ERROR: PRINTSHOP_URL kosong")
        raise SystemExit(2)

    loop(args.url, args.token, args.printer, args.worker, args.interval)


if __name__ == "__main__":
    main()
