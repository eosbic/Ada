"""
Meeting Intelligence Service — Procesa transcripts de Google Meet.
Detecta emails de reuniones, extrae insights, crea tareas y notifica.
"""

import json
import re
from datetime import datetime
from sqlalchemy import text as sql_text
from api.database import sync_engine
from models.selector import selector


# ─── Parsear transcript ──────────────────────────────────

def parse_transcript(raw_text: str) -> dict:
    """Parsea un transcript de Google Meet.
    Formato esperado:
        Hora de inicio: 2026-03-18 13:37 GMT-5
        Asistentes: Persona1, Persona2
        [Speaker]: texto
    """
    lines = raw_text.strip().split("\n")

    # Extraer metadata
    start_time = ""
    attendees = []
    transcript_lines = []
    speakers = set()
    in_transcript = False

    for line in lines:
        line = line.strip()
        if not line:
            continue

        if line.startswith("Hora de inicio"):
            start_time = line.split(":", 1)[-1].strip() if ":" in line else ""
        elif line.startswith("Asistentes"):
            raw_attendees = line.split("\n")
            for a in raw_attendees:
                a = a.strip().strip(",")
                if a and a != "Asistentes" and a != "Transcripción":
                    attendees.append(a)
        elif line == "Transcripción":
            in_transcript = True
            continue
        elif line.startswith("La reunión finalizó"):
            continue
        elif in_transcript or ":" in line:
            in_transcript = True
            # Detectar speaker: "NOMBRE: texto"
            speaker_match = re.match(r'^([^:]+?):\s*(.*)$', line)
            if speaker_match:
                speaker = speaker_match.group(1).strip()
                text = speaker_match.group(2).strip()
                if text and len(speaker) < 50:  # Evitar falsos positivos
                    speakers.add(speaker)
                    transcript_lines.append({"speaker": speaker, "text": text})

    # Si no encontró asistentes en el header, usar speakers
    if not attendees:
        attendees = list(speakers)

    # Reconstruir transcript limpio
    clean_transcript = "\n".join(
        f"[{t['speaker']}]: {t['text']}" for t in transcript_lines if t['text']
    )

    return {
        "start_time": start_time,
        "attendees": attendees,
        "speakers": list(speakers),
        "transcript": clean_transcript,
        "line_count": len(transcript_lines),
    }


# ─── Procesar transcript con LLM ──────────────────────────

async def analyze_transcript(
    transcript: str,
    attendees: list,
    event_title: str = "",
    empresa_id: str = "",
) -> dict:
    """Usa Gemini Flash (gratis) para extraer insights del transcript."""

    model, model_name = selector.get_model("alert_evaluation")  # gemini-flash

    prompt = f"""Analiza esta transcripción de reunión y extrae información estructurada.

TÍTULO DE LA REUNIÓN: {event_title or "Reunión de trabajo"}
PARTICIPANTES: {", ".join(attendees)}

TRANSCRIPCIÓN:
{transcript[:15000]}

Responde SOLO un JSON con esta estructura exacta:
{{
    "summary": "Resumen ejecutivo de la reunión en 3-5 oraciones. Enfocado en decisiones y resultados, no en describir quién dijo qué.",
    "tasks": [
        {{
            "task": "Descripción de la tarea",
            "assignee": "Nombre de la persona responsable",
            "deadline": "Fecha si se mencionó, o 'sin definir'",
            "priority": "alta|media|baja"
        }}
    ],
    "decisions": [
        "Decisión 1 tomada en la reunión",
        "Decisión 2"
    ],
    "risks": [
        "Riesgo o problema mencionado 1",
        "Riesgo o problema 2"
    ],
    "next_meeting": "Fecha y hora si se mencionó una próxima reunión, o vacío",
    "key_topics": ["Tema 1", "Tema 2", "Tema 3"],
    "tone": "productiva|tensa|informal|rutinaria"
}}

REGLAS:
- Las tareas SOLO se extraen si alguien se comprometió explícitamente ("yo me encargo", "lo tengo para el viernes")
- No inventar tareas ni responsables que no se mencionaron
- El resumen debe ser útil para alguien que NO estuvo en la reunión
- Si no hay riesgos, dejar lista vacía
- Si no se mencionó próxima reunión, dejar vacío
- Responde SOLO JSON, sin markdown, sin explicación"""

    try:
        response = await model.ainvoke([
            {"role": "system", "content": "Extraes información estructurada de transcripciones de reuniones. Responde SOLO JSON válido."},
            {"role": "user", "content": prompt},
        ])

        raw = (response.content or "").strip().replace("```json", "").replace("```", "")
        result = json.loads(raw)

        print(f"MEETING INTEL: Análisis OK — {len(result.get('tasks', []))} tareas, {len(result.get('decisions', []))} decisiones")
        return result

    except Exception as e:
        print(f"MEETING INTEL: Error analizando transcript: {e}")
        return {
            "summary": "Error procesando la transcripción.",
            "tasks": [], "decisions": [], "risks": [],
            "next_meeting": "", "key_topics": [], "tone": "unknown",
        }


