"""
Admin Auth — Autenticacion 2FA (email + OTP) para admin portal EOS IA.
"""

import os
import secrets
from datetime import datetime, timedelta

import bcrypt
from jose import jwt
from fastapi import APIRouter, Request, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy import text as sql_text
from api.database import AsyncSessionLocal


router = APIRouter()

ADMIN_JWT_SECRET = os.getenv("ADMIN_JWT_SECRET", os.getenv("JWT_SECRET_KEY", ""))
ADMIN_JWT_ALGORITHM = "HS256"
ADMIN_JWT_EXPIRATION_HOURS = 8
RESEND_API_KEY = os.getenv("RESEND_API_KEY")

MAX_FAILED_ATTEMPTS = 5
LOCKOUT_MINUTES = 30


# ─── Helpers ────────────────────────────────────────────


def hash_password(password: str) -> str:
    """Hash password con bcrypt."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    """Verifica password contra hash bcrypt."""
    return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))


def generate_otp() -> str:
    """Genera codigo OTP de 6 digitos."""
    return f"{secrets.randbelow(1000000):06d}"


def create_admin_token(admin_id: str, email: str, role: str) -> str:
    """Crea JWT para admin portal."""
    payload = {
        "admin_id": admin_id,
        "email": email,
        "role": role,
        "exp": datetime.utcnow() + timedelta(hours=ADMIN_JWT_EXPIRATION_HOURS),
        "iat": datetime.utcnow(),
        "type": "admin",
    }
    return jwt.encode(payload, ADMIN_JWT_SECRET, algorithm=ADMIN_JWT_ALGORITHM)


def decode_admin_token(token: str) -> dict:
    """Decodifica y valida JWT admin."""
    try:
        return jwt.decode(token, ADMIN_JWT_SECRET, algorithms=[ADMIN_JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expirado")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Token invalido")


def send_otp_email(email: str, otp_code: str, nombre: str) -> None:
    """Envia OTP via Resend API. Sin key, print en consola."""
    message = (
        f"Hola {nombre},\n\n"
        f"Tu codigo de verificacion para Ada Admin es: {otp_code}\n\n"
        f"Este codigo expira en 10 minutos.\n"
        f"Si no solicitaste este acceso, ignora este email."
    )

    if RESEND_API_KEY:
        try:
            import httpx
            httpx.post(
                "https://api.resend.com/emails",
                headers={
                    "Authorization": f"Bearer {RESEND_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "from": "Ada Admin <admin@notifications.ada.ai>",
                    "to": [email],
                    "subject": f"Ada Admin: Codigo de verificacion {otp_code}",
                    "text": message,
                },
                timeout=10,
            )
            print(f"ADMIN AUTH: OTP enviado a {email}")
        except Exception as e:
            print(f"ADMIN AUTH: Error enviando OTP email: {e}")
    else:
        print(f"ADMIN AUTH (dev mode): OTP para {email} = {otp_code}")


# ─── Dependency ─────────────────────────────────────────


async def get_current_admin(request: Request) -> dict:
    """Dependency: extrae y valida JWT admin del header Authorization."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authorization header requerido")

    token = auth_header.replace("Bearer ", "")
    payload = decode_admin_token(token)

    admin_id = payload.get("admin_id")
    if not admin_id:
        raise HTTPException(status_code=401, detail="Token invalido")

    # Verificar que admin sigue activo
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            sql_text("SELECT id, email, nombre, role, is_active FROM admin_users WHERE id = :id"),
            {"id": admin_id},
        )
        admin = result.fetchone()

    if not admin or not admin.is_active:
        raise HTTPException(status_code=401, detail="Admin no encontrado o desactivado")

    return {
        "admin_id": str(admin.id),
        "email": admin.email,
        "nombre": admin.nombre,
        "role": admin.role,
    }


# ─── Request models ────────────────────────────────────


class LoginRequest(BaseModel):
    email: str
    password: str


class VerifyOTPRequest(BaseModel):
    email: str
    otp_code: str


class CreateAdminRequest(BaseModel):
    email: str
    nombre: str
    password: str
    role: str = "viewer"


# ─── Endpoints ──────────────────────────────────────────


