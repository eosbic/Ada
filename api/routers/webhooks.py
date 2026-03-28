"""
Webhook endpoints para recibir eventos de Google Workspace y Microsoft Graph.
"""

import json
import re
import base64
import traceback
from datetime import datetime

from fastapi import APIRouter, Request, BackgroundTasks
from fastapi.responses import PlainTextResponse

router = APIRouter()


# ─── GOOGLE WORKSPACE EVENTS (via Pub/Sub) ────────────────

@router.post("/meet/google")
async def google_meet_webhook(request: Request, background_tasks: BackgroundTasks):
    """Recibe eventos de Google Meet via Google Cloud Pub/Sub push."""
    try:
        body = await request.json()

        # Pub/Sub envia un mensaje con data en base64
        message = body.get("message", {})
        data_b64 = message.get("data", "")

        if data_b64:
            decoded = base64.b64decode(data_b64).decode("utf-8")
            event_data = json.loads(decoded)
        else:
            event_data = body

        event_type = event_data.get("type", "")
        attributes = message.get("attributes", {})

        print(f"MEET WEBHOOK: Received event type={event_type}")

        # Verificar si es un evento de transcript listo
        if "transcript" in event_type and "fileGenerated" in event_type:
            resource_name = event_data.get("conferenceRecord", "")
            if not resource_name:
                resource_name = attributes.get("conferenceRecord", "")

            if resource_name:
                background_tasks.add_task(
                    _process_google_meet_transcript,
                    resource_name,
                )

        return {"status": "ok"}

    except Exception as e:
        print(f"MEET WEBHOOK: Error: {e}")
        return {"status": "error", "detail": str(e)}


async def _process_google_meet_transcript(conference_record_name: str):
    """Procesa un transcript de Google Meet via la API oficial."""
    try:
        from api.services.google_meet_service import (
            get_transcript_entries,
            get_conference_participants,
            format_transcript_from_entries,
        )
        from api.services.meeting_intelligence_service import (
            analyze_transcript,
            save_meeting_event,
            save_meeting_report,
            format_meeting_summary,
        )
        from api.database import sync_engine
        from sqlalchemy import text as sql_text

        # Buscar empresas con Google conectado
        with sync_engine.connect() as conn:
            empresas = conn.execute(
                sql_text("""
                    SELECT DISTINCT tc.empresa_id, COALESCE(tc.user_id, u.id) as user_id
                    FROM tenant_credentials tc
                    JOIN usuarios u ON u.empresa_id = tc.empresa_id
                    WHERE tc.provider = 'gmail' AND tc.is_active = TRUE
                    LIMIT 10
                """)
            ).fetchall()

        for emp in empresas:
            empresa_id = str(emp.empresa_id)
            user_id = str(emp.user_id)

            # Intentar obtener transcript entries
            entries = get_transcript_entries(empresa_id, user_id, conference_record_name)
            if not entries:
                continue

            # Verificar si ya procesamos este conference record
            ref_id = f"meet_api:{conference_record_name}"
            with sync_engine.connect() as conn:
                existing = conn.execute(
                    sql_text("SELECT id FROM meeting_events WHERE gmail_message_id = :ref LIMIT 1"),
                    {"ref": ref_id}
                ).fetchone()

            if existing:
                continue

            # Obtener participantes
            participants_data = get_conference_participants(empresa_id, user_id, conference_record_name)
            participants = [p.get("name", "Unknown") for p in participants_data]

            # Formatear transcript
            transcript_text = format_transcript_from_entries(entries)
            speakers = list(set(e.get("speaker", "") for e in entries))

            # Analizar con Gemini Flash ($0)
            event_title = f"Reunion {datetime.utcnow().strftime('%d/%m/%Y %H:%M')}"
            analysis = await analyze_transcript(
                transcript=transcript_text,
                attendees=participants,
                event_title=event_title,
                empresa_id=empresa_id,
            )

            # Guardar
            save_meeting_event(
                empresa_id=empresa_id,
                user_id=user_id,
                event_title=event_title,
                event_date=datetime.utcnow().isoformat(),
                participants=participants,
                transcript=transcript_text,
                speakers=speakers,
                analysis=analysis,
                gmail_message_id=ref_id,
            )

            save_meeting_report(empresa_id, event_title, analysis, participants)

            # Notificar por Telegram
            telegram_id = ""
            try:
                with sync_engine.connect() as conn:
                    row = conn.execute(
                        sql_text("SELECT telegram_id FROM usuarios WHERE id = :uid"),
                        {"uid": user_id}
                    ).fetchone()
                    if row and row.telegram_id:
                        telegram_id = row.telegram_id
            except Exception:
                pass

            if telegram_id:
                summary_text = format_meeting_summary(event_title, analysis, participants)
                from api.workers.email_monitor_worker import _send_telegram
                await _send_telegram(telegram_id, summary_text)

            print(f"MEET WEBHOOK: Processed conference {conference_record_name}")
            break  # Solo procesar una vez

    except Exception as e:
        print(f"MEET WEBHOOK: Error processing: {e}")
        traceback.print_exc()


# ─── MICROSOFT GRAPH SUBSCRIPTION ────────────────────────

