"""
Router Agent - clasifica intent y ruta de agente.
"""

import json
from typing import TypedDict, Optional
from langgraph.graph import StateGraph, END
from models.selector import selector
from api.agents.chat_agent import get_history


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

- "calendar" -> Agenda, reuniones, citas, horarios, eventos
- "email" -> Correo, emails, enviar, responder
- "data_query" -> Dato puntual de UN reporte: "cuanto vendimos ayer", "margen del ultimo reporte", "clientes nuevos esta semana"
- "data_consolidation" -> Agregar MULTIPLES reportes de un periodo: "reporte anual", "consolidado trimestral", "como fue el año", "tendencias del semestre", "resumen de los ultimos 6 meses", "comparar Q1 vs Q2", "evolucion de ventas 2025"
- "excel_analysis" -> SOLO si has_file=true y file_type=excel
- "image_analysis" -> SOLO si has_file=true y file_type=image
- "notion" -> Buscar/leer/crear en Notion, bases de datos de Notion
- "project" -> Gestión de tareas/issues/sprints en general: "tareas pendientes", "backlog del sprint", "crear tarea", "actualizar issue". NO usar cuando preguntan por una persona específica.
- "entity_360" -> Cuando preguntan POR una persona o empresa específica: "háblame de Juan", "qué sabes de Empresa X", "en qué participa Oswaldo", "qué relación tenemos con María", "todo sobre Carlos". Incluye preguntas sobre participación en proyectos, tareas asignadas, reuniones, emails — cualquier cosa que pida información CRUZADA sobre una entidad.
- "prospecting" -> Perfilar un cliente o empresa NUEVA que Ada no conoce: "perfila a empresa X", "investiga a este prospecto". NO usar cuando preguntan sobre alguien que ya está en el sistema.
- "team" -> Gestion de equipo interno (roles, permisos, miembros)
- "action" -> Ejecutar accion concreta
- "briefing" -> Briefing ejecutivo o resumen diario, "dame el brief de hoy"
- "configure_brief" -> Activar, desactivar o cambiar hora del brief diario: "activa el brief a las 6am", "desactiva el brief", "cambia el brief a las 9", "envíame el brief todos los dias a las 7"
- "onboarding" -> Configurar Ada, configurar empresa, hacer onboarding, setup inicial: "quiero configurar mi empresa", "configurar Ada", "hacer el onboarding", "setup"
- "my_company" -> Preguntas sobre MI propia empresa: "qué sabes de mi empresa", "háblame de mi empresa", "datos de mi empresa". NO confundir con entity_360 que es para terceros.
- "my_memories" -> El usuario pregunta qué sabe Ada de él: "qué sabes de mí", "qué recuerdas", "qué has aprendido de mí", "que sabes de mi"
- "explicit_memory" -> El usuario pide que Ada recuerde algo: "recuerda que", "ten en cuenta que", "no olvides que", "anota que"
- "cross_agent" -> Acciones que combinan calendario + mensajería: "cancela la reunión y avísale", "agenda con X y mándale email", "reagenda y dile por Telegram", "avísale urgente que se canceló la reunión"
- "conversational" -> Saludo, charla casual o pregunta general

DIFERENCIA CLAVE:
- data_query = consulta sobre dato especifico o reporte individual
- data_consolidation = analisis que cruza multiples reportes o periodos largos
- project = gestión de tareas/issues en general, sin referirse a una persona específica
- entity_360 = información cruzada sobre una persona o empresa específica

EJEMPLOS:
- "háblame de Oswaldo Gutierrez" → entity_360
- "qué sabes de Insights 4.0?" → entity_360
- "en qué proyectos participa María?" → entity_360
- "todo sobre Carlos Restrepo" → entity_360
- "qué relación tenemos con esa empresa?" → entity_360
- "qué tareas tiene Carlos?" → entity_360
- "muéstrame las tareas pendientes" → project
- "quién está asignado al sprint?" → project
- "crear tarea en Plane" → project
- "busca a María en notion" → notion
- "qué hay en la base de datos de clientes en notion?" → notion
- "reuniones de mañana" → calendar
- "eventos del proyecto X" → calendar

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
    "entity_360": "entity_360_agent",
    "prospecting": "prospecting_agent",
    "team": "team_agent",
    "action": "chat_agent",
    "conversational": "chat_agent",
    "briefing": "morning_brief_agent",
    "configure_brief": "chat_agent",
    "onboarding": "chat_agent",
    "my_company": "chat_agent",
    "my_memories": "chat_agent",
    "explicit_memory": "chat_agent",
    "cross_agent": "cross_agent",
    "follow_up": "chat_agent",
}


