"""
Google OAuth2 endpoints por empresa (multi-tenant).
Incluye Gmail, Calendar y Drive.
"""

import os
import json
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from cryptography.fernet import Fernet

from api.database import get_db

router = APIRouter()

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
FERNET_KEY = os.getenv("FERNET_KEY")
API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")
MICROSOFT_CLIENT_ID = os.getenv("MICROSOFT_CLIENT_ID")
MICROSOFT_CLIENT_SECRET = os.getenv("MICROSOFT_CLIENT_SECRET")
MICROSOFT_TENANT_ID = os.getenv("MICROSOFT_TENANT_ID", "common")

M365_SCOPES = [
    "offline_access",
    "Calendars.ReadWrite",
    "Mail.ReadWrite",
    "Mail.Send",
    "Files.Read.All",
]

SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]


@router.get("/connect/{service}/{empresa_id}")
async def get_oauth_url(service: str, empresa_id: str):
    if service not in ("gmail", "calendar", "drive", "google"):
        raise HTTPException(status_code=400, detail="Servicio no valido")

    state = f"{empresa_id}|{service}"

    import urllib.parse
    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": f"{API_BASE_URL}/oauth/callback",
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }

    url = f"https://accounts.google.com/o/oauth2/v2/auth?{urllib.parse.urlencode(params)}"
    return {"auth_url": url, "empresa_id": empresa_id, "service": service}


@router.get("/callback")
async def oauth_callback(code: str, state: str, db: AsyncSession = Depends(get_db)):
    import httpx

    try:
        parts = state.split("|")
        empresa_id = parts[0].strip()
        service = parts[1].split(",")[0].split('"')[0].strip()
    except Exception:
        raise HTTPException(status_code=400, detail="State invalido")

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": code,
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "redirect_uri": f"{API_BASE_URL}/oauth/callback",
                "grant_type": "authorization_code",
            },
        )

    if resp.status_code != 200:
        raise HTTPException(status_code=400, detail=f"Error obteniendo tokens: {resp.text}")

    token_data = resp.json()
    access_token = token_data.get("access_token")
    refresh_token = token_data.get("refresh_token")
    expires_in = token_data.get("expires_in", 3600)

    if not refresh_token:
        raise HTTPException(status_code=400, detail="No se obtuvo refresh_token")

    fernet = Fernet(FERNET_KEY.encode())
    creds = {
        "client_id": GOOGLE_CLIENT_ID,
        "client_secret": GOOGLE_CLIENT_SECRET,
        "access_token": access_token,
    }
    encrypted_creds = fernet.encrypt(json.dumps(creds).encode())
    encrypted_refresh = fernet.encrypt(refresh_token.encode())
    expiry = datetime.utcnow() + timedelta(seconds=expires_in)

    if service == "google":
        services_to_save = ["gmail", "google_calendar", "google_drive"]
    elif service == "gmail":
        services_to_save = ["gmail"]
    elif service == "calendar":
        services_to_save = ["google_calendar"]
    elif service == "drive":
        services_to_save = ["google_drive"]
    else:
        services_to_save = []

    for svc in services_to_save:
        await db.execute(
            text(
                """
                INSERT INTO tenant_credentials
                    (empresa_id, provider, encrypted_data,
                     oauth2_refresh_token_encrypted, oauth2_expiry, is_active)
                VALUES (:empresa_id, :provider, :creds, :refresh, :expiry, TRUE)
                ON CONFLICT (empresa_id, provider)
                DO UPDATE SET
                    encrypted_data = EXCLUDED.encrypted_data,
                    oauth2_refresh_token_encrypted = EXCLUDED.oauth2_refresh_token_encrypted,
                    oauth2_expiry = EXCLUDED.oauth2_expiry,
                    is_active = TRUE
                """
            ),
            {
                "empresa_id": empresa_id,
                "provider": svc,
                "creds": encrypted_creds.decode(),
                "refresh": encrypted_refresh.decode(),
                "expiry": expiry,
            },
        )

    await db.commit()

    try:
        from api.services.provider_router import clear_cache
        clear_cache(empresa_id)
    except Exception:
        pass

    return {
        "status": "connected",
        "empresa_id": empresa_id,
        "services": services_to_save,
        "message": "Servicios de Google conectados exitosamente.",
    }


