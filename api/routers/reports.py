"""
Reports Router — Bóveda de conocimiento de Ada.
Endpoints para el Portal Web (React).

GET  /reports              → Lista reportes de la empresa
GET  /reports/{id}         → Detalle de un reporte
GET  /reports/search       → Búsqueda full-text
PATCH /reports/{id}        → Archivar/desarchivar
POST /resume/{thread_id}   → Reanudar grafo pausado (HITL)
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from api.database import get_db
from typing import Optional

router = APIRouter()


@router.get("/reports")
async def list_reports(
    empresa_id: str,
    report_type: Optional[str] = None,
    archived: bool = False,
    limit: int = Query(default=20, le=100),
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    """Lista reportes de una empresa. El frontend consume esto para la bóveda."""

    query = """
        SELECT id, thread_id, title, report_type, source_file,
               markdown_content, metrics_summary, alerts,
               generated_by, is_archived, requires_action,
               allowed_roles, version, created_at
        FROM ada_reports
        WHERE empresa_id = :empresa_id
        AND is_archived = :archived
    """
    params = {"empresa_id": empresa_id, "archived": archived}

    if report_type:
        query += " AND report_type = :report_type"
        params["report_type"] = report_type

    query += " ORDER BY created_at DESC LIMIT :limit OFFSET :offset"
    params["limit"] = limit
    params["offset"] = offset

    result = await db.execute(text(query), params)
    rows = result.fetchall()

    reports = []
    for row in rows:
        reports.append({
            "id": str(row.id),
            "thread_id": row.thread_id,
            "title": row.title,
            "report_type": row.report_type,
            "source_file": row.source_file,
            "markdown_content": row.markdown_content,
            "metrics_summary": row.metrics_summary,
            "alerts": row.alerts,
            "generated_by": row.generated_by,
            "is_archived": row.is_archived,
            "requires_action": row.requires_action,
            "allowed_roles": row.allowed_roles,
            "version": row.version,
            "created_at": str(row.created_at),
        })

    return {"status": "success", "data": reports, "total": len(reports)}


@router.get("/reports/{report_id}")
async def get_report(report_id: str, db: AsyncSession = Depends(get_db)):
    """Detalle completo de un reporte."""

    result = await db.execute(
        text("SELECT * FROM ada_reports WHERE id = :id"),
        {"id": report_id},
    )
    row = result.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Reporte no encontrado")

    return {
        "id": str(row.id),
        "empresa_id": str(row.empresa_id),
        "thread_id": row.thread_id,
        "title": row.title,
        "report_type": row.report_type,
        "source_file": row.source_file,
        "markdown_content": row.markdown_content,
        "metrics_summary": row.metrics_summary,
        "alerts": row.alerts,
        "generated_by": row.generated_by,
        "is_archived": row.is_archived,
        "requires_action": row.requires_action,
        "allowed_roles": row.allowed_roles,
        "version": row.version,
        "created_at": str(row.created_at),
    }


@router.get("/reports/search/query")
async def search_reports(
    empresa_id: str,
    q: str,
    limit: int = Query(default=10, le=50),
    db: AsyncSession = Depends(get_db),
):
    """Búsqueda full-text dentro de reportes (estilo Obsidian)."""

    # Convertir query a tsquery
    search_terms = " & ".join(q.strip().split())

    result = await db.execute(
        text("""
            SELECT id, title, report_type, source_file,
                   ts_rank(search_vector, to_tsquery('pg_catalog.spanish', :query)) as rank,
                   substring(markdown_content, 1, 300) as preview,
                   created_at
            FROM ada_reports
            WHERE empresa_id = :empresa_id
            AND search_vector @@ to_tsquery('pg_catalog.spanish', :query)
            ORDER BY rank DESC
            LIMIT :limit
        """),
        {"empresa_id": empresa_id, "query": search_terms, "limit": limit},
    )
    rows = result.fetchall()

    results = []
    for row in rows:
        results.append({
            "id": str(row.id),
            "title": row.title,
            "report_type": row.report_type,
            "source_file": row.source_file,
            "rank": float(row.rank),
            "preview": row.preview,
            "created_at": str(row.created_at),
        })

    return {"status": "success", "query": q, "results": results, "total": len(results)}


@router.get("/entities/{entity_name}/360")
async def entity_360_view(entity_name: str, empresa_id: str):
    """Vista 360° de una entidad: todas sus menciones en todas las fuentes."""
    from api.services.graph_navigator import get_entity_360
    result = get_entity_360(entity_name, empresa_id)
    return {"entity": entity_name, "empresa_id": empresa_id, **result}


@router.patch("/reports/{report_id}")
async def update_report(report_id: str, data: dict, db: AsyncSession = Depends(get_db)):
    """Archivar/desarchivar un reporte."""

    is_archived = data.get("is_archived")
    if is_archived is None:
        raise HTTPException(status_code=400, detail="Campo is_archived requerido")

    await db.execute(
        text("""
            UPDATE ada_reports
            SET is_archived = :archived, updated_at = NOW()
            WHERE id = :id
        """),
        {"id": report_id, "archived": is_archived},
    )
    await db.commit()

    return {"status": "updated", "id": report_id, "is_archived": is_archived}


@router.post("/resume/{thread_id}")
async def resume_workflow(thread_id: str, data: dict, db: AsyncSession = Depends(get_db)):
    """
    Reanudar un grafo de LangGraph pausado (HITL).

    Payload:
    {
        "action": "approve|edit|reject",
        "payload_override": { ... }  // opcional
    }
    """

    action = data.get("action", "")
    payload_override = data.get("payload_override", {})

    if action not in ("approve", "edit", "reject"):
        raise HTTPException(status_code=400, detail="action debe ser: approve, edit, reject")

    # Buscar reporte asociado al thread
    result = await db.execute(
        text("SELECT id, empresa_id, report_type FROM ada_reports WHERE thread_id = :tid AND requires_action = TRUE"),
        {"tid": thread_id},
    )
    row = result.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="No hay acción pendiente para este thread")

    if action == "reject":
        # Marcar como resuelto sin ejecutar
        await db.execute(
            text("UPDATE ada_reports SET requires_action = FALSE, updated_at = NOW() WHERE thread_id = :tid"),
            {"tid": thread_id},
        )
        await db.commit()
        return {"status": "rejected", "thread_id": thread_id}

    if action == "approve" or action == "edit":
        # TODO: Reanudar el grafo de LangGraph con el checkpointer
        # Por ahora marcar como resuelto
        await db.execute(
            text("UPDATE ada_reports SET requires_action = FALSE, updated_at = NOW() WHERE thread_id = :tid"),
            {"tid": thread_id},
        )
        await db.commit()

        return {
            "status": "approved" if action == "approve" else "edited",
            "thread_id": thread_id,
            "payload_override": payload_override,
            "message": "Acción ejecutada.",
        }