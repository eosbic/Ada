"""
Provider Router — Determina qué provider usar por empresa y servicio.
Consulta tenant_credentials para decidir Google vs Microsoft 365.
"""

from typing import Tuple
from api.database import sync_engine
from sqlalchemy import text as sql_text


# Servicio lógico → providers posibles
SERVICE_PROVIDERS = {
    "calendar": ["google_calendar", "outlook_calendar"],
    "email": ["gmail", "outlook_email"],
    "drive": ["google_drive", "onedrive"],
}

# Provider → familia
PROVIDER_FAMILY = {
    "google_calendar": "google",
    "gmail": "google",
    "google_drive": "google",
    "outlook_calendar": "microsoft",
    "outlook_email": "microsoft",
    "onedrive": "microsoft",
}

# Cache in-memory por "empresa_id::service"
_provider_cache: dict = {}


def get_provider(empresa_id: str, service: str) -> Tuple[str, str]:
    """
    Retorna (provider_name, family) para una empresa y servicio.
    Ejemplo: ("outlook_calendar", "microsoft") o ("google_calendar", "google").
    Si no hay credenciales activas, retorna ("", "none").
    """
    cache_key = f"{empresa_id}::{service}"
    if cache_key in _provider_cache:
        return _provider_cache[cache_key]

    providers = SERVICE_PROVIDERS.get(service)
    if not providers:
        return ("", "none")

    try:
        with sync_engine.connect() as conn:
            result = conn.execute(
                sql_text("""
                    SELECT provider
                    FROM tenant_credentials
                    WHERE empresa_id = :eid
                      AND provider IN :providers
                      AND is_active = TRUE
                    ORDER BY created_at DESC
                    LIMIT 1
                """),
                {"eid": empresa_id, "providers": tuple(providers)},
            )
            row = result.fetchone()
    except Exception as e:
        print(f"PROVIDER_ROUTER: Error consultando provider {service}/{empresa_id}: {e}")
        return ("", "none")

    if not row:
        return ("", "none")

    provider_name = row.provider
    family = PROVIDER_FAMILY.get(provider_name, "none")
    _provider_cache[cache_key] = (provider_name, family)
    return (provider_name, family)


def clear_cache(empresa_id: str = None):
    """Limpia cache de providers. Si empresa_id es None, limpia todo."""
    global _provider_cache
    if empresa_id is None:
        _provider_cache = {}
    else:
        keys_to_remove = [k for k in _provider_cache if k.startswith(f"{empresa_id}::")]
        for k in keys_to_remove:
            del _provider_cache[k]


def is_microsoft(empresa_id: str, service: str) -> bool:
    """Retorna True si la empresa usa Microsoft para el servicio dado."""
    _, family = get_provider(empresa_id, service)
    return family == "microsoft"


def is_google(empresa_id: str, service: str) -> bool:
    """Retorna True si la empresa usa Google para el servicio dado."""
    _, family = get_provider(empresa_id, service)
    return family == "google"
