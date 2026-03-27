"""
Morning Brief Agent — Resumen ejecutivo diario.

Genera un briefing matutino cruzando:
1. Agenda del día (Calendar)
2. Emails importantes no leídos (Gmail)
3. Alertas pendientes (ada_reports)
4. Tareas vencidas o próximas (Plane)
5. Tips contextuales para cada reunión del día

El CEO abre Telegram o el portal y Ada le dice:
"Buenos días William. Tu día de hoy:"
"""

import json
from datetime import datetime
from typing import TypedDict, Optional, List, Dict
from langgraph.graph import StateGraph, END
from models.selector import selector


class MorningState(TypedDict, total=False):
    empresa_id: str
    user_id: str
    message: str

    # Datos recolectados
    calendar_events: str
    unread_emails: str
    pending_alerts: str
    pending_tasks: str
    user_name: str

    # Output
    response: str
    model_used: str


# ─── NODO 1: Obtener agenda del día ──────────────────────

async def fetch_today_calendar(state: MorningState) -> dict:
    empresa_id = state.get("empresa_id", "")
    user_id = state.get("user_id", "")

    try:
        from api.services.calendar_service import calendar_list_events
        events = calendar_list_events(days_ahead=1, max_results=10, empresa_id=empresa_id, user_id=user_id)

        if events:
            cal_text = "\n".join([
                f"🕐 {e['start'][11:16] if len(e['start']) > 11 else e['start']} — {e['summary']}"
                + (f" (📍 {e['location']})" if e.get('location') else "")
                + (f" (👥 {', '.join(e['attendees'][:3])})" if e.get('attendees') else "")
                for e in events
            ])
        else:
            cal_text = "📅 Sin reuniones hoy. Agenda libre."

        try:
            from api.services.trail_service import leave_calendar_trail
            if events:
                leave_calendar_trail(empresa_id, events, search_context="morning brief agenda")
        except Exception:
            pass

        print(f"MORNING BRIEF: {len(events)} eventos hoy")
        return {"calendar_events": cal_text}

    except Exception as e:
        print(f"MORNING BRIEF calendar error: {e}")
        return {"calendar_events": "No se pudo consultar el calendario."}


# ─── NODO 2: Obtener emails no leídos ────────────────────

async def fetch_unread_emails(state: MorningState) -> dict:
    empresa_id = state.get("empresa_id", "")
    user_id = state.get("user_id", "")

    try:
        from api.services.gmail_service import gmail_search
        emails = gmail_search("is:unread newer_than:1d", max_results=5, empresa_id=empresa_id, user_id=user_id)

        if emails:
            email_text = "\n".join([
                f"📧 {e['subject'][:60]} — de {e['from'].split('<')[0].strip()}"
                for e in emails
            ])
        else:
            email_text = "📧 Bandeja al día. Sin emails urgentes."

        try:
            from api.services.trail_service import leave_email_trail
            if emails:
                leave_email_trail(empresa_id, emails, search_query="morning brief unread")
        except Exception:
            pass

        print(f"MORNING BRIEF: {len(emails)} emails no leídos")
        return {"unread_emails": email_text}

    except Exception as e:
        print(f"MORNING BRIEF email error: {e}")
        return {"unread_emails": "No se pudo consultar el email."}


# ─── NODO 3: Obtener alertas pendientes ──────────────────

async def fetch_pending_alerts(state: MorningState) -> dict:
    empresa_id = state.get("empresa_id", "")

    try:
        from api.database import sync_engine
        from sqlalchemy import text as sql_text

        with sync_engine.connect() as conn:
            result = conn.execute(
                sql_text("""
                    SELECT title, alerts, created_at
                    FROM ada_reports
                    WHERE empresa_id = :eid
                    AND is_archived = FALSE
                    AND alerts::text != '[]'
                    ORDER BY created_at DESC
                    LIMIT 5
                """),
                {"eid": empresa_id},
            )
            rows = result.fetchall()

        alerts_text = ""
        for row in rows:
            alerts = row.alerts if isinstance(row.alerts, list) else json.loads(row.alerts) if row.alerts else []
            critical = [a for a in alerts if a.get("level") == "critical"]
            if critical:
                alerts_text += f"🔴 {row.title}: {critical[0].get('message', '')}\n"
            elif alerts:
                alerts_text += f"⚠️ {row.title}: {alerts[0].get('message', '')}\n"

        if not alerts_text:
            alerts_text = "✅ Sin alertas pendientes."

        print(f"MORNING BRIEF: {len(rows)} reportes con alertas")
        return {"pending_alerts": alerts_text}

    except Exception as e:
        print(f"MORNING BRIEF alerts error: {e}")
        return {"pending_alerts": "No se pudo consultar alertas."}


# ─── NODO 4: Obtener tareas pendientes (Plane) ───────────

