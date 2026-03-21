"""
Chat Router — con HITL (Human-in-the-Loop) automático.
Guarda estado de aprobaciones pendientes por usuario.
"""

from fastapi import APIRouter
from api.services.agent_runner import run_agent

router = APIRouter()

# Estado de acciones pendientes por usuario (empresa_id::user_id → action_data)
_PENDING_APPROVALS: dict[str, dict] = {}


def _user_key(empresa_id: str, user_id: str) -> str:
    return f"{empresa_id}::{user_id}"


def _is_approval(message: str) -> bool:
    return (message or "").strip().lower() in (
        "sí", "si", "ok", "enviar", "confirmar", "envíalo", "envialo", "dale", "aprobado", "send",
    )


def _is_rejection(message: str) -> bool:
    return (message or "").strip().lower() in (
        "no", "cancelar", "rechazar", "cancela", "cancel",
    )


@router.post("/chat")
async def chat(data: dict):
    message = data.get("message", "")
    empresa_id = data.get("empresa_id", "")
    user_id = data.get("user_id", "")
    has_file = bool(data.get("has_file", False))
    file_type = data.get("file_type")
    source = data.get("source", "api")

    if not message:
        return {"error": "message required"}

    key = _user_key(empresa_id, user_id)

    # ── HITL: Si hay acción pendiente para este usuario ──
    if key in _PENDING_APPROVALS:
        if _is_approval(message):
            action = _PENDING_APPROVALS.pop(key)

            if action.get("type") == "email_send":
                try:
                    from api.services.gmail_service import gmail_send
                    result = gmail_send(draft_id=action.get("draft_id", ""), empresa_id=empresa_id)
                    if isinstance(result, dict) and "error" in result:
                        return {
                            "response": f"❌ Error enviando email: {result['error']}",
                            "intent": "email",
                            "model_used": "hitl",
                        }
                    return {
                        "response": f"✅ Email enviado exitosamente a {action.get('to', 'destinatario')}.",
                        "intent": "email",
                        "model_used": "hitl",
                    }
                except Exception as e:
                    print(f"HITL email send error: {e}")
                    return {
                        "response": f"❌ Error enviando email: {e}",
                        "intent": "email",
                        "model_used": "hitl",
                    }

            elif action.get("type") == "calendar_create":
                # Futuro: crear evento aprobado
                pass

            return {"response": "✅ Acción ejecutada.", "intent": "action", "model_used": "hitl"}

        elif _is_rejection(message):
            _PENDING_APPROVALS.pop(key)
            return {
                "response": "❌ Acción cancelada.",
                "intent": "action",
                "model_used": "hitl",
            }
        else:
            # Si escribe otra cosa, cancelar pendiente y procesar normal
            _PENDING_APPROVALS.pop(key, None)

    # ── Flujo normal ──
    result = await run_agent(
        message=message,
        empresa_id=empresa_id,
        user_id=user_id,
        has_file=has_file,
        file_type=file_type,
        source=source,
    )

    # ── HITL: Detectar si la respuesta requiere aprobación ──
    if result.get("needs_approval") and result.get("draft_id"):
        import re
        response_text = result.get("response", "")
        to_match = re.search(r'(?:\*\*)?Para:(?:\*\*)?\s*(\S+)', response_text)
        to_addr = to_match.group(1) if to_match else ""

        _PENDING_APPROVALS[key] = {
            "type": "email_send",
            "draft_id": result["draft_id"],
            "to": to_addr,
            "empresa_id": empresa_id,
        }
        print(f"HITL: Aprobación pendiente para {key} → draft_id={result['draft_id']}, to={to_addr}")

    return result