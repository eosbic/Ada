"""
Trail Service — Guarda mini-reportes ("rastros") de datos externos en ada_reports.
Cuando un agente consulta emails, calendario, tareas o Notion, deja rastro aquí.
El KG pipeline existente conecta estos rastros automáticamente.
"""

import json
from api.database import sync_engine
from sqlalchemy import text as sql_text


def leave_trail(
    empresa_id: str,
    title: str,
    report_type: str,
    content: str,
    source_ref: str = "",
    metadata: dict = None,
) -> str:
    """Guarda un mini-reporte en ada_reports y ejecuta KG pipeline. Retorna report_id o None."""
    if not empresa_id or not content or len(content.strip()) < 20:
        return None

    try:
        with sync_engine.connect() as conn:
            result = conn.execute(
                sql_text("""
                    INSERT INTO ada_reports
                        (empresa_id, title, report_type, source_file,
                         markdown_content, metrics_summary, generated_by,
                         allowed_roles, requires_action)
                    VALUES (:eid, :title, :rtype, :source,
                            :markdown, :metrics, 'trail_service',
                            :roles, FALSE)
                    RETURNING id
                """),
                {
                    "eid": empresa_id,
                    "title": title[:200],
                    "rtype": report_type,
                    "source": source_ref[:255],
                    "markdown": content[:5000],
                    "metrics": json.dumps(metadata or {}, ensure_ascii=False, default=str),
                    "roles": ["administrador", "gerente"],
                },
            )
            row = result.fetchone()
            report_id = str(row[0]) if row else None
            conn.commit()

        if report_id:
            from api.services.kg_pipeline import run_kg_pipeline
            run_kg_pipeline(report_id, empresa_id, content, "")
            print(f"TRAIL: {report_type} guardado → {report_id[:8]}...")

        return report_id

    except Exception as e:
        print(f"TRAIL: Error guardando {report_type}: {e}")
        return None


def leave_email_trail(empresa_id: str, emails: list, search_query: str = "") -> None:
    """Guarda rastro de emails consultados."""
    if not emails:
        return
    lines = []
    for e in emails[:5]:
        lines.append(
            f"De: {e.get('from', '')}\n"
            f"Asunto: {e.get('subject', '')}\n"
            f"Fecha: {e.get('date', '')}\n"
            f"{e.get('snippet', '')}"
        )
    content = f"Emails encontrados para '{search_query}':\n\n" + "\n\n---\n\n".join(lines)
    leave_trail(
        empresa_id,
        f"Emails: {search_query[:80]}",
        "email_summary",
        content,
        source_ref=f"gmail_search:{search_query}",
        metadata={"email_count": len(emails), "query": search_query},
    )


def leave_calendar_trail(empresa_id: str, events: list, search_context: str = "") -> None:
    """Guarda rastro de eventos de calendario consultados."""
    if not events:
        return
    lines = []
    for ev in events[:10]:
        lines.append(
            f"Evento: {ev.get('summary', '')}\n"
            f"Inicio: {ev.get('start', '')}\n"
            f"Ubicacion: {ev.get('location', '')}\n"
            f"Asistentes: {', '.join(ev.get('attendees', []))}"
        )
    content = f"Eventos de calendario ({search_context}):\n\n" + "\n\n---\n\n".join(lines)
    leave_trail(
        empresa_id,
        f"Calendario: {search_context[:80]}",
        "calendar_event_summary",
        content,
        source_ref=f"calendar:{search_context}",
        metadata={"event_count": len(events), "context": search_context},
    )


def leave_pm_trail(
    empresa_id: str, tasks: list, project_name: str = "", pm_provider: str = ""
) -> None:
    """Guarda rastro de tareas de PM consultadas."""
    if not tasks:
        return
    lines = []
    for t in tasks[:15]:
        lines.append(
            f"Tarea: {t.get('name', '')}\n"
            f"Estado: {t.get('state', '')}\n"
            f"Prioridad: {t.get('priority', '')}\n"
            f"Asignado: {t.get('assignee', '')}\n"
            f"Fecha: {t.get('due_date', '')}"
        )
    content = (
        f"Tareas de {pm_provider or 'PM'} — Proyecto: {project_name}:\n\n"
        + "\n\n---\n\n".join(lines)
    )
    leave_trail(
        empresa_id,
        f"Tareas: {project_name[:80]}",
        "pm_task_summary",
        content,
        source_ref=f"{pm_provider}:{project_name}",
        metadata={"task_count": len(tasks), "project": project_name, "provider": pm_provider},
    )


def leave_notion_trail(empresa_id: str, docs: list, search_query: str = "") -> None:
    """Guarda rastro de documentos Notion consultados."""
    if not docs:
        return
    lines = []
    for d in docs[:10]:
        lines.append(
            f"Documento: {d.get('title', '')}\n"
            f"Tipo: {d.get('type', '')}\n"
            f"Ultima edicion: {d.get('last_edited', '')}\n"
            f"URL: {d.get('url', '')}"
        )
    content = f"Documentos Notion para '{search_query}':\n\n" + "\n\n---\n\n".join(lines)
    leave_trail(
        empresa_id,
        f"Notion: {search_query[:80]}",
        "notion_summary",
        content,
        source_ref=f"notion_search:{search_query}",
        metadata={"doc_count": len(docs), "query": search_query},
    )
