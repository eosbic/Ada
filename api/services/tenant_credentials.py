"""
Tenant Credentials — Lee credenciales OAuth2 por empresa y por usuario.
Reemplaza os.getenv() por lectura de tenant_credentials.
Auto-refresh si el token expiró.
"""

import os
import json
from datetime import datetime, timedelta
from cryptography.fernet import Fernet
from api.database import sync_engine
from sqlalchemy import text as sql_text
import httpx


FERNET_KEY = os.getenv("FERNET_KEY")
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
MICROSOFT_CLIENT_ID = os.getenv("MICROSOFT_CLIENT_ID")
MICROSOFT_CLIENT_SECRET = os.getenv("MICROSOFT_CLIENT_SECRET")
MICROSOFT_TENANT_ID = os.getenv("MICROSOFT_TENANT_ID", "common")

# Servicios personales: cada usuario conecta los suyos
PERSONAL_SERVICES = {
    "gmail", "google_calendar", "google_contacts", "google_drive",
    "outlook_email", "outlook_calendar", "outlook_contacts", "onedrive",
}

# Servicios de empresa: una conexión para todos
COMPANY_SERVICES = {
    "google_shared_drive", "sharepoint",
    "notion", "plane", "asana", "monday", "trello", "clickup", "jira",
}


def get_google_credentials(empresa_id: str, service: str = "gmail", user_id: str = "") -> dict:
    """
    Obtiene credenciales de Google para una empresa/usuario.
    Lookup: primero user-specific, luego fallback empresa.
    """

    #Validar formato UUID
    import re
    uuid_pattern = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.I)
    if not uuid_pattern.match(empresa_id or ""):
        return {"error": "ID de empresa no válido"}
    if not FERNET_KEY:
        return {"error": "Sistema de credenciales no configurado"}

    fernet = Fernet(FERNET_KEY.encode())

    try:
        with sync_engine.connect() as conn:
            # 1. Verificar que la empresa existe
            empresa = conn.execute(
                sql_text("SELECT id, nombre FROM empresas WHERE id = :eid"),
                {"eid": empresa_id},
            ).fetchone()

            if not empresa:
                print(f"CREDENTIALS: Empresa {empresa_id} no existe en el sistema")
                return {"error": "Empresa no registrada en el sistema"}

            # 2. Buscar credenciales: primero personales, luego empresa
            row = None
            if user_id and service in PERSONAL_SERVICES:
                result = conn.execute(
                    sql_text("""
                        SELECT encrypted_data, oauth2_refresh_token_encrypted, oauth2_expiry
                        FROM tenant_credentials
                        WHERE empresa_id = :eid AND provider = :provider AND user_id = :uid AND is_active = TRUE
                    """),
                    {"eid": empresa_id, "provider": service, "uid": user_id},
                )
                row = result.fetchone()
                if row:
                    print(f"CREDENTIALS: Credenciales personales de user {user_id[:8]} para {service}")

            if not row:
                result = conn.execute(
                    sql_text("""
                        SELECT encrypted_data, oauth2_refresh_token_encrypted, oauth2_expiry
                        FROM tenant_credentials
                        WHERE empresa_id = :eid AND provider = :provider AND user_id IS NULL AND is_active = TRUE
                    """),
                    {"eid": empresa_id, "provider": service},
                )
                row = result.fetchone()
                if row:
                    print(f"CREDENTIALS: Credenciales de empresa para {service}")

        if not row:
            service_name = "Gmail" if service == "gmail" else "Google Calendar"
            print(f"CREDENTIALS: {empresa.nombre} no tiene {service_name} conectado")
            return {"error": f"{empresa.nombre} no tiene {service_name} conectado. El administrador debe vincularlo desde configuración."}

        # 3. Descifrar
        creds = json.loads(fernet.decrypt(row.encrypted_data.encode()).decode())
        refresh_token = fernet.decrypt(row.oauth2_refresh_token_encrypted.encode()).decode()
        creds["refresh_token"] = refresh_token

        # 4. Auto-refresh si expiró
        if row.oauth2_expiry and row.oauth2_expiry < datetime.utcnow() + timedelta(minutes=5):
            creds = _refresh_token(empresa_id, service, creds, refresh_token, fernet, user_id=user_id)

        print(f"CREDENTIALS: OK {service} para {empresa.nombre}")
        return creds

    except Exception as e:
        print(f"ERROR credentials {service}/{empresa_id}: {e}")
        return {"error": f"Error obteniendo credenciales: {str(e)}"}