@router.post("/meet/microsoft")
async def microsoft_teams_webhook(request: Request, background_tasks: BackgroundTasks):
    """Recibe notificaciones de Microsoft Graph para transcripts de Teams."""
    try:
        # Microsoft Graph envia validationToken para validar el endpoint
        validation_token = request.query_params.get("validationToken", "")
        if validation_token:
            return PlainTextResponse(content=validation_token, status_code=200)

        body = await request.json()
        notifications = body.get("value", [])

        for notification in notifications:
            resource = notification.get("resource", "")
            change_type = notification.get("changeType", "")

            print(f"TEAMS WEBHOOK: Received {change_type} for {resource[:80]}")

            if "transcripts" in resource and change_type == "created":
                background_tasks.add_task(
                    _process_teams_transcript,
                    resource,
                    notification,
                )

        return {"status": "ok"}

    except Exception as e:
        print(f"TEAMS WEBHOOK: Error: {e}")
        return {"status": "error"}


async def _process_teams_transcript(resource: str, notification: dict):
    """Procesa un transcript de Microsoft Teams."""
    try:
        from api.services.teams_meet_service import (
            get_meeting_transcript,
            get_meeting_ai_insights,
            convert_ai_insights_to_analysis,
        )
        from api.services.meeting_intelligence_service import (
            analyze_transcript,
            save_meeting_event,
            save_meeting_report,
            format_meeting_summary,
        )
        from api.database import sync_engine
        from sqlalchemy import text as sql_text

        # Extraer meeting_id del resource path
        meeting_match = re.search(r"onlineMeetings\('([^']+)'\)", resource)
        if not meeting_match:
            meeting_match = re.search(r"onlineMeetings/([^/]+)/", resource)

        if not meeting_match:
            print(f"TEAMS WEBHOOK: Could not extract meeting_id from {resource}")
            return

        meeting_id = meeting_match.group(1)
        ref_id = f"teams_api:{meeting_id}"

        # Buscar usuario con Microsoft conectado
        with sync_engine.connect() as conn:
            empresas = conn.execute(
                sql_text("""
                    SELECT DISTINCT tc.empresa_id, COALESCE(tc.user_id, u.id) as user_id
                    FROM tenant_credentials tc
                    JOIN usuarios u ON u.empresa_id = tc.empresa_id
                    WHERE tc.provider IN ('outlook_email', 'microsoft365') AND tc.is_active = TRUE
                    LIMIT 10
                """)
            ).fetchall()

        for emp in empresas:
            empresa_id = str(emp.empresa_id)
            user_id = str(emp.user_id)

            # Verificar si ya procesamos
            with sync_engine.connect() as conn:
                existing = conn.execute(
                    sql_text("SELECT id FROM meeting_events WHERE gmail_message_id = :ref LIMIT 1"),
                    {"ref": ref_id}
                ).fetchone()

            if existing:
                continue

            # 1. Intentar AI Insights primero (gratis si tienen Copilot)
            ai_insights = await get_meeting_ai_insights(empresa_id, user_id, meeting_id)
            copilot_analysis = convert_ai_insights_to_analysis(ai_insights) if ai_insights.get("available") else None

            # 2. Obtener transcript
            transcript_data = await get_meeting_transcript(empresa_id, user_id, meeting_id)

            if "error" in transcript_data:
                print(f"TEAMS WEBHOOK: Transcript error: {transcript_data['error']}")
                continue

            transcript_text = transcript_data.get("transcript", "")
            speakers = transcript_data.get("speakers", [])
            participants = transcript_data.get("attendees", [])

            # 3. Si tenemos AI Insights de Copilot, usarlos. Si no, Gemini Flash.
            if copilot_analysis and copilot_analysis.get("summary"):
                analysis = copilot_analysis
                print("TEAMS WEBHOOK: Using Microsoft Copilot AI Insights")
            else:
                analysis = await analyze_transcript(
                    transcript=transcript_text,
                    attendees=participants,
                    event_title="Reunion Teams",
                    empresa_id=empresa_id,
                )
                print("TEAMS WEBHOOK: Using Gemini Flash for analysis")

            # 4. Guardar
            event_title = f"Reunion Teams {datetime.utcnow().strftime('%d/%m/%Y %H:%M')}"
            save_meeting_event(
                empresa_id=empresa_id,
                user_id=user_id,
                event_title=event_title,
                event_date=datetime.utcnow().isoformat(),
                participants=participants,
                transcript=transcript_text,
                speakers=speakers,
                analysis=analysis,
                gmail_message_id=ref_id,
            )

            save_meeting_report(empresa_id, event_title, analysis, participants)

            # 5. Notificar por Telegram
            telegram_id = ""
            try:
                with sync_engine.connect() as conn:
                    row = conn.execute(
                        sql_text("SELECT telegram_id FROM usuarios WHERE id = :uid"),
                        {"uid": user_id}
                    ).fetchone()
                    if row and row.telegram_id:
                        telegram_id = row.telegram_id
            except Exception:
                pass

            if telegram_id:
                summary_text = format_meeting_summary(event_title, analysis, participants)
                from api.workers.email_monitor_worker import _send_telegram
                await _send_telegram(telegram_id, summary_text)

            print(f"TEAMS WEBHOOK: Processed meeting {meeting_id}")
            break

    except Exception as e:
        print(f"TEAMS WEBHOOK: Error processing: {e}")
        traceback.print_exc()
