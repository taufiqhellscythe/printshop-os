#!/usr/bin/env python3
"""
Print agent for PC toko (USB → Epson L3110).

Jalankan di Windows/Linux yang printer-nya nyambung.
Agent poll job dari PrintShop OS (bisa di VPS), download file, print via CUPS/`lp`
atau fallback perintah custom.

Contoh:
  set PRINTSHOP_URL=http://129.226.135.26:8088
  set PRINT_AGENT_TOKEN=print-agent-change-me
  set CUPS_PRINTER=Epson_L3110
  python print_agent.py
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
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def http_json(method: str, url: str, token: str, data: dict | None = None, timeout: int = 30) -> dict:
    body = None
    headers = {
        "X-Print-Token": token,
        "Accept": "application/json",
        "User-Agent": "PrintShopAgent/1.0",
    }
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = Request(url, data=body, headers=headers, method=method)
    with urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8")
        return json.loads(raw) if raw else {}


def download(url: str, token: str, dest: Path) -> None:
    req = Request(url, headers={"X-Print-Token": token, "User-Agent": "PrintShopAgent/1.0"})
    with urlopen(req, timeout=120) as resp, dest.open("wb") as f:
        while True:
            chunk = resp.read(1024 * 256)
            if not chunk:
                break
            f.write(chunk)


def local_print(path: Path, *, printer: str, copies: int, color_mode: str, duplex: bool, media: str, title: str) -> dict:
    # Prefer CUPS lp on Linux/mac; on Windows try default PowerShell print if no lp
    if shutil.which("lp"):
        cmd = ["lp", "-d", printer, "-n", str(max(1, copies)), "-t", title[:80]]
        cmd += ["-o", f"media={media}"]
        if color_mode == "bw":
            cmd += ["-o", "print-color-mode=monochrome", "-o", "ColorModel=Gray"]
        else:
            cmd += ["-o", "print-color-mode=color"]
        cmd += ["-o", "sides=two-sided-long-edge" if duplex else "sides=one-sided"]
        cmd.append(str(path))
        try:
            out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True, timeout=90)
            return {"ok": True, "output": out.strip(), "printer": printer, "cmd": " ".join(cmd[:-1] + [path.name])}
        except subprocess.CalledProcessError as e:
            return {"ok": False, "error": (e.output or str(e)).strip()}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # Windows fallback: start default associated app print verb (best-effort)
    if os.name == "nt":
        try:
            # Uses default printer; user should set L3110 as default
            cmd = [
                "powershell",
                "-NoProfile",
                "-Command",
                f'Start-Process -FilePath "{path}" -Verb Print -WindowStyle Hidden',
            ]
            subprocess.check_call(cmd, timeout=60)
            return {
                "ok": True,
                "output": "Windows Start-Process -Verb Print",
                "printer": printer or "default",
                "note": "Pastikan L3110 adalah default printer Windows",
            }
        except Exception as e:
            return {"ok": False, "error": f"Windows print failed: {e}"}

    return {
        "ok": False,
        "error": "Tidak ada backend print (install CUPS/`lp` atau jalankan di Windows dengan default printer)",
    }


def loop(base_url: str, token: str, printer: str, worker: str, interval: float) -> None:
    base = base_url.rstrip("/")
    print(f"[agent] start worker={worker} server={base} printer={printer or '(auto/default)'}")
    while True:
        try:
            claimed = http_json("POST", f"{base}/api/print-agent/claim", token, {"worker": worker})
            job = claimed.get("job")
            if not job:
                time.sleep(interval)
                continue
            job_id = job["id"]
            file_meta = job.get("file") or {}
            print(f"[agent] claim job #{job_id} order={job.get('order', {}).get('code')} file={file_meta.get('filename')}")
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
                order_code = (job.get("order") or {}).get("code") or str(job_id)
                result = local_print(
                    dest,
                    printer=printer or job.get("printer_name") or "Epson_L3110",
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
                print(f"[agent] job #{job_id} -> {'OK' if result.get('ok') else 'FAIL'}: {result}")
        except HTTPError as e:
            print(f"[agent] HTTP {e.code}: {e.read().decode('utf-8', errors='ignore')[:300]}")
            time.sleep(max(interval, 3))
        except URLError as e:
            print(f"[agent] koneksi gagal: {e}. retry...")
            time.sleep(max(interval, 5))
        except Exception as e:
            print(f"[agent] error: {e}")
            time.sleep(max(interval, 3))


def main() -> None:
    p = argparse.ArgumentParser(description="PrintShop OS print agent")
    p.add_argument("--url", default=env("PRINTSHOP_URL", "http://127.0.0.1:8088"))
    p.add_argument("--token", default=env("PRINT_AGENT_TOKEN", "print-agent-change-me"))
    p.add_argument("--printer", default=env("CUPS_PRINTER", ""))
    p.add_argument("--worker", default=env("PRINT_WORKER_NAME", os.environ.get("COMPUTERNAME") or os.uname().nodename if hasattr(os, "uname") else "agent"))
    p.add_argument("--interval", type=float, default=float(env("PRINT_POLL_INTERVAL", "2") or 2))
    args = p.parse_args()
    if not args.token or args.token == "print-agent-change-me":
        print("WARNING: ganti PRINT_AGENT_TOKEN di server & agent biar aman", file=sys.stderr)
    loop(args.url, args.token, args.printer, args.worker, args.interval)


if __name__ == "__main__":
    main()
