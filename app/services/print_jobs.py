"""High-level print orchestration for orders."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from app.config import AUTO_PRINT_LOCAL, CUPS_PRINTER
from app.db import db
from app.services.print_bridge import (
    cups_available,
    resolve_print_settings,
    should_auto_print_status,
    submit_print_job,
)

logger = logging.getLogger(__name__)


def _printable_files(order: dict[str, Any]) -> list[dict[str, Any]]:
    files = []
    for f in order.get("files") or []:
        path = Path(f.get("stored_path") or "")
        name = (f.get("filename") or "").lower()
        mime = (f.get("mime") or "").lower()
        if not path.exists():
            continue
        # Prefer common printables; skip empty
        if path.stat().st_size <= 0:
            continue
        files.append(f)
    return files


def enqueue_order_prints(
    order_id: int,
    *,
    actor: str = "system",
    force: bool = False,
) -> list[dict[str, Any]]:
    order = db.get_order(order_id)
    if not order:
        return []
    files = _printable_files(order)
    if not files:
        return []
    jobs: list[dict[str, Any]] = []
    for f in files:
        settings = resolve_print_settings(order, f)
        job = db.enqueue_print_job(
            order_id,
            f["id"],
            copies=settings["copies"],
            color_mode=settings["color_mode"],
            duplex=settings["duplex"],
            media=settings["media"],
            printer_name=CUPS_PRINTER or None,
        )
        jobs.append(job)
    if force or AUTO_PRINT_LOCAL:
        for job in jobs:
            if job.get("status") == "queued":
                try_local_print_job(job["id"], actor=actor)
    return [db.get_print_job(j["id"]) for j in jobs if j]


def maybe_auto_print_for_status(order_id: int, status: str, *, actor: str = "system") -> list[dict[str, Any]]:
    if not should_auto_print_status(status):
        return []
    return enqueue_order_prints(order_id, actor=actor)


def try_local_print_job(job_id: int, *, actor: str = "local-cups") -> dict[str, Any]:
    job = db.get_print_job(job_id)
    if not job:
        return {"ok": False, "error": "job not found"}
    if job["status"] in ("done", "printing"):
        return {"ok": job["status"] == "done", "job": job, "skipped": True}

    if not cups_available():
        # remain queued for remote agent
        return {
            "ok": False,
            "queued": True,
            "error": "CUPS tidak ada di server ini — tunggu print agent di PC toko",
            "job": job,
        }

    claimed = None
    # claim if still queued
    if job["status"] == "queued":
        # direct claim by id
        from app.db import now_iso

        now = now_iso()
        with db.connect() as conn:
            conn.execute(
                """UPDATE print_jobs
                   SET status='printing', claimed_by=?, started_at=?, updated_at=?, attempts=attempts+1
                   WHERE id=? AND status='queued'""",
                (actor, now, now, job_id),
            )
        claimed = db.get_print_job(job_id)
    else:
        claimed = job

    f = (claimed or {}).get("file")
    if not f or not f.get("stored_path"):
        finished = db.finish_print_job(job_id, ok=False, message="file hilang")
        return {"ok": False, "error": "file hilang", "job": finished}

    order = db.get_order(claimed["order_id"])
    title = f"{(order or {}).get('code', job_id)} {f.get('filename', '')}".strip()
    result = submit_print_job(
        f["stored_path"],
        copies=int(claimed.get("copies") or 1),
        title=title,
        printer=claimed.get("printer_name") or CUPS_PRINTER or None,
        color_mode=claimed.get("color_mode") or "bw",
        duplex=bool(claimed.get("duplex")),
        media=claimed.get("media") or "A4",
    )
    finished = db.finish_print_job(
        job_id,
        ok=bool(result.get("ok")),
        message=result.get("output") if result.get("ok") else result.get("error", "print failed"),
        result=result,
        printer_name=result.get("printer"),
    )
    if result.get("ok") and order and order.get("status") in ("baru", "dikonfirmasi", "prepress", "antrian"):
        db.update_order_status(order["id"], "proses", actor=actor, message="Auto-print berhasil → proses")
    return {"ok": bool(result.get("ok")), "result": result, "job": finished}
