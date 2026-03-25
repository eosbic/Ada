"""
Entity 360 Agent — Vista completa de una persona o empresa cruzando TODAS las fuentes.

Este es el agente central de Ada. Cuando preguntan por una persona o empresa,
consulta RAG, Plane, Notion, Calendar, Gmail y Knowledge Graph en paralelo,
y consolida toda la información en una respuesta unificada.
"""

import json
import asyncio
import unicodedata
from typing import TypedDict, Optional, List, Dict
from langgraph.graph import StateGraph, END
from models.selector import selector
from api.services.memory_service import search_memory, search_reports, search_reports_qdrant, search_vector_store1
from api.services.graph_navigator import get_entity_360
from api.agents.chat_agent import get_history, save_history


def _normalize(text: str) -> str:
    """Quita acentos y convierte a minúscula para comparación fuzzy."""
    text = (text or "").lower()
    nfkd = unicodedata.normalize('NFKD', text)
    return ''.join(c for c in nfkd if not unicodedata.category(c).startswith('M'))


class Entity360State(TypedDict, total=False):
    message: str
    empresa_id: str
    user_id: str
    intent: str

    # Entidad detectada
    entity_name: str
    entity_type: str  # "person" o "company"

    # Datos recolectados de cada fuente
    rag_context: str
    plane_data: List[Dict]
    notion_data: List[Dict]
    calendar_data: List[Dict]
    gmail_data: List[Dict]
    kg_data: Dict
    sources_used: List[Dict]

    # Output
    response: str
    model_used: str
    model_preference: str


DETECT_ENTITY_PROMPT = """Analiza el mensaje y el contexto conversacional para identificar
sobre qué persona o empresa preguntan.

CONTEXTO CONVERSACIONAL:
{history}

MENSAJE ACTUAL:
{message}

REGLAS CRÍTICAS DE RESOLUCIÓN DE PRONOMBRES:
1. Si el mensaje usa "él", "ella", "esa persona", "esa empresa", "de él", "de ella",
   SIEMPRE se refiere a la ÚLTIMA persona o empresa mencionada en el contexto conversacional.
2. NUNCA resuelvas un pronombre como el usuario que está hablando. El usuario pregunta
   SOBRE alguien más, no sobre sí mismo.
3. Si en el contexto reciente se habló de "Oswaldo Gutiérrez" y el usuario dice
   "dame la información completa de él", la entidad es "Oswaldo Gutiérrez".
4. Si no hay contexto previo y el mensaje es ambiguo, responde con entity_name vacío.

Responde SOLO JSON:
{{
    "entity_name": "nombre completo de la persona o empresa",
    "entity_type": "person o company"
}}

Sin markdown, sin explicación."""


CONSOLIDATE_PROMPT = """Eres Ada, asesora ejecutiva. Consolida TODA la información sobre {entity_name}.

DATOS RECOLECTADOS DE MÚLTIPLES FUENTES:
{all_data}

FORMATO OBLIGATORIO — SIGUE ESTE ORDEN EXACTO:

1. **PERFIL** (👤): SIEMPRE primero. Nombre completo, cargo, empresa, sector, web, LinkedIn,
   redes sociales, email, teléfono. Si un dato existe en CUALQUIER fuente (RAG, reportes, etc),
   EXTRÁELO y muéstralo. Si no existe, pon ⚠️ NO DISPONIBLE.

2. **EMPRESA** (🏢): Si es persona, describe su empresa. Sector, tamaño, qué hacen,
   propuesta de valor. Solo si hay datos.

3. **TAREAS/PROYECTOS** (📋): TODAS las tareas de Plane agrupadas por proyecto.
   Mostrar: nombre | estado | prioridad | asignado | fecha. No omitir ninguna.

4. **NOTION** (📝): Páginas o databases que lo mencionan. Solo si hay datos.

5. **CALENDARIO** (📅): Eventos/reuniones próximas. Solo si hay datos.

6. **EMAILS** (📧): Correos recientes de/para esta persona. Solo si hay datos.

7. **REPORTES** (📊): Reportes y documentos que lo mencionan. Solo si hay datos.

8. **RESUMEN EJECUTIVO**: 3-4 líneas conectando los puntos más importantes.

REGLAS:
- EXTRAE datos de perfil del RAG aunque estén mezclados con otro texto. Si en el RAG
  aparece "LinkedIn: https://..." o "CEO de Insights 4.0", MUÉSTRALO en la sección de perfil.
- Si hay 7 tareas, muestra las 7. NUNCA resumas ni omitas.
- Conecta puntos: si tiene tareas pendientes Y una reunión próxima, menciónalo.
- No menciones fuentes que no tienen datos.
- Sé directo — nada de "según mis datos".
- Usa emojis y negritas para formato."""


