"""
RBAC Service — Permisos reales con mapeo a report_types y agentes.
Dos capas: 1) filtro SQL en queries de ada_reports, 2) bloqueo de agentes no autorizados.
Admin (usuarios.rol = 'admin') tiene acceso total siempre.
"""

import json
from api.database import sync_engine
from sqlalchemy import text as sql_text


# Mapea permisos a report_types que el usuario puede ver
PERMISSION_REPORT_TYPE_MAP = {
    "can_view_sales": ["excel_analysis", "excel_raw", "consolidated_analysis"],
    "can_view_finance": ["excel_analysis", "excel_raw", "consolidated_analysis"],
    "can_view_inventory": ["excel_analysis", "excel_raw"],
    "can_view_clients": ["prospect_profile", "email_summary", "proactive_briefing"],
    "can_view_projects": ["pm_task_summary", "notion_summary"],
    "can_view_hr": ["excel_analysis"],
}

# Mapea permisos a agentes permitidos
PERMISSION_AGENT_MAP = {
    "can_send_email": ["email_agent"],
    "can_manage_calendar": ["calendar_agent"],
    "can_upload_files": ["excel_analyst", "image_analyst"],
    "can_prospect": ["prospecting_agent", "generic_pm_agent"],
    "can_view_projects": ["project_agent", "notion_agent", "generic_pm_agent"],
}

# Agentes accesibles por todos los usuarios autenticados
BASE_AGENTS = [
    "chat_agent", "morning_brief_agent", "briefing_agent",
    "consolidation_agent", "alert_agent", "team_agent",
]

# Report types accesibles por todos los usuarios autenticados
BASE_REPORT_TYPES = ["calendar_event_summary", "proactive_briefing"]


def get_user_permissions(empresa_id: str, user_id: str) -> dict:
    """Retorna permisos completos del usuario incluyendo report_types y agentes permitidos."""
    try:
        with sync_engine.connect() as conn:
            user_row = conn.execute(
                sql_text("SELECT rol FROM usuarios WHERE id = :uid"),
                {"uid": user_id},
            ).fetchone()

            is_admin = user_row and user_row.rol == "admin"
            if is_admin:
                return {
                    "is_admin": True,
                    "permissions": {},
                    "role_title": "Administrador",
                    "allowed_report_types": ["ALL"],
                    "allowed_agents": ["ALL"],
                }

            member_row = conn.execute(
                sql_text("""
                    SELECT permissions, role_title
                    FROM team_members
                    WHERE empresa_id = :eid AND user_id = :uid AND is_active = TRUE
                """),
                {"eid": empresa_id, "uid": user_id},
            ).fetchone()

        if not member_row:
            return {
                "is_admin": False,
                "permissions": {},
                "role_title": "",
                "allowed_report_types": [],
                "allowed_agents": ["chat_agent"],
            }

        perms = member_row.permissions
        if isinstance(perms, str):
            try:
                perms = json.loads(perms)
            except (json.JSONDecodeError, ValueError):
                perms = {}
        if not isinstance(perms, dict):
            perms = {}

        role_title = member_row.role_title or ""

        # Build allowed_report_types
        allowed_rt = set(BASE_REPORT_TYPES)
        for perm_key, report_types in PERMISSION_REPORT_TYPE_MAP.items():
            if perms.get(perm_key):
                allowed_rt.update(report_types)

        # Build allowed_agents
        allowed_ag = set(BASE_AGENTS)
        for perm_key, agents in PERMISSION_AGENT_MAP.items():
            if perms.get(perm_key):
                allowed_ag.update(agents)

        return {
            "is_admin": False,
            "permissions": perms,
            "role_title": role_title,
            "allowed_report_types": list(allowed_rt),
            "allowed_agents": list(allowed_ag),
        }

    except Exception as e:
        print(f"RBAC: Error obteniendo permisos {user_id}: {e}")
        return {
            "is_admin": False,
            "permissions": {},
            "role_title": "",
            "allowed_report_types": [],
            "allowed_agents": ["chat_agent"],
        }


def check_agent_access(empresa_id: str, user_id: str, agent_name: str) -> tuple:
    """Verifica si el usuario puede usar un agente. Retorna (allowed, reason)."""
    rbac = get_user_permissions(empresa_id, user_id)
    if rbac["is_admin"]:
        return (True, "admin")
    if "ALL" in rbac["allowed_agents"]:
        return (True, "full_access")
    if agent_name in rbac["allowed_agents"]:
        return (True, "permitted")
    return (False, "No tienes permiso para usar esta funcion. Contacta a tu administrador.")


def get_report_type_filter(empresa_id: str, user_id: str) -> list:
    """Retorna lista de report_types que el usuario puede ver. ['ALL'] si es admin."""
    rbac = get_user_permissions(empresa_id, user_id)
    return rbac["allowed_report_types"]


def build_sql_rbac_clause(user_id: str, empresa_id: str) -> tuple:
    """Retorna (sql_clause, params) para inyectar en queries de ada_reports."""
    allowed = get_report_type_filter(empresa_id, user_id)
    if "ALL" in allowed:
        return ("", {})
    if not allowed:
        return ("AND 1=0", {})
    placeholders = ", ".join([f":rt_{i}" for i in range(len(allowed))])
    params = {f"rt_{i}": rt for i, rt in enumerate(allowed)}
    return (f"AND report_type IN ({placeholders})", params)
