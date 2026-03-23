"""
Budget Service — Control de presupuesto y consumo de tokens por empresa.
Verifica limites, fuerza downgrade, loguea uso y envia alertas.
"""

import os
import json
from dataclasses import dataclass
from typing import Optional
from sqlalchemy import text as sql_text
from api.database import sync_engine


RESEND_API_KEY = os.getenv("RESEND_API_KEY")

# Paquetes de topup permitidos (USD)
ALLOWED_TOPUP_AMOUNTS = [20, 50, 100]


@dataclass
class BudgetStatus:
    """Estado del presupuesto de una empresa."""
    allowed: bool
    plan_type: str
    monthly_limit: float
    topup_balance: float
    used: float
    remaining: float
    usage_percent: float
    is_downgraded: bool
    forced_model: Optional[str]


def check_budget(empresa_id: str) -> BudgetStatus:
    """Consulta budget_limits y retorna el estado del presupuesto."""
    if not empresa_id:
        return BudgetStatus(
            allowed=True, plan_type="start", monthly_limit=0,
            topup_balance=0, used=0, remaining=0, usage_percent=0,
            is_downgraded=False, forced_model=None,
        )

    try:
        with sync_engine.connect() as conn:
            row = conn.execute(
                sql_text("""
                    SELECT monthly_limit, used_this_month, plan_type,
                           alert_threshold, alert_sent_this_month,
                           topup_balance
                    FROM budget_limits
                    WHERE empresa_id = :eid
                """),
                {"eid": empresa_id}
            ).fetchone()

            if not row:
                return BudgetStatus(
                    allowed=True, plan_type="start", monthly_limit=0,
                    topup_balance=0, used=0, remaining=0, usage_percent=0,
                    is_downgraded=False, forced_model=None,
                )

            monthly_limit = float(row.monthly_limit or 0)
            topup_balance = float(row.topup_balance or 0)
            effective_limit = monthly_limit + topup_balance
            used = float(row.used_this_month or 0)
            plan_type = row.plan_type or "start"
            alert_threshold = float(row.alert_threshold or 0.8)
            alert_sent = row.alert_sent_this_month or False

            if effective_limit <= 0:
                return BudgetStatus(
                    allowed=True, plan_type=plan_type, monthly_limit=monthly_limit,
                    topup_balance=topup_balance, used=used, remaining=0,
                    usage_percent=0, is_downgraded=False, forced_model=None,
                )

            remaining = max(0, effective_limit - used)
            usage_percent = (used / effective_limit) * 100

            is_downgraded = used >= effective_limit
            forced_model = "gemini-flash" if is_downgraded else None

            # Alerta al 80% (una vez por mes)
            if usage_percent >= alert_threshold * 100 and not alert_sent and not is_downgraded:
                _send_budget_alert(empresa_id, used, effective_limit, usage_percent, conn)

            return BudgetStatus(
                allowed=not is_downgraded,
                plan_type=plan_type,
                monthly_limit=monthly_limit,
                topup_balance=topup_balance,
                used=round(used, 4),
                remaining=round(remaining, 4),
                usage_percent=round(usage_percent, 2),
                is_downgraded=is_downgraded,
                forced_model=forced_model,
            )

    except Exception as e:
        print(f"BUDGET: Error consultando presupuesto: {e}")
        return BudgetStatus(
            allowed=True, plan_type="start", monthly_limit=0,
            topup_balance=0, used=0, remaining=0, usage_percent=0,
            is_downgraded=False, forced_model=None,
        )


def _send_budget_alert(empresa_id: str, used: float, limit: float, pct: float, conn):
    """Envia alerta de presupuesto al admin de la empresa."""
    try:
        conn.execute(
            sql_text("""
                UPDATE budget_limits
                SET alert_sent_this_month = TRUE
                WHERE empresa_id = :eid
            """),
            {"eid": empresa_id}
        )
        conn.commit()
    except Exception as e:
        print(f"BUDGET: Error marcando alerta: {e}")

    message = (
        f"Alerta de presupuesto Ada: empresa {empresa_id[:8]}... "
        f"ha consumido ${used:.2f} de ${limit:.2f} ({pct:.1f}%). "
        f"Al alcanzar 100% se degradara automaticamente a modelos gratuitos."
    )

    if RESEND_API_KEY:
        try:
            import httpx
            httpx.post(
                "https://api.resend.com/emails",
                headers={
                    "Authorization": f"Bearer {RESEND_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "from": "Ada <ada@notifications.ada.ai>",
                    "to": [f"admin+{empresa_id[:8]}@empresa.com"],
                    "subject": f"Ada: Alerta de presupuesto ({pct:.0f}%)",
                    "text": message,
                },
                timeout=10,
            )
            print(f"BUDGET: Alerta email enviada para empresa {empresa_id[:8]}...")
        except Exception as e:
            print(f"BUDGET: Error enviando email: {e}")
    else:
        print(f"BUDGET ALERT (dev mode): {message}")