# ─── Mapear speakers a usuarios reales ──────────────────────

def map_speakers_to_users(speakers: list, empresa_id: str) -> dict:
    """Intenta mapear nombres del transcript a usuarios reales en la BD."""
    mapping = {}

    try:
        with sync_engine.connect() as conn:
            for speaker in speakers:
                # Buscar en usuarios de la empresa
                row = conn.execute(
                    sql_text("""
                        SELECT id, nombre, apellido, email, telegram_id
                        FROM usuarios
                        WHERE empresa_id = :eid
                        AND (
                            nombre ILIKE :pattern
                            OR CONCAT(nombre, ' ', apellido) ILIKE :pattern
                        )
                        LIMIT 1
                    """),
                    {"eid": empresa_id, "pattern": f"%{speaker.split()[0]}%"}
                ).fetchone()

                if row:
                    mapping[speaker] = {
                        "user_id": str(row.id),
                        "name": f"{row.nombre or ''} {row.apellido or ''}".strip(),
                        "email": row.email,
                        "telegram_id": row.telegram_id,
                        "is_internal": True,
                    }
                else:
                    mapping[speaker] = {
                        "name": speaker,
                        "is_internal": False,
                    }

        internal = sum(1 for v in mapping.values() if v.get("is_internal"))
        print(f"MEETING INTEL: Mapped {internal}/{len(speakers)} speakers to internal users")

    except Exception as e:
        print(f"MEETING INTEL: Error mapping speakers: {e}")

    return mapping


# ─── Guardar en BD ──────────────────────────────────────────

def save_meeting_event(
    empresa_id: str,
    user_id: str,
    event_title: str,
    event_date: str,
    participants: list,
    transcript: str,
    speakers: list,
    analysis: dict,
    gmail_message_id: str = "",
) -> str | None:
    """Guarda el evento de reunión procesado en meeting_events."""
    try:
        with sync_engine.connect() as conn:
            result = conn.execute(
                sql_text("""
                    INSERT INTO meeting_events
                        (empresa_id, user_id, event_title, event_date, participants,
                         transcript, transcript_speakers, gmail_message_id,
                         summary, tasks, risks, decisions, next_meeting, status)
                    VALUES
                        (:eid, :uid, :title, :date, CAST(:participants AS jsonb),
                         :transcript, CAST(:speakers AS jsonb), :msg_id,
                         :summary, CAST(:tasks AS jsonb), CAST(:risks AS jsonb),
                         CAST(:decisions AS jsonb), :next_meeting, 'processed')
                    RETURNING id
                """),
                {
                    "eid": empresa_id, "uid": user_id,
                    "title": event_title, "date": event_date or datetime.utcnow().isoformat(),
                    "participants": json.dumps(participants, ensure_ascii=False),
                    "transcript": transcript[:50000],
                    "speakers": json.dumps(speakers, ensure_ascii=False),
                    "msg_id": gmail_message_id,
                    "summary": analysis.get("summary", ""),
                    "tasks": json.dumps(analysis.get("tasks", []), ensure_ascii=False),
                    "risks": json.dumps(analysis.get("risks", []), ensure_ascii=False),
                    "decisions": json.dumps(analysis.get("decisions", []), ensure_ascii=False),
                    "next_meeting": analysis.get("next_meeting", ""),
                },
            )
            row = result.fetchone()
            conn.commit()
            meeting_id = str(row.id) if row else None
            print(f"MEETING INTEL: Saved meeting event {meeting_id}")
            return meeting_id

    except Exception as e:
        print(f"MEETING INTEL: Error saving: {e}")
        return None


