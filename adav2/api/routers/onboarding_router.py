"""
Onboarding Router — Endpoint para configuración inicial.
Solo para admin. Flujo conversacional paso a paso.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from api.database import get_db
from api.agents.onboarding_agent import process_onboarding

router = APIRouter()


@router.post("/onboarding")
async def onboarding(data: dict, db: AsyncSession = Depends(get_db)):
    """
    Flujo de onboarding conversacional.

    Primera llamada: solo empresa_id y user_id (sin response)
    Siguientes: empresa_id + user_id + response (respuesta del admin)

    Ejemplo primera llamada:
    {"empresa_id": "xxx", "user_id": "xxx", "user_name": "William"}

    Ejemplo siguientes:
    {"empresa_id": "xxx", "user_id": "xxx", "user_name": "William", "response": "Ada"}
    """

    empresa_id = data.get("empresa_id")
    user_id = data.get("user_id")
    user_name = data.get("user_name", "")
    user_response = data.get("response", "")

    if not empresa_id or not user_id:
        return {"error": "empresa_id y user_id son requeridos"}

    result = await process_onboarding(
        db=db,
        empresa_id=empresa_id,
        user_id=user_id,
        user_name=user_name,
        user_response=user_response,
    )

    return result