"""
Email Monitor Worker — Monitorea respuestas a emails enviados por Ada.
Cada 5 minutos:
1. Revisa emails activos en tracking
2. Busca respuestas en Gmail (por thread_id o to_email)
3. Si hay respuesta → notifica al usuario por Telegram
4. Si venció el tiempo de follow-up → envía follow-up automático
"""

import os
import asyncio
from datetime import datetime

from api.services.email_followup_service import (
    get_active_followups,
    mark_responded,
    mark_follow_up_sent,
)

ENABLE_EMAIL_MONITOR = os.getenv("ENABLE_EMAIL_MONITOR", "true").lower() in ("true", "1", "yes")
CHECK_INTERVAL_SECONDS = int(os.getenv("EMAIL_MONITOR_INTERVAL", "300"))
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_API", "")


async def _send_telegram(chat_id: str, text_msg: str):
    """Envía notificación por Telegram."""
    if not TELEGRAM_BOT_TOKEN or not chat_id:
        return
    try:
        import httpx
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                json={"chat_id": chat_id, "text": text_msg[:4000], "parse_mode": "Markdown"},
            )
            if not resp.json().get("ok"):
                await client.post(
                    f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                    json={"chat_id": chat_id, "text": text_msg[:4000]},
                )
    except Exception as e:
        print(f"EMAIL MONITOR: Telegram send error: {e}")


def _check_gmail_for_response(empresa_id: str, user_id: str, to_email: str, thread_id: str, sent_at) -> dict | None:
    """Busca en Gmail si hay respuesta al email enviado."""
    try:
        from api.services.gmail_service import gmail_search

        query = f"from:{to_email} newer_than:3d"
        results = gmail_search(query=query, max_results=5, empresa_id=empresa_id, user_id=user_id)

        if isinstance(results, list):
            for email in results:
                email_from = email.get("from", "").lower()
                if to_email.lower() in email_from:
                    snippet = email.get("snippet", email.get("subject", ""))
                    return {
                        "found": True,
                        "subject": email.get("subject", ""),
                        "snippet": snippet[:300],
                        "from": email.get("from", ""),
                        "message_id": email.get("id", ""),
                    }

        return None

    except Exception as e:
        print(f"EMAIL MONITOR: Gmail search error: {e}")
        return None


async def _send_follow_up(followup: dict) -> bool:
    """Envía un follow-up automático por email."""
    try:
        from api.services.gmail_service import gmail_draft, gmail_send

        empresa_id = str(followup["empresa_id"])
        user_id = str(followup["user_id"])
        to_email = followup["to_email"]
        to_name = followup.get("to_name", "")
        original_subject = followup.get("subject", "")
        follow_up_message = followup.get("follow_up_message", "")
        follow_up_count = followup.get("follow_up_count", 0)

        if follow_up_message:
            body = follow_up_message
        else:
            from models.selector import selector
            model, _ = selector.get_model("routing")

            prompt = f"""Redacta un follow-up breve y amable para un email que no fue respondido.

DESTINATARIO: {to_name or to_email}
ASUNTO ORIGINAL: {original_subject}
FOLLOW-UP NÚMERO: {follow_up_count + 1}
CONTEXTO: {followup.get('context', '')}

REGLAS:
- Máximo 3 líneas
- Amable pero directo
- No ser insistente si es el primer follow-up
- Si es el segundo, ser más directo
- NO usar "Estimado/a"

Responde SOLO el texto del body, sin JSON."""

            response = await model.ainvoke([
                {"role": "system", "content": "Redacta follow-ups breves y profesionales."},
                {"role": "user", "content": prompt},
            ])
            body = (response.content or "").strip()

        subject = f"Re: {original_subject}" if not original_subject.startswith("Re:") else original_subject
        draft_result = gmail_draft(
            to=to_email, subject=subject, body=body,
            empresa_id=empresa_id, user_id=user_id
        )

        if draft_result.get("draft_id"):
            send_result = gmail_send(draft_result["draft_id"], empresa_id=empresa_id, user_id=user_id)
            if not (isinstance(send_result, dict) and "error" in send_result):
                mark_follow_up_sent(str(followup["id"]))
                print(f"EMAIL MONITOR: Follow-up #{follow_up_count + 1} sent to {to_email}")
                return True

        return False

    except Exception as e:
        print(f"EMAIL MONITOR: Follow-up send error: {e}")
        return False


