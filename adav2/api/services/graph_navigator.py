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
                "snippet": (row.markdown_content or "")[:500],
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