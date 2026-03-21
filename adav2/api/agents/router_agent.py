"""
Router Agent - clasifica intent y ruta de agente.
"""

import json
from typing import TypedDict, Optional
from langgraph.graph import StateGraph, END
from models.selector import selector


class RouterState(TypedDict, total=False):
    message: str
    empresa_id: str
    user_id: str
    has_file: bool
    file_type: Optional[str]
    source: str

    intent: str
    confidence: float
    routed_to: str


ROUTER_PROMPT = """Clasifica el mensaje del usuario en UNA categoria:

- "calendar" -> Agenda, reuniones, citas, horarios, eventos especificos
- "email" -> Correo, emails, enviar, responder, buscar mails
- "data_query" -> Ventas, cartera, inventario, clientes, metricas, preguntas sobre datos
- "excel_analysis" -> SOLO si has_file=true y file_type=excel
- "image_analysis" -> SOLO si has_file=true y file_type=image
- "notion" -> Buscar/leer/crear en Notion
- "project" -> Plane, tareas, issues, sprints, tablero, proyectos
- "prospecting" -> Perfilar cliente o empresa
- "team" -> Gestion de equipo
- "action" -> Ejecutar accion concreta
- "briefing" -> Resumen del dia, como va el dia, que hay hoy, morning brief, resumen ejecutivo
- "conversational" -> Saludo, charla casual o pregunta general

Ejemplos de "briefing":
- "como va mi dia de hoy" → briefing
- "como va mi dia" → briefing
- "que tengo hoy" → briefing
- "resumen del dia" → briefing
- "resumen de hoy" → briefing
- "que hay para hoy" → briefing
- "dame mi briefing" → briefing
- "morning brief" → briefing
- "resumen ejecutivo de hoy" → briefing
- "que tengo pendiente hoy" → briefing
- "como esta mi agenda hoy" → briefing

Ejemplos de "calendar":
- "mis reuniones de mañana" → calendar
- "mi agenda de la semana" → calendar
- "eventos del viernes" → calendar
- "a que hora es mi reunion con Pedro" → calendar
- "agenda una reunion" → calendar
- "cancela la reunion" → calendar
- "que reuniones tengo esta semana" → calendar
- "busca en google calendar" → calendar
- "tengo algo el viernes" → calendar

Ejemplos de "project":
- "tareas pendientes en plane" → project
- "dame las tareas done" → project
- "busca proyectos en plane" → project
- "que tareas tiene Oswaldo" → project
- "issues del sprint" → project

Ejemplos de "data_query":
- "dame el reporte de ventas" → data_query
- "cual es el margen de distribuidora" → data_query
- "busca informacion sobre el cliente X" → data_query
- "cuales fueron las ventas del mes" → data_query

Default si no estas seguro: "data_query"

Responde SOLO JSON: {"intent": "...", "confidence": 0.0-1.0}
Sin markdown, sin explicacion."""


INTENT_AGENT_MAP = {
    "calendar": "calendar_agent",
    "email": "email_agent",
    "data_query": "multi_source_agent",
    "excel_analysis": "excel_analyst",
    "image_analysis": "image_analyst",
    "notion": "notion_agent",
    "project": "project_agent",
    "prospecting": "prospecting_agent",
    "team": "team_agent",
    "action": "chat_agent",
    "conversational": "chat_agent",
    "briefing": "morning_brief_agent",
}


async def classify_intent(state: RouterState) -> dict:
    model, _ = selector.get_model("routing")

    file_ctx = ""
    if state.get("has_file"):
        file_ctx = f"[has_file=true, file_type={state.get('file_type', 'unknown')}] "

    response = await model.ainvoke([
        {"role": "system", "content": ROUTER_PROMPT},
        {"role": "user", "content": f"{file_ctx}{state.get('message', '')}"}
    ])

    try:
        raw = (response.content or "").strip().replace("```json", "").replace("```", "")
        result = json.loads(raw)
        intent = result.get("intent", "data_query")
        confidence = float(result.get("confidence", 0.5))
    except Exception:
        intent = "data_query"
        confidence = 0.3

    if intent not in INTENT_AGENT_MAP:
        intent = "data_query"
        confidence = 0.3

    routed_to = INTENT_AGENT_MAP[intent]

    print(f"ROUTER: '{state.get('message', '')[:50]}...' -> {intent} ({confidence}) -> {routed_to}")

    return {
        "intent": intent,
        "confidence": confidence,
        "routed_to": routed_to,
    }


graph = StateGraph(RouterState)
graph.add_node("classify", classify_intent)
graph.set_entry_point("classify")
graph.add_edge("classify", END)
router_agent = graph.compile()