"""
Cross Agent — Orquesta workflows que combinan Calendar + Mensajería.
Agnóstico de canal: usa email, Telegram DM, o futuro Slack/WhatsApp según contexto.

Lógica de selección de canal:
- "avísale por email" / "envíale un correo" → email
- "dile urgente" / "mándale mensaje" / "notifícale" → Telegram DM (si tiene)
- "por Slack" → Slack (futuro)
- Si no especifica canal → Telegram DM si es interno, email si es externo
"""

import json
from datetime import datetime, timedelta
from typing import TypedDict
from zoneinfo import ZoneInfo

from langgraph.graph import StateGraph, END
from models.selector import selector
from api.services.calendar_service import (
    calendar_search_events,
    calendar_create_event,
    calendar_update_event,
    calendar_delete_event,
    calendar_get_availability,
)
from api.services.gmail_service import gmail_draft
from api.agents.chat_agent import get_history


def _get_company_tz(empresa_id: str) -> ZoneInfo:
    """Obtiene timezone de la empresa desde ada_company_profile."""
    tz_name = "America/Bogota"
    if empresa_id:
        try:
            from api.database import sync_engine
            from sqlalchemy import text as sql_text
            with sync_engine.connect() as conn:
                row = conn.execute(
                    sql_text("SELECT timezone FROM ada_company_profile WHERE empresa_id = :eid"),
                    {"eid": empresa_id}
                ).fetchone()
                if row and row.timezone:
                    tz_name = row.timezone
        except Exception:
            pass
    return ZoneInfo(tz_name)


class CrossState(TypedDict, total=False):
    message: str
    empresa_id: str
    user_id: str
    intent: str
    source: str

    plan: dict
    calendar_result: dict

    response: str
    model_used: str
    needs_approval: bool
    draft_id: str
    original_draft: str
    sources_used: list


PLANNER_PROMPT = """Eres Ada, asistente ejecutiva. El usuario pidió una acción que combina calendario y/o mensajería.

HOY es {today} ({weekday}).

## CANALES DE MENSAJERÍA DISPONIBLES:
1. **email** — comunicación formal, externa, o cuando el usuario dice "correo/email/mail"
2. **telegram** — mensajes internos urgentes entre miembros del equipo. Usar cuando: dice "dile", "avísale", "notifícale", "mensaje urgente", o cuando la persona es del equipo y no pide email explícitamente
3. **none** — no necesita enviar mensaje

## ACCIONES DE CALENDARIO:
- search: buscar evento existente
- cancel: cancelar evento
- update: cambiar fecha/hora
- create: crear evento nuevo
- availability: ver disponibilidad
- none: no necesita acción de calendario

## RESPONDE SOLO JSON:
{{
    "understanding": "resumen en 1 oración",
    "person_name": "nombre de la persona",
    "person_email": "email si lo mencionó, vacío si no",
    "calendar_action": "search|cancel|update|create|availability|none",
    "calendar_params": {{
        "query": "texto para buscar evento",
        "date": "fecha ISO si aplica",
        "new_date": "nueva fecha ISO si es reagendamiento",
        "title": "título si es evento nuevo",
        "duration_minutes": 60
    }},
    "message_channel": "email|telegram|none",
    "message_type": "notify_cancel|notify_reschedule|invite|confirm|urgent|custom",
    "message_content": "qué debe decir el mensaje",
    "is_urgent": false
}}

REGLAS:
- "mañana" = {tomorrow}
- "urgente" o "ya" → is_urgent=true + message_channel=telegram (si es interno)
- "por email" o "correo" → message_channel=email
- Si no especifica canal y la persona es del equipo → telegram
- Si no especifica canal y la persona es externa → email
- "cancela y avísale" → calendar_action=cancel + message apropiado
- "reagenda para el lunes y dile" → calendar_action=update + message apropiado
"""


