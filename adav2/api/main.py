from fastapi import FastAPI
from sqlalchemy import text
from fastapi.middleware.cors import CORSMiddleware
import asyncio

from api.database import engine
from api.routers import api_router
from api.workers.event_worker import worker_loop
from api.workers.drive_worker import drive_worker_loop
from api.services.memory_service import init_qdrant


app = FastAPI(title="Ada V5.0")


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup_event():
    init_qdrant()
    asyncio.create_task(worker_loop())
    asyncio.create_task(drive_worker_loop())


@app.get("/health")
async def health_check():
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return {"status": "ok", "database": "connected"}
    except Exception as e:
        return {"status": "error", "database": "disconnected", "detail": str(e)}


app.include_router(api_router)
