"""PrintShop OS — Web MIS for Epson L3110 print shops."""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.config import HOST, PORT, SECRET_KEY, SHOP_NAME, UPLOAD_DIR
from app.db import db
from app.routers import admin, payment, print_agent, public

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("printshop-os")

app = FastAPI(title=f"{SHOP_NAME} OS", docs_url="/api/docs", redoc_url=None)
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY, session_cookie="printshop_session")

static_dir = Path(__file__).parent / "static"
static_dir.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")

app.include_router(public.router)
app.include_router(payment.router)
app.include_router(admin.router)
app.include_router(print_agent.router)


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "shop": SHOP_NAME,
        "orders": len(db.list_orders(limit=1)) >= 0,
        "db": str(db.path),
    }


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    logger.exception("Unhandled error on %s", request.url.path)
    # Let HTTPException-like responses pass; only catch unexpected errors
    from starlette.exceptions import HTTPException as StarletteHTTPException
    if isinstance(exc, StarletteHTTPException):
        raise exc
    if request.url.path.startswith("/api/") or "application/json" in (request.headers.get("accept") or ""):
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)
    return JSONResponse({"detail": str(exc)}, status_code=500)


def main() -> None:
    import uvicorn

    # ensure seed
    _ = db.list_services()
    logger.info("Starting %s on %s:%s", SHOP_NAME, HOST, PORT)
    uvicorn.run("app.main:app", host=HOST, port=PORT, reload=False)


if __name__ == "__main__":
    main()
