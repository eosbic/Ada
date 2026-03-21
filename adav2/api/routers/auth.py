from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from api.database import engine, get_db
from api.security import verify_password, create_access_token

router = APIRouter()


class LoginRequest(BaseModel):
    email: str
    password: str


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

        token = create_access_token({
            "user_id": str(user.id),
            "empresa_id": str(user.empresa_id)
        })

    return {"access_token": token, "token_type": "bearer"}


@router.get("/telegram/{telegram_id}")
async def get_user_by_telegram(telegram_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        text("SELECT id, empresa_id FROM usuarios WHERE telegram_id = :tid"),
        {"tid": telegram_id}
    )
    row = result.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="No registrado")
    return {"user_id": str(row.id), "empresa_id": str(row.empresa_id)}


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