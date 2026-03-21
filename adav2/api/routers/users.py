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