async def plan_workflow(state: CrossState) -> dict:
    """Paso 1: Planificar qué hacer."""
    model, model_name = selector.get_model("chat_with_tools")
    empresa_id = state.get("empresa_id", "")
    user_id = state.get("user_id", "")
    message = state.get("message", "")

    # Extraer mensaje real si viene enriquecido con contexto
    if "MENSAJE ACTUAL:" in message:
        message = message.split("MENSAJE ACTUAL:")[-1].strip()
    elif "[CONTEXTO CONVERSACIONAL RECIENTE:" in message:
        message = message.split("]")[-1].strip()

    # Timezone de la empresa para calcular "hoy" y "mañana" correctamente
    tz = _get_company_tz(empresa_id)
    today = datetime.now(tz)
    tomorrow = today + timedelta(days=1)
    weekdays_es = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]

    history_context = ""
    try:
        history = get_history(empresa_id, user_id)
        if history:
            recent = history[-4:]
            history_context = "\nCONTEXTO RECIENTE:\n" + "\n".join(
                f"{m.get('role','user')}: {m.get('content','')[:150]}"
                for m in recent
            )
    except Exception:
        pass

    prompt = PLANNER_PROMPT.format(
        today=today.strftime("%Y-%m-%d"),
        weekday=weekdays_es[today.weekday()],
        tomorrow=tomorrow.strftime("%Y-%m-%d"),
    )

    response = await model.ainvoke([
        {"role": "system", "content": prompt},
        {"role": "user", "content": message + history_context},
    ])

    try:
        raw = (response.content or "").strip().replace("```json", "").replace("```", "")
        plan = json.loads(raw)
    except Exception as e:
        print(f"CROSS AGENT: Error parsing plan: {e}")
        plan = {"understanding": message, "calendar_action": "none", "message_channel": "none"}

    print(f"CROSS AGENT: Plan = {json.dumps(plan, ensure_ascii=False)[:200]}")
    return {"plan": plan, "model_used": model_name}


async def execute_calendar(state: CrossState) -> dict:
    """Paso 2: Ejecutar acción de calendario."""
    plan = state.get("plan", {})
    empresa_id = state.get("empresa_id", "")
    user_id = state.get("user_id", "")
    cal_action = plan.get("calendar_action", "none")
    cal_params = plan.get("calendar_params", {})

    if cal_action == "none":
        return {"calendar_result": {"status": "skipped"}}

    tz = _get_company_tz(empresa_id)
    result = {}

    try:
        if cal_action in ("cancel", "search"):
            query = cal_params.get("query", plan.get("person_name", ""))
            events = calendar_search_events(
                query=query, days_ahead=14,
                empresa_id=empresa_id, user_id=user_id
            )
            if isinstance(events, list) and events:
                if cal_action == "cancel":
                    event = events[0]
                    event_id = event.get("id", "")
                    if event_id:
                        del_result = calendar_delete_event(
                            event_id=event_id,
                            empresa_id=empresa_id, user_id=user_id
                        )
                        result = {"status": "cancelled", "event": event, "delete_result": del_result}
                        print(f"CROSS AGENT: Cancelled event '{event.get('summary', '')}'")
                    else:
                        result = {"status": "error", "message": "Evento sin ID"}
                else:
                    result = {"status": "found", "events": events, "count": len(events)}
            else:
                result = {"status": "not_found", "query": query}

        elif cal_action == "update":
            query = cal_params.get("query", plan.get("person_name", ""))
            events = calendar_search_events(query=query, days_ahead=14, empresa_id=empresa_id, user_id=user_id)
            if isinstance(events, list) and events:
                event = events[0]
                event_id = event.get("id", "")
                new_date = cal_params.get("new_date", "")
                if event_id and new_date:
                    duration = cal_params.get("duration_minutes", 60)
                    try:
                        start_dt = datetime.fromisoformat(new_date)
                        end_dt = start_dt + timedelta(minutes=duration)
                    except Exception:
                        start_dt = datetime.now(tz) + timedelta(days=7)
                        end_dt = start_dt + timedelta(minutes=60)

                    calendar_update_event(
                        event_id=event_id,
                        start_datetime=start_dt.isoformat(),
                        end_datetime=end_dt.isoformat(),
                        empresa_id=empresa_id, user_id=user_id
                    )
                    result = {"status": "updated", "event": event, "new_date": new_date}
                else:
                    result = {"status": "error", "message": "Falta event_id o new_date"}
            else:
                result = {"status": "not_found", "query": query}

        elif cal_action == "create":
            title = cal_params.get("title", f"Reunión con {plan.get('person_name', '')}")
            date = cal_params.get("date", "")
            duration = cal_params.get("duration_minutes", 60)
            if date:
                try:
                    start_dt = datetime.fromisoformat(date)
                except Exception:
                    start_dt = datetime.now(tz) + timedelta(days=7)
                end_dt = start_dt + timedelta(minutes=duration)
                calendar_create_event(
                    summary=title, start_datetime=start_dt.isoformat(),
                    end_datetime=end_dt.isoformat(),
                    empresa_id=empresa_id, user_id=user_id
                )
                result = {"status": "created", "event_title": title, "date": start_dt.isoformat()}
            else:
                avail = calendar_get_availability(days_ahead=7, empresa_id=empresa_id, user_id=user_id)
                result = {"status": "need_date", "availability": avail, "title": title}

        elif cal_action == "availability":
            avail = calendar_get_availability(days_ahead=7, empresa_id=empresa_id, user_id=user_id)
            result = {"status": "availability", "data": avail}

    except Exception as e:
        print(f"CROSS AGENT: Calendar error: {e}")
        result = {"status": "error", "message": str(e)}

    return {"calendar_result": result}