# Modelos permitidos por plan
PLAN_MODELS = {
    "start": {
        "allowed": ["gemini-flash", "qwen-72b"],
        "priority": ["gemini-flash", "qwen-72b"],
    },
    "premium": {
        "allowed": ["gemini-flash", "qwen-72b", "sonnet", "opus"],
        "priority": ["qwen-72b", "sonnet", "gemini-flash", "opus"],
    },
    "enterprise": {
        "allowed": ["gemini-flash", "qwen-72b", "sonnet", "opus"],
        "priority": ["opus", "sonnet", "qwen-72b", "gemini-flash"],
    },
}


def get_model_for_plan(
    plan_type: str, task: str, requested_model: str = None
) -> tuple[str, bool]:
    """
    Verifica si el modelo solicitado esta permitido en el plan.
    Retorna (model_name, was_downgraded).
    """
    plan = PLAN_MODELS.get(plan_type, PLAN_MODELS["start"])
    allowed = plan["allowed"]

    if requested_model and requested_model in allowed:
        return requested_model, False

    if requested_model and requested_model not in allowed:
        fallback = plan["priority"][0] if plan["priority"] else "gemini-flash"
        return fallback, True

    # Sin preferencia: usar el primero de la prioridad del plan
    return plan["priority"][0] if plan["priority"] else "gemini-flash", False


def log_usage(
    empresa_id: str,
    user_id: str,
    agent: str,
    model_name: str,
    task_type: str,
    input_tokens: int,
    output_tokens: int,
    cost_usd: float,
    was_downgraded: bool = False,
    original_model: str = None,
) -> None:
    """Inserta en token_usage_log y actualiza budget_limits."""
    try:
        with sync_engine.connect() as conn:
            conn.execute(
                sql_text("""
                    INSERT INTO token_usage_log
                        (empresa_id, user_id, agent, model_name, task_type,
                         input_tokens, output_tokens, cost_usd,
                         was_downgraded, original_model)
                    VALUES
                        (:eid, :uid, :agent, :model, :task,
                         :inp, :out, :cost,
                         :downgraded, :orig)
                """),
                {
                    "eid": empresa_id, "uid": user_id or None,
                    "agent": agent, "model": model_name, "task": task_type,
                    "inp": input_tokens, "out": output_tokens, "cost": cost_usd,
                    "downgraded": was_downgraded, "orig": original_model,
                }
            )

            total_tokens = input_tokens + output_tokens
            conn.execute(
                sql_text("""
                    UPDATE budget_limits
                    SET used_this_month = used_this_month + :cost,
                        total_tokens_this_month = total_tokens_this_month + :tokens
                    WHERE empresa_id = :eid
                """),
                {"cost": cost_usd, "tokens": total_tokens, "eid": empresa_id}
            )

            conn.commit()
    except Exception as e:
        print(f"BUDGET: Error logueando uso: {e}")


def extract_token_usage(llm_response) -> tuple[int, int]:
    """
    Extrae input/output tokens de response_metadata.
    Compatible con Anthropic, OpenAI, Google.
    Fallback: estimar por longitud de contenido.
    """
    try:
        meta = getattr(llm_response, "response_metadata", {}) or {}

        # Anthropic format
        usage = meta.get("usage", {})
        if usage:
            inp = usage.get("input_tokens", 0)
            out = usage.get("output_tokens", 0)
            if inp or out:
                return int(inp), int(out)

        # OpenAI format
        token_usage = meta.get("token_usage", {})
        if token_usage:
            inp = token_usage.get("prompt_tokens", 0)
            out = token_usage.get("completion_tokens", 0)
            if inp or out:
                return int(inp), int(out)

        # Google format
        usage_meta = meta.get("usage_metadata", {})
        if usage_meta:
            inp = usage_meta.get("prompt_token_count", 0)
            out = usage_meta.get("candidates_token_count", 0)
            if inp or out:
                return int(inp), int(out)

    except Exception:
        pass

    # Fallback: estimar por contenido
    content = getattr(llm_response, "content", "") or ""
    return 0, len(content) // 4


