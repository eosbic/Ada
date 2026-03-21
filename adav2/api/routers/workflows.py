from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from uuid import UUID
import json

from api.database import get_db
from api.dependencies import get_tenant_id
from api.schemas import WorkflowCreate

router = APIRouter()


@router.post("/")
async def create_workflow(
    data: WorkflowCreate,
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db)
):

    query = text("""
        INSERT INTO workflows (empresa_id, name, trigger_event, actions)
        VALUES (:empresa_id, :name, :trigger_event, :actions)
        RETURNING id
    """)

    result = await db.execute(query, {
        "empresa_id": tenant_id,
        "name": data.name,
        "trigger_event": data.trigger_event,
        "actions": json.dumps(data.actions)
    })

    await db.commit()

    workflow = result.fetchone()

    return {
        "workflow_id": str(workflow.id)
    }