async def detect_entity(state: Entity360State) -> dict:
    """Detecta la entidad (persona/empresa) usando reglas + LLM + contexto conversacional."""
    import re as _re

    message = state.get("message", "")
    empresa_id = state.get("empresa_id", "")
    user_id = state.get("user_id", "")

    # Cargar historial
    history = []
    if empresa_id and user_id:
        try:
            history = get_history(empresa_id, user_id)
        except Exception as e:
            print(f"ENTITY360: history error: {e}")

    # PASO 1: Detección determinística de pronombres
    # Si el mensaje es un follow-up con pronombre, reusar la última entidad del usuario
    msg_lower = message.lower().strip()
    pronoun_patterns = [
        "de él", "de el", "de ella", "sobre él", "sobre el", "sobre ella",
        "completa de él", "completa de el", "completa de ella",
        "información de él", "informacion de el",
        "participa él", "participa el", "participa ella",
        "sus proyectos", "sus tareas",
    ]

    is_pronoun_followup = any(p in msg_lower for p in pronoun_patterns)

    if is_pronoun_followup and history:
        # Buscar la última entidad mencionada por el USUARIO (no por Ada)
        # Recorrer historial de atrás para adelante, solo mensajes del usuario
        for msg_entry in reversed(history[-8:]):
            if msg_entry.get("role") != "user":
                continue
            content = msg_entry.get("content", "")
            # Buscar nombres propios (palabras que empiezan con mayúscula, 2+ palabras seguidas)
            name_match = _re.findall(r'\b([A-ZÁÉÍÓÚÑ][a-záéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+)+)\b', content)
            if name_match:
                entity_name = name_match[-1]  # Tomar el último nombre encontrado
                print(f"ENTITY360: pronoun resolved deterministically -> '{entity_name}'")
                return {
                    "entity_name": entity_name,
                    "entity_type": "person",
                    "model_used": "deterministic_pronoun",
                }

    # PASO 2: Si no es pronombre, usar LLM normalmente
    history_text = ""
    if history:
        recent = history[-6:]
        history_text = "\n".join(
            f"{m.get('role', 'user')}: {m.get('content', '')[:200]}"
            for m in recent
        )

    model, model_name = selector.get_model("routing")

    prompt = DETECT_ENTITY_PROMPT.format(
        history=history_text or "Sin historial previo",
        message=message,
    )

    response = await model.ainvoke([
        {"role": "system", "content": prompt},
        {"role": "user", "content": message},
    ])

    try:
        raw = response.content.strip().replace("```json", "").replace("```", "")
        result = json.loads(raw)
        entity_name = result.get("entity_name", "").strip()
        entity_type = result.get("entity_type", "person")
    except Exception:
        entity_name = ""
        entity_type = "person"

    print(f"ENTITY360: detected entity='{entity_name}' type={entity_type}")

    return {
        "entity_name": entity_name,
        "entity_type": entity_type,
        "model_used": model_name,
    }


