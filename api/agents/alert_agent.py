"""
Alert Agent — Evalúa eventos y notifica solo si es urgente.
Referencia: ADA_MIGRACION_V5_SECCIONES_10-15.md §10.6

Se activa por el Event Bus, NO por mensajes del usuario.
Filtra ruido: si el evento es trivial, lo ignora.
Si es urgente, notifica al admin por Telegram con acción sugerida.
"""

import json
from typing import TypedDict, Optional, List
from langgraph.graph import StateGraph, END
from models.selector import selector


class AlertState(TypedDict, total=False):
    event_type: str
    event_data: dict
    empresa_id: str

    # Internos
    urgency: str       # high, medium, low, ignore
    notification: str
    action_suggested: str

    # Output
    should_notify: bool
    response: str
    model_used: str


ALERT_PROMPT = """Eres Ada, asistente ejecutiva. Evalúa este evento del negocio.

REGLA PRINCIPAL: El CEO no quiere ser molestado por trivialidades.
Solo notifica si REALMENTE requiere atención o acción.

## Niveles de urgencia
- "high": Notificar INMEDIATAMENTE (dinero en riesgo, deadline perdido, error crítico)
- "medium": Notificar en resumen diario (info importante pero no urgente)
- "low": Registrar pero NO notificar (rutina normal)
- "ignore": No hacer nada (spam, duplicado, irrelevante)

## Ejemplos
- Email de cliente pidiendo cotización urgente → high
- Evento de calendario cancelado → medium
- Newsletter de marketing → ignore
- Factura vencida > 30 días → high
- Nuevo lead en CRM → medium
- Email de spam → ignore

Responde SOLO JSON:
{
    "urgency": "high|medium|low|ignore",
    "should_notify": true/false,
    "notification": "Texto corto para el CEO (máx 200 chars)",
    "action_suggested": "Acción concreta recomendada"
}
Sin markdown, sin explicación."""


async def evaluate_event(state: AlertState) -> dict:
    """Evalúa urgencia del evento con LLM."""
    model, model_name = selector.get_model("alert_evaluation")

    event_context = json.dumps({
        "type": state.get("event_type", ""),
        "data": state.get("event_data", {}),
    }, ensure_ascii=False, default=str)

    response = await model.ainvoke([
        {"role": "system", "content": ALERT_PROMPT},
        {"role": "user", "content": event_context},
    ])

    try:
        raw = response.content.strip().replace("```json", "").replace("```", "")
        result = json.loads(raw)
        urgency = result.get("urgency", "ignore")
        should_notify = result.get("should_notify", False)
        notification = result.get("notification", "")
        action = result.get("action_suggested", "")
    except (json.JSONDecodeError, AttributeError):
        urgency = "ignore"
        should_notify = False
        notification = ""
        action = ""

    print(f"ALERT AGENT: {state.get('event_type')} → urgency={urgency}, notify={should_notify}")

    return {
        "urgency": urgency,
        "should_notify": should_notify,
        "notification": notification,
        "action_suggested": action,
        "response": notification,
        "model_used": model_name,
    }


async def send_notification(state: AlertState) -> dict:
    """Envía notificación por Telegram si es necesario."""
    if not state.get("should_notify"):
        return {}

    urgency = state.get("urgency", "")
    notification = state.get("notification", "")
    action = state.get("action_suggested", "")

    emoji = {"high": "🔴", "medium": "🟡"}.get(urgency, "ℹ️")

    message = f"{emoji} **Alerta Ada**\n\n{notification}"
    if action:
        message += f"\n\n💡 Acción sugerida: {action}"

    # TODO: Enviar por Telegram al admin de la empresa
    # Por ahora solo loggea
    print(f"ALERT NOTIFICATION [{urgency}]: {notification}")
    print(f"ACTION: {action}")

    return {}


# ─── Compilar grafo ──────────────────────────────────────
graph = StateGraph(AlertState)
graph.add_node("evaluate", evaluate_event)
graph.add_node("notify", send_notification)
graph.set_entry_point("evaluate")
graph.add_edge("evaluate", "notify")
graph.add_edge("notify", END)
alert_agent = graph.compile()