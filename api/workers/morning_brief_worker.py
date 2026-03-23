"""
Morning Brief Worker — Cron diario que ejecuta morning brief para todas las empresas activas.
Envía briefing por Telegram a admins si bot está configurado.
"""

import os
import asyncio
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from api.database import AsyncSessionLocal
from sqlalchemy import text


ENABLE_MORNING_BRIEF = os.getenv("ENABLE_MORNING_BRIEF", "false").lower() in ("true", "1", "yes")
MORNING_BRIEF_HOUR = int(os.getenv("MORNING_BRIEF_HOUR", "7"))
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TZ = ZoneInfo("America/Bogota")


async def _send_telegram(chat_id: str, text_msg: str):
    """Envía mensaje por Telegram si el bot está configurado."""
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
        print(f"MORNING BRIEF: Telegram send error: {e}")


async def morning_brief_worker_loop():
    """Loop principal del morning brief worker."""
    if not ENABLE_MORNING_BRIEF:
        print("MORNING BRIEF: Deshabilitado (ENABLE_MORNING_BRIEF != true)")
        return

    print(f"MORNING BRIEF: Worker iniciado, ejecutará a las {MORNING_BRIEF_HOUR}:00 Colombia")

    while True:
        try:
            now = datetime.now(TZ)
            target = now.replace(hour=MORNING_BRIEF_HOUR, minute=0, second=0, microsecond=0)

            if now >= target:
                target += timedelta(days=1)

            wait_seconds = (target - now).total_seconds()
            print(f"MORNING BRIEF: Esperando {wait_seconds:.0f}s hasta {target.isoformat()}")
            await asyncio.sleep(wait_seconds)

            # Ejecutar morning brief
            print("MORNING BRIEF: Iniciando briefing diario...")
            await _run_morning_briefs()

        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"MORNING BRIEF: Error en loop: {e}")
            await asyncio.sleep(3600)


async def _run_morning_briefs():
    """Ejecuta morning brief para todas las empresas activas."""
    from api.agents.morning_brief_agent import morning_brief_agent

    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                text("""
                    SELECT DISTINCT e.id as empresa_id, u.id as user_id, u.nombre
                    FROM empresas e
                    JOIN usuarios u ON u.empresa_id = e.id
                    WHERE u.rol = 'admin'
                    LIMIT 50
                """)
            )
            rows = result.fetchall()
    except Exception as e:
        print(f"MORNING BRIEF: Error consultando empresas: {e}")
        return

    if not rows:
        print("MORNING BRIEF: Sin empresas/admins para procesar")
        return

    print(f"MORNING BRIEF: Procesando {len(rows)} admin(s)")

    for row in rows:
        empresa_id = str(row.empresa_id)
        user_id = str(row.user_id)
        nombre = row.nombre or "Admin"

        try:
            result = await morning_brief_agent.ainvoke({
                "empresa_id": empresa_id,
                "user_id": user_id,
                "message": "morning brief",
            })

            response = result.get("response", "")
            if response:
                print(f"MORNING BRIEF: OK para {nombre} ({empresa_id[:8]}...)")

                # Enviar por Telegram si hay bot configurado
                if TELEGRAM_BOT_TOKEN:
                    try:
                        async with AsyncSessionLocal() as db:
                            tg_result = await db.execute(
                                text("SELECT telegram_id FROM usuarios WHERE id = :uid"),
                                {"uid": user_id},
                            )
                            tg_row = tg_result.fetchone()
                            if tg_row and tg_row.telegram_id:
                                await _send_telegram(str(tg_row.telegram_id), f"*Buenos dias, {nombre}*\n\n{response}")
                    except Exception as e:
                        print(f"MORNING BRIEF: Error enviando Telegram a {nombre}: {e}")

        except Exception as e:
            print(f"MORNING BRIEF: Error procesando {empresa_id[:8]}: {e}")

    print("MORNING BRIEF: Ciclo completado")
