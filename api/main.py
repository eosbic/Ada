import os
import time
import logging
from collections import defaultdict
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
import asyncio

from api.database import engine
from api.routers import api_router
from api.workers.event_worker import worker_loop
from api.workers.drive_worker import drive_worker_loop
from api.workers.morning_brief_worker import morning_brief_worker_loop
from api.workers.alert_worker import alert_worker_loop
from api.workers.email_monitor_worker import email_monitor_worker_loop
from api.workers.prospect_scout_worker import prospect_scout_worker_loop
from api.services.memory_service import init_qdrant


# ── Logging estructurado ──────────────────────────────────
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("ada")


ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "").split(",")
ALLOWED_ORIGINS = [o.strip() for o in ALLOWED_ORIGINS if o.strip()]


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Rate limiter: 60 requests/min por IP."""

    def __init__(self, app, max_requests: int = 60, window_seconds: int = 60):
        super().__init__(app)
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._requests: dict[str, list[float]] = defaultdict(list)

    async def dispatch(self, request: Request, call_next):
        client_ip = request.client.host if request.client else "unknown"
        now = time.time()
        cutoff = now - self.window_seconds

        # Limpiar entradas expiradas
        self._requests[client_ip] = [
            t for t in self._requests[client_ip] if t > cutoff
        ]

        if len(self._requests[client_ip]) >= self.max_requests:
            return JSONResponse(
                status_code=429,
                content={"detail": "Too many requests. Limit: 60/min."},
            )

        self._requests[client_ip].append(now)
        return await call_next(request)


# ── Lifespan (reemplaza @app.on_event deprecated) ────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup & shutdown de la aplicación."""
    logger.info("Ada V5.0 iniciando...")
    init_qdrant()
    asyncio.create_task(worker_loop())
    asyncio.create_task(drive_worker_loop())
    asyncio.create_task(morning_brief_worker_loop())
    asyncio.create_task(alert_worker_loop())
    asyncio.create_task(email_monitor_worker_loop())
    asyncio.create_task(prospect_scout_worker_loop())
    logger.info("Workers iniciados correctamente")
    yield
    logger.info("Ada V5.0 apagándose...")


app = FastAPI(title="Ada V5.0", lifespan=lifespan)

app.add_middleware(RateLimitMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health_check():
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return {"status": "ok", "database": "connected"}
    except Exception as e:
        return {"status": "error", "database": "disconnected", "detail": str(e)}


app.include_router(api_router)
