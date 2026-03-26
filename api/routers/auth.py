from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from api.database import engine, get_db
from api.security import (
    verify_password, create_access_token, create_refresh_token, decode_token
)

router = APIRouter()


class LoginRequest(BaseModel):
    email: str
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


@router.post("/login")
async def login(data: LoginRequest):
    async with engine.begin() as conn:
        result = await conn.execute(
            text("""
                SELECT id, empresa_id, password
                FROM usuarios
                WHERE email = :email
            """),
            {"email": data.email}
        )

        user = result.fetchone()

        if not user:
            raise HTTPException(status_code=401, detail="Invalid credentials")

        if not verify_password(data.password, user.password):
            raise HTTPException(status_code=401, detail="Invalid credentials")

        payload = {
            "user_id": str(user.id),
            "empresa_id": str(user.empresa_id)
        }
        access_token = create_access_token(payload)
        refresh_token = create_refresh_token(payload)

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
    }


@router.post("/refresh")
async def refresh_access_token(data: RefreshRequest):
    """Renueva el access_token usando un refresh_token válido."""
    token_data = decode_token(data.refresh_token)

    if token_data.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    payload = {
        "user_id": token_data["user_id"],
        "empresa_id": token_data["empresa_id"],
    }
    new_access = create_access_token(payload)
    new_refresh = create_refresh_token(payload)

    return {
        "access_token": new_access,
        "refresh_token": new_refresh,
        "token_type": "bearer",
    }


@router.get("/telegram/{telegram_id}")
async def get_user_by_telegram(telegram_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        text("SELECT id, empresa_id, nombre FROM usuarios WHERE telegram_id = :tid"),
        {"tid": telegram_id}
    )
    row = result.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="No registrado")

    token = create_access_token({
        "user_id": str(row.id),
        "empresa_id": str(row.empresa_id)
    })

    return {
        "user_id": str(row.id),
        "empresa_id": str(row.empresa_id),
        "nombre": getattr(row, "nombre", ""),
        "access_token": token,
    }


@router.post("/link-telegram")
async def link_telegram(data: dict, db: AsyncSession = Depends(get_db)):
    email = data.get("email", "")
    telegram_id = data.get("telegram_id", "")

    result = await db.execute(
        text("SELECT id, nombre, empresa_id FROM usuarios WHERE email = :email"),
        {"email": email}
    )
    row = result.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Email no encontrado")

    await db.execute(
        text("UPDATE usuarios SET telegram_id = :tid WHERE id = :uid"),
        {"tid": telegram_id, "uid": row.id}
    )
    await db.commit()

    return {"user_id": str(row.id), "empresa_id": str(row.empresa_id), "nombre": row.nombre}