@router.get("/microsoft/connect/{service}/{empresa_id}")
async def get_microsoft_oauth_url(service: str, empresa_id: str):
    """Genera URL de autorización Azure AD para Microsoft 365."""
    valid_services = ("outlook", "outlook_calendar", "outlook_email", "onedrive", "microsoft365")
    if service not in valid_services:
        raise HTTPException(status_code=400, detail=f"Servicio no válido. Usa: {', '.join(valid_services)}")

    import urllib.parse
    state = f"{empresa_id}|{service}"
    params = {
        "client_id": MICROSOFT_CLIENT_ID,
        "redirect_uri": f"{API_BASE_URL}/oauth/microsoft/callback",
        "response_type": "code",
        "scope": " ".join(M365_SCOPES),
        "state": state,
        "prompt": "consent",
    }

    url = f"https://login.microsoftonline.com/{MICROSOFT_TENANT_ID}/oauth2/v2.0/authorize?{urllib.parse.urlencode(params)}"
    return {"auth_url": url, "empresa_id": empresa_id, "service": service}


@router.get("/microsoft/callback")
async def microsoft_oauth_callback(code: str, state: str, db: AsyncSession = Depends(get_db)):
    """Callback OAuth2 Microsoft 365 — intercambia code por tokens."""
    import httpx

    try:
        parts = state.split("|")
        empresa_id = parts[0].strip()
        service = parts[1].strip()
    except Exception:
        raise HTTPException(status_code=400, detail="State inválido")

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"https://login.microsoftonline.com/{MICROSOFT_TENANT_ID}/oauth2/v2.0/token",
            data={
                "code": code,
                "client_id": MICROSOFT_CLIENT_ID,
                "client_secret": MICROSOFT_CLIENT_SECRET,
                "redirect_uri": f"{API_BASE_URL}/oauth/microsoft/callback",
                "grant_type": "authorization_code",
                "scope": " ".join(M365_SCOPES),
            },
        )

    if resp.status_code != 200:
        raise HTTPException(status_code=400, detail=f"Error obteniendo tokens M365: {resp.text}")

    token_data = resp.json()
    access_token = token_data.get("access_token")
    refresh_token = token_data.get("refresh_token")
    expires_in = token_data.get("expires_in", 3600)

    if not refresh_token:
        raise HTTPException(status_code=400, detail="No se obtuvo refresh_token de Microsoft")

    fernet = Fernet(FERNET_KEY.encode())
    creds = {
        "client_id": MICROSOFT_CLIENT_ID,
        "client_secret": MICROSOFT_CLIENT_SECRET,
        "tenant_id": MICROSOFT_TENANT_ID,
        "access_token": access_token,
    }
    encrypted_creds = fernet.encrypt(json.dumps(creds).encode())
    encrypted_refresh = fernet.encrypt(refresh_token.encode())
    expiry = datetime.utcnow() + timedelta(seconds=expires_in)

    # Determinar qué providers guardar
    if service in ("microsoft365", "outlook"):
        services_to_save = ["outlook_email", "outlook_calendar", "onedrive"]
    elif service == "outlook_calendar":
        services_to_save = ["outlook_calendar"]
    elif service == "outlook_email":
        services_to_save = ["outlook_email"]
    elif service == "onedrive":
        services_to_save = ["onedrive"]
    else:
        services_to_save = []

    for svc in services_to_save:
        await db.execute(
            text(
                """
                INSERT INTO tenant_credentials
                    (empresa_id, provider, encrypted_data,
                     oauth2_refresh_token_encrypted, oauth2_expiry, is_active)
                VALUES (:empresa_id, :provider, :creds, :refresh, :expiry, TRUE)
                ON CONFLICT (empresa_id, provider)
                DO UPDATE SET
                    encrypted_data = EXCLUDED.encrypted_data,
                    oauth2_refresh_token_encrypted = EXCLUDED.oauth2_refresh_token_encrypted,
                    oauth2_expiry = EXCLUDED.oauth2_expiry,
                    is_active = TRUE
                """
            ),
            {
                "empresa_id": empresa_id,
                "provider": svc,
                "creds": encrypted_creds.decode(),
                "refresh": encrypted_refresh.decode(),
                "expiry": expiry,
            },
        )

    await db.commit()

    try:
        from api.services.provider_router import clear_cache
        clear_cache(empresa_id)
    except Exception:
        pass

    return {
        "status": "connected",
        "empresa_id": empresa_id,
        "services": services_to_save,
        "message": "Servicios de Microsoft 365 conectados exitosamente.",
    }