async def send_message(state: CrossState) -> dict:
    """Paso 3: Enviar mensaje por el canal adecuado (email, Telegram DM, etc.)."""
    plan = state.get("plan", {})
    empresa_id = state.get("empresa_id", "")
    user_id = state.get("user_id", "")
    calendar_result = state.get("calendar_result", {})
    channel = plan.get("message_channel", "none")

    if channel == "none":
        return {"response": _format_calendar_only(calendar_result)}

    person_name = plan.get("person_name", "")
    person_email = plan.get("person_email", "")
    message_content = plan.get("message_content", "")
    message_type = plan.get("message_type", "custom")
    is_urgent = plan.get("is_urgent", False)

    # ─── CANAL: TELEGRAM DM ──────────────────────────
    if channel == "telegram":
        from api.services.telegram_dm_service import get_team_member_telegram, send_telegram_dm

        member = get_team_member_telegram(empresa_id, person_name)

        if not member:
            # No encontrado en Telegram — fallback a email
            print(f"CROSS AGENT: {person_name} no tiene Telegram, falling back to email")
            channel = "email"
        elif member.get("multiple"):
            options = "\n".join(
                f"{i+1}. **{m['name']}** — {m.get('email', '')}"
                for i, m in enumerate(member["options"])
            )
            cal_summary = _format_calendar_only(calendar_result)
            return {"response": f"{cal_summary}\n\nEncontré varios miembros con ese nombre:\n{options}\n\n¿A cuál te refieres?"}
        else:
            # Encontrado — enviar por Telegram
            telegram_id = member["telegram_id"]
            member_name = member["name"]

            model, _ = selector.get_model("routing")

            # Obtener nombre del remitente
            remitent_name = ""
            try:
                from api.database import sync_engine
                from sqlalchemy import text as sql_text
                with sync_engine.connect() as conn:
                    row = conn.execute(sql_text("SELECT nombre FROM usuarios WHERE id = :uid"), {"uid": user_id}).fetchone()
                    if row:
                        remitent_name = row.nombre or ""
            except Exception:
                pass

            msg_prompt = f"""Redacta un mensaje de Telegram breve y directo.

DE: {remitent_name} (vía Ada)
PARA: {member_name}
TIPO: {message_type}
CONTENIDO: {message_content}
URGENTE: {'SÍ' if is_urgent else 'No'}
CONTEXTO CALENDARIO: {json.dumps(calendar_result, ensure_ascii=False, default=str)[:200]}

REGLAS:
- Máximo 3-4 líneas
- Directo, sin formalidades de email
- Si es urgente, empezar con ⚠️
- Firmar como "— {remitent_name} (vía Ada)"
- Usar el nombre del destinatario

Responde SOLO el texto del mensaje, sin JSON."""

            msg_response = await model.ainvoke([
                {"role": "system", "content": "Redacta mensajes de Telegram breves y directos."},
                {"role": "user", "content": msg_prompt},
            ])

            telegram_message = (msg_response.content or "").strip()

            send_result = await send_telegram_dm(telegram_id, telegram_message)

            cal_summary = _format_calendar_only(calendar_result)

            if send_result.get("sent"):
                return {
                    "response": (
                        f"{cal_summary}\n\n"
                        f"📱 **Mensaje enviado a {member_name} por Telegram:**\n"
                        f"_{telegram_message}_"
                    ),
                    "sources_used": [
                        {"name": "calendar", "detail": "cross_agent", "confidence": 0.85},
                        {"name": "telegram_dm", "detail": f"sent to {member_name}", "confidence": 0.9},
                    ],
                }
            else:
                return {
                    "response": (
                        f"{cal_summary}\n\n"
                        f"⚠️ No pude enviar el mensaje por Telegram: {send_result.get('error', '')}\n"
                        f"¿Quieres que le envíe un email en su lugar?"
                    ),
                }

    # ─── CANAL: EMAIL ──────────────────────────────
    if channel == "email":
        # Resolver email del contacto si no lo tenemos
        if not person_email and person_name:
            try:
                from api.agents.email_agent import _search_contacts
                contacts = _search_contacts(empresa_id, user_id, person_name)
                if contacts and len(contacts) == 1:
                    person_email = contacts[0]["email"]
                elif contacts and len(contacts) > 1:
                    options = "\n".join(
                        f"{i+1}. **{c['name']}** — {c.get('org', '')} ({c['email']})"
                        for i, c in enumerate(contacts)
                    )
                    cal_summary = _format_calendar_only(calendar_result)
                    return {"response": f"{cal_summary}\n\nEncontré varios contactos:\n{options}\n\n¿A cuál te refieres?"}
            except Exception as e:
                print(f"CROSS AGENT: Contact resolution error: {e}")

        # Si tampoco por contactos, buscar en team_members
        if not person_email and person_name:
            try:
                from api.database import sync_engine
                from sqlalchemy import text as sql_text
                with sync_engine.connect() as conn:
                    row = conn.execute(
                        sql_text("""
                            SELECT u.email FROM usuarios u
                            WHERE u.empresa_id = :eid AND u.nombre ILIKE :name
                        """),
                        {"eid": empresa_id, "name": f"%{person_name}%"}
                    ).fetchone()
                    if row:
                        person_email = row.email
            except Exception:
                pass

        if not person_email:
            cal_summary = _format_calendar_only(calendar_result)
            return {"response": f"{cal_summary}\n\nNo encontré el email de {person_name}. ¿Me lo das?"}

        # Redactar email
        model, _ = selector.get_model("chat_with_tools")

        email_prompt = f"""Redacta un email breve y profesional.

DESTINATARIO: {person_name} ({person_email})
TIPO: {message_type}
CONTENIDO: {message_content}
CONTEXTO CALENDARIO: {json.dumps(calendar_result, ensure_ascii=False, default=str)[:300]}

REGLAS:
- Email corto (3-5 líneas)
- Usar el nombre del destinatario
- NO usar "Estimado/a" genérico
- Ir al punto directamente

Responde JSON: {{"subject": "...", "body": "..."}}"""

        response = await model.ainvoke([
            {"role": "system", "content": "Redacta emails profesionales y breves. Responde SOLO JSON."},
            {"role": "user", "content": email_prompt},
        ])

        try:
            raw = (response.content or "").strip().replace("```json", "").replace("```", "")
            email_data = json.loads(raw)
            subject = email_data.get("subject", "Actualización de reunión")
            body = email_data.get("body", message_content)
        except Exception:
            subject = "Actualización de reunión"
            body = message_content

        draft_result = gmail_draft(to=person_email, subject=subject, body=body, empresa_id=empresa_id, user_id=user_id)

        if isinstance(draft_result, dict) and "error" in draft_result:
            cal_summary = _format_calendar_only(calendar_result)
            return {"response": f"{cal_summary}\n\n⚠️ Error creando borrador: {draft_result['error']}"}

        cal_summary = _format_calendar_only(calendar_result)
        original_draft = f"Para: {person_email}\nAsunto: {subject}\n\n{body}"

        return {
            "response": (
                f"{cal_summary}\n\n"
                f"✉️ **Borrador de email:**\n\n"
                f"📬 **Para:** {person_email}\n"
                f"📝 **Asunto:** {subject}\n\n"
                f"💬 **Cuerpo:**\n{body}\n\n"
                f"---\n"
                f"¿Lo envío? Responde **sí** para confirmar o **no** para cancelar."
            ),
            "needs_approval": True,
            "draft_id": draft_result.get("draft_id", ""),
            "original_draft": original_draft,
            "sources_used": [
                {"name": "calendar", "detail": "cross_agent", "confidence": 0.85},
                {"name": "email", "detail": f"draft to {person_email}", "confidence": 0.88},
            ],
        }

    # Fallback
    return {"response": _format_calendar_only(calendar_result)}


