"""
Google Meet REST API Service — Accede a transcripts y participantes directamente.
Usa la API oficial en vez de parsear emails.

Docs: https://developers.google.com/workspace/meet/api/guides/overview
"""

from datetime import datetime, timedelta
from googleapiclient.discovery import build


def _get_meet_service(empresa_id: str, user_id: str = ""):
    """Obtiene el servicio autenticado de Google Meet API."""
    try:
        from api.services.tenant_credentials import get_raw_google_credentials
        creds = get_raw_google_credentials(empresa_id, user_id=user_id)
        if not creds:
            return None
        return build("meet", "v2", credentials=creds, cache_discovery=False)
    except Exception as e:
        print(f"MEET API: Error building service: {e}")
        return None


def list_recent_conferences(empresa_id: str, user_id: str = "", hours_back: int = 24) -> list:
    """Lista conferencias recientes del usuario."""
    service = _get_meet_service(empresa_id, user_id)
    if not service:
        return []

    try:
        cutoff = (datetime.utcnow() - timedelta(hours=hours_back)).isoformat() + "Z"
        response = service.conferenceRecords().list(
            filter=f'end_time>"{cutoff}"'
        ).execute()

        records = response.get("conferenceRecords", [])
        print(f"MEET API: Found {len(records)} recent conferences")
        return records

    except Exception as e:
        print(f"MEET API: Error listing conferences: {e}")
        return []


def get_transcript_entries(empresa_id: str, user_id: str, conference_record_name: str) -> list:
    """Obtiene las entradas del transcript con speaker y texto."""
    service = _get_meet_service(empresa_id, user_id)
    if not service:
        return []

    try:
        # Obtener transcript IDs
        transcripts_response = service.conferenceRecords().transcripts().list(
            parent=conference_record_name
        ).execute()

        transcripts = transcripts_response.get("transcripts", [])
        if not transcripts:
            print(f"MEET API: No transcripts found for {conference_record_name}")
            return []

        # Obtener entries del primer transcript
        transcript_name = transcripts[0].get("name", "")
        all_entries = []
        page_token = None

        while True:
            entries_response = service.conferenceRecords().transcripts().entries().list(
                parent=transcript_name,
                pageToken=page_token,
            ).execute()

            entries = entries_response.get("transcriptEntries", [])
            for entry in entries:
                participant_name = entry.get("participant", "")
                all_entries.append({
                    "speaker": entry.get("displayName", participant_name),
                    "text": entry.get("text", ""),
                    "start_time": entry.get("startOffset", ""),
                    "end_time": entry.get("endOffset", ""),
                    "language": entry.get("languageCode", "es"),
                })

            page_token = entries_response.get("nextPageToken")
            if not page_token:
                break

        print(f"MEET API: Got {len(all_entries)} transcript entries")
        return all_entries

    except Exception as e:
        print(f"MEET API: Error getting transcript entries: {e}")
        return []


def get_conference_participants(empresa_id: str, user_id: str, conference_record_name: str) -> list:
    """Obtiene lista de participantes con info de usuario."""
    service = _get_meet_service(empresa_id, user_id)
    if not service:
        return []

    try:
        response = service.conferenceRecords().participants().list(
            parent=conference_record_name
        ).execute()

        participants = []
        for p in response.get("participants", []):
            info = {}
            if p.get("signedinUser"):
                info = {
                    "name": p["signedinUser"].get("displayName", ""),
                    "user_id": p["signedinUser"].get("user", ""),
                    "type": "signed_in",
                }
            elif p.get("anonymousUser"):
                info = {
                    "name": p["anonymousUser"].get("displayName", "Unknown"),
                    "type": "anonymous",
                }
            elif p.get("phoneUser"):
                info = {
                    "name": p["phoneUser"].get("displayName", "Phone"),
                    "type": "phone",
                }

            if info:
                participants.append(info)

        print(f"MEET API: Got {len(participants)} participants")
        return participants

    except Exception as e:
        print(f"MEET API: Error getting participants: {e}")
        return []


def format_transcript_from_entries(entries: list) -> str:
    """Convierte entries de la API a formato de transcript legible."""
    lines = []
    for entry in entries:
        speaker = entry.get("speaker", "Unknown")
        text = entry.get("text", "").strip()
        if text:
            lines.append(f"[{speaker}]: {text}")
    return "\n".join(lines)
