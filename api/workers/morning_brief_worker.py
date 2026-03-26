"""
Morning Brief Worker — Envia briefing personalizado por usuario.
Cada minuto revisa que usuarios tienen morning_brief_enabled=true
y cuya hora coincide con la hora actual en su timezone.
No depende de ENABLE_MORNING_BRIEF env var.
"""

import os
import asyncio
from datetime import datetime, date
from zoneinfo import ZoneInfo

from api.database import AsyncSessionLocal
from sqlalchemy import text


TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", os.getenv("TELEGRAM_API", ""))
CHECK_INTERVAL_SECONDS = 60  # revisar cada minuto


async def _send_telegram(chat_id: str, text_msg: str):
    """Envia mensaje por Telegram."""
    if not TELEGRAM_BOT_TOKEN or not chat_id:
        return
    try:
        import httpx
        async with httpx.AsyncClient(timeout=15) as client:
            await client.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                json={"chat_id": chat_id, "text": text_msg[:4000], "parse_mode": "Markdown"},
            )
    except Exception as e:
        print(f"MORNING BRIEF: Telegram send error: {e}")


async def _get_users_due_now() -> list[dict]:
    """
    Busca usuarios con morning_brief_enabled=true cuya hora
    coincide con la hora actual en su timezone.
    Excluye los que ya recibieron brief hoy.
    """
    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(text("""
                SELECT
                    up.user_id,
                    up.preferences,
                    u.empresa_id,
                    u.nombre,
                    u.telegram_id
                FROM user_preferences up
                JOIN usuarios u ON u.id = up.user_id
                WHERE (up.preferences->>'morning_brief_enabled')::boolean = true
                  AND u.is_active = true
            """))
            rows = result.fetchall()
    except Exception as e:
        print(f"MORNING BRIEF: Error consultando usuarios: {e}")
        return []

    due = []
    today = date.today()

    for row in rows:
        prefs = row.preferences if isinstance(row.preferences, dict) else {}
        target_hour = prefs.get("morning_brief_hour", 7)
        tz_name = prefs.get("morning_brief_timezone", "America/Bogota")
        last_sent = prefs.get("_brief_last_sent_date", "")

        # Ya enviado hoy?
        if last_sent == str(today):
            continue

        try:
            tz = ZoneInfo(tz_name)
        except Exception:
            tz = ZoneInfo("America/Bogota")

        now_user = datetime.now(tz)
        if now_user.hour == target_hour and now_user.minute < 5:
            due.append({
                "user_id": str(row.user_id),
                "empresa_id": str(row.empresa_id),
                "nombre": row.nombre or "Usuario",
                "telegram_id": str(row.telegram_id) if row.telegram_id else "",
                "timezone": tz_name,
            })

    return due


async def _mark_sent_today(user_id: str):
    """Marca que el brief ya se envio hoy para no duplicar."""
    import json
    today_str = str(date.today())
    try:
        async with AsyncSessionLocal() as db:
            await db.execute(text("""
                UPDATE user_preferences
                SET preferences = preferences || :patch::jsonb,
                    updated_at = NOW()
                WHERE user_id = :uid
            """), {
                "uid": user_id,
                "patch": json.dumps({"_brief_last_sent_date": today_str}),
            })
            await db.commit()
    except Exception as e:
        print(f"MORNING BRIEF: Error marcando enviado: {e}")


async def _generate_and_send_brief(user: dict):
    """Genera brief para un usuario y lo envia por Telegram."""
    from api.agents.morning_brief_agent import morning_brief_agent

    empresa_id = user["empresa_id"]
    user_id = user["user_id"]
    nombre = user["nombre"]

    try:
        result = await morning_brief_agent.ainvoke({
            "empresa_id": empresa_id,
            "user_id": user_id,
            "message": "morning brief",
        })

        response = result.get("response", "")
        if not response:
            print(f"MORNING BRIEF: Respuesta vacia para {nombre}")
            return

        print(f"MORNING BRIEF: Brief generado para {nombre} ({empresa_id[:8]})")

        # Enviar por Telegram
        telegram_id = user.get("telegram_id", "")
        if telegram_id and TELEGRAM_BOT_TOKEN:
            await _send_telegram(telegram_id, f"*Buenos dias, {nombre}* ☀️\n\n{response}")
            print(f"MORNING BRIEF: Enviado por Telegram a {nombre}")

        # Marcar como enviado hoy
        await _mark_sent_today(user_id)

    except Exception as e:
        print(f"MORNING BRIEF: Error para {nombre}: {e}")


async def morning_brief_worker_loop():
    """Loop principal: cada minuto revisa si hay briefs pendientes."""
    print("MORNING BRIEF: Worker iniciado (per-user scheduling, check cada 60s)")

    # Esperar 30s al inicio para que la BD este lista
    await asyncio.sleep(30)

    while True:
        try:
            users_due = await _get_users_due_now()

            if users_due:
                print(f"MORNING BRIEF: {len(users_due)} usuario(s) pendiente(s)")
                for user in users_due:
                    await _generate_and_send_brief(user)
            # else: silencio, no loguear cada minuto

        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"MORNING BRIEF: Error en ciclo: {e}")

        await asyncio.sleep(CHECK_INTERVAL_SECONDS)
