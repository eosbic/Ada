"""
Agent Status Service — Controla el estado de los agentes de Ada por empresa.
Permite activar/desactivar agentes y consultar su estado para el brief y dashboard.
"""

import json
from datetime import datetime
from sqlalchemy import text as sql_text
from api.database import sync_engine


def get_all_agent_status(empresa_id: str) -> list:
    """Obtiene el estado de todos los agentes de una empresa."""
    try:
        with sync_engine.connect() as conn:
            rows = conn.execute(
                sql_text("""
                    SELECT agent_name, display_name, is_active, last_run_at, last_result, config, deactivated_at
                    FROM agent_status
                    WHERE empresa_id = :eid
                    ORDER BY agent_name
                """),
                {"eid": empresa_id}
            ).fetchall()

        return [
            {
                "agent_name": r.agent_name,
                "display_name": r.display_name,
                "is_active": r.is_active,
                "last_run_at": r.last_run_at.isoformat() if r.last_run_at else None,
                "last_result": r.last_result or "",
                "config": r.config if isinstance(r.config, dict) else json.loads(r.config or "{}"),
                "days_inactive": (datetime.utcnow() - r.deactivated_at).days if r.deactivated_at and not r.is_active else 0,
            }
            for r in rows
        ]
    except Exception as e:
        print(f"AGENT STATUS: Error getting status: {e}")
        return []


def set_agent_active(empresa_id: str, agent_name: str, active: bool) -> bool:
    """Activa o desactiva un agente."""
    try:
        with sync_engine.connect() as conn:
            if active:
                conn.execute(
                    sql_text("""
                        UPDATE agent_status
                        SET is_active = TRUE, activated_at = NOW(), deactivated_at = NULL
                        WHERE empresa_id = :eid AND agent_name = :name
                    """),
                    {"eid": empresa_id, "name": agent_name}
                )
            else:
                conn.execute(
                    sql_text("""
                        UPDATE agent_status
                        SET is_active = FALSE, deactivated_at = NOW()
                        WHERE empresa_id = :eid AND agent_name = :name
                    """),
                    {"eid": empresa_id, "name": agent_name}
                )
            conn.commit()

        status = "activado" if active else "desactivado"
        print(f"AGENT STATUS: {agent_name} {status} para {empresa_id[:8]}")
        return True
    except Exception as e:
        print(f"AGENT STATUS: Error: {e}")
        return False


def update_agent_last_run(empresa_id: str, agent_name: str, result: str = ""):
    """Actualiza la ultima ejecucion de un agente."""
    try:
        with sync_engine.connect() as conn:
            conn.execute(
                sql_text("""
                    UPDATE agent_status
                    SET last_run_at = NOW(), last_result = :result
                    WHERE empresa_id = :eid AND agent_name = :name
                """),
                {"eid": empresa_id, "name": agent_name, "result": result[:200]}
            )
            conn.commit()
    except Exception as e:
        print(f"AGENT STATUS: Error updating run: {e}")


def ensure_agent_status_exists(empresa_id: str):
    """Crea registros de agent_status si no existen para una empresa."""
    defaults = [
        ("email_monitor", "Monitoreo de emails", True),
        ("meeting_intel", "Meeting Intelligence", True),
        ("brief", "Brief diario", True),
        ("follow_up", "Follow-up automatico", True),
        ("prospect_scout", "Prospeccion de mercado", False),
    ]
    try:
        with sync_engine.connect() as conn:
            for agent_name, display_name, is_active in defaults:
                conn.execute(
                    sql_text("""
                        INSERT INTO agent_status (empresa_id, agent_name, display_name, is_active)
                        VALUES (:eid, :name, :display, :active)
                        ON CONFLICT (empresa_id, agent_name) DO NOTHING
                    """),
                    {"eid": empresa_id, "name": agent_name, "display": display_name, "active": is_active}
                )
            conn.commit()
    except Exception as e:
        print(f"AGENT STATUS: Error ensuring: {e}")


def format_agent_status_for_brief(empresa_id: str) -> str:
    """Formatea el estado de agentes para incluir en el brief diario."""
    agents = get_all_agent_status(empresa_id)
    if not agents:
        return ""

    lines = ["🤖 **Estado de tus agentes:**"]

    for a in agents:
        if a["is_active"]:
            emoji = "✅"
            extra = ""
            if a["last_result"]:
                extra = f" — {a['last_result']}"
            lines.append(f"  {emoji} {a['display_name']}{extra}")
        else:
            emoji = "⚠️"
            days = a.get("days_inactive", 0)
            days_text = f" hace {days} dias" if days > 0 else ""
            lines.append(f"  {emoji} {a['display_name']} — **PAUSADO**{days_text}")
            lines.append(f"     → Escribe \"activa {a['agent_name'].replace('_', ' ')}\"")

    return "\n".join(lines)
