"""
Telegram DM Service — Ada envía mensajes directos a miembros del equipo.
Usa el Bot API de Telegram para enviar mensajes a usuarios vinculados.
"""

import os
import httpx
from sqlalchemy import text as sql_text
from api.database import sync_engine

TELEGRAM_TOKEN = os.getenv("TELEGRAM_API", "")
TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"


def get_team_member_telegram(empresa_id: str, person_name: str) -> dict | None:
    """Busca un miembro del equipo por nombre y retorna su telegram_id + info."""
    if not empresa_id or not person_name:
        return None
    try:
        with sync_engine.connect() as conn:
            rows = conn.execute(
                sql_text("""
                    SELECT u.id, u.nombre, u.apellido, u.email, u.telegram_id
                    FROM usuarios u
                    WHERE u.empresa_id = :eid
                    AND u.telegram_id IS NOT NULL
                    AND (
                        u.nombre ILIKE :name_pattern
                        OR CONCAT(u.nombre, ' ', u.apellido) ILIKE :name_pattern
                    )
                """),
                {"eid": empresa_id, "name_pattern": f"%{person_name}%"}
            ).fetchall()

            if not rows:
                return None

            if len(rows) == 1:
                r = rows[0]
                return {
                    "user_id": str(r.id),
                    "name": f"{r.nombre or ''} {r.apellido or ''}".strip(),
                    "email": r.email,
                    "telegram_id": r.telegram_id,
                }
            else:
                return {
                    "multiple": True,
                    "options": [
                        {
                            "user_id": str(r.id),
                            "name": f"{r.nombre or ''} {r.apellido or ''}".strip(),
                            "email": r.email,
                            "telegram_id": r.telegram_id,
                        }
                        for r in rows
                    ],
                }
    except Exception as e:
        print(f"TELEGRAM DM: Error buscando miembro: {e}")
        return None


async def send_telegram_dm(telegram_id: str, message: str) -> dict:
    """Envía un mensaje directo a un usuario por Telegram."""
    if not TELEGRAM_TOKEN or not telegram_id:
        return {"error": "Telegram no configurado o usuario sin Telegram vinculado"}

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{TELEGRAM_API_URL}/sendMessage",
                json={
                    "chat_id": telegram_id,
                    "text": message,
                    "parse_mode": "Markdown",
                },
            )

            data = resp.json()
            if data.get("ok"):
                print(f"TELEGRAM DM: Mensaje enviado a {telegram_id}")
                return {"sent": True, "message_id": data.get("result", {}).get("message_id")}
            else:
                error = data.get("description", "Error desconocido")
                print(f"TELEGRAM DM: Error enviando: {error}")
                # Fallback sin Markdown si falla el parseo
                if "parse" in error.lower():
                    resp2 = await client.post(
                        f"{TELEGRAM_API_URL}/sendMessage",
                        json={"chat_id": telegram_id, "text": message},
                    )
                    data2 = resp2.json()
                    if data2.get("ok"):
                        return {"sent": True, "message_id": data2.get("result", {}).get("message_id")}
                return {"error": error}

    except Exception as e:
        print(f"TELEGRAM DM: Error: {e}")
        return {"error": str(e)}


def list_team_with_telegram(empresa_id: str) -> list:
    """Lista todos los miembros del equipo que tienen Telegram vinculado."""
    try:
        with sync_engine.connect() as conn:
            rows = conn.execute(
                sql_text("""
                    SELECT u.id, u.nombre, u.apellido, u.email, u.telegram_id,
                           tm.role_title, tm.department
                    FROM usuarios u
                    LEFT JOIN team_members tm ON tm.user_id = u.id AND tm.empresa_id = u.empresa_id
                    WHERE u.empresa_id = :eid AND u.telegram_id IS NOT NULL
                """),
                {"eid": empresa_id}
            ).fetchall()

        return [
            {
                "name": f"{r.nombre or ''} {r.apellido or ''}".strip(),
                "email": r.email,
                "telegram_id": r.telegram_id,
                "role": r.role_title or "",
                "department": r.department or "",
            }
            for r in rows
        ]
    except Exception as e:
        print(f"TELEGRAM DM: Error listando equipo: {e}")
        return []
