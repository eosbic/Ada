"""
Calendar Service — Conexión directa a Google Calendar API.
Multi-tenant: cada empresa usa SU Google Calendar.
"""

import os
from datetime import datetime, timedelta
from typing import Optional

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build


def _get_calendar_service(empresa_id: str = ""):
    from api.services.tenant_credentials import get_google_credentials
    creds_data = get_google_credentials(empresa_id, "google_calendar")
    creds = Credentials(
        token=creds_data.get("access_token"),
        refresh_token=creds_data.get("refresh_token"),
        client_id=creds_data.get("client_id"),
        client_secret=creds_data.get("client_secret"),
        token_uri="https://oauth2.googleapis.com/token",
    )
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def calendar_list_events(
    days_ahead: int = 7,
    max_results: int = 20,
    calendar_id: str = "primary",
    empresa_id: str = "",
    time_min: str = None,
    time_max: str = None,
) -> list:
    try:
        service = _get_calendar_service(empresa_id)

        now = datetime.utcnow()

        # Usar rangos personalizados si se pasan, si no usar days_ahead
        if not time_min:
            # Por defecto buscar desde 12h atrás para cubrir zonas horarias
            time_min = (now - timedelta(hours=12)).isoformat() + "Z"
        if not time_max:
            time_max = (now + timedelta(days=days_ahead)).isoformat() + "Z"

        print(f"CALENDAR list: time_min={time_min}, time_max={time_max}")

        result = service.events().list(
            calendarId=calendar_id,
            timeMin=time_min,
            timeMax=time_max,
            maxResults=max_results,
            singleEvents=True,
            orderBy="startTime",
        ).execute()

        events = []
        for e in result.get("items", []):
            start = e.get("start", {}).get("dateTime") or e.get("start", {}).get("date", "")
            end = e.get("end", {}).get("dateTime") or e.get("end", {}).get("date", "")
            events.append({
                "id": e.get("id"),
                "summary": e.get("summary", "Sin título"),
                "start": start,
                "end": end,
                "location": e.get("location", ""),
                "description": e.get("description", "")[:200],
                "attendees": [a.get("email") for a in e.get("attendees", [])],
            })

        print(f"CALENDAR: {len(events)} eventos encontrados")
        return events

    except Exception as e:
        print(f"ERROR Calendar list: {e}")
        return []


def calendar_search_events(
    query: str,
    days_ahead: int = 30,
    max_results: int = 10,
    calendar_id: str = "primary",
    empresa_id: str = "",
    time_min: str = None,
    time_max: str = None,
) -> list:
    try:
        service = _get_calendar_service(empresa_id)

        now = datetime.utcnow()

        if not time_min:
            time_min = (now - timedelta(hours=12)).isoformat() + "Z"
        if not time_max:
            time_max = (now + timedelta(days=days_ahead)).isoformat() + "Z"

        print(f"CALENDAR search '{query}': time_min={time_min}, time_max={time_max}")

        result = service.events().list(
            calendarId=calendar_id,
            timeMin=time_min,
            timeMax=time_max,
            maxResults=max_results,
            singleEvents=True,
            orderBy="startTime",
            q=query,
        ).execute()

        events = []
        for e in result.get("items", []):
            start = e.get("start", {}).get("dateTime") or e.get("start", {}).get("date", "")
            end = e.get("end", {}).get("dateTime") or e.get("end", {}).get("date", "")
            events.append({
                "id": e.get("id"),
                "summary": e.get("summary", "Sin título"),
                "start": start,
                "end": end,
                "location": e.get("location", ""),
                "description": e.get("description", "")[:200],
                "attendees": [a.get("email") for a in e.get("attendees", [])],
            })

        print(f"CALENDAR: Búsqueda '{query}' → {len(events)} eventos")
        return events

    except Exception as e:
        print(f"ERROR Calendar search: {e}")
        return []


def calendar_create_event(
    summary: str,
    start_datetime: str,
    end_datetime: str,
    description: str = "",
    location: str = "",
    attendees: list = None,
    calendar_id: str = "primary",
    timezone: str = "America/Bogota",
    empresa_id: str = "",
) -> dict:
    try:
        service = _get_calendar_service(empresa_id)

        event_body = {
            "summary": summary,
            "description": description,
            "location": location,
            "start": {"dateTime": start_datetime, "timeZone": timezone},
            "end": {"dateTime": end_datetime, "timeZone": timezone},
        }

        if attendees:
            event_body["attendees"] = [{"email": a} for a in attendees]

        event = service.events().insert(
            calendarId=calendar_id, body=event_body
        ).execute()

        print(f"CALENDAR: Evento creado → {event.get('id')}: {summary}")
        return {
            "event_id": event.get("id"),
            "summary": summary,
            "start": start_datetime,
            "end": end_datetime,
            "link": event.get("htmlLink", ""),
            "status": "created",
            "message": f"Evento '{summary}' creado exitosamente.",
        }

    except Exception as e:
        print(f"ERROR Calendar create: {e}")
        return {"error": str(e)}


def calendar_update_event(
    event_id: str,
    summary: str = None,
    start_datetime: str = None,
    end_datetime: str = None,
    description: str = None,
    location: str = None,
    calendar_id: str = "primary",
    timezone: str = "America/Bogota",
    empresa_id: str = "",
) -> dict:
    try:
        service = _get_calendar_service(empresa_id)

        event = service.events().get(
            calendarId=calendar_id, eventId=event_id
        ).execute()

        if summary:
            event["summary"] = summary
        if description is not None:
            event["description"] = description
        if location is not None:
            event["location"] = location
        if start_datetime:
            event["start"] = {"dateTime": start_datetime, "timeZone": timezone}
        if end_datetime:
            event["end"] = {"dateTime": end_datetime, "timeZone": timezone}

        updated = service.events().update(
            calendarId=calendar_id, eventId=event_id, body=event
        ).execute()

        print(f"CALENDAR: Evento actualizado → {event_id}")
        return {
            "event_id": event_id,
            "status": "updated",
            "message": f"Evento '{updated.get('summary')}' actualizado.",
        }

    except Exception as e:
        print(f"ERROR Calendar update: {e}")
        return {"error": str(e)}


def calendar_delete_event(
    event_id: str,
    calendar_id: str = "primary",
    empresa_id: str = "",
) -> dict:
    try:
        service = _get_calendar_service(empresa_id)
        service.events().delete(
            calendarId=calendar_id, eventId=event_id
        ).execute()

        print(f"CALENDAR: Evento eliminado → {event_id}")
        return {
            "event_id": event_id,
            "status": "deleted",
            "message": "Evento eliminado exitosamente.",
        }

    except Exception as e:
        print(f"ERROR Calendar delete: {e}")
        return {"error": str(e)}


def calendar_get_availability(
    days_ahead: int = 7,
    calendar_id: str = "primary",
    empresa_id: str = "",
) -> dict:
    events = calendar_list_events(
        days_ahead=days_ahead,
        calendar_id=calendar_id,
        empresa_id=empresa_id,
    )

    busy_slots = []
    for e in events:
        busy_slots.append({
            "start": e["start"],
            "end": e["end"],
            "summary": e["summary"],
        })

    return {
        "days_checked": days_ahead,
        "busy_slots": busy_slots,
        "total_events": len(busy_slots),
        "message": f"Tienes {len(busy_slots)} eventos en los próximos {days_ahead} días.",
    }