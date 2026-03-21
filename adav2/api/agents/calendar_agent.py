"""
Calendar Agent - protocolo operacional estricto.
"""

import json
import re
from datetime import datetime, timedelta
from typing import TypedDict

from langgraph.graph import StateGraph, END
from models.selector import selector
from api.services.calendar_service import (
    calendar_list_events,
    calendar_search_events,
    calendar_create_event,
    calendar_update_event,
    calendar_delete_event,
    calendar_get_availability,
)


def _parse_relative_date(message: str) -> dict:
    """
    Convierte frases de fecha relativa a time_min/time_max.
    Usa rango amplio (+/-12h) para cubrir todas las zonas horarias.
    """
    now = datetime.utcnow()
    msg = message.lower()

    if "pasado" in msg and "mañana" in msg:
        # Pasado mañana
        base = now + timedelta(days=2)
        t_min = base.replace(hour=0, minute=0, second=0) - timedelta(hours=12)
        t_max = base.replace(hour=23, minute=59, second=59) + timedelta(hours=12)
    elif "proxima semana" in msg or "próxima semana" in msg:
        base = now + timedelta(days=7)
        return {
            "time_min": (base.replace(hour=0, minute=0, second=0) - timedelta(hours=12)).isoformat() + "Z",
            "time_max": (base + timedelta(days=7)).replace(hour=23, minute=59, second=59).isoformat() + "Z",
            "days_ahead": 14,
        }
    elif "ayer" in msg:
        # Ayer: desde 12h antes de medianoche de ayer hasta medianoche de hoy
        base = now - timedelta(days=1)
        t_min = base.replace(hour=0, minute=0, second=0) - timedelta(hours=12)
        t_max = now  # hasta ahora para no perder eventos
    elif "mañana" in msg and "hoy" not in msg:
        base = now + timedelta(days=1)
        t_min = base.replace(hour=0, minute=0, second=0) - timedelta(hours=12)
        t_max = base.replace(hour=23, minute=59, second=59) + timedelta(hours=12)
    else:
        # Hoy: desde 12h antes hasta 12h después para cubrir cualquier zona
        t_min = now - timedelta(hours=12)
        t_max = now + timedelta(hours=36)  # cubre hoy en cualquier zona horaria

    days_ahead = max(1, (t_max.date() - now.date()).days + 1)

    return {
        "time_min": t_min.isoformat() + "Z",
        "time_max": t_max.isoformat() + "Z",
        "days_ahead": days_ahead,
    }


def _resolve_relative_dates(params: dict, message: str) -> dict:
    """Convierte fechas relativas a valores reales para params del LLM."""
    now = datetime.now()
    lower = message.lower()

    if "days_ahead" not in params:
        if "mañana" in lower and "hoy" not in lower:
            params["days_ahead"] = 2
        elif "hoy" in lower or "tarde" in lower or "noche" in lower:
            params["days_ahead"] = 2  # amplio para zonas horarias
        elif "semana" in lower:
            params["days_ahead"] = 7
        elif "mes" in lower:
            params["days_ahead"] = 30
        else:
            params["days_ahead"] = 7

    start = params.get("start_datetime", "")
    if start and not _is_iso_datetime(start):
        if "mañana" in start.lower() or ("mañana" in lower and "hoy" not in lower):
            dt = now + timedelta(days=1)
        else:
            dt = now

        hour_match = re.search(r'(\d{1,2})\s*(?::|h)\s*(\d{2})?\s*(am|pm|a\.m\.|p\.m\.)?', lower)
        if hour_match:
            hour = int(hour_match.group(1))
            minute = int(hour_match.group(2) or 0)
            ampm = hour_match.group(3) or ""
            if "pm" in ampm or "p.m" in ampm:
                if hour < 12:
                    hour += 12
            dt = dt.replace(hour=hour, minute=minute, second=0)
        else:
            dt = dt.replace(hour=9, minute=0, second=0)

        params["start_datetime"] = dt.isoformat()

    return params


class CalendarState(TypedDict, total=False):
    message: str
    empresa_id: str
    user_id: str
    intent: str

    action: str
    action_params: dict
    needs_approval: bool

    response: str
    model_used: str
    sources_used: list


