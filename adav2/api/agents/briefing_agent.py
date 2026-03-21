"""
Proactive Briefing Agent — EL DIFERENCIADOR DE ADA.

Después de analizar datos (Excel, reportes), Ada AUTOMÁTICAMENTE:
1. Detecta alertas y entidades clave (clientes, productos, proveedores)
2. Cruza con Calendar (¿hay reuniones relacionadas?)
3. Cruza con Gmail (¿hay emails recientes sobre esto?)
4. Cruza con Notion (¿hay documentos relacionados?)
5. Genera un BRIEFING EJECUTIVO con contexto cruzado + recomendación accionable
6. Ofrece ejecutar la acción (draft email, crear evento, etc.)

Esto es lo que ningún chatbot hace — Ada CONECTA los puntos.
"""

import json
from typing import TypedDict, Optional, List, Dict
from langgraph.graph import StateGraph, END
from models.selector import selector
from api.services.entity_extractor import extract_entities as extract_entities_service


class BriefingState(TypedDict, total=False):
    # Input
    empresa_id: str
    user_id: str
    trigger: str          # "excel_analysis", "alert", "manual"
    analysis: str         # Análisis original (del Excel Analyst)
    alerts: List[Dict]    # Alertas detectadas
    file_name: str
    message: str          # Si fue manual: "prepara briefing sobre cartera"

    # Cross-reference data
    calendar_context: str
    email_context: str
    notion_context: str
    entities: List[str]   # Entidades extraídas (clientes, productos, personas)

    # Output
    response: str
    model_used: str


# ─── NODO 1: Extraer entidades clave ─────────────────────

async def extract_entities(state: BriefingState) -> dict:
    """Extrae entidades usando el servicio compartido entity_extractor."""
    source_text = state.get("analysis", "") or state.get("message", "")
    alerts = state.get("alerts", [])

    entities = await extract_entities_service(source_text, alerts, max_entities=5)

    print(f"BRIEFING: Entidades extraidas: {entities}")
    return {"entities": entities[:5]}


# ─── NODO 2: Cruzar con Calendar ─────────────────────────

async def cross_calendar(state: BriefingState) -> dict:
    """Busca en el calendario reuniones relacionadas con las entidades."""
    empresa_id = state.get("empresa_id", "")
    entities = state.get("entities", [])

    if not entities or not empresa_id:
        return {"calendar_context": "Sin información de calendario."}

    try:
        from api.services.calendar_service import calendar_search_events
        
        calendar_hits = []
        for entity in entities[:3]:
            events = calendar_search_events(entity, days_ahead=14, max_results=3, empresa_id=empresa_id)
            for e in events:
                calendar_hits.append(
                    f"📅 {e['summary']} — {e['start'][:16].replace('T', ' ')}"
                )

        if calendar_hits:
            context = "REUNIONES RELACIONADAS:\n" + "\n".join(calendar_hits)
        else:
            context = "No hay reuniones próximas relacionadas con estos temas."

        print(f"BRIEFING: Calendar → {len(calendar_hits)} eventos encontrados")
        return {"calendar_context": context}

    except Exception as e:
        print(f"BRIEFING: Calendar error: {e}")
        return {"calendar_context": "No se pudo consultar el calendario."}


# ─── NODO 3: Cruzar con Gmail ────────────────────────────

async def cross_email(state: BriefingState) -> dict:
    """Busca emails recientes relacionados con las entidades."""
    empresa_id = state.get("empresa_id", "")
    entities = state.get("entities", [])

    if not entities or not empresa_id:
        return {"email_context": "Sin información de email."}

    try:
        from api.services.gmail_service import gmail_search

        email_hits = []
        for entity in entities[:3]:
            emails = gmail_search(entity, max_results=2, empresa_id=empresa_id)
            for e in emails:
                email_hits.append(
                    f"📧 {e['subject']} — de {e['from']} ({e['date'][:16]})\n   {e['snippet'][:80]}"
                )

        if email_hits:
            context = "EMAILS RELACIONADOS:\n" + "\n".join(email_hits)
        else:
            context = "No hay emails recientes sobre estos temas."

        print(f"BRIEFING: Email → {len(email_hits)} emails encontrados")
        return {"email_context": context}

    except Exception as e:
        print(f"BRIEFING: Email error: {e}")
        return {"email_context": "No se pudo consultar el email."}


# ─── NODO 4: Cruzar con Notion ───────────────────────────

