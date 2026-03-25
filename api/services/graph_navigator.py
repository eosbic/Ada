"""
Graph Navigator — Traversal de report_links para busqueda en grafo.
Dado un set de reportes, sigue enlaces 1 hop para traer contexto conectado.
"""

from sqlalchemy import text as sql_text
from api.database import sync_engine


def traverse_report_graph(
    report_ids: list,
    empresa_id: str,
    max_hops: int = 1,
    limit: int = 10,
) -> list:
    """
    Dado un set de reportes, sigue enlaces bidireccionales para traer
    reportes conectados con su tipo de enlace.
    Retorna lista de dicts con: id, title, link_type, snippet, metrics, source_file, created_at
    """
    if not report_ids or not empresa_id:
        return []

    try:
        with sync_engine.connect() as conn:
            params = {"eid": empresa_id}
            placeholders = []
            for i, rid in enumerate(report_ids[:20]):
                key = f"id_{i}"
                params[key] = rid
                placeholders.append(f":{key}")

            ids_sql = ", ".join(placeholders)

            rows_out = conn.execute(
                sql_text(f"""
                    SELECT r.id, r.title, r.source_file, r.created_at,
                           r.markdown_content, r.metrics_summary, r.tags,
                           rl.link_type,
                           rl.source_report_id as linked_from
                    FROM report_links rl
                    JOIN ada_reports r ON r.id = rl.target_report_id
                    WHERE rl.source_report_id IN ({ids_sql})
                    AND r.empresa_id = :eid
                    AND r.is_archived = FALSE
                    ORDER BY r.created_at DESC
                    LIMIT :lim
                """),
                {**params, "lim": limit}
            ).fetchall()

            rows_in = conn.execute(
                sql_text(f"""
                    SELECT r.id, r.title, r.source_file, r.created_at,
                           r.markdown_content, r.metrics_summary, r.tags,
                           rl.link_type,
                           rl.target_report_id as linked_from
                    FROM report_links rl
                    JOIN ada_reports r ON r.id = rl.source_report_id
                    WHERE rl.target_report_id IN ({ids_sql})
                    AND r.empresa_id = :eid
                    AND r.is_archived = FALSE
                    ORDER BY r.created_at DESC
                    LIMIT :lim
                """),
                {**params, "lim": limit}
            ).fetchall()

        seen = set(report_ids)
        results = []

        for row in list(rows_out) + list(rows_in):
            rid = str(row.id)
            if rid in seen:
                continue
            seen.add(rid)
            results.append({
                "id": rid,
                "title": row.title,
                "source_file": row.source_file,
                "link_type": row.link_type,
                "snippet": (row.markdown_content or "")[:1500],
                "metrics": row.metrics_summary,
                "tags": row.tags or [],
                "created_at": str(row.created_at) if row.created_at else "",
            })

        print(f"GRAPH_NAV: {len(report_ids)} reportes -> {len(results)} conectados")
        return results[:limit]

    except Exception as e:
        print(f"GRAPH_NAV: Error: {e}")
        import traceback
        traceback.print_exc()
        return []


def get_report_links(report_id: str, empresa_id: str) -> list:
    """Obtener todos los enlaces de un reporte especifico (para API/frontend)."""
    return traverse_report_graph([report_id], empresa_id, limit=20)


REPORT_TYPE_LABELS = {
    "excel_analysis": "Analisis Excel",
    "email_summary": "Emails",
    "calendar_event_summary": "Calendario",
    "pm_task_summary": "Tareas de proyectos",
    "notion_summary": "Documentos Notion",
    "prospect_profile": "Prospectos",
    "proactive_briefing": "Briefings",
    "consolidated_analysis": "Consolidados",
    "document_analysis": "Documentos",
}


def get_entity_360(entity_name: str, empresa_id: str, limit: int = 20) -> dict:
    """Vista 360° de una entidad: busca en ada_reports por TODOS los report_types."""
    if not entity_name or not empresa_id:
        return {}

    try:
        with sync_engine.connect() as conn:
            rows = conn.execute(
                sql_text("""
                    SELECT id, title, report_type, source_file, created_at,
                           markdown_content, metrics_summary
                    FROM ada_reports
                    WHERE empresa_id = :eid
                      AND is_archived = FALSE
                      AND (title ILIKE :like OR markdown_content ILIKE :like)
                    ORDER BY created_at DESC
                    LIMIT :lim
                """),
                {"eid": empresa_id, "like": f"%{entity_name}%", "lim": limit},
            ).fetchall()

        if not rows:
            return {"entity": entity_name, "total_mentions": 0, "by_source": {}, "source_types": []}

        grouped = {}
        for row in rows:
            rtype = row.report_type or "unknown"
            if rtype not in grouped:
                grouped[rtype] = []
            grouped[rtype].append({
                "id": str(row.id),
                "title": row.title,
                "source_file": row.source_file,
                "created_at": str(row.created_at) if row.created_at else "",
                "snippet": (row.markdown_content or "")[:1500],
            })

        return {
            "entity": entity_name,
            "total_mentions": len(rows),
            "by_source": grouped,
            "source_types": list(grouped.keys()),
        }

    except Exception as e:
        print(f"GRAPH_NAV 360 error: {e}")
        return {}


def get_entity_360_text(entity_name: str, empresa_id: str) -> str:
    """Version texto de 360° para inyectar en prompts."""
    data = get_entity_360(entity_name, empresa_id)
    if not data or data.get("total_mentions", 0) == 0:
        return ""

    lines = [f"### {entity_name} — {data['total_mentions']} menciones"]
    for rtype, items in data.get("by_source", {}).items():
        label = REPORT_TYPE_LABELS.get(rtype, rtype.replace("_", " ").title())
        recent_titles = [it["title"] for it in items[:2]]
        lines.append(f"- **{label}**: {len(items)} registros — {', '.join(recent_titles)}")

    return "\n".join(lines)


def search_with_graph(query: str, empresa_id: str, base_results: list) -> list:
    """
    Enriquece resultados de busqueda base con reportes conectados via grafo.
    base_results debe tener al menos 'id' en cada dict.
    """
    if not base_results:
        return []
    base_ids = [r.get("id") for r in base_results if r.get("id")]
    if not base_ids:
        return base_results
    connected = traverse_report_graph(base_ids, empresa_id, limit=5)
    for c in connected:
        c["_source"] = "graph_link"
        c["_link_info"] = f"Conectado via: {c.get('link_type', 'related')}"
    return base_results + connected