def _format_calendar_only(result: dict) -> str:
    """Formatea resultado de calendario."""
    status = result.get("status", "")
    event = result.get("event", {})

    if status == "cancelled":
        return f"📅 **Reunión cancelada:** {event.get('summary', 'reunión')}\n🗓️ Era para: {event.get('start', 'N/D')}"
    elif status == "updated":
        return f"📅 **Reunión reagendada:** {event.get('summary', 'reunión')}\n🗓️ Nueva fecha: {result.get('new_date', 'N/D')}"
    elif status == "created":
        return f"📅 **Reunión creada:** {result.get('event_title', 'reunión')}\n🗓️ Fecha: {result.get('date', 'N/D')}"
    elif status == "not_found":
        return f"⚠️ No encontré eventos con '{result.get('query', '')}' en tu calendario."
    elif status == "skipped":
        return ""
    elif status == "error":
        return f"⚠️ Error en calendario: {result.get('message', '')}"
    return ""


# ─── Compilar grafo ──────────────────────────────────────
graph = StateGraph(CrossState)
graph.add_node("plan", plan_workflow)
graph.add_node("calendar", execute_calendar)
graph.add_node("message", send_message)
graph.set_entry_point("plan")
graph.add_edge("plan", "calendar")
graph.add_edge("calendar", "message")
graph.add_edge("message", END)
cross_agent = graph.compile()
