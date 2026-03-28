"""
Microsoft Teams Meeting Service — Accede a transcripts y AI insights via Microsoft Graph API.

Docs: https://learn.microsoft.com/en-us/microsoftteams/platform/graph-api/meeting-transcripts/overview-transcripts
"""

import json
import httpx

GRAPH_BASE = "https://graph.microsoft.com/v1.0"


def _get_graph_token(empresa_id: str, user_id: str = "") -> str:
    """Obtiene el access token de Microsoft Graph para el usuario."""
    from api.services.tenant_credentials import get_microsoft_credentials
    creds = get_microsoft_credentials(empresa_id, "outlook_email", user_id=user_id)
    if "error" in creds:
        creds = get_microsoft_credentials(empresa_id, "microsoft365", user_id=user_id)
    if "error" in creds:
        return ""
    return creds.get("access_token", "")


async def list_recent_meetings(empresa_id: str, user_id: str = "") -> list:
    """Lista reuniones recientes del usuario en Teams."""
    token = _get_graph_token(empresa_id, user_id)
    if not token:
        return []

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{GRAPH_BASE}/me/onlineMeetings",
                headers={"Authorization": f"Bearer {token}"},
            )

        if resp.status_code == 200:
            meetings = resp.json().get("value", [])
            print(f"TEAMS API: Found {len(meetings)} meetings")
            return meetings
        else:
            print(f"TEAMS API: Error listing meetings: {resp.status_code}")
            return []

    except Exception as e:
        print(f"TEAMS API: Error: {e}")
        return []


async def get_meeting_transcript(empresa_id: str, user_id: str, meeting_id: str) -> dict:
    """Obtiene el transcript de una reunion de Teams en formato VTT."""
    token = _get_graph_token(empresa_id, user_id)
    if not token:
        return {"error": "No token"}

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            # 1. Listar transcripts disponibles
            resp = await client.get(
                f"{GRAPH_BASE}/me/onlineMeetings/{meeting_id}/transcripts",
                headers={"Authorization": f"Bearer {token}"},
            )

            if resp.status_code != 200:
                return {"error": f"List transcripts failed: {resp.status_code}"}

            transcripts = resp.json().get("value", [])
            if not transcripts:
                return {"error": "No transcripts available"}

            transcript_id = transcripts[0].get("id", "")

            # 2. Descargar contenido del transcript (formato VTT)
            resp2 = await client.get(
                f"{GRAPH_BASE}/me/onlineMeetings/{meeting_id}/transcripts/{transcript_id}/content",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "text/vtt",
                },
            )

            if resp2.status_code == 200:
                parsed = parse_teams_vtt(resp2.text)
                print(f"TEAMS API: Got transcript with {parsed['line_count']} entries")
                return parsed
            else:
                return {"error": f"Get transcript content failed: {resp2.status_code}"}

    except Exception as e:
        print(f"TEAMS API: Error getting transcript: {e}")
        return {"error": str(e)}


async def get_meeting_ai_insights(empresa_id: str, user_id: str, meeting_id: str) -> dict:
    """Obtiene AI Insights de Microsoft Copilot para la reunion.

    Solo disponible si la empresa tiene Microsoft 365 con Copilot.
    """
    token = _get_graph_token(empresa_id, user_id)
    if not token:
        return {"available": False}

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{GRAPH_BASE}/copilot/users/me/onlineMeetings/{meeting_id}/aiInsights",
                headers={"Authorization": f"Bearer {token}"},
            )

        if resp.status_code == 200:
            insights = resp.json().get("value", [])
            if insights:
                insight = insights[0]
                insight_id = insight.get("id", "")

                async with httpx.AsyncClient(timeout=15) as client:
                    resp2 = await client.get(
                        f"{GRAPH_BASE}/copilot/users/me/onlineMeetings/{meeting_id}/aiInsights/{insight_id}",
                        headers={"Authorization": f"Bearer {token}"},
                    )

                if resp2.status_code == 200:
                    detail = resp2.json()
                    return {
                        "available": True,
                        "meeting_notes": detail.get("meetingNotes", []),
                        "action_items": detail.get("actionItems", []),
                    }

            return {"available": False}

        else:
            return {"available": False}

    except Exception as e:
        print(f"TEAMS API: AI Insights error: {e}")
        return {"available": False}


def parse_teams_vtt(vtt_content: str) -> dict:
    """Parsea el contenido VTT de Teams con speakerName y spokenText."""
    entries = []
    speakers = set()

    for line in vtt_content.split("\n"):
        line = line.strip()
        if not line or line == "WEBVTT" or "-->" in line:
            continue

        try:
            data = json.loads(line)
            speaker = data.get("speakerName", "Unknown")
            text = data.get("spokenText", "")

            if text:
                speakers.add(speaker)
                entries.append({
                    "speaker": speaker,
                    "text": text,
                    "language": data.get("spokenLanguage", ""),
                })
        except (json.JSONDecodeError, TypeError):
            continue

    transcript = "\n".join(f"[{e['speaker']}]: {e['text']}" for e in entries)

    return {
        "transcript": transcript,
        "speakers": list(speakers),
        "attendees": list(speakers),
        "entries": entries,
        "line_count": len(entries),
    }


def convert_ai_insights_to_analysis(insights: dict) -> dict | None:
    """Convierte AI Insights de Microsoft al formato de analisis de Ada."""
    if not insights.get("available"):
        return None

    notes = insights.get("meeting_notes", [])
    summary_parts = []
    for note in notes:
        title = note.get("title", "")
        text = note.get("text", "")
        if title:
            summary_parts.append(f"{title}: {text}")
        elif text:
            summary_parts.append(text)

    action_items = insights.get("action_items", [])
    tasks = []
    for item in action_items:
        tasks.append({
            "task": item.get("text", item.get("title", "")),
            "assignee": item.get("ownerDisplayName", "Sin asignar"),
            "deadline": "sin definir",
            "priority": "media",
        })

    return {
        "summary": " ".join(summary_parts) if summary_parts else "",
        "tasks": tasks,
        "decisions": [],
        "risks": [],
        "next_meeting": "",
        "key_topics": [n.get("title", "") for n in notes if n.get("title")],
        "tone": "productiva",
        "source": "microsoft_copilot",
    }