@router.get("/status/{empresa_id}")
async def check_connection_status(empresa_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        text(
            """
            SELECT provider, is_active, oauth2_expiry
            FROM tenant_credentials
            WHERE empresa_id = :empresa_id
            """
        ),
        {"empresa_id": empresa_id},
    )
    rows = result.fetchall()

    services = {}
    for row in rows:
        services[row.provider] = {
            "connected": row.is_active,
            "expires": str(row.oauth2_expiry) if row.oauth2_expiry else None,
        }

    return {
        "empresa_id": empresa_id,
        "gmail": services.get("gmail", {"connected": False}),
        "google_calendar": services.get("google_calendar", {"connected": False}),
        "google_drive": services.get("google_drive", {"connected": False}),
        "outlook_email": services.get("outlook_email", {"connected": False}),
        "outlook_calendar": services.get("outlook_calendar", {"connected": False}),
        "onedrive": services.get("onedrive", {"connected": False}),
    }


@router.delete("/disconnect/{service}/{empresa_id}")
async def disconnect_service(service: str, empresa_id: str, db: AsyncSession = Depends(get_db)):
    await db.execute(
        text(
            """
            UPDATE tenant_credentials
            SET is_active = FALSE
            WHERE empresa_id = :empresa_id AND provider = :provider
            """
        ),
        {"empresa_id": empresa_id, "provider": service},
    )
    await db.commit()

    return {"status": "disconnected", "service": service, "empresa_id": empresa_id}


@router.post("/connect-service")
async def connect_service(data: dict, db: AsyncSession = Depends(get_db)):
    empresa_id = data.get("empresa_id")
    service = data.get("service", "")
    credentials = data.get("credentials", {})

    if not empresa_id or not service:
        raise HTTPException(status_code=400, detail="empresa_id y service son requeridos")

    if service not in ("notion", "plane"):
        raise HTTPException(status_code=400, detail="Servicio no valido. Usa: notion, plane")

    api_key = credentials.get("api_key", "")
    if not api_key:
        raise HTTPException(status_code=400, detail="api_key es requerido")

    fernet = Fernet(FERNET_KEY.encode())
    encrypted = fernet.encrypt(json.dumps(credentials).encode())

    await db.execute(
        text(
            """
            INSERT INTO tenant_credentials
                (empresa_id, provider, encrypted_data, is_active)
            VALUES (:empresa_id, :provider, :creds, TRUE)
            ON CONFLICT (empresa_id, provider)
            DO UPDATE SET
                encrypted_data = EXCLUDED.encrypted_data,
                is_active = TRUE
            """
        ),
        {
            "empresa_id": empresa_id,
            "provider": service,
            "creds": encrypted.decode(),
        },
    )
    await db.commit()

    return {
        "status": "connected",
        "empresa_id": empresa_id,
        "service": service,
        "message": f"{service.capitalize()} conectado exitosamente.",
    }


@router.get("/connections/{empresa_id}")
async def list_connections(empresa_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        text("SELECT provider, is_active, created_at FROM tenant_credentials WHERE empresa_id = :eid"),
        {"eid": empresa_id},
    )
    rows = result.fetchall()

    connections = {}
    for row in rows:
        connections[row.provider] = {"connected": row.is_active, "since": str(row.created_at)[:10]}

    for svc in ["gmail", "google_calendar", "google_drive", "outlook_email", "outlook_calendar", "onedrive", "notion", "plane"]:
        if svc not in connections:
            connections[svc] = {"connected": False}

    return {"empresa_id": empresa_id, "connections": connections}
