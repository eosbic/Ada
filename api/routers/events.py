from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from uuid import UUID
import json

from pydantic import BaseModel


from api.dependencies import get_tenant_id
from api.database import get_db

router = APIRouter()


class EventCreate(BaseModel):
    event_type: str
    payload: dict



# Función de negocio (reutilizable)
async def insert_event(db: AsyncSession, tenant_id, data: dict):
    query = text("""
        INSERT INTO events (empresa_id, event_type, payload)
        VALUES (:empresa_id, :event_type, :payload)
        RETURNING id, event_type, payload, created_at
    """)
    result = await db.execute(query, {
        "empresa_id": tenant_id,
        "event_type": data["event_type"],
        "payload": json.dumps(data["payload"])
    })
    await db.commit()
    return result.fetchone()

@router.post("/")
async def create_event(
    data: EventCreate,
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db)
):

    query = text("""
        INSERT INTO events (empresa_id, event_type, payload)
        VALUES (:empresa_id, :event_type, :payload)
        RETURNING id, event_type, payload, created_at
    """)

    result = await db.execute(query, {
        "empresa_id": tenant_id,
        "event_type": data.event_type,
        "payload": json.dumps(data.payload)
    })

    await db.commit()

    event = result.fetchone()

    return {
        "event_id": str(event.id),
        "event_type": event.event_type,
        "payload": event.payload,
        "created_at": event.created_at
    }

@router.get("/")
async def list_events(
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db)
):

    query = text("""
        SELECT id, event_type, payload, processed, created_at
        FROM events
        WHERE empresa_id = :empresa_id
        ORDER BY created_at DESC
    """)

    result = await db.execute(query, {
        "empresa_id": tenant_id
    })

    rows = result.fetchall()

    return [
        {
            "id": str(row.id),
            "event_type": row.event_type,
            "payload": row.payload,
            "processed": row.processed,
            "created_at": row.created_at
        }
        for row in rows
    ]