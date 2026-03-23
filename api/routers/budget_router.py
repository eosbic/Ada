"""
Budget Router — Endpoints de presupuesto, uso de tokens y compra de topups.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text as sql_text
from api.dependencies import get_current_user
from api.database import sync_engine
from api.services.budget_service import (
    get_usage_summary,
    purchase_topup,
    ALLOWED_TOPUP_AMOUNTS,
)


router = APIRouter()


class TopupRequest(BaseModel):
    empresa_id: str
    amount: float
    purchased_by: str


@router.get("/usage/{empresa_id}")
async def usage_endpoint(empresa_id: str, user: dict = Depends(get_current_user)):
    """Resumen de uso de tokens para una empresa."""
    summary = get_usage_summary(empresa_id)
    if summary.get("error"):
        raise HTTPException(status_code=404, detail=summary["error"])
    return summary


@router.get("/usage-all")
async def usage_all_endpoint(
    page: int = 1,
    per_page: int = 20,
    user: dict = Depends(get_current_user),
):
    """Lista budget de todas las empresas con paginacion."""
    offset = (page - 1) * per_page
    try:
        with sync_engine.connect() as conn:
            rows = conn.execute(
                sql_text("""
                    SELECT bl.empresa_id, bl.plan_type, bl.monthly_limit,
                           bl.used_this_month, bl.total_tokens_this_month,
                           bl.topup_balance,
                           e.nombre as empresa_nombre
                    FROM budget_limits bl
                    LEFT JOIN empresas e ON e.id = bl.empresa_id
                    ORDER BY bl.used_this_month DESC
                    LIMIT :lim OFFSET :off
                """),
                {"lim": per_page, "off": offset}
            ).fetchall()

            total = conn.execute(
                sql_text("SELECT COUNT(*) FROM budget_limits")
            ).scalar()

        return {
            "page": page,
            "per_page": per_page,
            "total": total,
            "data": [
                {
                    "empresa_id": str(r.empresa_id),
                    "empresa_nombre": r.empresa_nombre,
                    "plan_type": r.plan_type,
                    "monthly_limit": float(r.monthly_limit or 0),
                    "topup_balance": float(r.topup_balance or 0),
                    "effective_limit": float(r.monthly_limit or 0) + float(r.topup_balance or 0),
                    "used_this_month": float(r.used_this_month or 0),
                    "total_tokens_this_month": int(r.total_tokens_this_month or 0),
                }
                for r in rows
            ],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/top-consumers")
async def top_consumers_endpoint(
    days: int = 30,
    user: dict = Depends(get_current_user),
):
    """Top 10 consumidores de tokens."""
    try:
        with sync_engine.connect() as conn:
            rows = conn.execute(
                sql_text("""
                    SELECT t.empresa_id,
                           e.nombre as empresa_nombre,
                           COUNT(*) as total_calls,
                           SUM(t.input_tokens) as total_input,
                           SUM(t.output_tokens) as total_output,
                           SUM(t.cost_usd) as total_cost
                    FROM token_usage_log t
                    LEFT JOIN empresas e ON e.id = t.empresa_id
                    WHERE t.created_at >= NOW() - INTERVAL '1 day' * :days
                    GROUP BY t.empresa_id, e.nombre
                    ORDER BY total_cost DESC
                    LIMIT 10
                """),
                {"days": days}
            ).fetchall()

        return {
            "days": days,
            "top_consumers": [
                {
                    "empresa_id": str(r.empresa_id),
                    "empresa_nombre": r.empresa_nombre,
                    "total_calls": r.total_calls,
                    "total_input_tokens": int(r.total_input or 0),
                    "total_output_tokens": int(r.total_output or 0),
                    "total_cost_usd": round(float(r.total_cost or 0), 4),
                }
                for r in rows
            ],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/model-breakdown")
async def model_breakdown_endpoint(
    days: int = 30,
    user: dict = Depends(get_current_user),
):
    """Distribucion de uso por modelo."""
    try:
        with sync_engine.connect() as conn:
            rows = conn.execute(
                sql_text("""
                    SELECT model_name,
                           COUNT(*) as total_calls,
                           SUM(input_tokens) as total_input,
                           SUM(output_tokens) as total_output,
                           SUM(cost_usd) as total_cost,
                           SUM(CASE WHEN was_downgraded THEN 1 ELSE 0 END) as downgraded_calls
                    FROM token_usage_log
                    WHERE created_at >= NOW() - INTERVAL '1 day' * :days
                    GROUP BY model_name
                    ORDER BY total_cost DESC
                """),
                {"days": days}
            ).fetchall()

        return {
            "days": days,
            "models": [
                {
                    "model": r.model_name,
                    "total_calls": r.total_calls,
                    "total_input_tokens": int(r.total_input or 0),
                    "total_output_tokens": int(r.total_output or 0),
                    "total_cost_usd": round(float(r.total_cost or 0), 4),
                    "downgraded_calls": int(r.downgraded_calls or 0),
                }
                for r in rows
            ],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/topup")
async def topup_endpoint(
    req: TopupRequest,
    user: dict = Depends(get_current_user),
):
    """Compra un paquete de tokens adicionales."""
    if req.amount not in ALLOWED_TOPUP_AMOUNTS:
        raise HTTPException(
            status_code=400,
            detail=f"Monto invalido. Paquetes disponibles: {ALLOWED_TOPUP_AMOUNTS} USD",
        )

    result = purchase_topup(
        empresa_id=req.empresa_id,
        amount=req.amount,
        purchased_by=req.purchased_by,
    )

    if result.get("error"):
        raise HTTPException(status_code=400, detail=result["error"])

    return result
