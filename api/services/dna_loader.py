"""
DNA Loader — Servicio central para cargar Company DNA.
Todos los agentes que necesiten contexto de empresa lo importan de aquí.
Lee de ada_company_profile (tabla extendida con campos DNA).
"""

import json
from api.database import sync_engine
from sqlalchemy import text as sql_text


def _safe_json(value, default=None):
    """Convierte valor a Python. Si ya es list/dict, lo deja. Si es str, parsea."""
    if default is None:
        default = {}
    if not value:
        return default
    if isinstance(value, (list, dict)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, ValueError):
            return default
    return default


def load_company_dna(empresa_id: str) -> dict:
    """Carga el DNA completo de la empresa. Retorna dict con todos los campos o dict vacío."""
    if not empresa_id:
        return {}

    try:
        with sync_engine.connect() as conn:
            row = conn.execute(
                sql_text("SELECT * FROM ada_company_profile WHERE empresa_id = :eid"),
                {"eid": empresa_id},
            ).fetchone()

        if not row:
            return {}

        dna = {
            # Campos originales
            "company_name": getattr(row, "company_name", None) or "",
            "industry_type": getattr(row, "industry_type", None) or "",
            "business_description": getattr(row, "business_description", None) or "",
            "main_products": _safe_json(getattr(row, "main_products", None), []),
            "main_services": _safe_json(getattr(row, "main_services", None), []),
            "company_size": getattr(row, "company_size", None) or "",
            "num_employees": getattr(row, "num_employees", None),
            "city": getattr(row, "city", None) or "",
            "country": getattr(row, "country", None) or "Colombia",
            "currency": getattr(row, "currency", None) or "COP",
            "ada_custom_name": getattr(row, "ada_custom_name", None) or "Ada",
            "ada_personality": getattr(row, "ada_personality", None) or "directo",
            "admin_interests": _safe_json(getattr(row, "admin_interests", None), []),
            "fiscal_year_start": getattr(row, "fiscal_year_start", None),
            "main_competitors": _safe_json(getattr(row, "main_competitors", None), []),
            "key_metrics": _safe_json(getattr(row, "key_metrics", None), []),
            "kpi_targets": _safe_json(getattr(row, "kpi_targets", None), {}),
            # Campos DNA nuevos
            "mission": getattr(row, "mission", None) or "",
            "vision": getattr(row, "vision", None) or "",
            "objectives": _safe_json(getattr(row, "objectives", None), []),
            "value_proposition": getattr(row, "value_proposition", None) or "",
            "business_model": getattr(row, "business_model", None) or "",
            "sales_cycle_days": getattr(row, "sales_cycle_days", None),
            "brand_voice": getattr(row, "brand_voice", None) or "",
            "product_catalog": _safe_json(getattr(row, "product_catalog", None), []),
            "target_icp": _safe_json(getattr(row, "target_icp", None), {}),
            "success_cases": getattr(row, "success_cases", None) or "",
            "website_url": getattr(row, "website_url", None) or "",
            "website_summary": getattr(row, "website_summary", None) or "",
            "social_urls": _safe_json(getattr(row, "social_urls", None), {}),
            "social_analysis": getattr(row, "social_analysis", None) or "",
            "logo_url": getattr(row, "logo_url", None) or "",
            "brand_colors": _safe_json(getattr(row, "brand_colors", None), {}),
            "agent_configs": _safe_json(getattr(row, "agent_configs", None), {}),
            "productivity_suite": getattr(row, "productivity_suite", None) or "",
            "pm_tool": getattr(row, "pm_tool", None) or "",
            "extra_apps": _safe_json(getattr(row, "extra_apps", None), []),
            "onboarding_complete": getattr(row, "onboarding_complete", None) or False,
        }

        print(f"DNA_LOADER: OK {dna['company_name']}")
        return dna

    except Exception as e:
        print(f"DNA_LOADER: Error cargando DNA para {empresa_id}: {e}")
        return {}


def load_agent_config(empresa_id: str, agent_name: str) -> dict:
    """Carga configuración específica para un agente desde agent_configs."""
    dna = load_company_dna(empresa_id)
    configs = dna.get("agent_configs", {})
    if isinstance(configs, str):
        try:
            configs = json.loads(configs)
        except (json.JSONDecodeError, ValueError):
            configs = {}
    return configs.get(agent_name, {})


def update_dna_field(empresa_id: str, field: str, value) -> bool:
    """Actualiza un campo específico del DNA."""
    ALLOWED_FIELDS = [
        "mission", "vision", "objectives", "value_proposition", "business_model",
        "sales_cycle_days", "brand_voice", "product_catalog", "target_icp",
        "success_cases", "website_url", "website_summary", "social_urls",
        "social_analysis", "logo_url", "brand_colors", "agent_configs",
        "productivity_suite", "pm_tool", "extra_apps", "onboarding_complete",
        "main_competitors",
    ]
    if field not in ALLOWED_FIELDS:
        return False

    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False, default=str)

    try:
        with sync_engine.connect() as conn:
            conn.execute(
                sql_text(f"UPDATE ada_company_profile SET {field} = :val WHERE empresa_id = :eid"),
                {"val": value, "eid": empresa_id},
            )
            conn.commit()
        return True
    except Exception as e:
        print(f"DNA_LOADER: Error actualizando {field}: {e}")
        return False


def save_agent_configs(empresa_id: str, configs: dict) -> bool:
    """Guarda agent_configs generadas por el DNA agent."""
    return update_dna_field(empresa_id, "agent_configs", configs)
