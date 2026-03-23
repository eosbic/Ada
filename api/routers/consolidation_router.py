"""
Consolidation Router — Endpoints para analisis consolidado multi-reporte.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from api.dependencies import get_current_user
from api.services.report_consolidator import (
    parse_period,
    fetch_reports_for_period,
    consolidate_metrics,
)
from api.agents.consolidation_agent import consolidation_agent


router = APIRouter()


class ConsolidationRequest(BaseModel):
    empresa_id: str
    message: str
    user_id: str = ""


@router.get("/consolidation/preview")
async def preview_endpoint(
    empresa_id: str = Query(...),
    period: str = Query("ultimos 12 meses"),
    user: dict = Depends(get_current_user),
):
    """Preview rapido SIN LLM. Instantaneo y gratis."""
    start, end = parse_period(period)
    reports = fetch_reports_for_period(
        empresa_id=empresa_id,
        period_start=start,
        period_end=end,
        include_markdown=False,
    )

    if not reports:
        return {
            "total_reports": 0,
            "period": f"{start} a {end}",
            "message": "Sin reportes en este periodo",
        }

    consolidated = consolidate_metrics(reports)

    return {
        "total_reports": consolidated["total_reports"],
        "period": consolidated["period"],
        "months_covered": consolidated["months_covered"],
        "global_totals": consolidated["global_totals"],
        "trends": consolidated["trends"],
        "report_files": consolidated["report_files"],
        "alerts_count": len(consolidated["all_alerts"]),
    }


@router.post("/consolidation/generate")
async def generate_endpoint(
    req: ConsolidationRequest,
    user: dict = Depends(get_current_user),
):
    """Invoca consolidation_agent para analisis completo."""
    try:
        result = await consolidation_agent.ainvoke({
            "message": req.message,
            "empresa_id": req.empresa_id,
            "user_id": req.user_id,
        })

        return {
            "response": result.get("response", ""),
            "model_used": result.get("model_used", "unknown"),
            "report_count": result.get("report_count", 0),
            "period_start": result.get("period_start", ""),
            "period_end": result.get("period_end", ""),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/consolidation/timeline")
async def timeline_endpoint(
    empresa_id: str = Query(...),
    metric_key: str = Query(...),
    period: str = Query("ultimos 12 meses"),
    user: dict = Depends(get_current_user),
):
    """Serie temporal de una metrica para graficas."""
    start, end = parse_period(period)
    reports = fetch_reports_for_period(
        empresa_id=empresa_id,
        period_start=start,
        period_end=end,
        include_markdown=False,
    )

    if not reports:
        return {"metric_key": metric_key, "data_points": [], "trend": None}

    consolidated = consolidate_metrics(reports)
    by_month = consolidated.get("by_month", {})

    data_points = []
    for month in sorted(by_month.keys()):
        month_data = by_month[month]
        if metric_key in month_data:
            data_points.append({
                "month": month,
                "value": month_data[metric_key]["total"],
                "avg": month_data[metric_key]["avg"],
                "count": month_data[metric_key]["count"],
            })

    trend = consolidated.get("trends", {}).get(metric_key)

    return {
        "metric_key": metric_key,
        "period": f"{start} a {end}",
        "data_points": data_points,
        "trend": trend,
    }


@router.get("/consolidation/available-metrics")
async def available_metrics_endpoint(
    empresa_id: str = Query(...),
    period: str = Query("ultimos 12 meses"),
    user: dict = Depends(get_current_user),
):
    """Lista todas las metricas disponibles en los reportes del periodo."""
    start, end = parse_period(period)
    reports = fetch_reports_for_period(
        empresa_id=empresa_id,
        period_start=start,
        period_end=end,
        include_markdown=False,
    )

    if not reports:
        return {"metrics": [], "total_reports": 0}

    metric_counts = {}
    for r in reports:
        for key, value in r.get("metrics_summary", {}).items():
            if isinstance(value, (int, float)):
                if key not in metric_counts:
                    metric_counts[key] = {"count": 0, "sample_value": value}
                metric_counts[key]["count"] += 1

    metrics = [
        {
            "key": key,
            "appears_in": data["count"],
            "sample_value": data["sample_value"],
        }
        for key, data in sorted(metric_counts.items(), key=lambda x: x[1]["count"], reverse=True)
    ]

    return {
        "period": f"{start} a {end}",
        "total_reports": len(reports),
        "metrics": metrics,
    }
