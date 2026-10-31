import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import deps
from . import models as m
from .config import BILLING_AUTORUN_MINUTES, CORS_ORIGINS, DEV_MAILBOX
from .db import SessionLocal, engine, get_db
from .routers import auth, billing, catalog, subscriptions
from .services.billing import run_billing
from .services.subscriptions import DomainError

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("brightloop")


def _sweep_once() -> None:
    with SessionLocal() as db:
        r = run_billing(db, deps.today())
        log.info("scheduled billing run: %s", r)


async def _scheduler():
    while True:
        await asyncio.sleep(BILLING_AUTORUN_MINUTES * 60)
        try:
            await asyncio.to_thread(_sweep_once)
        except Exception:  # noqa: BLE001 - the loop must survive a bad run
            log.exception("scheduled billing run failed")


@asynccontextmanager
async def lifespan(_: FastAPI):
    m.Base.metadata.create_all(engine)
    task = asyncio.create_task(_scheduler()) if BILLING_AUTORUN_MINUTES > 0 else None
    yield
    if task:
        task.cancel()


app = FastAPI(title="Brightloop Subscription Management", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=CORS_ORIGINS, allow_methods=["*"], allow_headers=["*"])


@app.exception_handler(DomainError)
async def domain_error(_: Request, e: DomainError):
    return JSONResponse({"detail": e.message}, status_code=e.status)


for r in (auth.router, catalog.router, subscriptions.router, billing.router):
    app.include_router(r, prefix="/api")


@app.get("/api/health")
def health():
    return {"ok": True}


if DEV_MAILBOX:
    @app.get("/api/dev/mails")
    def mails(limit: int = 20, db: Session = Depends(get_db)):
        """Demo only: stands in for an inbox so the password-reset link can be followed."""
        rows = db.scalars(select(m.MailLog).order_by(m.MailLog.id.desc()).limit(min(limit, 100))).all()
        return [{"id": x.id, "to": x.to, "subject": x.subject, "body": x.body, "created_at": x.created_at}
                for x in rows]