async def classify_intent(state: RouterState) -> dict:
    # PRIORIDAD MÁXIMA: Si hay sesión de onboarding activa, TODO va a onboarding
    from api.agents.onboarding_agent import _onboarding_sessions
    empresa_id = state.get("empresa_id", "")
    if empresa_id and empresa_id in _onboarding_sessions:
        session = _onboarding_sessions[empresa_id]
        if session.get("step") != "welcome":
            print(f"ROUTER: Onboarding session active (step={session['step']}) -> forcing onboarding")
            return {"intent": "onboarding", "confidence": 1.0, "routed_to": "chat_agent"}

    # WHITELIST: saludos siempre van a conversational
    msg_lower = (state.get("message", "") or "").lower().strip()
    greeting_patterns = [
        "hola", "buenos dias", "buenos días", "buenas tardes", "buenas noches",
        "buen dia", "buen día", "como estas", "cómo estás", "que tal", "qué tal",
        "hey", "hi", "hello", "good morning", "saludos",
    ]
    if msg_lower in greeting_patterns or any(msg_lower == p for p in greeting_patterns):
        print(f"ROUTER: greeting detected -> conversational")
        return {
            "intent": "conversational",
            "confidence": 1.0,
            "routed_to": "chat_agent",
        }

    # WHITELIST: preguntas sobre MI empresa -> chat_agent con handler dedicado
    my_company_triggers = [
        "qué sabes de mi empresa", "que sabes de mi empresa",
        "cuéntame de mi empresa", "cuentame de mi empresa",
        "háblame de mi empresa", "hablame de mi empresa",
        "información de mi empresa", "informacion de mi empresa",
        "datos de mi empresa", "perfil de mi empresa",
    ]
    if any(trigger in msg_lower for trigger in my_company_triggers):
        print(f"ROUTER: my_company detected")
        return {"intent": "my_company", "confidence": 1.0, "routed_to": "chat_agent"}

    # Detectar nombre de empresa del usuario para no confundir con entity_360
    empresa_id = state.get("empresa_id", "")
    if empresa_id:
        try:
            from api.database import sync_engine
            from sqlalchemy import text as _sql
            with sync_engine.connect() as conn:
                row = conn.execute(
                    _sql("SELECT company_name FROM ada_company_profile WHERE empresa_id = :eid"),
                    {"eid": empresa_id}
                ).fetchone()
                if row and row.company_name:
                    company_name_lower = row.company_name.lower().strip()
                    if company_name_lower in msg_lower and any(w in msg_lower for w in ["sabes", "háblame", "hablame", "cuéntame", "cuentame", "información", "informacion", "qué es", "que es"]):
                        print(f"ROUTER: Company name '{row.company_name}' detected -> my_company")
                        return {"intent": "my_company", "confidence": 1.0, "routed_to": "chat_agent"}
        except Exception as e:
            print(f"ROUTER: Error checking company name: {e}")

    # WHITELIST: "qué sabes de mí" (exact match para no atrapar "qué sabes de mi empresa")
    my_memory_exact = [
        "qué sabes de mí", "que sabes de mi", "qué recuerdas de mí",
        "que recuerdas de mi", "qué has aprendido de mí", "que has aprendido de mi",
    ]
    cleaned = msg_lower.rstrip("?!., ")
    if cleaned in my_memory_exact:
        print(f"ROUTER: my_memories detected")
        return {"intent": "my_memories", "confidence": 1.0, "routed_to": "chat_agent"}

    # WHITELIST: "recuerda que..."
    explicit_prefixes = ["recuerda que ", "ten en cuenta que ", "no olvides que ", "anota que "]
    if any(msg_lower.startswith(p) for p in explicit_prefixes):
        print(f"ROUTER: explicit_memory detected")
        return {"intent": "explicit_memory", "confidence": 1.0, "routed_to": "chat_agent"}

    # WHITELIST: onboarding
    onboarding_triggers = [
        "configurar mi empresa", "configurar ada", "quiero hacer el onboarding",
        "hacer el onboarding", "onboarding", "setup de ada", "setup de mi empresa",
        "configurar la empresa", "quiero configurar",
    ]
    if any(trigger in msg_lower for trigger in onboarding_triggers):
        print(f"ROUTER: onboarding detected")
        return {"intent": "onboarding", "confidence": 1.0, "routed_to": "chat_agent"}

    # WHITELIST: cross-agent (calendar + mensajería combinados)
    calendar_words = ["reunión", "reunion", "agenda", "agendar", "reagendar", "reagenda",
                      "cancelar reunión", "cancelar reunion", "cita", "evento"]
    message_words = ["avísale", "avisale", "avísele", "avisele", "mándale", "mandale",
                     "envíale", "enviale", "escríbele", "escribele", "notifícale", "notificale",
                     "dile", "correo", "email", "mail", "mensaje"]
    has_calendar = any(w in msg_lower for w in calendar_words)
    has_message = any(w in msg_lower for w in message_words)
    if has_calendar and has_message:
        print(f"ROUTER: cross_agent detected (calendar + message)")
        return {"intent": "cross_agent", "confidence": 1.0, "routed_to": "cross_agent"}

    # WHITELIST: mensaje urgente interno (sin calendario pero es DM)
    urgent_patterns = [
        "dile a ", "avísale a ", "avisale a ", "notifícale a ", "notificale a ",
        "mándale mensaje a ", "mandale mensaje a ", "envíale mensaje a ",
    ]
    if any(msg_lower.startswith(p) for p in urgent_patterns):
        print(f"ROUTER: cross_agent detected (internal message)")
        return {"intent": "cross_agent", "confidence": 1.0, "routed_to": "cross_agent"}

    # WHITELIST: configurar follow-up de email
    follow_up_triggers = [
        "si no responde", "si no contesta", "si no contestan",
        "recuérdale", "recuerdale", "follow up", "follow-up", "followup",
        "hazle seguimiento", "dale seguimiento",
    ]
    if any(trigger in msg_lower for trigger in follow_up_triggers):
        print(f"ROUTER: follow_up detected")
        return {"intent": "follow_up", "confidence": 1.0, "routed_to": "chat_agent"}

    model, _ = selector.get_model("routing")

    file_ctx = ""
    if state.get("has_file"):
        file_ctx = f"[has_file=true, file_type={state.get('file_type', 'unknown')}] "

    # Contexto conversacional para el router
    conversation_hint = ""
    empresa_id = state.get("empresa_id", "")
    user_id = state.get("user_id", "")

    history = []
    if empresa_id and user_id:
        try:
            history = get_history(empresa_id, user_id)
        except Exception as e:
            print(f"ROUTER: history hint error: {e}")

    # DETECCIÓN DETERMINÍSTICA: Si el mensaje tiene pronombres y el historial
    # habla de una persona/entidad, forzar entity_360
    msg_lower = (state.get("message", "") or "").lower().strip()
    pronoun_markers = [
        "de él", "de el", "de ella", "sobre él", "sobre el", "sobre ella",
        "completa de él", "completa de el", "información de él", "informacion de el",
        "todo sobre él", "todo sobre el", "todo de él", "todo de el",
    ]

    has_pronoun = any(p in msg_lower for p in pronoun_markers)

    if has_pronoun and history:
        # Verificar si en los últimos mensajes del usuario se mencionó una persona
        import re as _re
        for msg_entry in reversed(history[-6:]):
            if msg_entry.get("role") != "user":
                continue
            content = msg_entry.get("content", "")
            # Buscar nombres propios (2+ palabras con mayúscula)
            name_match = _re.findall(r'\b([A-ZÁÉÍÓÚÑ][a-záéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+)+)\b', content)
            if name_match:
                print(f"ROUTER: pronoun detected -> forcing entity_360 (last entity: '{name_match[-1]}')")
                return {
                    "intent": "entity_360",
                    "confidence": 0.95,
                    "routed_to": "entity_360_agent",
                }

    # Si hay historial, construir hint para el LLM
    if history:
        recent = history[-4:]
        recent_text = "\n".join(
            f"{m.get('role','user')}: {m.get('content','')[:150]}"
            for m in recent
        )
        conversation_hint = f"\n[CONTEXTO: La conversación reciente trata sobre:\n{recent_text}\n]\nSi el usuario pide más detalles, alertas o profundizar sobre un tema ya en curso, clasifica como data_query, NO como data_consolidation."

    response = await model.ainvoke([
        {"role": "system", "content": ROUTER_PROMPT},
        {"role": "user", "content": f"{file_ctx}{state.get('message', '')}{conversation_hint}"}
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