def get_usage_summary(empresa_id: str) -> dict:
    """Resumen de uso para dashboard."""
    try:
        with sync_engine.connect() as conn:
            # Budget actual
            budget = conn.execute(
                sql_text("""
                    SELECT monthly_limit, used_this_month, plan_type,
                           total_tokens_this_month, topup_balance
                    FROM budget_limits
                    WHERE empresa_id = :eid
                """),
                {"eid": empresa_id}
            ).fetchone()

            if not budget:
                return {"error": "No budget configured", "empresa_id": empresa_id}

            # Uso por modelo
            by_model = conn.execute(
                sql_text("""
                    SELECT model_name,
                           COUNT(*) as calls,
                           SUM(input_tokens) as total_input,
                           SUM(output_tokens) as total_output,
                           SUM(cost_usd) as total_cost
                    FROM token_usage_log
                    WHERE empresa_id = :eid
                    AND created_at >= DATE_TRUNC('month', NOW())
                    GROUP BY model_name
                    ORDER BY total_cost DESC
                """),
                {"eid": empresa_id}
            ).fetchall()

            # Uso por agente
            by_agent = conn.execute(
                sql_text("""
                    SELECT agent,
                           COUNT(*) as calls,
                           SUM(cost_usd) as total_cost
                    FROM token_usage_log
                    WHERE empresa_id = :eid
                    AND created_at >= DATE_TRUNC('month', NOW())
                    GROUP BY agent
                    ORDER BY total_cost DESC
                """),
                {"eid": empresa_id}
            ).fetchall()

            # Downgrades
            downgrades = conn.execute(
                sql_text("""
                    SELECT COUNT(*) as total_downgrades
                    FROM token_usage_log
                    WHERE empresa_id = :eid
                    AND was_downgraded = TRUE
                    AND created_at >= DATE_TRUNC('month', NOW())
                """),
                {"eid": empresa_id}
            ).fetchone()

            effective_limit = float(budget.monthly_limit or 0) + float(budget.topup_balance or 0)

            return {
                "empresa_id": empresa_id,
                "plan_type": budget.plan_type,
                "monthly_limit": float(budget.monthly_limit or 0),
                "topup_balance": float(budget.topup_balance or 0),
                "effective_limit": effective_limit,
                "used_this_month": float(budget.used_this_month or 0),
                "total_tokens_this_month": int(budget.total_tokens_this_month or 0),
                "remaining": max(0, effective_limit - float(budget.used_this_month or 0)),
                "by_model": [
                    {
                        "model": r.model_name,
                        "calls": r.calls,
                        "input_tokens": int(r.total_input or 0),
                        "output_tokens": int(r.total_output or 0),
                        "cost_usd": round(float(r.total_cost or 0), 4),
                    }
                    for r in by_model
                ],
                "by_agent": [
                    {
                        "agent": r.agent,
                        "calls": r.calls,
                        "cost_usd": round(float(r.total_cost or 0), 4),
                    }
                    for r in by_agent
                ],
                "downgrades": int(downgrades.total_downgrades) if downgrades else 0,
            }

    except Exception as e:
        print(f"BUDGET: Error obteniendo resumen: {e}")
        return {"error": str(e), "empresa_id": empresa_id}


def purchase_topup(empresa_id: str, amount: float, purchased_by: str) -> dict:
    """
    Compra un paquete de tokens adicionales.
    Valida que amount este en [20, 50, 100].
    """
    if amount not in ALLOWED_TOPUP_AMOUNTS:
        return {
            "error": f"Monto invalido. Paquetes disponibles: {ALLOWED_TOPUP_AMOUNTS} USD",
            "allowed_amounts": ALLOWED_TOPUP_AMOUNTS,
        }

    try:
        with sync_engine.connect() as conn:
            # Incrementar topup_balance
            conn.execute(
                sql_text("""
                    UPDATE budget_limits
                    SET topup_balance = topup_balance + :amount
                    WHERE empresa_id = :eid
                """),
                {"amount": amount, "eid": empresa_id}
            )

            # Registrar la compra
            conn.execute(
                sql_text("""
                    INSERT INTO budget_topups (empresa_id, amount, purchased_by)
                    VALUES (:eid, :amount, :uid)
                """),
                {"eid": empresa_id, "amount": amount, "uid": purchased_by or None}
            )

            # Obtener nuevo balance
            row = conn.execute(
                sql_text("""
                    SELECT monthly_limit, topup_balance, used_this_month
                    FROM budget_limits
                    WHERE empresa_id = :eid
                """),
                {"eid": empresa_id}
            ).fetchone()

            conn.commit()

            if row:
                effective = float(row.monthly_limit or 0) + float(row.topup_balance or 0)
                return {
                    "success": True,
                    "amount_purchased": amount,
                    "new_topup_balance": float(row.topup_balance or 0),
                    "effective_limit": effective,
                    "used": float(row.used_this_month or 0),
                    "remaining": max(0, effective - float(row.used_this_month or 0)),
                }

            return {"error": "Empresa no encontrada en budget_limits"}

    except Exception as e:
        print(f"BUDGET: Error comprando topup: {e}")
        return {"error": str(e)}
