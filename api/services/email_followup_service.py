"""
Email Followup Service — Registra y gestiona el tracking de emails enviados por Ada.
"""

from sqlalchemy import text as sql_text
from api.database import sync_engine


def create_followup(
    empresa_id: str,
    user_id: str,
    to_email: str,
    to_name: str = "",
    subject: str = "",
    gmail_message_id: str = "",
    gmail_thread_id: str = "",
    context: str = "",
    follow_up_enabled: bool = False,
    follow_up_after_hours: int = 48,
    follow_up_message: str = "",
    max_follow_ups: int = 2,
) -> str | None:
    """Crea un registro de tracking para un email enviado."""
    try:
        with sync_engine.connect() as conn:
            result = conn.execute(
                sql_text("""
                    INSERT INTO email_followups
                        (empresa_id, user_id, to_email, to_name, subject,
                         gmail_message_id, gmail_thread_id, context,
                         follow_up_enabled, follow_up_after_hours, follow_up_message, max_follow_ups)
                    VALUES
                        (:eid, :uid, :to_email, :to_name, :subject,
                         :msg_id, :thread_id, :context,
                         :fu_enabled, :fu_hours, :fu_message, :max_fu)
                    RETURNING id
                """),
                {
                    "eid": empresa_id, "uid": user_id,
                    "to_email": to_email, "to_name": to_name, "subject": subject,
                    "msg_id": gmail_message_id, "thread_id": gmail_thread_id,
                    "context": context,
                    "fu_enabled": follow_up_enabled,
                    "fu_hours": follow_up_after_hours,
                    "fu_message": follow_up_message,
                    "max_fu": max_follow_ups,
                },
            )
            row = result.fetchone()
            conn.commit()
            followup_id = str(row.id) if row else None
            print(f"EMAIL FOLLOWUP: Created tracking for {to_email} (subject: {subject[:50]})")
            return followup_id
    except Exception as e:
        print(f"EMAIL FOLLOWUP: Error creating: {e}")
        return None


def get_active_followups() -> list:
    """Obtiene todos los followups activos (monitoring o follow_up_sent) que no han expirado."""
    try:
        with sync_engine.connect() as conn:
            rows = conn.execute(
                sql_text("""
                    SELECT f.*, u.telegram_id, u.nombre as user_name
                    FROM email_followups f
                    JOIN usuarios u ON u.id = f.user_id
                    WHERE f.status IN ('monitoring', 'follow_up_sent')
                    AND f.expires_at > NOW()
                    ORDER BY f.sent_at ASC
                """)
            ).fetchall()
        return [dict(row._mapping) for row in rows]
    except Exception as e:
        print(f"EMAIL FOLLOWUP: Error fetching active: {e}")
        return []


def mark_responded(followup_id: str, response_snippet: str = "") -> bool:
    """Marca un followup como respondido."""
    try:
        with sync_engine.connect() as conn:
            conn.execute(
                sql_text("""
                    UPDATE email_followups
                    SET status = 'responded',
                        response_detected_at = NOW(),
                        response_snippet = :snippet
                    WHERE id = :id
                """),
                {"id": followup_id, "snippet": response_snippet[:500]},
            )
            conn.commit()
        print(f"EMAIL FOLLOWUP: Marked {followup_id} as responded")
        return True
    except Exception as e:
        print(f"EMAIL FOLLOWUP: Error marking responded: {e}")
        return False


def mark_follow_up_sent(followup_id: str) -> bool:
    """Registra que se envió un follow-up."""
    try:
        with sync_engine.connect() as conn:
            conn.execute(
                sql_text("""
                    UPDATE email_followups
                    SET follow_up_count = follow_up_count + 1,
                        follow_up_sent_at = NOW(),
                        status = CASE
                            WHEN follow_up_count + 1 >= max_follow_ups THEN 'expired'
                            ELSE 'follow_up_sent'
                        END
                    WHERE id = :id
                """),
                {"id": followup_id},
            )
            conn.commit()
        return True
    except Exception as e:
        print(f"EMAIL FOLLOWUP: Error marking follow-up sent: {e}")
        return False


def mark_completed(followup_id: str) -> bool:
    """Marca un followup como completado (el usuario resolvió manualmente)."""
    try:
        with sync_engine.connect() as conn:
            conn.execute(
                sql_text("UPDATE email_followups SET status = 'completed' WHERE id = :id"),
                {"id": followup_id},
            )
            conn.commit()
        return True
    except Exception as e:
        print(f"EMAIL FOLLOWUP: Error completing: {e}")
        return False