async def gather_all_sources(state: Entity360State) -> dict:
    """Consulta TODAS las fuentes en paralelo para la entidad detectada."""
    entity_name = state.get("entity_name", "")
    empresa_id = state.get("empresa_id", "")
    sources_used = []

    if not entity_name or not empresa_id:
        return {
            "response": "No pude identificar sobre quién o qué empresa preguntas. ¿Puedes ser más específico?",
            "sources_used": [],
        }

    # Ejecutar todas las consultas en paralelo
    rag_context = ""
    plane_data = []
    notion_data = []
    calendar_data = []
    gmail_data = []
    kg_data = {}

    # 1. RAG: buscar en todas las fuentes vectoriales y SQL
    try:
        memories = search_memory(entity_name, empresa_id)
        reports_sql = search_reports(entity_name, empresa_id)
        reports_qdrant = search_reports_qdrant(entity_name, empresa_id, limit=5)
        vector_docs = search_vector_store1(entity_name, empresa_id, limit=5)

        rag_parts = []
        if memories:
            rag_parts.append("Memoria:\n" + "\n".join(memories[:3]))
            sources_used.append({"name": "agent_memory", "detail": f"{len(memories)} memorias", "confidence": 0.7})
        if reports_sql:
            rag_parts.append("Reportes SQL:\n" + "\n".join(reports_sql[:3]))
            sources_used.append({"name": "postgres_reports", "detail": f"{len(reports_sql)} reportes", "confidence": 0.8})
        if reports_qdrant:
            rag_parts.append("Reportes Qdrant:\n" + "\n".join(reports_qdrant[:3]))
            sources_used.append({"name": "qdrant_excel_reports", "detail": f"{len(reports_qdrant)} reportes", "confidence": 0.85})
        if vector_docs:
            rag_parts.append("Documentos:\n" + "\n".join(vector_docs[:3]))
            sources_used.append({"name": "qdrant_vector_store1", "detail": f"{len(vector_docs)} docs", "confidence": 0.82})

        rag_context = "\n\n".join(rag_parts)
    except Exception as e:
        print(f"ENTITY360 RAG error: {e}")

    # 2. Knowledge Graph: entity_360 desde ada_reports
    try:
        kg_data = get_entity_360(entity_name, empresa_id)
        if kg_data and kg_data.get("total_mentions", 0) > 0:
            sources_used.append({"name": "knowledge_graph", "detail": f"{kg_data['total_mentions']} menciones", "confidence": 0.88})
    except Exception as e:
        print(f"ENTITY360 KG error: {e}")

    # 3. Plane: buscar issues que mencionan a la entidad en TODOS los proyectos
    try:
        from api.mcp_servers.mcp_host import mcp_host

        projects = await mcp_host.call_tool_by_name("plane_list_projects", {}, empresa_id)
        if isinstance(projects, list):
            for project in projects:
                try:
                    issues = await mcp_host.call_tool_by_name(
                        "plane_list_issues",
                        {"project_id": project["id"], "max_results": 50},
                        empresa_id,
                    )
                    if isinstance(issues, list):
                        for issue in issues:
                            name_norm = _normalize(issue.get("name", ""))
                            desc_norm = _normalize(issue.get("description", ""))
                            assignee_norm = _normalize(issue.get("assignee", ""))

                            # Normalizar entidad y generar variantes de búsqueda
                            entity_words = _normalize(entity_name).split()

                            # Buscar en nombre, descripción y assignee (incluyendo usernames parciales)
                            matches = any(
                                word in name_norm or word in desc_norm or word in assignee_norm
                                for word in entity_words if len(word) > 3
                            )

                            if matches:
                                issue["_project_name"] = project.get("name", "")
                                plane_data.append(issue)
                except Exception as e:
                    print(f"ENTITY360 Plane project {project.get('name', '')} error: {e}")

            if plane_data:
                sources_used.append({"name": "plane", "detail": f"{len(plane_data)} tareas relacionadas", "confidence": 0.9})
    except Exception as e:
        print(f"ENTITY360 Plane error: {e}")

    # 4. Notion: buscar por nombre de la entidad
    try:
        from api.mcp_servers.mcp_host import mcp_host

        notion_results = await mcp_host.call_tool_by_name(
            "notion_search",
            {"query": entity_name, "max_results": 10},
            empresa_id,
        )
        if isinstance(notion_results, list) and notion_results:
            notion_data = notion_results
            sources_used.append({"name": "notion", "detail": f"{len(notion_data)} páginas", "confidence": 0.75})
    except Exception as e:
        print(f"ENTITY360 Notion error: {e}")

    # 5. Calendar: buscar eventos con la entidad
    try:
        from api.services.calendar_service import calendar_search_events

        events = calendar_search_events(entity_name, max_results=5, empresa_id=empresa_id)
        if events:
            calendar_data = events
            sources_used.append({"name": "calendar", "detail": f"{len(calendar_data)} eventos", "confidence": 0.8})
    except Exception as e:
        print(f"ENTITY360 Calendar error: {e}")

    # 6. Gmail: buscar emails relacionados
    try:
        from api.services.gmail_service import gmail_search

        emails = gmail_search(entity_name, max_results=5, empresa_id=empresa_id)
        if emails:
            gmail_data = emails
            sources_used.append({"name": "gmail", "detail": f"{len(gmail_data)} correos", "confidence": 0.75})
    except Exception as e:
        print(f"ENTITY360 Gmail error: {e}")

    print(f"ENTITY360: rag={'yes' if rag_context else 'no'} plane={len(plane_data)} "
          f"notion={len(notion_data)} calendar={len(calendar_data)} gmail={len(gmail_data)} "
          f"kg={kg_data.get('total_mentions', 0)}")

    return {
        "rag_context": rag_context,
        "plane_data": plane_data,
        "notion_data": notion_data,
        "calendar_data": calendar_data,
        "gmail_data": gmail_data,
        "kg_data": kg_data,
        "sources_used": sources_used,
    }


