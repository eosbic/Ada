"""
Alert Worker — Cron periódico que evalúa alertas pendientes en ada_reports.
Ejecuta alert_agent para reportes con requires_action=TRUE.
"""

import os
import json
import asyncio

from api.database import AsyncSessionLocal
from sqlalchemy import text


ENABLE_ALERT_WORKER = os.getenv("ENABLE_ALERT_WORKER", "false").lower() in ("true", "1", "yes")
ALERT_CHECK_INTERVAL_SECONDS = int(os.getenv("ALERT_CHECK_INTERVAL_SECONDS", "300"))
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")


async def _send_telegram(chat_id: str, text_msg: str):
    """Envía mensaje por Telegram."""
    if not TELEGRAM_BOT_TOKEN or not chat_id:
        return
    try:
        import httpx
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                json={"chat_id": chat_id, "text": text_msg[:4000], "parse_mode": "Markdown"},
            )
    except Exception as e:
        print(f"ALERT WORKER: Telegram send error: {e}")


async def alert_worker_loop():
    """Loop principal del alert worker."""
    if not ENABLE_ALERT_WORKER:
        print("ALERT WORKER: Deshabilitado (ENABLE_ALERT_WORKER != true)")
        return

    print(f"ALERT WORKER: Worker iniciado, intervalo={ALERT_CHECK_INTERVAL_SECONDS}s")

    while True:
        try:
            await _evaluate_pending_alerts()
        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"ALERT WORKER: Error en ciclo: {e}")

        await asyncio.sleep(ALERT_CHECK_INTERVAL_SECONDS)


async def _evaluate_pending_alerts():
    """Evalúa reportes con alertas pendientes."""
    from api.agents.alert_agent import alert_agent

    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                text("""
                    SELECT id, empresa_id, title, report_type, alerts, metrics_summary, created_at
                    FROM ada_reports
                    WHERE requires_action = TRUE AND is_archived = FALSE
                    ORDER BY created_at DESC
                    LIMIT 20
                """)
            )
            rows = result.fetchall()
    except Exception as e:
        print(f"ALERT WORKER: Error consultando reportes: {e}")
        return

    if not rows:
        return

    print(f"ALERT WORKER: Evaluando {len(rows)} reporte(s) pendiente(s)")

    for row in rows:
        report_id = str(row.id)
        empresa_id = str(row.empresa_id)

        try:
            alerts_data = json.loads(row.alerts) if row.alerts else []
            if not isinstance(alerts_data, list) or not alerts_data:
                await _mark_processed(report_id)
                continue

            metrics = json.loads(row.metrics_summary) if row.metrics_summary else {}

            agent_result = await alert_agent.ainvoke({
                "event_type": row.report_type or "unknown",
                "event_data": {
                    "title": row.title or "",
                    "alerts": alerts_data,
                    "metrics": metrics,
                },
                "empresa_id": empresa_id,
            })

            should_notify = agent_result.get("should_notify", False)
            response = agent_result.get("response", "")

            if should_notify and response:
                print(f"ALERT WORKER: Notificación para empresa {empresa_id[:8]} — {row.title}")
                await _notify_admin(empresa_id, response)

            await _mark_processed(report_id)

        except Exception as e:
            print(f"ALERT WORKER: Error evaluando reporte {report_id[:8]}: {e}")
            await _mark_processed(report_id)


async def _mark_processed(report_id: str):
    """Marca reporte como procesado para evitar re-evaluación."""
    try:
        async with AsyncSessionLocal() as db:
            await db.execute(
                text("UPDATE ada_reports SET requires_action = FALSE WHERE id = :id"),
                {"id": report_id},
            )
            await db.commit()
    except Exception as e:
        print(f"ALERT WORKER: Error marcando reporte {report_id[:8]}: {e}")


async def _notify_admin(empresa_id: str, message: str):
    """Envía notificación al admin de la empresa por Telegram."""
    if not TELEGRAM_BOT_TOKEN:
        return

    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                text("""
                    SELECT u.telegram_id, u.nombre
                    FROM usuarios u
                    WHERE u.empresa_id = :eid AND u.rol = 'admin' AND u.telegram_id IS NOT NULL
                    LIMIT 1
                """),
                {"eid": empresa_id},
            )
            row = result.fetchone()

        if row and row.telegram_id:
            await _send_telegram(str(row.telegram_id), f"*Alerta Ada*\n\n{message}")
    except Exception as e:
        print(f"ALERT WORKER: Error notificando admin: {e}")
