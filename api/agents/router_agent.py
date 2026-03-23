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

- "calendar" -> Agenda, reuniones, citas, horarios
- "email" -> Correo, emails, enviar, responder
- "data_query" -> Dato puntual de UN reporte: "cuanto vendimos ayer", "margen del ultimo reporte", "clientes nuevos esta semana"
- "data_consolidation" -> Agregar MULTIPLES reportes de un periodo: "reporte anual", "consolidado trimestral", "como fue el año", "tendencias del semestre", "resumen de los ultimos 6 meses", "comparar Q1 vs Q2", "evolucion de ventas 2025"
- "excel_analysis" -> SOLO si has_file=true y file_type=excel
- "image_analysis" -> SOLO si has_file=true y file_type=image
- "notion" -> Buscar/leer/crear en Notion
- "project" -> Plane, tareas, issues, sprints, tablero
- "prospecting" -> Perfilar cliente o empresa
- "team" -> Gestion de equipo
- "action" -> Ejecutar accion concreta
- "briefing" -> Briefing ejecutivo o resumen diario
- "conversational" -> Saludo, charla casual o pregunta general

DIFERENCIA CLAVE:
- data_query = consulta sobre dato especifico o reporte individual
- data_consolidation = analisis que cruza multiples reportes o periodos largos

Default si no estas seguro: "data_query"

Responde SOLO JSON: {"intent": "...", "confidence": 0.0-1.0}
Sin markdown, sin explicacion."""


INTENT_AGENT_MAP = {
    "calendar": "calendar_agent",
    "email": "email_agent",
    "data_query": "chat_agent",
    "data_consolidation": "consolidation_agent",
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
