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

    return {
        "company": company_data,
        "kpis": {
            "reports_count": reports_count,
            "alerts_count": len(alerts),
            "approvals_count": len(approvals),
            "team_count": team_count,
        },
        "alerts": alerts[:10],
        "approvals": approvals,
        "recent_reports": recent_reports,
        "budget": budget,
        "connections": connections,
    }
