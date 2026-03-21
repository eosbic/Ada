import os
import asyncio

from api.services.drive_ingestion import run_drive_ingestion_once


async def drive_worker_loop():
    interval = int(os.getenv("DRIVE_INGEST_POLL_SECONDS", "120"))
    enabled = os.getenv("ENABLE_DRIVE_INGESTION", "true").strip().lower() in {"1", "true", "yes", "on"}
    if not enabled:
        return

    while True:
        try:
            await run_drive_ingestion_once()
        except Exception as e:
            print(f"DRIVE WORKER error: {e}")
        await asyncio.sleep(interval)
