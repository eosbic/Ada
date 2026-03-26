"""
Chat Router — con HITL (Human-in-the-Loop) automatico.
Aprobaciones pendientes persistidas en PostgreSQL.
"""

import re
import json
from fastapi import APIRouter, Depends
from sqlalchemy import text as sql_text
from api.services.agent_runner import run_agent
from api.dependencies import get_current_user
from api.database import sync_engine, AsyncSessionLocal

router = APIRouter()


async def _handle_configure_brief(message: str, empresa_id: str, user_id: str) -> dict | None:
    """Detecta y maneja comandos de configuracion del morning brief."""
    msg = (message or "").lower().strip()

    # Patrones de activacion
    brief_keywords = [
        "activa el brief", "activar brief", "activa brief", "activar el brief",
        "envíame el brief", "enviame el brief", "quiero el brief",
        "brief diario", "brief a las", "brief todos los dias", "brief todos los días",
        "desactiva el brief", "desactivar brief", "desactiva brief",
        "cancela el brief", "cancelar brief", "no quiero brief",
        "cambia el brief", "cambiar hora del brief",
    ]

    if not any(k in msg for k in brief_keywords):
        return None

    # Detectar si es desactivar
    disable_kw = ["desactiva", "cancelar", "cancela", "no quiero", "desactivar"]
    if any(k in msg for k in disable_kw):
        await _update_brief_pref(user_id, {"morning_brief_enabled": False})
        return {
            "response": "✅ Brief diario desactivado. Puedes reactivarlo cuando quieras diciendo *\"activa el brief a las 7am\"*.",
            "intent": "configure_brief",
            "model_used": "rule_brief_config",
        }

    # Detectar hora
    import re as _re
    hour_match = _re.search(r'(\d{1,2})\s*(?:am|:00|hrs?|horas?)?', msg)
    hour = int(hour_match.group(1)) if hour_match else 7
    if hour > 23:
        hour = 7

    await _update_brief_pref(user_id, {
        "morning_brief_enabled": True,
        "morning_brief_hour": hour,
    })

    return {
        "response": f"✅ Brief diario activado a las **{hour}:00** (America/Bogota).\n\n"
                    f"Cada mañana recibirás un resumen ejecutivo con tu agenda, emails pendientes y alertas.\n\n"
                    f"Para cambiar la hora: *\"cambia el brief a las 9am\"*\n"
                    f"Para desactivar: *\"desactiva el brief\"*",
        "intent": "configure_brief",
        "model_used": "rule_brief_config",
    }


async def _update_brief_pref(user_id: str, prefs: dict):
    """Actualiza preferencias de brief en user_preferences."""
    import json as _json
    try:
        async with AsyncSessionLocal() as db:
            from sqlalchemy import text as _t
            await db.execute(_t("""
                INSERT INTO user_preferences (user_id, preferences, updated_at)
                VALUES (:uid, :prefs::jsonb, NOW())
                ON CONFLICT (user_id)
                DO UPDATE SET
                    preferences = user_preferences.preferences || :prefs::jsonb,
                    updated_at = NOW()
            """), {"uid": user_id, "prefs": _json.dumps(prefs)})
            await db.commit()
    except Exception as e:
        print(f"BRIEF CONFIG: Error actualizando preferencias: {e}")


APPROVAL_WORDS = (
    "sí", "si", "ok", "enviar", "confirmar", "envíalo", "envialo", "dale", "aprobado", "send",
)
REJECTION_WORDS = (
    "no", "cancelar", "rechazar", "cancela", "cancel",
)


def _is_approval(message: str) -> bool:
    return (message or "").strip().lower() in APPROVAL_WORDS


def _is_rejection(message: str) -> bool:
    return (message or "").strip().lower() in REJECTION_WORDS


def _get_pending(empresa_id: str, user_id: str) -> dict | None:
    """Obtiene aprobacion pendiente desde PostgreSQL."""
    try:
        with sync_engine.connect() as conn:
            row = conn.execute(
                sql_text("""
                    SELECT id, draft_type, draft_content
                    FROM pending_approvals
                    WHERE empresa_id = :eid AND user_id = :uid
                    AND status = 'pending'
                    AND expires_at > NOW()
                    ORDER BY created_at DESC
                    LIMIT 1
                """),
                {"eid": empresa_id, "uid": user_id}
            ).fetchone()
            if row:
                content = row.draft_content if isinstance(row.draft_content, dict) else json.loads(row.draft_content)
                return {"id": str(row.id), "type": row.draft_type, **content}
    except Exception as e:
        print(f"HITL: Error leyendo pending: {e}")
    return None


