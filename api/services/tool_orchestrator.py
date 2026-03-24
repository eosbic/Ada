"""
Orquestador central de herramientas multi-fuente.

Reglas:
- Consulta dual obligatoria antes de declarar ausencia de informacion.
- Registra trazabilidad de fuentes (primaria/secundaria).
"""

from typing import Dict, List

from api.services.memory_service import (
    search_reports_qdrant,
    search_vector_store1,
    search_reports,
)


def _add_source(sources: List[Dict], name: str, detail: str, confidence: float):
    sources.append({"name": name, "detail": detail, "confidence": confidence})


async def collect_multi_source_context(message: str, empresa_id: str, intent: str = "data_query", user_id: str = "") -> Dict:
    query = (message or "").strip()
    sources: List[Dict] = []
    chunks: List[str] = []

    # 1) Regla dual obligatoria (Qdrant excel reports + Vector Store1)
    qdrant_reports = []
    vector_store_docs = []
    tried_qdrant_reports = False
    tried_vector_store1 = False
    if empresa_id and query:
        try:
            tried_qdrant_reports = True
            qdrant_reports = search_reports_qdrant(query, empresa_id, limit=4, user_id=user_id)
            if qdrant_reports:
                chunks.append("## Qdrant Excel Reports\n" + "\n\n".join(qdrant_reports))
                _add_source(sources, "qdrant_excel_reports", f"{len(qdrant_reports)} hallazgos", 0.86)
        except Exception as e:
            print(f"ORCHESTRATOR qdrant_reports error: {e}")

        try:
            tried_vector_store1 = True
            vector_store_docs = search_vector_store1(query, empresa_id, limit=4, user_id=user_id)
            if vector_store_docs:
                chunks.append("## Qdrant Vector Store1\n" + "\n\n".join(vector_store_docs))
                _add_source(sources, "qdrant_vector_store1", f"{len(vector_store_docs)} hallazgos", 0.82)
        except Exception as e:
            print(f"ORCHESTRATOR vector_store1 error: {e}")

    dual_repo_checked = bool(tried_qdrant_reports and tried_vector_store1)

    # 2) Base SQL de reportes (adicional)
    if empresa_id and query:
        try:
            sql_reports = search_reports(query, empresa_id, user_id=user_id)
            if sql_reports:
                chunks.append("## PostgreSQL Reports\n" + "\n\n".join(sql_reports[:3]))
                _add_source(sources, "postgres_reports", f"{len(sql_reports)} hallazgos", 0.78)
        except Exception as e:
            print(f"ORCHESTRATOR postgres_reports error: {e}")

    # 3) Fuentes operacionales externas (contextuales)
    q = query.lower()
    needs_email = any(k in q for k in ["correo", "email", "gmail"])
    needs_calendar = any(k in q for k in ["reunion", "agenda", "calendario", "evento"])
    needs_project = any(k in q for k in ["proyecto", "tarea", "issue", "sprint", "plane"])
    needs_notion = any(k in q for k in ["notion", "wiki", "documento", "base de conocimiento"])

    if needs_email and empresa_id:
        try:
            from api.services.gmail_service import gmail_search

            emails = gmail_search(query, max_results=3, empresa_id=empresa_id)
            if emails:
                lines = [f"- {e.get('subject', '')} ({e.get('date', '')})" for e in emails]
                chunks.append("## Gmail\n" + "\n".join(lines))
                _add_source(sources, "gmail", f"{len(emails)} correos", 0.74)
        except Exception as e:
            print(f"ORCHESTRATOR gmail error: {e}")

    if needs_calendar and empresa_id:
        try:
            from api.services.calendar_service import calendar_search_events

            events = calendar_search_events(query, max_results=3, empresa_id=empresa_id)
            if events:
                lines = [f"- {ev.get('summary', '')} ({ev.get('start', '')})" for ev in events]
                chunks.append("## Calendar\n" + "\n".join(lines))
                _add_source(sources, "calendar", f"{len(events)} eventos", 0.74)
        except Exception as e:
            print(f"ORCHESTRATOR calendar error: {e}")

    if needs_project and empresa_id:
        try:
            from api.mcp_servers.mcp_host import mcp_host

            projects = await mcp_host.call_tool_by_name("plane_list_projects", {}, empresa_id)
            if isinstance(projects, list) and projects:
                lines = [f"- {p.get('name', '')}" for p in projects[:5]]
                chunks.append("## Plane Projects\n" + "\n".join(lines))
                _add_source(sources, "plane_projects", f"{len(projects)} proyectos", 0.71)
        except Exception as e:
            print(f"ORCHESTRATOR plane error: {e}")

    if needs_notion and empresa_id:
        try:
            from api.mcp_servers.mcp_host import mcp_host

            docs = await mcp_host.call_tool_by_name(
                "notion_search",
                {"query": query, "max_results": 5},
                empresa_id
            )
            if isinstance(docs, list) and docs:
                lines = [f"- {d.get('title', '')}" for d in docs[:5]]
                chunks.append("## Notion\n" + "\n".join(lines))
                _add_source(sources, "notion", f"{len(docs)} documentos", 0.7)
        except Exception as e:
            print(f"ORCHESTRATOR notion error: {e}")

    # 4) Contexto 360° de entidades mencionadas
    if empresa_id and query:
        try:
            from api.services.graph_navigator import get_entity_360_text

            words = [w for w in query.split() if len(w) > 3 and w[0].isupper()]
            entity_contexts = []
            for word in words[:3]:
                ctx = get_entity_360_text(word, empresa_id)
                if ctx:
                    entity_contexts.append(ctx)

            if entity_contexts:
                chunks.append("## Contexto 360\n" + "\n\n".join(entity_contexts))
                _add_source(sources, "entity_360", "contexto cruzado de entidades", 0.88)
        except Exception as e:
            print(f"ORCHESTRATOR entity_360 error: {e}")

    return {
        "context_text": "\n\n".join(chunks) if chunks else "",
        "sources_used": sources,
        "dual_repo_checked": dual_repo_checked,
        "dual_repo_stats": {
            "tried_qdrant_reports": tried_qdrant_reports,
            "tried_vector_store1": tried_vector_store1,
            "hits_qdrant_reports": len(qdrant_reports),
            "hits_vector_store1": len(vector_store_docs),
        },
        "found_any": bool(chunks),
    }