async def fetch_pending_tasks(state: MorningState) -> dict:
    empresa_id = state.get("empresa_id", "")

    try:
        from api.mcp_servers.mcp_host import mcp_host

        projects = await mcp_host.call_tool_by_name("plane_list_projects", {}, empresa_id)

        tasks_text = ""
        all_tasks = []
        if isinstance(projects, list) and projects:
            for project in projects[:2]:
                issues = await mcp_host.call_tool_by_name(
                    "plane_list_issues",
                    {"project_id": project["id"], "max_results": 5},
                    empresa_id
                )
                if isinstance(issues, list):
                    all_tasks.extend(issues)
                    urgent = [i for i in issues if i.get("priority") in ("urgent", "high")]
                    if urgent:
                        for i in urgent[:3]:
                            emoji = "🔴" if i.get("priority") == "urgent" else "🟠"
                            tasks_text += f"{emoji} {i.get('name', '')} ({project.get('name', '')})\n"

        try:
            from api.services.trail_service import leave_pm_trail
            if all_tasks:
                leave_pm_trail(empresa_id, all_tasks, project_name="morning brief", pm_provider="plane")
        except Exception:
            pass

        if not tasks_text:
            tasks_text = "✅ Sin tareas urgentes."

        print(f"MORNING BRIEF: Tareas consultadas")
        return {"pending_tasks": tasks_text}

    except Exception as e:
        print(f"MORNING BRIEF tasks error: {e}")
        return {"pending_tasks": "No se pudo consultar tareas."}


# ─── NODO 5: Obtener nombre del usuario ──────────────────

async def fetch_user_name(state: MorningState) -> dict:
    user_id = state.get("user_id", "")
    empresa_id = state.get("empresa_id", "")

    try:
        from api.database import sync_engine
        from sqlalchemy import text as sql_text

        with sync_engine.connect() as conn:
            result = conn.execute(
                sql_text("SELECT display_name FROM team_members WHERE empresa_id = :eid AND user_id = :uid"),
                {"eid": empresa_id, "uid": user_id},
            )
            row = result.fetchone()

        name = row.display_name if row else ""
        return {"user_name": name}

    except Exception:
        return {"user_name": ""}


# ─── NODO 6: Generar briefing matutino ───────────────────

async def generate_morning_brief(state: MorningState) -> dict:
    model, model_name = selector.get_model("chat_with_tools")

    user_name = state.get("user_name", "")
    calendar = state.get("calendar_events", "")
    emails = state.get("unread_emails", "")
    alerts = state.get("pending_alerts", "")
    tasks = state.get("pending_tasks", "")

    today = datetime.now().strftime("%A %d de %B de %Y")

    prompt = f"""Genera el BRIEFING MATUTINO para {user_name or 'el CEO'}.
Fecha: {today}

## DATOS RECOLECTADOS POR ADA:

### Agenda de hoy
{calendar}

### Emails no leídos
{emails}

### Alertas de reportes
{alerts}

### Tareas urgentes
{tasks}

## INSTRUCCIONES:

1. Saludo breve y directo con el nombre
2. Resumen del día en 2 oraciones (cuántas reuniones, emails pendientes, alertas)
3. AGENDA detallada con tips para cada reunión:
   - Para cada reunión: nombre, hora, y un TIP contextual
   - Ejemplo: "10:00 AM — Reunión con Proveedor X. TIP: En el último análisis detectamos margen negativo en sus productos. Negociar descuento."
4. ALERTAS que necesitan atención HOY
5. TAREAS urgentes/vencidas
6. Cierre motivacional de 1 oración

FORMATO: Directo, profesional, español. Emojis semánticos. Sin markdown excesivo.
NO inventes datos. Si algo no tiene info, sáltalo."""

    response = await model.ainvoke([
        {"role": "system", "content": (
            "Eres Ada, la asistente ejecutiva más eficiente del mundo. "
            "Tu Morning Brief es lo primero que el CEO lee cada mañana. "
            "Debe ser tan bueno que el CEO no pueda empezar su día sin él."
        )},
        {"role": "user", "content": prompt},
    ])

    print(f"MORNING BRIEF: Generado con {model_name}")

    return {
        "response": response.content,
        "model_used": model_name,
    }


# ─── Compilar grafo ──────────────────────────────────────

graph = StateGraph(MorningState)
graph.add_node("calendar", fetch_today_calendar)
graph.add_node("emails", fetch_unread_emails)
graph.add_node("alerts", fetch_pending_alerts)
graph.add_node("tasks", fetch_pending_tasks)
graph.add_node("user", fetch_user_name)
graph.add_node("brief", generate_morning_brief)

graph.set_entry_point("calendar")
graph.add_edge("calendar", "emails")
graph.add_edge("emails", "alerts")
graph.add_edge("alerts", "tasks")
graph.add_edge("tasks", "user")
graph.add_edge("user", "brief")
graph.add_edge("brief", END)

morning_brief_agent = graph.compile()