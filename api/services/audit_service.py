"""
Audit Service — Registra accesos a datos sensibles.
No-throw: errores se loguean pero no rompen el flujo principal.
"""

import json
from api.database import sync_engine
from sqlalchemy import text as sql_text


def log_access(
    empresa_id: str,
    user_id: str,
    action: str,
    resource_type: str = "",
    resource_id: str = "",
    agent_name: str = "",
    detail: dict = None,
) -> None:
    """Registra un acceso en audit_log."""
    if not empresa_id or not user_id:
        return
    if not empresa_id or not user_id:
        return
    try:
        with sync_engine.connect() as conn:
            conn.execute(
                sql_text("""
                    INSERT INTO audit_log (empresa_id, user_id, action, resource_type, resource_id, agent_name, detail)
                    VALUES (:eid, :uid, :action, :rtype, :rid, :agent, CAST(:detail AS jsonb))
                """),
                {
                    "eid": empresa_id,
                    "uid": user_id,
                    "action": action,
                    "rtype": resource_type,
                    "rid": resource_id,
                    "agent": agent_name,
                    "detail": json.dumps(detail or {}),
                },
            )
            conn.commit()
    except Exception as e:
        print(f"AUDIT: Error logging {action}: {e}")


def log_rbac_blocked(empresa_id: str, user_id: str, agent_name: str, reason: str = "") -> None:
    """Atajo para registrar bloqueo RBAC."""
    log_access(
        empresa_id=empresa_id,
        user_id=user_id,
        action="rbac_blocked",
        agent_name=agent_name,
        detail={"reason": reason},
    )


def get_audit_log(empresa_id: str, limit: int = 50, action_filter: str = "") -> list:
    """Consulta audit log para admin dashboard."""
    try:
        with sync_engine.connect() as conn:
            query = """
                SELECT al.*, u.nombre, u.apellido
                FROM audit_log al
                LEFT JOIN usuarios u ON al.user_id = u.id
                WHERE al.empresa_id = :eid
            """
            params = {"eid": empresa_id, "limit": limit}

            if action_filter:
                query += " AND al.action = :action"
                params["action"] = action_filter

            query += " ORDER BY al.created_at DESC LIMIT :limit"

            rows = conn.execute(sql_text(query), params).fetchall()
            return [
                {
                    "id": str(r.id),
                    "user": f"{r.nombre or ''} {r.apellido or ''}".strip(),
                    "user_id": str(r.user_id),
                    "action": r.action,
                    "resource_type": r.resource_type,
                    "resource_id": r.resource_id,
                    "agent_name": r.agent_name,
                    "detail": r.detail,
                    "created_at": r.created_at.isoformat() if r.created_at else "",
                }
                for r in rows
            ]
    except Exception as e:
        print(f"AUDIT: Error querying log: {e}")
        return []
