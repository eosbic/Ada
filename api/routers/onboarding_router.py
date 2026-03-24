"""
Onboarding Router — Endpoint para configuración inicial + Company DNA.
Solo para admin. Flujo conversacional paso a paso.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
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


@router.get("/dna/{empresa_id}")
async def get_company_dna(empresa_id: str):
    """Retorna el DNA completo de la empresa."""
    from api.services.dna_loader import load_company_dna
    dna = load_company_dna(empresa_id)
    if not dna:
        raise HTTPException(status_code=404, detail="Perfil de empresa no encontrado")
    return dna


@router.post("/dna/update")
async def update_company_dna(data: dict):
    """Actualiza campos específicos del DNA de la empresa."""
    empresa_id = data.get("empresa_id")
    if not empresa_id:
        raise HTTPException(status_code=400, detail="empresa_id es requerido")

    from api.services.dna_loader import update_dna_field
    updated = []
    for field, value in data.items():
        if field == "empresa_id":
            continue
        if update_dna_field(empresa_id, field, value):
            updated.append(field)

    return {"updated_fields": updated, "empresa_id": empresa_id}


@router.post("/dna/generate-configs")
async def generate_configs(data: dict):
    """Genera agent_configs basados en el DNA actual."""
    empresa_id = data.get("empresa_id")
    if not empresa_id:
        raise HTTPException(status_code=400, detail="empresa_id es requerido")

    from api.services.dna_generator import generate_agent_configs
    configs = await generate_agent_configs(empresa_id)
    return {"empresa_id": empresa_id, "agent_configs": configs}


@router.post("/dna/analyze-web")
async def analyze_web(data: dict):
    """Scrapea y analiza el sitio web de la empresa."""
    empresa_id = data.get("empresa_id")
    url = data.get("url")
    if not empresa_id or not url:
        raise HTTPException(status_code=400, detail="empresa_id y url son requeridos")

    from api.services.dna_generator import scrape_and_analyze_web
    result = await scrape_and_analyze_web(empresa_id, url)
    return result


@router.post("/dna/analyze-competitors")
async def analyze_competitors_endpoint(data: dict):
    """Analiza competidores de la empresa."""
    empresa_id = data.get("empresa_id")
    competitors = data.get("competitors", [])
    if not empresa_id or not competitors:
        raise HTTPException(status_code=400, detail="empresa_id y competitors son requeridos")

    from api.services.dna_generator import analyze_competitors
    result = await analyze_competitors(empresa_id, competitors)
    return {"empresa_id": empresa_id, "competitors": result}


@router.post("/apps/setup")
async def setup_app_connections(data: dict, db: AsyncSession = Depends(get_db)):
    """Configura qué provider usa la empresa para cada servicio."""
    empresa_id = data.get("empresa_id")
    suite = data.get("suite", "google")
    pm = data.get("pm")

    if not empresa_id:
        raise HTTPException(status_code=400, detail="empresa_id es requerido")

    configs = []
    for service in ["email", "calendar", "drive"]:
        configs.append({"empresa_id": empresa_id, "service": service, "provider": suite})
    if pm:
        configs.append({"empresa_id": empresa_id, "service": "pm", "provider": pm})

    for cfg in configs:
        await db.execute(
            text("""
                INSERT INTO tenant_app_config (empresa_id, service, provider)
                VALUES (:empresa_id, :service, :provider)
                ON CONFLICT (empresa_id, service)
                DO UPDATE SET provider = :provider
            """),
            cfg,
        )
    await db.commit()

    from api.services.dna_loader import update_dna_field
    update_dna_field(empresa_id, "productivity_suite", suite)
    if pm:
        update_dna_field(empresa_id, "pm_tool", pm)

    return {"empresa_id": empresa_id, "configs": configs}