def _resolve_pending(approval_id: str, status: str) -> None:
    """Marca una aprobacion como resuelta."""
    try:
        with sync_engine.connect() as conn:
            conn.execute(
                sql_text("UPDATE pending_approvals SET status = :status WHERE id = :id"),
                {"status": status, "id": approval_id}
            )
            conn.commit()
    except Exception as e:
        print(f"HITL: Error resolviendo pending: {e}")


def _clear_pending(empresa_id: str, user_id: str) -> None:
    """Cancela todas las aprobaciones pendientes de un usuario."""
    try:
        with sync_engine.connect() as conn:
            conn.execute(
                sql_text("""
                    UPDATE pending_approvals SET status = 'cancelled'
                    WHERE empresa_id = :eid AND user_id = :uid AND status = 'pending'
                """),
                {"eid": empresa_id, "uid": user_id}
            )
            conn.commit()
    except Exception as e:
        print(f"HITL: Error limpiando pending: {e}")


def _save_pending(empresa_id: str, user_id: str, draft_type: str, draft_content: dict) -> None:
    """Guarda una nueva aprobacion pendiente."""
    try:
        with sync_engine.connect() as conn:
            # Cancelar previas
            conn.execute(
                sql_text("""
                    UPDATE pending_approvals SET status = 'cancelled'
                    WHERE empresa_id = :eid AND user_id = :uid AND status = 'pending'
                """),
                {"eid": empresa_id, "uid": user_id}
            )
            conn.execute(
                sql_text("""
                    INSERT INTO pending_approvals (empresa_id, user_id, draft_type, draft_content)
                    VALUES (:eid, :uid, :dtype, :content::jsonb)
                """),
                {
                    "eid": empresa_id, "uid": user_id,
                    "dtype": draft_type,
                    "content": json.dumps(draft_content, ensure_ascii=False),
                }
            )
            conn.commit()
    except Exception as e:
        print(f"HITL: Error guardando pending: {e}")


@router.post("/chat")
async def chat(data: dict, current_user: dict = Depends(get_current_user)):
    message = data.get("message")
    empresa_id = current_user["empresa_id"]
    user_id = current_user["user_id"]
    has_file = bool(data.get("has_file", False))
    file_type = data.get("file_type")
    source = data.get("source", "api")

    if not message:
        return {"error": "message required"}

    # ── HITL: Si hay accion pendiente para este usuario ──
    pending = _get_pending(empresa_id, user_id)
    if pending:
        if _is_approval(message):
            _resolve_pending(pending["id"], "approved")

            if pending.get("type") == "email_send":
                try:
                    from api.services.gmail_service import gmail_send
                    result = gmail_send(draft_id=pending.get("draft_id", ""), empresa_id=empresa_id)
                    if isinstance(result, dict) and "error" in result:
                        return {
                            "response": f"Error enviando email: {result['error']}",
                            "intent": "email",
                            "model_used": "hitl",
                        }
                    return {
                        "response": f"Email enviado exitosamente a {pending.get('to', 'destinatario')}.",
                        "intent": "email",
                        "model_used": "hitl",
                    }
                except Exception as e:
                    print(f"HITL email send error: {e}")
                    return {
                        "response": f"Error enviando email: {e}",
                        "intent": "email",
                        "model_used": "hitl",
                    }

            return {"response": "Accion ejecutada.", "intent": "action", "model_used": "hitl"}

        elif _is_rejection(message):
            _resolve_pending(pending["id"], "rejected")
            return {
                "response": "Accion cancelada.",
                "intent": "action",
                "model_used": "hitl",
            }
        else:
            # Si escribe otra cosa, cancelar pendiente y procesar normal
            _clear_pending(empresa_id, user_id)

    # ── Configure Brief: detección rápida antes del router ──
    brief_result = await _handle_configure_brief(message, empresa_id, user_id)
    if brief_result:
        return brief_result

    # ── Flujo normal ──
    result = await run_agent(
        message=message,
        empresa_id=empresa_id,
        user_id=user_id,
        has_file=has_file,
        file_type=file_type,
        source=source,
    )

    # ── HITL: Detectar si la respuesta requiere aprobacion ──
    if result.get("needs_approval") and result.get("draft_id"):
        response_text = result.get("response", "")
        to_match = re.search(r'(?:\*\*)?Para:(?:\*\*)?\s*(\S+)', response_text)
        to_addr = to_match.group(1) if to_match else ""

        _save_pending(empresa_id, user_id, "email_send", {
            "draft_id": result["draft_id"],
            "to": to_addr,
        })
        print(f"HITL: Aprobacion pendiente para {empresa_id[:8]}::{user_id[:8]} -> draft_id={result['draft_id']}")

    return result