# ─── Guardar en ada_reports ──────────────────────────────────

def save_meeting_report(empresa_id: str, event_title: str, analysis: dict, participants: list) -> str | None:
    """Guarda el resumen como reporte en ada_reports."""
    try:
        tasks_md = "\n".join(
            f"- **{t['task']}** → {t['assignee']} (deadline: {t.get('deadline', 'sin definir')})"
            for t in analysis.get("tasks", [])
        )
        decisions_md = "\n".join(f"- {d}" for d in analysis.get("decisions", []))
        risks_md = "\n".join(f"- {r}" for r in analysis.get("risks", []))

        markdown = f"""# Resumen: {event_title}

## Participantes
{', '.join(participants)}

## Resumen Ejecutivo
{analysis.get('summary', '')}

## Tareas y Compromisos
{tasks_md or 'Ninguna tarea asignada.'}

## Decisiones Tomadas
{decisions_md or 'No se tomaron decisiones formales.'}

## Riesgos y Problemas
{risks_md or 'No se identificaron riesgos.'}

## Próxima Reunión
{analysis.get('next_meeting', 'No se agendó.')}
"""

        with sync_engine.connect() as conn:
            result = conn.execute(
                sql_text("""
                    INSERT INTO ada_reports
                    (empresa_id, title, report_type, markdown_content, generated_by)
                    VALUES (:eid, :title, 'meeting_summary', :content, 'meeting_intelligence')
                    RETURNING id
                """),
                {
                    "eid": empresa_id,
                    "title": f"Resumen: {event_title}",
                    "content": markdown,
                },
            )
            row = result.fetchone()
            conn.commit()
            return str(row.id) if row else None

    except Exception as e:
        print(f"MEETING INTEL: Error saving report: {e}")
        return None


# ─── Formatear resumen para Telegram/Chat ───────────────────

def format_meeting_summary(event_title: str, analysis: dict, participants: list) -> str:
    """Formatea el resumen para enviar por Telegram o mostrar en chat."""
    tasks = analysis.get("tasks", [])
    decisions = analysis.get("decisions", [])
    risks = analysis.get("risks", [])

    tasks_text = ""
    if tasks:
        tasks_text = "\n".join(
            f"• **{t['task']}** → {t['assignee']}"
            for t in tasks
        )

    decisions_text = ""
    if decisions:
        decisions_text = "\n".join(f"• {d}" for d in decisions)

    risks_text = ""
    if risks:
        risks_text = "\n".join(f"• {r}" for r in risks)

    summary = f"""📝 **Resumen de reunión: {event_title}**

📅 **Participantes:** {', '.join(participants)}

📋 **Resumen:**
{analysis.get('summary', '')}"""

    if tasks:
        summary += f"\n\n✅ **Tareas asignadas ({len(tasks)}):**\n{tasks_text}"

    if decisions:
        summary += f"\n\n💡 **Decisiones:**\n{decisions_text}"

    if risks:
        summary += f"\n\n⚠️ **Riesgos:**\n{risks_text}"

    next_meeting = analysis.get("next_meeting", "")
    if next_meeting:
        summary += f"\n\n📅 **Próxima reunión:** {next_meeting}"

    return summary