CALENDAR_SYSTEM_PROMPT = """Eres Ada, asistente ejecutiva de agenda. Clasifica la intención del usuario y responde JSON.

ACCIONES DISPONIBLES:
- "list": ver eventos de un período (hoy, mañana, esta semana)
- "search": buscar un evento específico por nombre o persona
- "create": crear un nuevo evento
- "update": modificar un evento existente
- "delete": eliminar un evento
- "availability": consultar disponibilidad

EJEMPLOS DE CLASIFICACIÓN:
- "que eventos tengo hoy" → {"action": "list", "params": {"days_ahead": 2}}
- "eventos de ayer" → {"action": "list", "params": {"days_ahead": 1}}
- "que tuve ayer" → {"action": "list", "params": {"days_ahead": 1}}
- "que reuniones tuve hoy" → {"action": "list", "params": {"days_ahead": 2}}
- "eventos de hoy en la noche" → {"action": "list", "params": {"days_ahead": 2}}
- "eventos de mañana" → {"action": "list", "params": {"days_ahead": 3}}
- "mi agenda de esta semana" → {"action": "list", "params": {"days_ahead": 7}}
- "busca la reunion con Pedro" → {"action": "search", "params": {"query": "Pedro"}}
- "tengo algo con Kompatech" → {"action": "search", "params": {"query": "Kompatech"}}
- "agenda reunion mañana a las 3pm con Juan" → {"action": "create", "params": {"summary": "Reunion con Juan", "start_datetime": "mañana 15:00"}}
- "cancela la reunion de hoy" → {"action": "delete", "params": {"query": "reunion hoy"}}
- "mueve la reunion al viernes" → {"action": "update", "params": {"query": "reunion"}}

REGLA IMPORTANTE: Para ver eventos de un período usa SIEMPRE "list", nunca "search" ni "get_events".
Para buscar un evento específico por nombre usa "search".

Responde SOLO JSON sin markdown:
{"action": "...", "params": {...}}"""


def _is_iso_datetime(value: str) -> bool:
    if not value or "T" not in value:
        return False
    try:
        datetime.fromisoformat(value)
        return True
    except ValueError:
        return False


def _format_event(e: dict) -> str:
    """Formatea un evento de forma legible."""
    start = e.get("start", "")
    # Convertir ISO a formato legible
    try:
        if "T" in start:
            dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
            start_fmt = dt.strftime("%d/%m/%Y %H:%M")
        else:
            start_fmt = start
    except Exception:
        start_fmt = start

    summary = e.get("summary", "Sin título")
    location = f" 📍 {e['location']}" if e.get("location") else ""
    attendees = e.get("attendees", [])
    att_str = f" 👥 {', '.join(attendees[:3])}" if attendees else ""

    return f"• {summary} — {start_fmt}{location}{att_str}"


async def classify_calendar_action(state: CalendarState) -> dict:
    model, model_name = selector.get_model("routing")

    response = await model.ainvoke([
        {"role": "system", "content": CALENDAR_SYSTEM_PROMPT},
        {"role": "user", "content": state.get("message", "")},
    ])

    try:
        raw = (response.content or "").strip().replace("```json", "").replace("```", "").strip()
        result = json.loads(raw)
        action = result.get("action", "list")
        params = result.get("params", {})
    except Exception as e:
        print(f"CALENDAR classify error: {e}, raw: {response.content[:100] if response else ''}")
        action = "list"
        params = {"days_ahead": 2}

    # Guardia: si el LLM generó una acción inválida, corregir
    valid_actions = {"list", "search", "create", "update", "delete", "availability"}
    if action not in valid_actions:
        print(f"CALENDAR: acción inválida '{action}', usando 'list'")
        action = "list"
        params = {"days_ahead": 2}

    print(f"CALENDAR classify: action={action}, params={params}")

    return {
        "action": action,
        "action_params": params,
        "model_used": model_name,
    }


