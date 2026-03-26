"""
Dashboard Router — Datos agregados por empresa.
Un solo endpoint que devuelve TODO lo que el frontend necesita.
"""

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from api.database import get_db
from uuid import UUID

router = APIRouter()


@router.get("/dashboard/{empresa_id}")
async def get_dashboard(empresa_id: UUID, db: AsyncSession = Depends(get_db)):
    """
    Devuelve datos agregados del dashboard para una empresa.
    El frontend consume esto para poblar KPIs, alertas, aprobaciones, etc.
    """

    eid = str(empresa_id)

    # 1. Perfil de empresa
    result = await db.execute(
        text("""
            SELECT company_name, industry_type, business_description, 
                   city, country, currency, num_employees, company_size,
                   ada_custom_name, ada_personality, admin_interests, custom_prompt,
                   main_products, main_services
            FROM ada_company_profile WHERE empresa_id = :eid
        """),
        {"eid": eid}
    )
    profile = result.fetchone()

    company_data = {}
    if profile:
        company_data = {
            "company_name": profile.company_name,
            "industry_type": profile.industry_type,
            "business_description": profile.business_description,
            "city": profile.city,
            "country": profile.country,
            "currency": profile.currency,
            "num_employees": profile.num_employees,
            "company_size": profile.company_size,
            "ada_custom_name": profile.ada_custom_name,
            "ada_personality": profile.ada_personality,
            "custom_prompt": getattr(profile, "custom_prompt", "") or "",
            "admin_interests": profile.admin_interests,
            "main_products": profile.main_products,
            "main_services": profile.main_services,
        }

    # 2. Conteo de reportes
    result = await db.execute(
        text("SELECT COUNT(*) as total FROM ada_reports WHERE empresa_id = :eid AND is_archived = FALSE"),
        {"eid": eid}
    )
    reports_count = result.fetchone().total

    # 3. Alertas activas (de reportes no archivados)
    result = await db.execute(
        text("""
            SELECT id, title, alerts, created_at 
            FROM ada_reports 
            WHERE empresa_id = :eid AND is_archived = FALSE AND alerts != '[]'::jsonb
            ORDER BY created_at DESC LIMIT 10
        """),
        {"eid": eid}
    )
    alert_rows = result.fetchall()
    
    alerts = []
    for row in alert_rows:
        report_alerts = row.alerts if isinstance(row.alerts, list) else []
        for a in report_alerts:
            alerts.append({
                "level": a.get("level", "info"),
                "msg": a.get("message", a.get("msg", "")),
                "source": row.title,
                "created_at": str(row.created_at)[:16],
            })

    # 4. Aprobaciones pendientes
    result = await db.execute(
        text("""
            SELECT id, title, report_type, thread_id, created_at
            FROM ada_reports 
            WHERE empresa_id = :eid AND requires_action = TRUE AND is_archived = FALSE
            ORDER BY created_at DESC
        """),
        {"eid": eid}
    )
    approval_rows = result.fetchall()
    approvals = [{
        "id": str(row.id),
        "title": row.title,
        "type": row.report_type,
        "thread_id": row.thread_id,
        "created_at": str(row.created_at)[:16],
    } for row in approval_rows]

    # 5. Miembros del equipo
    result = await db.execute(
        text("SELECT COUNT(*) as total FROM team_members WHERE empresa_id = :eid AND is_active = TRUE"),
        {"eid": eid}
    )
    team_count = result.fetchone().total

    # 6. Últimos reportes
    result = await db.execute(
        text("""
            SELECT id, title, report_type, source_file, created_at, generated_by, alerts
            FROM ada_reports 
            WHERE empresa_id = :eid AND is_archived = FALSE
            ORDER BY created_at DESC LIMIT 5
        """),
        {"eid": eid}
    )
    recent_rows = result.fetchall()
    recent_reports = [{
        "id": str(row.id),
        "title": row.title,
        "type": row.report_type,
        "source": row.source_file,
        "model": row.generated_by,
        "created_at": str(row.created_at)[:16],
        "alerts_count": len(row.alerts) if isinstance(row.alerts, list) else 0,
    } for row in recent_rows]

    # 7. Budget
    result = await db.execute(
        text("SELECT monthly_limit, used_this_month FROM budget_limits WHERE empresa_id = :eid"),
        {"eid": eid}
    )
    budget_row = result.fetchone()
    budget = {
        "limit": float(budget_row.monthly_limit) if budget_row else 100,
        "used": float(budget_row.used_this_month) if budget_row else 0,
    }

    # 8. Conexiones OAuth
    result = await db.execute(
        text("SELECT provider, is_active FROM tenant_credentials WHERE empresa_id = :eid"),
        {"eid": eid}
    )
    conn_rows = result.fetchall()
    connections = {row.provider: row.is_active for row in conn_rows}

    # 9. Metricas del ultimo excel_analysis
    result = await db.execute(
        text("""
            SELECT metrics_summary, created_at FROM ada_reports
            WHERE empresa_id = :eid AND report_type = 'excel_analysis'
              AND is_archived = FALSE AND metrics_summary IS NOT NULL
            ORDER BY created_at DESC LIMIT 1
        """),
        {"eid": eid}
    )
    last_metrics_row = result.fetchone()
    last_metrics = {}
    last_report_date = None
    if last_metrics_row:
        ms = last_metrics_row.metrics_summary
        last_metrics = ms if isinstance(ms, dict) else {}
        last_report_date = last_metrics_row.created_at

    # 10. Dias desde ultimo reporte (cualquier tipo)
    days_since_last = None
    if recent_rows:
        from datetime import datetime, timezone
        last_dt = recent_rows[0].created_at
        if last_dt:
            if last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)
            days_since_last = (now - last_dt).days

    # 11. Resumen de alertas por severidad
    alert_summary = {"critical": 0, "warning": 0, "info": 0}
    for a in alerts:
        lvl = a.get("level", "info")
        if lvl in alert_summary:
            alert_summary[lvl] += 1

    # 12. Top entidades mencionadas (tags de reportes)
    top_entities = []
    try:
        result = await db.execute(
            text("""
                SELECT entity_name, entity_type, COUNT(*) as mentions
                FROM report_links
                WHERE report_id IN (
                    SELECT id FROM ada_reports WHERE empresa_id = :eid AND is_archived = FALSE
                )
                AND entity_name IS NOT NULL
                GROUP BY entity_name, entity_type
                ORDER BY mentions DESC
                LIMIT 8
            """),
            {"eid": eid}
        )
        entity_rows = result.fetchall()
        top_entities = [
            {"name": r.entity_name, "type": r.entity_type or "otro", "mentions": r.mentions}
            for r in entity_rows
        ]
    except Exception:
        # report_links puede no tener entity_name — fallback a tags
        try:
            result = await db.execute(
                text("""
                    SELECT tag, COUNT(*) as cnt
                    FROM (
                        SELECT jsonb_array_elements_text(
                            CASE WHEN jsonb_typeof(metrics_summary->'semantic_tags') = 'array'
                                 THEN metrics_summary->'semantic_tags'
                                 ELSE '[]'::jsonb END
                        ) as tag
                        FROM ada_reports
                        WHERE empresa_id = :eid AND is_archived = FALSE
                    ) sub
                    GROUP BY tag ORDER BY cnt DESC LIMIT 8
                """),
                {"eid": eid}
            )
            tag_rows = result.fetchall()
            top_entities = [{"name": r.tag, "type": "tag", "mentions": r.cnt} for r in tag_rows]
        except Exception:
            pass

    return {
        "company": company_data,
        "kpis": {
            "reports_count": reports_count,
            "alerts_count": len(alerts),
            "approvals_count": len(approvals),
            "team_count": team_count,
        },
        "alerts": alerts[:10],
        "alert_summary": alert_summary,
        "approvals": approvals,
        "recent_reports": recent_reports,
        "budget": budget,
        "connections": connections,
        "last_metrics": last_metrics,
        "days_since_last": days_since_last,
        "top_entities": top_entities,
    }
