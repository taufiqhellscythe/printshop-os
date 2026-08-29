"""API for remote print agent (PC toko + L3110)."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.config import PRINT_AGENT_TOKEN
from app.db import db

router = APIRouter(prefix="/api/print-agent", tags=["print-agent"])


def _auth(token: str | None) -> None:
    expected = PRINT_AGENT_TOKEN or ""
    if not expected or token != expected:
        raise HTTPException(status_code=401, detail="Invalid print agent token")


class ClaimIn(BaseModel):
    worker: str = Field(default="agent")


class CompleteIn(BaseModel):
    ok: bool
    message: str = ""
    printer_name: str | None = None
    result: dict | None = None


@router.get("/health")
async def agent_health(x_print_token: str | None = Header(default=None)):
    _auth(x_print_token)
    queued = db.list_print_jobs(status="queued", limit=100)
    printing = db.list_print_jobs(status="printing", limit=100)
    return {
        "ok": True,
        "queued": len(queued),
        "printing": len(printing),
    }


@router.post("/claim")
async def claim_job(payload: ClaimIn, x_print_token: str | None = Header(default=None)):
    _auth(x_print_token)
    job = db.claim_next_print_job(payload.worker or "agent")
    return {"ok": True, "job": job}


@router.get("/jobs/{job_id}/file")
async def job_file(job_id: int, x_print_token: str | None = Header(default=None)):
    _auth(x_print_token)
    job = db.get_print_job(job_id)
    if not job or not job.get("file"):
        raise HTTPException(404, "file not found")
    path = Path(job["file"]["stored_path"])
    if not path.exists():
        raise HTTPException(404, "file missing on disk")
    return FileResponse(
        path,
        filename=job["file"].get("filename") or path.name,
        media_type=job["file"].get("mime") or "application/octet-stream",
    )


@router.post("/jobs/{job_id}/complete")
async def complete_job(
    job_id: int,
    payload: CompleteIn,
    x_print_token: str | None = Header(default=None),
):
    _auth(x_print_token)
    job = db.finish_print_job(
        job_id,
        ok=payload.ok,
        message=payload.message,
        result=payload.result,
        printer_name=payload.printer_name,
    )
    if not job:
        raise HTTPException(404, "job not found")
    # bump order to proses on success if still early
    if payload.ok and job.get("order_id"):
        order = db.get_order(job["order_id"])
        if order and order["status"] in ("baru", "dikonfirmasi", "prepress", "antrian"):
            db.update_order_status(
                order["id"],
                "proses",
                actor=job.get("claimed_by") or "print-agent",
                message="Print agent sukses → proses",
            )
    return {"ok": True, "job": job}