@router.post("/login")
async def login(req: LoginRequest, request: Request):
    """Paso 1 de 2FA: valida credenciales y envia OTP por email."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            sql_text("""
                SELECT id, email, nombre, password_hash, role, is_active,
                       failed_attempts, locked_until
                FROM admin_users WHERE email = :email
            """),
            {"email": req.email.strip().lower()},
        )
        admin = result.fetchone()

    if not admin:
        raise HTTPException(status_code=401, detail="Credenciales invalidas")

    if not admin.is_active:
        raise HTTPException(status_code=403, detail="Cuenta desactivada")

    # Lockout check
    if admin.locked_until and admin.locked_until > datetime.utcnow():
        remaining = int((admin.locked_until - datetime.utcnow()).total_seconds() // 60)
        raise HTTPException(
            status_code=429,
            detail=f"Cuenta bloqueada. Intenta en {remaining} minutos.",
        )

    if not verify_password(req.password, admin.password_hash):
        # Incrementar intentos fallidos
        async with AsyncSessionLocal() as db:
            new_attempts = (admin.failed_attempts or 0) + 1
            locked_until = None
            if new_attempts >= MAX_FAILED_ATTEMPTS:
                locked_until = datetime.utcnow() + timedelta(minutes=LOCKOUT_MINUTES)

            await db.execute(
                sql_text("""
                    UPDATE admin_users
                    SET failed_attempts = :attempts, locked_until = :locked
                    WHERE id = :id
                """),
                {"attempts": new_attempts, "locked": locked_until, "id": admin.id},
            )
            await db.commit()

        raise HTTPException(status_code=401, detail="Credenciales invalidas")

    # Generar OTP
    otp_code = generate_otp()
    ip_address = request.client.host if request.client else "unknown"

    async with AsyncSessionLocal() as db:
        # Invalidar OTPs anteriores
        await db.execute(
            sql_text("UPDATE admin_otp_codes SET used = TRUE WHERE admin_user_id = :id AND used = FALSE"),
            {"id": admin.id},
        )

        # Crear nuevo OTP
        await db.execute(
            sql_text("""
                INSERT INTO admin_otp_codes (admin_user_id, code, expires_at, ip_address)
                VALUES (:id, :code, :expires, :ip)
            """),
            {
                "id": admin.id,
                "code": otp_code,
                "expires": datetime.utcnow() + timedelta(minutes=10),
                "ip": ip_address,
            },
        )

        # Reset failed attempts
        await db.execute(
            sql_text("UPDATE admin_users SET failed_attempts = 0, locked_until = NULL WHERE id = :id"),
            {"id": admin.id},
        )
        await db.commit()

    send_otp_email(admin.email, otp_code, admin.nombre)

    # Mask email
    parts = admin.email.split("@")
    masked = parts[0][:2] + "***@" + parts[1] if len(parts) == 2 else "***"

    return {"otp_sent": True, "email_masked": masked}


@router.post("/verify-otp")
async def verify_otp(req: VerifyOTPRequest, request: Request):
    """Paso 2 de 2FA: verifica OTP y retorna JWT admin."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            sql_text("SELECT id, email, nombre, role FROM admin_users WHERE email = :email AND is_active = TRUE"),
            {"email": req.email.strip().lower()},
        )
        admin = result.fetchone()

    if not admin:
        raise HTTPException(status_code=401, detail="Admin no encontrado")

    # Buscar OTP valido
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            sql_text("""
                SELECT id, code FROM admin_otp_codes
                WHERE admin_user_id = :id
                AND used = FALSE
                AND expires_at > NOW()
                ORDER BY created_at DESC
                LIMIT 1
            """),
            {"id": admin.id},
        )
        otp_row = result.fetchone()

    if not otp_row:
        raise HTTPException(status_code=401, detail="OTP expirado o no encontrado")

    # Comparacion timing-safe
    if not secrets.compare_digest(otp_row.code, req.otp_code.strip()):
        raise HTTPException(status_code=401, detail="Codigo OTP incorrecto")

    ip_address = request.client.host if request.client else "unknown"

    # Marcar OTP como usado, actualizar last_login, registrar audit
    async with AsyncSessionLocal() as db:
        await db.execute(
            sql_text("UPDATE admin_otp_codes SET used = TRUE WHERE id = :id"),
            {"id": otp_row.id},
        )
        await db.execute(
            sql_text("UPDATE admin_users SET last_login = NOW() WHERE id = :id"),
            {"id": admin.id},
        )
        await db.execute(
            sql_text("""
                INSERT INTO admin_audit_log (admin_user_id, action, target_type, target_id, details, ip_address)
                VALUES (:aid, 'login', 'admin_user', :aid, :details, :ip)
            """),
            {
                "aid": admin.id,
                "details": '{"method": "2fa_otp"}',
                "ip": ip_address,
            },
        )
        await db.commit()

    token = create_admin_token(str(admin.id), admin.email, admin.role)

    return {
        "token": token,
        "admin": {
            "id": str(admin.id),
            "email": admin.email,
            "nombre": admin.nombre,
            "role": admin.role,
        },
    }


@router.get("/me")
async def me(admin: dict = Depends(get_current_admin)):
    """Retorna datos del admin autenticado."""
    return admin


@router.post("/create-admin")
async def create_admin(req: CreateAdminRequest, admin: dict = Depends(get_current_admin)):
    """Crea un nuevo admin. Solo superadmin."""
    if admin["role"] != "superadmin":
        raise HTTPException(status_code=403, detail="Solo superadmin puede crear admins")

    if req.role not in ("superadmin", "admin", "viewer"):
        raise HTTPException(status_code=400, detail="Roles validos: superadmin, admin, viewer")

    password_hash = hash_password(req.password)

    try:
        async with AsyncSessionLocal() as db:
            await db.execute(
                sql_text("""
                    INSERT INTO admin_users (email, nombre, password_hash, role)
                    VALUES (:email, :nombre, :hash, :role)
                """),
                {
                    "email": req.email.strip().lower(),
                    "nombre": req.nombre,
                    "hash": password_hash,
                    "role": req.role,
                },
            )
            await db.commit()

        return {"created": True, "email": req.email, "role": req.role}

    except Exception as e:
        if "unique" in str(e).lower() or "duplicate" in str(e).lower():
            raise HTTPException(status_code=409, detail="Email ya registrado")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/seed-superadmin")
async def seed_superadmin(req: CreateAdminRequest):
    """Crea primer superadmin. Solo funciona si NO existe ningun admin."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(sql_text("SELECT COUNT(*) FROM admin_users"))
        count = result.scalar()

    if count > 0:
        raise HTTPException(status_code=403, detail="Ya existen admins. Endpoint desactivado.")

    password_hash = hash_password(req.password)

    async with AsyncSessionLocal() as db:
        await db.execute(
            sql_text("""
                INSERT INTO admin_users (email, nombre, password_hash, role)
                VALUES (:email, :nombre, :hash, 'superadmin')
            """),
            {
                "email": req.email.strip().lower(),
                "nombre": req.nombre,
                "hash": password_hash,
            },
        )
        await db.commit()

    return {"created": True, "email": req.email, "role": "superadmin"}