async def consolidate_response(state: Entity360State) -> dict:
    """LLM consolida toda la información en una respuesta 360° unificada."""
    entity_name = state.get("entity_name", "")
    sources_used = state.get("sources_used", [])

    if not sources_used:
        return {
            "response": f"No encontré información sobre {entity_name} en ninguna fuente. "
                        "¿Quieres que lo perfile como prospecto nuevo?",
        }

    # Construir contexto con toda la data
    all_data_parts = []

    rag_context = state.get("rag_context", "")
    if rag_context:
        all_data_parts.insert(0, f"## INFORMACIÓN DE PERFIL Y DOCUMENTOS (RAG)\n⚠️ IMPORTANTE: Extrae TODOS los datos de contacto, cargo, empresa, LinkedIn, web, redes sociales de este texto y muéstralos en la sección de PERFIL.\n\n{rag_context}")

    kg_data = state.get("kg_data", {})
    if kg_data and kg_data.get("total_mentions", 0) > 0:
        kg_lines = [f"Menciones totales: {kg_data['total_mentions']}"]
        for rtype, items in kg_data.get("by_source", {}).items():
            titles = [it["title"] for it in items[:3]]
            kg_lines.append(f"- {rtype}: {', '.join(titles)}")
        all_data_parts.append(f"## KNOWLEDGE GRAPH\n" + "\n".join(kg_lines))

    plane_data = state.get("plane_data", [])
    if plane_data:
        plane_lines = []
        # Agrupar por proyecto
        by_project = {}
        for issue in plane_data:
            proj = issue.get("_project_name", "Sin proyecto")
            by_project.setdefault(proj, []).append(issue)

        for proj, issues in by_project.items():
            plane_lines.append(f"\nProyecto: {proj}")
            for i in issues:
                state_str = i.get("state", "") or i.get("state_group", "") or "sin estado"
                priority = i.get("priority", "")
                due = i.get("due_date", "")
                assignee = i.get("assignee", "")
                line = f"  - {i.get('name', '')} | estado: {state_str} | prioridad: {priority}"
                if assignee:
                    line += f" | asignado: {assignee}"
                if due:
                    line += f" | fecha: {due}"
                plane_lines.append(line)

        all_data_parts.append(f"## TAREAS EN PLANE\n" + "\n".join(plane_lines))

    notion_data = state.get("notion_data", [])
    if notion_data:
        notion_lines = [
            f"- {d.get('title', 'Sin título')} ({d.get('type', '')}) — {d.get('last_edited', '')}"
            for d in notion_data
        ]
        all_data_parts.append(f"## NOTION\n" + "\n".join(notion_lines))

    calendar_data = state.get("calendar_data", [])
    if calendar_data:
        cal_lines = [
            f"- {e.get('summary', '')} ({e.get('start', '')})"
            for e in calendar_data
        ]
        all_data_parts.append(f"## CALENDARIO\n" + "\n".join(cal_lines))

    gmail_data = state.get("gmail_data", [])
    if gmail_data:
        gmail_lines = [
            f"- {e.get('subject', '')} ({e.get('date', '')}) — de: {e.get('from', '')}"
            for e in gmail_data
        ]
        all_data_parts.append(f"## EMAILS\n" + "\n".join(gmail_lines))

    all_data = "\n\n".join(all_data_parts)

    model, model_name = selector.get_model("chat", state.get("model_preference"))

    prompt = CONSOLIDATE_PROMPT.format(
        entity_name=entity_name,
        all_data=all_data,
    )

    # Si el usuario pide info completa, reforzar que muestre TODO
    msg_lower = (state.get("message", "") or "").lower()
    completeness_keywords = ["completa", "completo", "todo sobre", "toda la", "todo de", "todo lo que"]
    if any(kw in msg_lower for kw in completeness_keywords):
        prompt += "\n\nIMPORTANTE: El usuario pidió información COMPLETA. Muestra ABSOLUTAMENTE TODO lo que tengas. No resumas, no omitas, no acortes. Si la primera vez mostraste 7 tareas, ahora muestra las mismas 7. Si hay perfil, empresa, tareas, emails, reportes — muestra TODO otra vez con el mismo nivel de detalle o más."

    response = await model.ainvoke([
        {"role": "system", "content": prompt},
        {"role": "user", "content": state.get("message", "")},
    ])

    return {
        "response": response.content,
        "model_used": model_name,
    }


async def save_to_history(state: Entity360State) -> dict:
    """Guarda el mensaje y respuesta en conversation_history."""
    message = state.get("message", "")
    response = state.get("response", "")
    empresa_id = state.get("empresa_id", "")
    user_id = state.get("user_id", "")

    if empresa_id and user_id and message:
        try:
            history = get_history(empresa_id, user_id)
            if message:
                history.append({"role": "user", "content": message})
            if response:
                history.append({"role": "assistant", "content": response[:2000]})
            save_history(empresa_id, user_id, history)
        except Exception as e:
            print(f"ENTITY360: Error guardando historial: {e}")

    return {}


# Construir grafo
graph = StateGraph(Entity360State)
graph.add_node("detect_entity", detect_entity)
graph.add_node("gather_sources", gather_all_sources)
graph.add_node("consolidate", consolidate_response)
graph.add_node("save", save_to_history)
graph.set_entry_point("detect_entity")
graph.add_edge("detect_entity", "gather_sources")
graph.add_edge("gather_sources", "consolidate")
graph.add_edge("consolidate", "save")
graph.add_edge("save", END)
entity_360_agent = graph.compile()