async def cross_notion(state: BriefingState) -> dict:
    """Busca en Notion documentos relacionados con las entidades."""
    empresa_id = state.get("empresa_id", "")
    entities = state.get("entities", [])

    if not entities or not empresa_id:
        return {"notion_context": "Sin información de Notion."}

    try:
        from api.mcp_servers.mcp_host import mcp_host

        notion_hits = []
        for entity in entities[:3]:
            result = await mcp_host.call_tool_by_name(
                "notion_search", {"query": entity, "max_results": 2}, empresa_id
            )
            if isinstance(result, list):
                for r in result:
                    notion_hits.append(
                        f"📄 {r.get('title', 'Sin título')} ({r.get('type', '')}) — {r.get('last_edited', '')}"
                    )

        if notion_hits:
            context = "DOCUMENTOS EN NOTION:\n" + "\n".join(notion_hits)
        else:
            context = "No hay documentos en Notion sobre estos temas."

        print(f"BRIEFING: Notion → {len(notion_hits)} docs encontrados")
        return {"notion_context": context}

    except Exception as e:
        print(f"BRIEFING: Notion error: {e}")
        return {"notion_context": "No se pudo consultar Notion."}


# ─── NODO 5: Generar Briefing Ejecutivo ──────────────────

async def generate_briefing(state: BriefingState) -> dict:
    """Genera el briefing ejecutivo cruzando TODAS las fuentes."""
    model, model_name = selector.get_model("excel_analysis")

    analysis = state.get("analysis", "")
    alerts = state.get("alerts", [])
    alerts_text = "\n".join([f"- {a.get('message', '')}" for a in alerts]) if alerts else "Sin alertas."
    file_name = state.get("file_name", "")
    calendar_ctx = state.get("calendar_context", "")
    email_ctx = state.get("email_context", "")
    notion_ctx = state.get("notion_context", "")
    entities = state.get("entities", [])

    prompt = f"""Genera un BRIEFING EJECUTIVO PROACTIVO para el CEO.

## DATOS DEL ANÁLISIS
Archivo: {file_name}
{analysis[:4000]}

## ALERTAS DETECTADAS
{alerts_text}

## ENTIDADES CLAVE
{', '.join(entities)}

## CONTEXTO CRUZADO (información que Ada encontró automáticamente)

### Calendario
{calendar_ctx}

### Emails recientes
{email_ctx}

### Documentos en Notion
{notion_ctx}

## INSTRUCCIONES PARA EL BRIEFING:

1. **BLUF**: El hallazgo MÁS IMPORTANTE en 2 oraciones impactantes
2. **Conexiones detectadas**: Cruza los datos del análisis con el calendario, emails y Notion. ¿Hay reuniones próximas con clientes o proveedores mencionados en las alertas? ¿Hay emails que dan contexto a los problemas detectados?
3. **Riesgos con contexto**: No solo digas "margen negativo" — di "margen negativo Y tienes reunión con ese proveedor el jueves Y en el último email pidieron subir precios"
4. **3 acciones ejecutivas**: Cada acción debe ser CONCRETA y EJECUTABLE (no "revisar", sino "en la reunión del jueves negociar descuento por volumen")
5. **Oferta proactiva**: Ofrece al CEO ejecutar una acción: "¿Quieres que prepare el borrador del email de negociación?" o "¿Agendo una reunión con el equipo comercial?"

FORMATO: Profesional, directo, español. Emojis semánticos. NO inventes datos que no estén en el contexto.
Si no encontraste cruces, dilo honestamente pero igual da recomendaciones basadas en los datos del análisis."""

    response = await model.ainvoke([
        {"role": "system", "content": (
            "Eres Ada, Asistente Ejecutiva Senior de IA. Tu superpoder es CONECTAR información "
            "de múltiples fuentes para dar al CEO una visión de 360° que ningún otro asistente "
            "puede dar. No eres un chatbot — eres una socia estratégica."
        )},
        {"role": "user", "content": prompt},
    ])

    print(f"BRIEFING: Generado con {model_name}")

    return {
        "response": response.content,
        "model_used": model_name,
    }


# ─── Compilar grafo ──────────────────────────────────────

graph = StateGraph(BriefingState)
graph.add_node("extract_entities", extract_entities)
graph.add_node("cross_calendar", cross_calendar)
graph.add_node("cross_email", cross_email)
graph.add_node("cross_notion", cross_notion)
graph.add_node("generate_briefing", generate_briefing)

graph.set_entry_point("extract_entities")
graph.add_edge("extract_entities", "cross_calendar")
graph.add_edge("cross_calendar", "cross_email")
graph.add_edge("cross_email", "cross_notion")
graph.add_edge("cross_notion", "generate_briefing")
graph.add_edge("generate_briefing", END)

briefing_agent = graph.compile()