"""
Calendar Service — Conexión a Calendar API (Google / Microsoft 365).
Provider routing automático vía provider_router.
Multi-tenant: cada empresa usa SU Calendar.
"""

import os
import asyncio
from datetime import datetime, timedelta
from typing import Optional

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build


def _get_provider_family(empresa_id: str) -> str:
    """Determina familia de provider (google/microsoft) para calendar."""
    try:
        from api.services.provider_router import get_provider
        _, family = get_provider(empresa_id, "calendar")
        return family if family != "none" else "google"
    except Exception:
        return "google"


def _get_m365_token(empresa_id: str) -> str:
    """Obtiene access_token de Microsoft 365 para calendar."""
    from api.services.tenant_credentials import get_microsoft_credentials
    creds = get_microsoft_credentials(empresa_id, "outlook_calendar")
    if "error" in creds:
        raise RuntimeError(creds["error"])
    return creds["access_token"]


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
) -> list:
    if _get_provider_family(empresa_id) == "microsoft":
        return _m365_calendar_list(empresa_id, days_ahead, max_results)

    try:
        service = _get_calendar_service(empresa_id)

        now = datetime.utcnow()
        time_min = now.isoformat() + "Z"
        time_max = (now + timedelta(days=days_ahead)).isoformat() + "Z"

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

        print(f"CALENDAR: {len(events)} eventos en próximos {days_ahead} días")
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
) -> list:
    if _get_provider_family(empresa_id) == "microsoft":
        return _m365_calendar_search(empresa_id, query, days_ahead)

    try:
        service = _get_calendar_service(empresa_id)

        now = datetime.utcnow()
        time_min = now.isoformat() + "Z"
        time_max = (now + timedelta(days=days_ahead)).isoformat() + "Z"

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
            events.append({
                "id": e.get("id"),
                "summary": e.get("summary", "Sin título"),
                "start": start,
                "location": e.get("location", ""),
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
    if _get_provider_family(empresa_id) == "microsoft":
        return _m365_calendar_create(empresa_id, summary, start_datetime, end_datetime, description, location, attendees, timezone)

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
    if _get_provider_family(empresa_id) == "microsoft":
        return _m365_calendar_update(empresa_id, event_id, summary, start_datetime, end_datetime, description, location, timezone)

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
    if _get_provider_family(empresa_id) == "microsoft":
        return _m365_calendar_delete(empresa_id, event_id)

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
    events = calendar_list_events(days_ahead=days_ahead, calendar_id=calendar_id, empresa_id=empresa_id)

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


# ─── Microsoft 365 Sync Wrappers ────────────────────────────

def _m365_calendar_list(empresa_id: str, days_ahead: int = 7, max_results: int = 20) -> list:
    try:
        from api.mcp_servers.mcp_microsoft365_server import m365_calendar_list
        token = _get_m365_token(empresa_id)
        return asyncio.run(m365_calendar_list(token, days_ahead=days_ahead, max_results=max_results))
    except Exception as e:
        print(f"ERROR M365 Calendar list: {e}")
        return []


def _m365_calendar_search(empresa_id: str, query: str, days_ahead: int = 30) -> list:
    try:
        from api.mcp_servers.mcp_microsoft365_server import m365_calendar_search
        token = _get_m365_token(empresa_id)
        return asyncio.run(m365_calendar_search(token, query=query, days_ahead=days_ahead))
    except Exception as e:
        print(f"ERROR M365 Calendar search: {e}")
        return []


def _m365_calendar_create(
    empresa_id: str, summary: str, start_datetime: str, end_datetime: str,
    description: str = "", location: str = "", attendees: list = None,
    timezone: str = "America/Bogota",
) -> dict:
    try:
        from api.mcp_servers.mcp_microsoft365_server import m365_calendar_create
        token = _get_m365_token(empresa_id)
        return asyncio.run(m365_calendar_create(
            token, summary=summary, start_datetime=start_datetime,
            end_datetime=end_datetime, description=description,
            location=location, attendees=attendees, timezone=timezone,
        ))
    except Exception as e:
        print(f"ERROR M365 Calendar create: {e}")
        return {"error": str(e)}


def _m365_calendar_update(
    empresa_id: str, event_id: str, summary: str = None,
    start_datetime: str = None, end_datetime: str = None,
    description: str = None, location: str = None,
    timezone: str = "America/Bogota",
) -> dict:
    try:
        from api.mcp_servers.mcp_microsoft365_server import m365_calendar_update
        token = _get_m365_token(empresa_id)
        return asyncio.run(m365_calendar_update(
            token, event_id=event_id, summary=summary,
            start_datetime=start_datetime, end_datetime=end_datetime,
            description=description, location=location, timezone=timezone,
        ))
    except Exception as e:
        print(f"ERROR M365 Calendar update: {e}")
        return {"error": str(e)}


def _m365_calendar_delete(empresa_id: str, event_id: str) -> dict:
    try:
        from api.mcp_servers.mcp_microsoft365_server import m365_calendar_delete
        token = _get_m365_token(empresa_id)
        return asyncio.run(m365_calendar_delete(token, event_id=event_id))
    except Exception as e:
        print(f"ERROR M365 Calendar delete: {e}")
        return {"error": str(e)}