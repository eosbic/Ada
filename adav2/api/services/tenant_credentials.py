"""
Tenant Credentials — Lee credenciales OAuth2 por empresa.
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


def get_google_credentials(empresa_id: str, service: str = "gmail") -> dict:
    """
    Obtiene credenciales de Google para una empresa.
    Verifica que la empresa exista y tenga credenciales activas.
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

            # 2. Buscar credenciales activas
            result = conn.execute(
                sql_text("""
                    SELECT encrypted_data, oauth2_refresh_token_encrypted, oauth2_expiry
                    FROM tenant_credentials
                    WHERE empresa_id = :eid AND provider = :provider AND is_active = TRUE
                """),
                {"eid": empresa_id, "provider": service},
            )
            row = result.fetchone()

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
            creds = _refresh_token(empresa_id, service, creds, refresh_token, fernet)

        print(f"CREDENTIALS: OK {service} para {empresa.nombre}")
        return creds

    except Exception as e:
        print(f"ERROR credentials {service}/{empresa_id}: {e}")
        return {"error": f"Error obteniendo credenciales: {str(e)}"}

def _refresh_token(empresa_id, service, creds, refresh_token, fernet) -> dict:
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
            conn.execute(
                sql_text("""
                    UPDATE tenant_credentials
                    SET encrypted_data = :creds, oauth2_expiry = :expiry
                    WHERE empresa_id = :eid AND provider = :provider
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


def get_service_credentials(empresa_id: str, service: str) -> dict:
    """Obtiene credenciales para servicios con API key (Notion, Plane)."""
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

            result = conn.execute(
                sql_text("""
                    SELECT encrypted_data
                    FROM tenant_credentials
                    WHERE empresa_id = :eid AND provider = :provider AND is_active = TRUE
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