"""
Calendar Agent - protocolo operacional estricto.
"""

import json
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


CALENDAR_SYSTEM_PROMPT = """Eres Ada, asistente ejecutiva de agenda.

Protocolo estricto:
- crear evento: primero availability, luego create_event
- actualizar evento: primero get_events/search, luego update_event
- borrar evento: primero get_events/search, luego delete_event
- Fechas SIEMPRE ISO 8601 completo: YYYY-MM-DDTHH:MM:SS

Responde SOLO JSON:
{
  "action": "list|search|create|update|delete|availability",
  "params": {}
}
"""


def _is_iso_datetime(value: str) -> bool:
    if not value or "T" not in value:
        return False
    try:
        datetime.fromisoformat(value)
        return True
    except ValueError:
        return False


async def classify_calendar_action(state: CalendarState) -> dict:
    model, model_name = selector.get_model("routing")

    # Limpiar contexto conversacional residual si se coló
    msg = state.get("message", "")
    for marker in ["[CONTEXTO CONVERSACIONAL RECIENTE:", "CONVERSACIÓN RECIENTE:"]:
        if marker in msg:
            msg = msg.split(marker)[0].strip()

    response = await model.ainvoke([
        {"role": "system", "content": CALENDAR_SYSTEM_PROMPT},
        {"role": "user", "content": msg},
    ])

    try:
        raw = (response.content or "").strip().replace("```json", "").replace("```", "")
        result = json.loads(raw)
        action = result.get("action", "list")
        params = result.get("params", {})
    except Exception:
        action = "list"
        params = {"days_ahead": 7}

    return {
        "action": action,
        "action_params": params,
        "model_used": model_name,
    }


async def execute_calendar_action(state: CalendarState) -> dict:
    action = state.get("action", "")
    params = state.get("action_params", {})
    empresa_id = state.get("empresa_id", "")
    user_id = state.get("user_id", "")

    if action == "list":
        days = int(params.get("days_ahead", 7))
        events = calendar_list_events(days_ahead=days, empresa_id=empresa_id, user_id=user_id)
        if not events:
            return {
                "response": f"No tienes eventos en los proximos {days} dias.",
                "sources_used": [{"name": "calendar", "detail": "list_events", "confidence": 0.8}],
            }
        formatted = "\n".join([f"- {e['summary']} ({e['start']})" for e in events])
        return {
            "response": f"Eventos ({len(events)}):\n{formatted}",
            "sources_used": [{"name": "calendar", "detail": "list_events", "confidence": 0.82}],
        }

    if action == "search":
        query = params.get("query", state.get("message", ""))
        events = calendar_search_events(query, empresa_id=empresa_id, user_id=user_id)
        if not events:
            return {
                "response": f"No encontre eventos con '{query}'.",
                "sources_used": [{"name": "calendar", "detail": "search_events", "confidence": 0.78}],
            }
        formatted = "\n".join([f"- {e['summary']} ({e['start']})" for e in events])
        return {
            "response": f"Eventos encontrados ({len(events)}):\n{formatted}",
            "sources_used": [{"name": "calendar", "detail": "search_events", "confidence": 0.82}],
        }

    if action == "create":
        summary = params.get("summary", "")
        start = params.get("start_datetime", "")
        end = params.get("end_datetime", "")
        description = params.get("description", "")
        location = params.get("location", "")
        attendees = params.get("attendees", [])

        if not summary or not start:
            return {"response": "Para crear evento necesito summary y start_datetime (ISO 8601)."}

        if not _is_iso_datetime(start):
            return {"response": "start_datetime invalido. Usa ISO 8601 completo: YYYY-MM-DDTHH:MM:SS"}

        if not end:
            end = (datetime.fromisoformat(start) + timedelta(hours=1)).isoformat()

        if not _is_iso_datetime(end):
            return {"response": "end_datetime invalido. Usa ISO 8601 completo: YYYY-MM-DDTHH:MM:SS"}

        # protocolo: availability -> create_event
        avail = calendar_get_availability(days_ahead=7, empresa_id=empresa_id, user_id=user_id)
        result = calendar_create_event(
            summary=summary,
            start_datetime=start,
            end_datetime=end,
            description=description,
            location=location,
            attendees=attendees,
            empresa_id=empresa_id,
            user_id=user_id,
        )

        if "error" in result:
            return {"response": f"Error creando evento: {result['error']}"}

        return {
            "response": (
                f"Evento creado: {summary} ({start} -> {end}). "
                f"Agenda actual: {avail.get('total_events', 0)} eventos en ventana consultada."
            ),
            "sources_used": [
                {"name": "calendar", "detail": "availability", "confidence": 0.78},
                {"name": "calendar", "detail": "create_event", "confidence": 0.86},
            ],
        }

    if action == "update":
        query = params.get("query", "")
        event_id = params.get("event_id", "")

        # protocolo: get_events/search -> update
        target_event = None
        if event_id:
            target_event = {"id": event_id}
        else:
            if not query:
                return {"response": "Para actualizar necesito event_id o query para buscar el evento."}
            found = calendar_search_events(query, max_results=1, empresa_id=empresa_id, user_id=user_id)
            if not found:
                return {"response": f"No encontre evento para actualizar con '{query}'."}
            target_event = found[0]

        result = calendar_update_event(
            event_id=target_event["id"],
            summary=params.get("summary"),
            start_datetime=params.get("start_datetime"),
            end_datetime=params.get("end_datetime"),
            description=params.get("description"),
            location=params.get("location"),
            empresa_id=empresa_id,
            user_id=user_id,
        )
        if "error" in result:
            return {"response": f"Error actualizando evento: {result['error']}"}

        return {
            "response": "Evento actualizado correctamente.",
            "sources_used": [
                {"name": "calendar", "detail": "search_events", "confidence": 0.79},
                {"name": "calendar", "detail": "update_event", "confidence": 0.85},
            ],
        }

    if action == "delete":
        query = params.get("query", "")
        event_id = params.get("event_id", "")

        # protocolo: get_events/search -> delete
        if not event_id:
            if not query:
                return {"response": "Para borrar necesito event_id o query para buscar el evento."}
            found = calendar_search_events(query, max_results=1, empresa_id=empresa_id, user_id=user_id)
            if not found:
                return {"response": f"No encontre evento para eliminar con '{query}'."}
            event_id = found[0]["id"]

        result = calendar_delete_event(event_id, empresa_id=empresa_id, user_id=user_id)
        if "error" in result:
            return {"response": f"Error eliminando evento: {result['error']}"}

        return {
            "response": "Evento eliminado correctamente.",
            "sources_used": [
                {"name": "calendar", "detail": "search_events", "confidence": 0.79},
                {"name": "calendar", "detail": "delete_event", "confidence": 0.85},
            ],
        }

    if action == "availability":
        days = int(params.get("days_ahead", 7))
        avail = calendar_get_availability(days_ahead=days, empresa_id=empresa_id, user_id=user_id)
        return {
            "response": f"Disponibilidad consultada: {avail.get('total_events', 0)} eventos en {days} dias.",
            "sources_used": [{"name": "calendar", "detail": "availability", "confidence": 0.82}],
        }

    return {"response": f"No entendi la accion '{action}'."}


graph = StateGraph(CalendarState)
graph.add_node("classify", classify_calendar_action)
graph.add_node("execute", execute_calendar_action)
graph.set_entry_point("classify")
graph.add_edge("classify", "execute")
graph.add_edge("execute", END)
calendar_agent = graph.compile()