def _refresh_token(empresa_id, service, creds, refresh_token, fernet, user_id: str = "") -> dict:
    """Refresh automático de OAuth2 token."""
    import requests

    resp = requests.post(
        "https://oauth2.googleapis.com/token",
        data={
            "client_id": creds["client_id"],
            "client_secret": creds["client_secret"],
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
    )

    if resp.status_code != 200:
        print(f"ERROR refresh {service}/{empresa_id}: {resp.text}")
        return creds

    token_data = resp.json()
    creds["access_token"] = token_data["access_token"]
    new_expiry = datetime.utcnow() + timedelta(seconds=token_data.get("expires_in", 3600))

    # Actualizar en DB
    try:
        encrypted_creds = fernet.encrypt(json.dumps(creds).encode())
        with sync_engine.connect() as conn:
            if user_id:
                conn.execute(
                    sql_text("""
                        UPDATE tenant_credentials
                        SET encrypted_data = :creds, oauth2_expiry = :expiry
                        WHERE empresa_id = :eid AND provider = :provider AND user_id = :uid
                    """),
                    {
                        "creds": encrypted_creds.decode(),
                        "expiry": new_expiry,
                        "eid": empresa_id,
                        "provider": service,
                        "uid": user_id,
                    },
                )
            else:
                conn.execute(
                    sql_text("""
                        UPDATE tenant_credentials
                        SET encrypted_data = :creds, oauth2_expiry = :expiry
                        WHERE empresa_id = :eid AND provider = :provider AND user_id IS NULL
                    """),
                    {
                        "creds": encrypted_creds.decode(),
                        "expiry": new_expiry,
                        "eid": empresa_id,
                        "provider": service,
                    },
                )
            conn.commit()
        print(f"CREDENTIALS: Refresh OK {service}/{empresa_id}")
    except Exception as e:
        print(f"ERROR saving refreshed token: {e}")

    return creds


def get_microsoft_credentials(empresa_id: str, service: str = "outlook_calendar", user_id: str = "") -> dict:
    """
    Obtiene credenciales de Microsoft 365 para una empresa/usuario.
    Lookup: primero user-specific, luego fallback empresa.
    """
    import re
    uuid_pattern = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.I)
    if not uuid_pattern.match(empresa_id or ""):
        return {"error": "ID de empresa no válido"}
    if not FERNET_KEY:
        return {"error": "Sistema de credenciales no configurado"}

    fernet = Fernet(FERNET_KEY.encode())

    try:
        with sync_engine.connect() as conn:
            empresa = conn.execute(
                sql_text("SELECT id, nombre FROM empresas WHERE id = :eid"),
                {"eid": empresa_id},
            ).fetchone()

            if not empresa:
                return {"error": "Empresa no registrada en el sistema"}

            # Buscar credenciales: primero personales, luego empresa
            row = None
            if user_id and service in PERSONAL_SERVICES:
                result = conn.execute(
                    sql_text("""
                        SELECT encrypted_data, oauth2_refresh_token_encrypted, oauth2_expiry
                        FROM tenant_credentials
                        WHERE empresa_id = :eid AND provider = :provider AND user_id = :uid AND is_active = TRUE
                    """),
                    {"eid": empresa_id, "provider": service, "uid": user_id},
                )
                row = result.fetchone()
                if row:
                    print(f"CREDENTIALS: Credenciales personales de user {user_id[:8]} para {service}")

            if not row:
                result = conn.execute(
                    sql_text("""
                        SELECT encrypted_data, oauth2_refresh_token_encrypted, oauth2_expiry
                        FROM tenant_credentials
                        WHERE empresa_id = :eid AND provider = :provider AND user_id IS NULL AND is_active = TRUE
                    """),
                    {"eid": empresa_id, "provider": service},
                )
                row = result.fetchone()
                if row:
                    print(f"CREDENTIALS: Credenciales de empresa para {service}")

        if not row:
            service_names = {
                "outlook_calendar": "Outlook Calendar",
                "outlook_email": "Outlook Email",
                "onedrive": "OneDrive",
                "outlook_contacts": "Outlook Contacts",
                "sharepoint": "SharePoint",
            }
            svc_name = service_names.get(service, service)
            return {"error": f"{empresa.nombre} no tiene {svc_name} conectado. El administrador debe vincularlo desde configuración."}

        # Descifrar
        creds = json.loads(fernet.decrypt(row.encrypted_data.encode()).decode())
        refresh_token = fernet.decrypt(row.oauth2_refresh_token_encrypted.encode()).decode()
        creds["refresh_token"] = refresh_token

        # Auto-refresh si expiró
        if row.oauth2_expiry and row.oauth2_expiry < datetime.utcnow() + timedelta(minutes=5):
            creds = _refresh_microsoft_token(empresa_id, service, creds, refresh_token, fernet, user_id=user_id)

        creds.setdefault("client_id", MICROSOFT_CLIENT_ID)
        creds.setdefault("client_secret", MICROSOFT_CLIENT_SECRET)
        creds.setdefault("tenant_id", MICROSOFT_TENANT_ID)

        print(f"CREDENTIALS: OK {service} (M365) para {empresa.nombre}")
        return creds

    except Exception as e:
        print(f"ERROR credentials M365 {service}/{empresa_id}: {e}")
        return {"error": f"Error obteniendo credenciales M365: {str(e)}"}