async def email_monitor_worker_loop():
    """Loop principal del email monitor."""
    if not ENABLE_EMAIL_MONITOR:
        print("EMAIL MONITOR: Deshabilitado (ENABLE_EMAIL_MONITOR != true)")
        return

    print(f"EMAIL MONITOR: Worker iniciado, intervalo={CHECK_INTERVAL_SECONDS}s")

    await asyncio.sleep(60)

    while True:
        try:
            followups = get_active_followups()

            if followups:
                _notified_emails = set()
                print(f"EMAIL MONITOR: Revisando {len(followups)} emails en seguimiento")

            for f in followups:
                empresa_id = str(f["empresa_id"])
                user_id = str(f["user_id"])
                to_email = f["to_email"]
                telegram_id = f.get("telegram_id", "")
                followup_id = str(f["id"])

                # 1. Buscar respuesta en Gmail
                response = _check_gmail_for_response(
                    empresa_id, user_id, to_email,
                    f.get("gmail_thread_id", ""),
                    f.get("sent_at"),
                )

                if response and response.get("found"):
                    mark_responded(followup_id, response.get("snippet", ""))

                    if telegram_id and to_email not in _notified_emails:
                        _notified_emails.add(to_email)
                        notification = (
                            f"📬 **{f.get('to_name') or to_email}** respondió a tu email:\n\n"
                            f"📝 **Asunto:** {response.get('subject', 'Sin asunto')}\n"
                            f"💬 _{response.get('snippet', '')[:200]}_\n\n"
                            f"¿Quieres que le responda algo?"
                        )
                        await _send_telegram(telegram_id, notification)

                    print(f"EMAIL MONITOR: Response detected from {to_email}, user notified")
                    continue

                # 2. Verificar si toca enviar follow-up
                if f.get("follow_up_enabled") and f.get("follow_up_count", 0) < f.get("max_follow_ups", 2):
                    hours_since = 0
                    reference_time = f.get("follow_up_sent_at") or f.get("sent_at")
                    if reference_time:
                        if isinstance(reference_time, str):
                            reference_time = datetime.fromisoformat(reference_time)
                        hours_since = (datetime.utcnow() - reference_time.replace(tzinfo=None)).total_seconds() / 3600

                    if hours_since >= f.get("follow_up_after_hours", 48):
                        sent = await _send_follow_up(f)

                        if sent and telegram_id:
                            notification = (
                                f"📤 Envié follow-up #{f.get('follow_up_count', 0) + 1} a **{f.get('to_name') or to_email}**.\n"
                                f"📝 Asunto: Re: {f.get('subject', '')}\n\n"
                                f"Si responde, te aviso."
                            )
                            await _send_telegram(telegram_id, notification)

            # Revisar transcripts de Google Meet
            try:
                await _check_google_meet_transcripts()
            except Exception as e:
                print(f"EMAIL MONITOR: Error checking Meet transcripts: {e}")

        except asyncio.CancelledError:
            print("EMAIL MONITOR: Worker cancelado")
            break
        except Exception as e:
            print(f"EMAIL MONITOR: Error en loop: {e}")

        await asyncio.sleep(CHECK_INTERVAL_SECONDS)


# ─── Google Meet Transcript Detection ─────────────────────

