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
    "sí", "si", "ok", "enviar", "confirmar", "envíalo", "envialo",
    "dale", "aprobado", "send", "yes", "mándalo", "mandalo",
    "perfecto", "listo", "va", "hazlo", "claro", "por favor",
    "adelante", "hágale", "hagale", "eso", "correcto",
)
REJECTION_WORDS = (
    "no", "cancelar", "rechazar", "cancela", "cancel",
    "no envíes", "no envies", "mejor no", "déjalo", "dejalo",
    "olvídalo", "olvidalo", "para", "detente",
)


def _is_approval(message: str) -> bool:
    msg = (message or "").strip().lower().rstrip("!.,")
    return msg in APPROVAL_WORDS


def _is_rejection(message: str) -> bool:
    msg = (message or "").strip().lower().rstrip("!.,")
    return msg in REJECTION_WORDS


def _get_pending(empresa_id: str, user_id: str) -> dict | None:
    """Obtiene aprobacion pendiente desde PostgreSQL."""
    from datetime import datetime
    try:
        with sync_engine.connect() as conn:
            row = conn.execute(
                sql_text("""
                    SELECT id, draft_type, draft_content, created_at, expires_at
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
                print(f"HITL: Found pending for {empresa_id[:8]}::{user_id[:8]} type={row.draft_type} created={row.created_at}")
                return {"id": str(row.id), "type": row.draft_type, **content}
            else:
                # Debug: buscar si hay pending expirados o con otro status
                debug_row = conn.execute(
                    sql_text("""
                        SELECT id, status, created_at, expires_at
                        FROM pending_approvals
                        WHERE empresa_id = :eid AND user_id = :uid
                        ORDER BY created_at DESC
                        LIMIT 1
                    """),
                    {"eid": empresa_id, "uid": user_id}
                ).fetchone()
                if debug_row:
                    print(f"HITL: No pending ACTIVE, but found {debug_row.status} from {debug_row.created_at}, expires={debug_row.expires_at}, NOW={datetime.utcnow()}")
                else:
                    print(f"HITL: No pending at all for {empresa_id[:8]}::{user_id[:8]}")
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
                    INSERT INTO pending_approvals (empresa_id, user_id, draft_type, draft_content, expires_at)
                    VALUES (:eid, :uid, :dtype, CAST(:content AS jsonb), NOW() + INTERVAL '1 hour')
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
        print(f"HITL: Pending found: type={pending.get('type')}, user said: '{message}'")

        # Email en composición — el usuario responde con info faltante
        if pending.get("type") == "email_composing":
            if _is_rejection(message):
                _resolve_pending(pending["id"], "cancelled")
                return {"response": "Email cancelado.", "intent": "email", "model_used": "hitl"}

            _resolve_pending(pending["id"], "completed")
            partial_to = pending.get("partial_to", "")

            if partial_to:
                enriched = f"Escribe un email a {partial_to} con este contenido: {message}"
            else:
                enriched = f"Escribe un email a {message}"

            print(f"HITL: Email composing -> enriched: '{enriched[:100]}'")
            result = await run_agent(
                message=enriched,
                empresa_id=empresa_id,
                user_id=user_id,
                source=source,
            )

            if result.get("needs_approval") and result.get("draft_id"):
                response_text = result.get("response", "")
                to_match = re.search(r'[\w.-]+@[\w.-]+\.\w+', response_text)
                to_addr = to_match.group(0) if to_match else partial_to
                _save_pending(empresa_id, user_id, "email_send", {
                    "draft_id": result["draft_id"],
                    "to": to_addr,
                    "original_draft": result.get("original_draft", ""),
                })
                print(f"HITL: Draft created from composing, draft_id={result['draft_id']}")

            return result

        if _is_approval(message):
            print(f"HITL: Approving draft_id={pending.get('draft_id')}")
            _resolve_pending(pending["id"], "approved")

            if pending.get("type") == "email_send":
                try:
                    from api.services.gmail_service import gmail_send
                    result = gmail_send(draft_id=pending.get("draft_id", ""), empresa_id=empresa_id, user_id=user_id)
                    if isinstance(result, dict) and "error" in result:
                        return {
                            "response": f"Error enviando email: {result['error']}",
                            "intent": "email",
                            "model_used": "hitl",
                        }

                    # Crear tracking para monitoreo de respuesta
                    to_addr = pending.get("to", "destinatario")
                    try:
                        from api.services.email_followup_service import create_followup
                        create_followup(
                            empresa_id=empresa_id,
                            user_id=user_id,
                            to_email=to_addr,
                            to_name="",
                            subject="",
                            gmail_message_id="",
                            gmail_thread_id="",
                            context=pending.get("original_draft", "")[:200],
                        )
                    except Exception as e:
                        print(f"HITL: Error creating followup tracking: {e}")

                    return {
                        "response": (
                            f"✅ Email enviado a **{to_addr}**.\n\n"
                            f"📬 Estoy monitoreando la respuesta — te aviso cuando conteste.\n\n"
                            f"💡 Si quieres que le haga follow-up automático si no responde, dime: \"recuérdale en 2 días\"."
                        ),
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
        elif pending.get("type") == "email_send":
            # El usuario quiere modificar el borrador (corrección o edición directa)
            original_draft = pending.get("original_draft", "")

            # Si original_draft está vacío, reconstruir desde el historial
            if not original_draft:
                try:
                    from api.agents.chat_agent import get_history
                    history = get_history(empresa_id, user_id)
                    for msg in reversed(history[-6:]):
                        if msg.get("role") == "assistant" and "Borrador" in msg.get("content", ""):
                            content = msg["content"]
                            to_match = re.search(r'\*?\*?Para:\*?\*?\s*(\S+)', content)
                            subject_match = re.search(r'\*?\*?Asunto:\*?\*?\s*(.+?)(?:\n|$)', content)
                            body_match = re.search(r'\*?\*?Cuerpo:\*?\*?\s*\n(.*?)(?:\n---|\Z)', content, re.DOTALL)

                            to_val = to_match.group(1).strip("*") if to_match else pending.get("to", "")
                            subj_val = subject_match.group(1).strip().strip("*") if subject_match else ""
                            body_val = body_match.group(1).strip() if body_match else ""

                            if body_val:
                                original_draft = f"Para: {to_val}\nAsunto: {subj_val}\n\n{body_val}"
                                print(f"HITL: Reconstructed original_draft from history")
                            break
                except Exception as e:
                    print(f"HITL: Error reconstructing original_draft: {e}")

            # Usar LLM para interpretar la corrección y aplicarla al borrador
            to = pending.get("to", "")
            subject = ""
            body = message  # fallback

            if original_draft:
                try:
                    from models.selector import selector
                    _model, _ = selector.get_model("routing")

                    correction_prompt = f"""Tienes un borrador de email y una instrucción del usuario.
Aplica la corrección al borrador y retorna el email corregido.

BORRADOR ORIGINAL:
{original_draft}

INSTRUCCIÓN DEL USUARIO:
{message}

Responde SOLO JSON:
{{"to": "email@ejemplo.com", "subject": "asunto corregido", "body": "cuerpo corregido"}}

REGLAS:
- Extrae "to" y "subject" del borrador original si el usuario no los cambia
- Aplica la corrección que pide el usuario al body
- Si el usuario pega un email completo nuevo (con Para:/Asunto:), usarlo directamente
- Mantén todo lo demás igual
- NO incluir markdown en el JSON"""

                    _resp = await _model.ainvoke([
                        {"role": "system", "content": "Aplica correcciones a borradores de email. Responde SOLO JSON."},
                        {"role": "user", "content": correction_prompt},
                    ])

                    raw = (_resp.content or "").strip().replace("```json", "").replace("```", "")
                    corrected = json.loads(raw)
                    to = corrected.get("to", "") or to
                    subject = corrected.get("subject", "")
                    body = corrected.get("body", "")

                except Exception as e:
                    print(f"HITL: Error applying correction via LLM: {e}")
                    edited_parts = _parse_edited_email(message, pending)
                    to = edited_parts["to"]
                    subject = edited_parts["subject"]
                    body = edited_parts["body"]
            else:
                edited_parts = _parse_edited_email(message, pending)
                to = edited_parts["to"]
                subject = edited_parts["subject"]
                body = edited_parts["body"]

            # Aprender de la corrección
            if original_draft:
                try:
                    from api.services.user_memory_service import extract_correction_learnings
                    corrected_text = f"Para: {to}\nAsunto: {subject}\n\n{body}"
                    await extract_correction_learnings(
                        empresa_id, user_id, original_draft, corrected_text,
                        f"Email dirigido a: {to}"
                    )
                except Exception as e:
                    print(f"HITL: Error extracting corrections: {e}")

            # Mostrar borrador corregido para aprobación (NUNCA enviar directo)
            _resolve_pending(pending["id"], "edited")

            from api.services.gmail_service import gmail_draft
            new_draft = gmail_draft(to=to, subject=subject, body=body, empresa_id=empresa_id, user_id=user_id)

            if new_draft.get("draft_id"):
                _save_pending(empresa_id, user_id, "email_send", {
                    "draft_id": new_draft["draft_id"],
                    "to": to,
                    "original_draft": f"Para: {to}\nAsunto: {subject}\n\n{body}",
                })

                return {
                    "response": (
                        f"✉️ **Borrador corregido:**\n\n"
                        f"📬 **Para:** {to}\n"
                        f"📝 **Asunto:** {subject}\n\n"
                        f"💬 **Cuerpo:**\n{body}\n\n"
                        f"---\n"
                        f"¿Lo envío? Responde **sí** para confirmar o **no** para cancelar."
                    ),
                    "intent": "email",
                    "model_used": "hitl_correction",
                }
            else:
                return {
                    "response": f"Error creando borrador corregido: {new_draft.get('error', 'desconocido')}",
                    "intent": "email",
                    "model_used": "hitl",
                }
        else:
            # Pending activo pero no es email_send — mantener vivo
            print(f"HITL: User said '{message[:50]}' with pending active — keeping pending alive")

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
            "original_draft": result.get("original_draft", ""),
        })
        print(f"HITL: Aprobacion pendiente para {empresa_id[:8]}::{user_id[:8]} -> draft_id={result['draft_id']}")

    # ── HITL: Si el email_agent pidió más info, guardar estado de composición ──
    elif result.get("intent") == "email" and not result.get("needs_approval"):
        response_text = result.get("response", "")
        response_lower = response_text.lower()
        composing_phrases = ["qué quieres que le diga", "a quién le envío", "a quién le escribo", "me das el email"]
        if any(phrase in response_lower for phrase in composing_phrases):
            # Extraer email del texto de respuesta si existe
            email_match = re.search(r'[\w.-]+@[\w.-]+\.\w+', response_text)
            partial_email = email_match.group(0) if email_match else ""
            _save_pending(empresa_id, user_id, "email_composing", {
                "partial_to": partial_email,
                "awaiting": "body" if partial_email else "to",
            })
            print(f"HITL: Email composing saved — partial_to={partial_email}, awaiting={'body' if partial_email else 'to'}")

    return result


def _looks_like_edit(message: str, pending: dict) -> bool:
    """Detecta si el mensaje del usuario parece una versión editada del borrador."""
    msg_lower = message.lower().strip()
    has_email_structure = any(marker in msg_lower for marker in ["para:", "asunto:", "subject:", "to:"])
    is_substantial = len(message) > 50
    not_command = not _is_approval(message) and not _is_rejection(message)
    return (has_email_structure or is_substantial) and not_command and pending.get("type") == "email_send"


def _parse_edited_email(message: str, pending: dict) -> dict:
    """Extrae to, subject, body de un email editado por el usuario."""
    lines = message.strip().split("\n")
    to = pending.get("to", "")
    subject = ""
    body_lines = []
    body_started = False

    for line in lines:
        lower = line.lower().strip()
        if lower.startswith(("para:", "to:")):
            to = line.split(":", 1)[1].strip()
        elif lower.startswith(("asunto:", "subject:")):
            subject = line.split(":", 1)[1].strip()
        elif body_started or (not lower.startswith(("para:", "to:", "asunto:", "subject:")) and line.strip()):
            body_started = True
            body_lines.append(line)

    return {
        "to": to,
        "subject": subject or "Sin asunto",
        "body": "\n".join(body_lines).strip() or message,
    }


@router.get("/memories")
async def my_memories(empresa_id: str, user_id: str):
    """Memorias del usuario."""
    from api.services.user_memory_service import get_all_memories
    return {"memories": get_all_memories(empresa_id, user_id)}
