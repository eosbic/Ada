from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy import text
from api.database import engine
from pydantic import BaseModel, EmailStr
from uuid import UUID
from datetime import datetime

from api.dependencies import get_current_user
from api.security import hash_password


from sqlalchemy.ext.asyncio import AsyncSession
from api.database import get_db


router = APIRouter()


class UsuarioCreate(BaseModel):
    empresa_id: UUID
    email: EmailStr
    nombre: str
    password: str


class UsuarioResponse(BaseModel):
    id: UUID
    empresa_id: UUID
    email: str
    nombre: str
    created_at: datetime


# =========================
# CREAR USUARIO
# =========================
@router.post("/", response_model=UsuarioResponse)
async def crear_usuario(data: UsuarioCreate):

    hashed_password = hash_password(data.password)

    async with engine.begin() as conn:
        result = await conn.execute(
            text("""
                INSERT INTO usuarios (empresa_id, email, nombre, password)
                VALUES (:empresa_id, :email, :nombre, :password)
                RETURNING id, empresa_id, email, nombre, created_at
            """),
            {
                "empresa_id": data.empresa_id,
                "email": data.email,
                "nombre": data.nombre,
                "password": hashed_password
            }
        )

        row = result.fetchone()

    return UsuarioResponse(
        id=row.id,
        empresa_id=row.empresa_id,
        email=row.email,
        nombre=row.nombre,
        created_at=row.created_at
    )


# =========================
# LISTAR USUARIOS (TENANT)
# =========================
@router.get("/", response_model=list[UsuarioResponse])
async def listar_usuarios(
    current_user: dict = Depends(get_current_user)
):

    tenant_id = current_user["empresa_id"]

    async with engine.begin() as conn:
        result = await conn.execute(
            text("""
                SELECT id, empresa_id, email, nombre, created_at
                FROM usuarios
                WHERE empresa_id = :empresa_id
                ORDER BY created_at DESC
            """),
            {"empresa_id": tenant_id}
        )

        rows = result.fetchall()

    return [
        UsuarioResponse(
            id=row.id,
            empresa_id=row.empresa_id,
            email=row.email,
            nombre=row.nombre,
            created_at=row.created_at
        )
        for row in rows
    ]


@router.get("/team/members")
async def list_team_members(empresa_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        text("""
            SELECT u.id, u.email, u.nombre, u.rol, u.telegram_id, u.created_at
            FROM usuarios u
            WHERE u.empresa_id = :eid
            ORDER BY u.created_at
        """),
        {"eid": empresa_id},
    )
    rows = result.fetchall()

    members = []
    for row in rows:
        members.append({
            "user_id": str(row.id),
            "display_name": row.nombre or row.email,
            "email": row.email,
            "role": row.rol or "member",
            "department": "",
            "is_active": True,
            "telegram_linked": bool(row.telegram_id),
            "created_at": str(row.created_at),
        })

    return {"empresa_id": empresa_id, "members": members, "total": len(members)}


@router.patch("/team/members/{user_id}")
async def update_team_member(user_id: str, data: dict, db: AsyncSession = Depends(get_db)):
    empresa_id = data.get("empresa_id")
    admin_user_id = data.get("admin_user_id")
    role = data.get("role", "")
    department = data.get("department", "")

    # Verificar que es admin
    admin = await db.execute(
        text("SELECT rol FROM usuarios WHERE id = :uid AND empresa_id = :eid"),
        {"uid": admin_user_id, "eid": empresa_id},
    )
    admin_row = admin.fetchone()
    if not admin_row or admin_row.rol != "admin":
        raise HTTPException(status_code=403, detail="Solo el administrador puede editar miembros")

    await db.execute(
        text("UPDATE usuarios SET rol = :rol WHERE id = :uid AND empresa_id = :eid"),
        {"rol": role, "uid": user_id, "eid": empresa_id},
    )
    await db.commit()

    return {"status": "updated", "user_id": user_id, "role": role}


# =========================
# PREFERENCIAS DE USUARIO
# =========================
@router.get("/preferences")
async def get_preferences(current_user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Obtiene preferencias del usuario autenticado."""
    user_id = current_user["user_id"]
    result = await db.execute(
        text("SELECT preferences FROM user_preferences WHERE user_id = :uid"),
        {"uid": user_id},
    )
    row = result.fetchone()
    prefs = row.preferences if row and row.preferences else {}
    # Defaults
    defaults = {
        "morning_brief_enabled": False,
        "morning_brief_hour": 7,
        "morning_brief_timezone": "America/Bogota",
    }
    merged = {**defaults, **(prefs if isinstance(prefs, dict) else {})}
    return {"user_id": user_id, "preferences": merged}


@router.put("/preferences")
async def update_preferences(data: dict, current_user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Actualiza preferencias del usuario autenticado (merge parcial)."""
    import json as _json
    user_id = current_user["user_id"]
    new_prefs = data.get("preferences", {})
    if not isinstance(new_prefs, dict):
        raise HTTPException(status_code=400, detail="preferences debe ser un objeto JSON")

    # Validar campos de morning brief si vienen
    if "morning_brief_hour" in new_prefs:
        h = new_prefs["morning_brief_hour"]
        if not isinstance(h, int) or h < 0 or h > 23:
            raise HTTPException(status_code=400, detail="morning_brief_hour debe ser entero 0-23")
    if "morning_brief_timezone" in new_prefs:
        tz = new_prefs["morning_brief_timezone"]
        try:
            from zoneinfo import ZoneInfo
            ZoneInfo(tz)
        except Exception:
            raise HTTPException(status_code=400, detail=f"Timezone invalido: {tz}")

    # UPSERT con merge de JSONB
    await db.execute(
        text("""
            INSERT INTO user_preferences (user_id, preferences, updated_at)
            VALUES (:uid, :prefs::jsonb, NOW())
            ON CONFLICT (user_id)
            DO UPDATE SET
                preferences = user_preferences.preferences || :prefs::jsonb,
                updated_at = NOW()
        """),
        {"uid": user_id, "prefs": _json.dumps(new_prefs, ensure_ascii=False)},
    )
    await db.commit()

    # Re-read merged
    result = await db.execute(
        text("SELECT preferences FROM user_preferences WHERE user_id = :uid"),
        {"uid": user_id},
    )
    row = result.fetchone()
    return {"status": "updated", "preferences": row.preferences if row else new_prefs}