def _refresh_microsoft_token(empresa_id, service, creds, refresh_token, fernet, user_id: str = "") -> dict:
    """Refresh automático de OAuth2 token para Microsoft 365."""
    import requests

    tenant = creds.get("tenant_id", MICROSOFT_TENANT_ID) or MICROSOFT_TENANT_ID

    resp = requests.post(
        f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token",
        data={
            "client_id": creds.get("client_id", MICROSOFT_CLIENT_ID),
            "client_secret": creds.get("client_secret", MICROSOFT_CLIENT_SECRET),
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
            "scope": "https://graph.microsoft.com/.default offline_access",
        },
    )

    if resp.status_code != 200:
        print(f"ERROR M365 refresh {service}/{empresa_id}: {resp.text}")
        return creds

    token_data = resp.json()
    creds["access_token"] = token_data["access_token"]
    new_expiry = datetime.utcnow() + timedelta(seconds=token_data.get("expires_in", 3600))

    # Si Microsoft rota el refresh_token, guardar el nuevo
    new_refresh = token_data.get("refresh_token")
    if new_refresh:
        creds["refresh_token"] = new_refresh

    # Actualizar en DB
    try:
        creds_to_store = {k: v for k, v in creds.items() if k != "refresh_token"}
        encrypted_creds = fernet.encrypt(json.dumps(creds_to_store).encode())
        encrypted_refresh = fernet.encrypt(creds["refresh_token"].encode())

        with sync_engine.connect() as conn:
            if user_id:
                conn.execute(
                    sql_text("""
                        UPDATE tenant_credentials
                        SET encrypted_data = :creds,
                            oauth2_refresh_token_encrypted = :refresh,
                            oauth2_expiry = :expiry
                        WHERE empresa_id = :eid AND provider = :provider AND user_id = :uid
                    """),
                    {
                        "creds": encrypted_creds.decode(),
                        "refresh": encrypted_refresh.decode(),
                        "expiry": new_expiry,
                        "eid": empresa_id,
                        "provider": service,
                        "uid": user_id,
                    },
                )
            else:
                conn.execute(
                    sql_text("""
                        UPDATE tenant_credentials
                        SET encrypted_data = :creds,
                            oauth2_refresh_token_encrypted = :refresh,
                            oauth2_expiry = :expiry
                        WHERE empresa_id = :eid AND provider = :provider AND user_id IS NULL
                    """),
                    {
                        "creds": encrypted_creds.decode(),
                        "refresh": encrypted_refresh.decode(),
                        "expiry": new_expiry,
                        "eid": empresa_id,
                        "provider": service,
                    },
                )
            conn.commit()
        print(f"CREDENTIALS: M365 Refresh OK {service}/{empresa_id}")
    except Exception as e:
        print(f"ERROR saving M365 refreshed token: {e}")

    return creds


def get_service_credentials(empresa_id: str, service: str, user_id: str = "") -> dict:
    """Obtiene credenciales para servicios con API key (Notion, Plane, etc.)."""
    import re

    if not FERNET_KEY:
        return {"error": "Sistema de credenciales no configurado"}

    uuid_pattern = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.I)
    if not uuid_pattern.match(empresa_id or ""):
        return {"error": "ID de empresa no válido"}

    fernet = Fernet(FERNET_KEY.encode())

    try:
        with sync_engine.connect() as conn:
            empresa = conn.execute(
                sql_text("SELECT id, nombre FROM empresas WHERE id = :eid"),
                {"eid": empresa_id},
            ).fetchone()

            if not empresa:
                return {"error": "Empresa no registrada"}

            # Buscar credenciales: primero personales, luego empresa
            row = None
            if user_id and service in PERSONAL_SERVICES:
                result = conn.execute(
                    sql_text("""
                        SELECT encrypted_data
                        FROM tenant_credentials
                        WHERE empresa_id = :eid AND provider = :provider AND user_id = :uid AND is_active = TRUE
                    """),
                    {"eid": empresa_id, "provider": service, "uid": user_id},
                )
                row = result.fetchone()

            if not row:
                result = conn.execute(
                    sql_text("""
                        SELECT encrypted_data
                        FROM tenant_credentials
                        WHERE empresa_id = :eid AND provider = :provider AND user_id IS NULL AND is_active = TRUE
                    """),
                    {"eid": empresa_id, "provider": service},
                )
                row = result.fetchone()

        if not row:
            return {"error": f"{empresa.nombre} no tiene {service} conectado."}

        creds = json.loads(fernet.decrypt(row.encrypted_data.encode()).decode())
        print(f"CREDENTIALS: OK {service} para {empresa.nombre}")
        return creds

    except Exception as e:
        print(f"ERROR credentials {service}/{empresa_id}: {e}")
        return {"error": str(e)}