async def execute_calendar_action(state: CalendarState) -> dict:
    action = state.get("action", "")
    params = state.get("action_params", {})
    empresa_id = state.get("empresa_id", "")
    message = state.get("message", "")

    # Resolver fechas relativas
    params = _resolve_relative_dates(params, message)

    if action == "list":
        date_range = _parse_relative_date(message)
        days = date_range["days_ahead"]
        events = calendar_list_events(
            days_ahead=days,
            empresa_id=empresa_id,
            time_min=date_range["time_min"],
            time_max=date_range["time_max"],
        )
        if not events:
            return {
                "response": "No tienes eventos en ese período.",
                "sources_used": [{"name": "google_calendar", "detail": "list_events", "confidence": 0.9}],
            }
        formatted = "\n".join([_format_event(e) for e in events])
        return {
            "response": f"Eventos ({len(events)}):\n\n{formatted}",
            "sources_used": [{"name": "google_calendar", "detail": "list_events", "confidence": 0.9}],
        }

    if action == "search":
        query = params.get("query", "")
        if not query:
            query = message
        date_range = _parse_relative_date(message)
        days = date_range["days_ahead"]
        events = calendar_search_events(
            query,
            days_ahead=days,
            empresa_id=empresa_id,
            time_min=date_range["time_min"],
            time_max=date_range["time_max"],
        )
        if not events:
            # Fallback: listar todos del período
            events = calendar_list_events(
                days_ahead=days,
                empresa_id=empresa_id,
                time_min=date_range["time_min"],
                time_max=date_range["time_max"],
            )
        if not events:
            return {
                "response": f"No encontré eventos para '{query}'.",
                "sources_used": [{"name": "google_calendar", "detail": "search_events", "confidence": 0.85}],
            }
        formatted = "\n".join([_format_event(e) for e in events])
        return {
            "response": f"Eventos encontrados ({len(events)}):\n\n{formatted}",
            "sources_used": [{"name": "google_calendar", "detail": "search_events", "confidence": 0.9}],
        }

    if action == "create":
        summary = params.get("summary", "")
        start = params.get("start_datetime", "")
        end = params.get("end_datetime", "")
        description = params.get("description", "")
        location = params.get("location", "")
        attendees = params.get("attendees", [])

        if not summary or not start:
            return {"response": "Para crear evento necesito el título y la fecha/hora."}

        if not _is_iso_datetime(start):
            return {"response": "Fecha inválida. Usa formato: YYYY-MM-DDTHH:MM:SS"}

        if not end:
            end = (datetime.fromisoformat(start) + timedelta(hours=1)).isoformat()

        avail = calendar_get_availability(days_ahead=7, empresa_id=empresa_id)
        result = calendar_create_event(
            summary=summary,
            start_datetime=start,
            end_datetime=end,
            description=description,
            location=location,
            attendees=attendees,
            empresa_id=empresa_id,
        )

        if "error" in result:
            return {"response": f"Error creando evento: {result['error']}"}

        return {
            "response": f"Evento creado: {summary} ({start}). Tienes {avail.get('total_events', 0)} eventos en la próxima semana.",
            "sources_used": [{"name": "google_calendar", "detail": "create_event", "confidence": 0.9}],
        }

    if action == "update":
        query = params.get("query", "")
        event_id = params.get("event_id", "")

        target_event = None
        if event_id:
            target_event = {"id": event_id}
        else:
            if not query:
                return {"response": "¿Qué evento quieres actualizar? Dime el nombre o tema."}
            found = calendar_search_events(query, max_results=1, empresa_id=empresa_id)
            if not found:
                return {"response": f"No encontré evento con '{query}'."}
            target_event = found[0]

        result = calendar_update_event(
            event_id=target_event["id"],
            summary=params.get("summary"),
            start_datetime=params.get("start_datetime"),
            end_datetime=params.get("end_datetime"),
            description=params.get("description"),
            location=params.get("location"),
            empresa_id=empresa_id,
        )
        if "error" in result:
            return {"response": f"Error actualizando: {result['error']}"}

        return {
            "response": "Evento actualizado correctamente.",
            "sources_used": [{"name": "google_calendar", "detail": "update_event", "confidence": 0.9}],
        }

    if action == "delete":
        query = params.get("query", "")
        event_id = params.get("event_id", "")

        if not event_id:
            if not query:
                return {"response": "¿Qué evento quieres eliminar? Dime el nombre o tema."}
            found = calendar_search_events(query, max_results=1, empresa_id=empresa_id)
            if not found:
                return {"response": f"No encontré evento con '{query}'."}
            event_id = found[0]["id"]

        result = calendar_delete_event(event_id, empresa_id=empresa_id)
        if "error" in result:
            return {"response": f"Error eliminando: {result['error']}"}

        return {
            "response": "Evento eliminado correctamente.",
            "sources_used": [{"name": "google_calendar", "detail": "delete_event", "confidence": 0.9}],
        }

    if action == "availability":
        days = int(params.get("days_ahead", 7))
        avail = calendar_get_availability(days_ahead=days, empresa_id=empresa_id)
        return {
            "response": f"Tienes {avail.get('total_events', 0)} eventos en los próximos {days} días.",
            "sources_used": [{"name": "google_calendar", "detail": "availability", "confidence": 0.9}],
        }

    return {"response": f"No entendí la acción '{action}'. Puedo listar, buscar, crear, actualizar o eliminar eventos."}


graph = StateGraph(CalendarState)
graph.add_node("classify", classify_calendar_action)
graph.add_node("execute", execute_calendar_action)
graph.set_entry_point("classify")
graph.add_edge("classify", "execute")
graph.add_edge("execute", END)
calendar_agent = graph.compile()