async def _check_google_meet_transcripts():
    """Busca emails de Google Meet con transcripciones nuevas."""
    try:
        from api.database import sync_engine
        from sqlalchemy import text as sql_text

        # Obtener todas las empresas con Gmail activo
        with sync_engine.connect() as conn:
            empresas = conn.execute(
                sql_text("""
                    SELECT DISTINCT tc.empresa_id, tc.user_id
                    FROM tenant_credentials tc
                    WHERE tc.provider = 'gmail' AND tc.is_active = TRUE
                """)
            ).fetchall()

        for emp in empresas:
            empresa_id = str(emp.empresa_id)
            user_id = str(emp.user_id) if emp.user_id else ""

            try:
                from api.services.gmail_service import gmail_search, gmail_get_attachments

                # Buscar emails de Google Meet de los últimos 3 días
                results = gmail_search(
                    query="from:meetings-noreply@google.com newer_than:3d",
                    max_results=5,
                    empresa_id=empresa_id,
                    user_id=user_id,
                )

                if not isinstance(results, list) or not results:
                    continue

                for email in results:
                    msg_id = email.get("id", "")
                    if not msg_id:
                        continue

                    # Verificar si ya procesamos este email
                    with sync_engine.connect() as conn:
                        existing = conn.execute(
                            sql_text("""
                                SELECT id FROM meeting_events
                                WHERE gmail_message_id = :msg_id
                                LIMIT 1
                            """),
                            {"msg_id": msg_id}
                        ).fetchone()

                    if existing:
                        continue  # Ya procesado

                    print(f"MEETING MONITOR: Nuevo transcript detectado — msg_id={msg_id}")

                    # Descargar attachments
                    attachments = gmail_get_attachments(msg_id, empresa_id=empresa_id, user_id=user_id)

                    transcript_text = ""
                    for att in attachments:
                        filename = att.get("filename", "").lower()
                        if filename.endswith(".txt") and "transcript" in filename:
                            transcript_text = att.get("content", "")
                            break

                    # Si no hay attachment con "transcript", buscar cualquier .txt
                    if not transcript_text:
                        for att in attachments:
                            if att.get("filename", "").lower().endswith(".txt"):
                                transcript_text = att.get("content", "")
                                break

                    # Si todavía no hay transcript, intentar leer del body del email
                    if not transcript_text:
                        from api.services.gmail_service import gmail_read
                        full_email = gmail_read(msg_id, empresa_id=empresa_id, user_id=user_id)
                        body = full_email.get("body", "")
                        if "Transcripción" in body or "[" in body:
                            transcript_text = body

                    if not transcript_text or len(transcript_text) < 50:
                        print(f"MEETING MONITOR: No transcript found in email {msg_id}")
                        continue

                    # Procesar el transcript
                    await _process_meeting_transcript(
                        empresa_id=empresa_id,
                        user_id=user_id,
                        gmail_message_id=msg_id,
                        transcript_text=transcript_text,
                        email_subject=email.get("subject", "Reunión"),
                    )

            except Exception as e:
                print(f"MEETING MONITOR: Error processing empresa {empresa_id[:8]}: {e}")

    except Exception as e:
        print(f"MEETING MONITOR: Error general: {e}")


async def _process_meeting_transcript(
    empresa_id: str,
    user_id: str,
    gmail_message_id: str,
    transcript_text: str,
    email_subject: str,
):
    """Procesa un transcript de Google Meet completo."""
    from api.services.meeting_intelligence_service import (
        parse_transcript,
        analyze_transcript,
        map_speakers_to_users,
        save_meeting_event,
        save_meeting_report,
        format_meeting_summary,
    )

    print(f"MEETING MONITOR: Procesando transcript ({len(transcript_text)} chars)")

    # 1. Parsear transcript
    parsed = parse_transcript(transcript_text)

    if parsed["line_count"] < 3:
        print(f"MEETING MONITOR: Transcript muy corto ({parsed['line_count']} líneas), ignorando")
        return

    # 2. Extraer título del subject del email
    event_title = email_subject
    if "Registros de la reunión" in event_title:
        event_title = f"Reunión {parsed.get('start_time', '')}"

    # 3. Analizar con LLM (Gemini Flash = gratis)
    analysis = await analyze_transcript(
        transcript=parsed["transcript"],
        attendees=parsed["attendees"],
        event_title=event_title,
        empresa_id=empresa_id,
    )

    # 4. Mapear speakers a usuarios reales
    map_speakers_to_users(parsed["speakers"], empresa_id)

    # 5. Guardar en meeting_events
    save_meeting_event(
        empresa_id=empresa_id,
        user_id=user_id,
        event_title=event_title,
        event_date=parsed.get("start_time", ""),
        participants=parsed["attendees"],
        transcript=parsed["transcript"],
        speakers=parsed["speakers"],
        analysis=analysis,
        gmail_message_id=gmail_message_id,
    )

    # 6. Guardar en ada_reports
    save_meeting_report(empresa_id, event_title, analysis, parsed["attendees"])

    # 7. Notificar al usuario por Telegram
    telegram_id = ""
    user_name = ""
    try:
        from api.database import sync_engine
        from sqlalchemy import text as sql_text
        with sync_engine.connect() as conn:
            row = conn.execute(
                sql_text("SELECT nombre, telegram_id FROM usuarios WHERE id = :uid"),
                {"uid": user_id}
            ).fetchone()
            if row:
                telegram_id = row.telegram_id or ""
                user_name = row.nombre or ""
    except Exception:
        pass

    if telegram_id:
        summary_text = format_meeting_summary(event_title, analysis, parsed["attendees"])

        # Agregar acciones sugeridas
        tasks = analysis.get("tasks", [])
        if tasks:
            summary_text += f"\n\n💡 ¿Quieres que cree estas {len(tasks)} tareas en tu herramienta de proyectos?"

        await _send_telegram(telegram_id, summary_text)
        print(f"MEETING MONITOR: Resumen enviado a {user_name} por Telegram")

    print(f"MEETING MONITOR: Reunión procesada — {len(analysis.get('tasks', []))} tareas, {len(analysis.get('decisions', []))} decisiones")
