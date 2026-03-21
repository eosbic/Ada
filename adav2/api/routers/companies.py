from fastapi import APIRouter, HTTPException
from sqlalchemy import text
from api.database import engine
from api.schemas import EmpresaCreate, EmpresaResponse


from api.database import get_db
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Depends
router = APIRouter()


@router.post("/", response_model=EmpresaResponse)
async def crear_empresa(data: EmpresaCreate):

    query = text("""
        INSERT INTO empresas (nombre, sector)
        VALUES (:nombre, :sector)
        RETURNING id, nombre, sector, created_at
    """)

    try:
        async with engine.begin() as conn:
            result = await conn.execute(query, {
                "nombre": data.nombre,
                "sector": data.sector
            })
            row = result.fetchone()

        if not row:
            raise HTTPException(status_code=400, detail="No se pudo crear empresa")

        return EmpresaResponse(
            id=row.id,
            nombre=row.nombre,
            sector=row.sector,
            created_at=row.created_at
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/onboarding-status/{empresa_id}")
async def check_onboarding(empresa_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        text("SELECT company_name FROM ada_company_profile WHERE empresa_id = :eid"),
        {"eid": empresa_id}
    )
    row = result.fetchone()
    if row:
        return {"completed": True, "company_name": row.company_name}
    return {"completed": False}