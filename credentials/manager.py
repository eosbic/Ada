"""
CredentialManager — Credenciales cifradas por tenant.
Referencia: ADA_MIGRACION_V5_PART1.md §6

Seguridad:
- Cifradas con Fernet (AES-128-CBC) en reposo
- Encryption key en env var FERNET_KEY
- Nunca se loggean descifradas
- OAuth2 refresh automático
"""

import json
import os
from datetime import datetime, timedelta
from typing import Dict, Optional

import httpx
from cryptography.fernet import Fernet
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class CredentialNotFoundError(Exception):
    pass


class CredentialManager:

    def __init__(self):
        key = os.getenv("FERNET_KEY")
        if not key:
            raise ValueError(
                "FERNET_KEY no configurada. "
                "Genera una con: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
            )
        self.fernet = Fernet(key.encode())

    async def get_credentials(
        self, db: AsyncSession, empresa_id: str, service_type: str
    ) -> Dict:
        """Obtiene credenciales descifradas. Auto-refresh si OAuth2 expiró."""

        result = await db.execute(
            text("""
                SELECT credentials_encrypted, oauth2_refresh_token_encrypted,
                       oauth2_expiry
                FROM tenant_credentials
                WHERE empresa_id = :empresa_id
                  AND service_type = :service_type
                  AND is_active = TRUE
            """),
            {"empresa_id": empresa_id, "service_type": service_type},
        )
        row = result.fetchone()

        if not row:
            raise CredentialNotFoundError(
                f"No hay credenciales de '{service_type}' para empresa '{empresa_id}'"
            )

        # Descifrar
        creds = json.loads(
            self.fernet.decrypt(row.credentials_encrypted).decode()
        )

        # Auto-refresh si OAuth2 expiró o está por expirar (5 min antes)
        if row.oauth2_expiry and row.oauth2_expiry < datetime.utcnow() + timedelta(minutes=5):
            if row.oauth2_refresh_token_encrypted:
                refresh_token = self.fernet.decrypt(
                    row.oauth2_refresh_token_encrypted
                ).decode()
                creds = await self._refresh_oauth2(
                    db, empresa_id, service_type, creds, refresh_token
                )

        return creds

    async def store_credentials(
        self,
        db: AsyncSession,
        empresa_id: str,
        service_type: str,
        credentials: Dict,
        refresh_token: str = None,
        expiry: datetime = None,
    ):
        """Guarda credenciales cifradas. Upsert si ya existen."""

        enc_creds = self.fernet.encrypt(json.dumps(credentials).encode())
        enc_refresh = (
            self.fernet.encrypt(refresh_token.encode()) if refresh_token else None
        )

        await db.execute(
            text("""
                INSERT INTO tenant_credentials
                    (empresa_id, service_type, credentials_encrypted,
                     oauth2_refresh_token_encrypted, oauth2_expiry)
                VALUES (:empresa_id, :service_type, :creds, :refresh, :expiry)
                ON CONFLICT (empresa_id, service_type)
                DO UPDATE SET
                    credentials_encrypted = EXCLUDED.credentials_encrypted,
                    oauth2_refresh_token_encrypted = EXCLUDED.oauth2_refresh_token_encrypted,
                    oauth2_expiry = EXCLUDED.oauth2_expiry,
                    updated_at = NOW()
            """),
            {
                "empresa_id": empresa_id,
                "service_type": service_type,
                "creds": enc_creds,
                "refresh": enc_refresh,
                "expiry": expiry,
            },
        )
        await db.commit()

    async def delete_credentials(
        self, db: AsyncSession, empresa_id: str, service_type: str
    ):
        """Desactiva credenciales (soft delete)."""

        await db.execute(
            text("""
                UPDATE tenant_credentials
                SET is_active = FALSE, updated_at = NOW()
                WHERE empresa_id = :empresa_id AND service_type = :service_type
            """),
            {"empresa_id": empresa_id, "service_type": service_type},
        )
        await db.commit()

    async def _refresh_oauth2(
        self,
        db: AsyncSession,
        empresa_id: str,
        service_type: str,
        creds: Dict,
        refresh_token: str,
    ) -> Dict:
        """Refresh automático de tokens OAuth2 de Google."""

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "client_id": creds["client_id"],
                    "client_secret": creds["client_secret"],
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                },
            )

        if resp.status_code != 200:
            raise RuntimeError(
                f"OAuth2 refresh falló para {service_type}/{empresa_id}: {resp.text}"
            )

        token_data = resp.json()
        creds["access_token"] = token_data["access_token"]
        new_expiry = datetime.utcnow() + timedelta(
            seconds=token_data.get("expires_in", 3600)
        )

        # Actualizar en DB
        await self.store_credentials(
            db, empresa_id, service_type, creds, refresh_token, new_expiry
        )

        print(f"OAuth2 refresh OK para {service_type}/{empresa_id}")
        return creds


# Instancia global reutilizable
credential_manager = CredentialManager() if os.getenv("FERNET_KEY") else None