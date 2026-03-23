"""
MCP Server — Microsoft Graph API v1.0
Calendar + Email + Drive tools para Microsoft 365.
Retorna misma estructura que las funciones Google equivalentes.
"""

import re
from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta

import httpx


GRAPH_BASE = "https://graph.microsoft.com/v1.0"


# ─── Helpers ────────────────────────────────────────────────

def _headers(access_token: str) -> dict:
    """Headers estándar para Microsoft Graph API."""
    return {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }


def _safe_date(iso_str: str) -> str:
    """Normaliza fechas ISO de Microsoft Graph."""
    if not iso_str:
        return ""
    try:
        # Microsoft a veces incluye fracciones de segundo
        clean = iso_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(clean)
        return dt.isoformat()
    except Exception:
        return iso_str


# ─── Calendar Tools ─────────────────────────────────────────

async def m365_calendar_list(
    access_token: str,
    days_ahead: int = 7,
    max_results: int = 20,
) -> List[Dict]:
    """Lista eventos del calendario M365."""
    now = datetime.utcnow()
    start_dt = now.isoformat() + "Z"
    end_dt = (now + timedelta(days=days_ahead)).isoformat() + "Z"

    url = f"{GRAPH_BASE}/me/calendarView"
    params = {
        "startDateTime": start_dt,
        "endDateTime": end_dt,
        "$top": max_results,
        "$orderby": "start/dateTime",
        "$select": "id,subject,start,end,location,bodyPreview,attendees",
    }

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(url, headers=_headers(access_token), params=params)

    if resp.status_code != 200:
        print(f"M365 Calendar list error: {resp.status_code} {resp.text[:200]}")
        return []

    events = []
    for e in resp.json().get("value", []):
        attendees = []
        for a in e.get("attendees", []):
            email = a.get("emailAddress", {}).get("address", "")
            if email:
                attendees.append(email)

        events.append({
            "id": e.get("id", ""),
            "summary": e.get("subject", "Sin título"),
            "start": _safe_date(e.get("start", {}).get("dateTime", "")),
            "end": _safe_date(e.get("end", {}).get("dateTime", "")),
            "location": e.get("location", {}).get("displayName", ""),
            "description": (e.get("bodyPreview", "") or "")[:200],
            "attendees": attendees,
        })

    print(f"M365 CALENDAR: {len(events)} eventos en próximos {days_ahead} días")
    return events


async def m365_calendar_search(
    access_token: str,
    query: str,
    days_ahead: int = 30,
    max_results: int = 10,
) -> List[Dict]:
    """Busca eventos por query (client-side filter)."""
    events = await m365_calendar_list(access_token, days_ahead=days_ahead, max_results=50)
    query_lower = query.lower()

    filtered = []
    for e in events:
        if (query_lower in e.get("summary", "").lower()
                or query_lower in e.get("description", "").lower()
                or query_lower in e.get("location", "").lower()):
            filtered.append({
                "id": e["id"],
                "summary": e["summary"],
                "start": e["start"],
                "location": e["location"],
            })

    print(f"M365 CALENDAR: Búsqueda '{query}' → {len(filtered)} eventos")
    return filtered[:max_results]


async def m365_calendar_create(
    access_token: str,
    summary: str,
    start_datetime: str,
    end_datetime: str,
    description: str = "",
    location: str = "",
    attendees: list = None,
    timezone: str = "America/Bogota",
) -> Dict:
    """Crea evento en calendario M365."""
    body = {
        "subject": summary,
        "body": {"contentType": "Text", "content": description},
        "start": {"dateTime": start_datetime, "timeZone": timezone},
        "end": {"dateTime": end_datetime, "timeZone": timezone},
    }

    if location:
        body["location"] = {"displayName": location}

    if attendees:
        body["attendees"] = [
            {"emailAddress": {"address": a}, "type": "required"}
            for a in attendees
        ]

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"{GRAPH_BASE}/me/events",
            headers=_headers(access_token),
            json=body,
        )

    if resp.status_code not in (200, 201):
        print(f"M365 Calendar create error: {resp.status_code} {resp.text[:200]}")
        return {"error": f"Error creando evento: {resp.status_code}"}

    event = resp.json()
    print(f"M365 CALENDAR: Evento creado → {event.get('id')}: {summary}")
    return {
        "event_id": event.get("id"),
        "summary": summary,
        "start": start_datetime,
        "end": end_datetime,
        "link": event.get("webLink", ""),
        "status": "created",
        "message": f"Evento '{summary}' creado exitosamente.",
    }


async def m365_calendar_update(
    access_token: str,
    event_id: str,
    summary: str = None,
    start_datetime: str = None,
    end_datetime: str = None,
    description: str = None,
    location: str = None,
    timezone: str = "America/Bogota",
) -> Dict:
    """Actualiza evento en calendario M365."""
    body = {}
    if summary:
        body["subject"] = summary
    if description is not None:
        body["body"] = {"contentType": "Text", "content": description}
    if start_datetime:
        body["start"] = {"dateTime": start_datetime, "timeZone": timezone}
    if end_datetime:
        body["end"] = {"dateTime": end_datetime, "timeZone": timezone}
    if location is not None:
        body["location"] = {"displayName": location}

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.patch(
            f"{GRAPH_BASE}/me/events/{event_id}",
            headers=_headers(access_token),
            json=body,
        )

    if resp.status_code != 200:
        print(f"M365 Calendar update error: {resp.status_code} {resp.text[:200]}")
        return {"error": f"Error actualizando evento: {resp.status_code}"}

    print(f"M365 CALENDAR: Evento actualizado → {event_id}")
    return {
        "event_id": event_id,
        "status": "updated",
        "message": f"Evento '{summary or event_id}' actualizado.",
    }


async def m365_calendar_delete(
    access_token: str,
    event_id: str,
) -> Dict:
    """Elimina evento del calendario M365."""
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.delete(
            f"{GRAPH_BASE}/me/events/{event_id}",
            headers=_headers(access_token),
        )

    if resp.status_code not in (200, 204):
        print(f"M365 Calendar delete error: {resp.status_code} {resp.text[:200]}")
        return {"error": f"Error eliminando evento: {resp.status_code}"}

    print(f"M365 CALENDAR: Evento eliminado → {event_id}")
    return {
        "event_id": event_id,
        "status": "deleted",
        "message": "Evento eliminado exitosamente.",
    }


# ─── Email Tools ─────────────────────────────────────────────

async def m365_email_search(
    access_token: str,
    query: str,
    max_results: int = 10,
) -> List[Dict]:
    """Busca emails en Outlook M365."""
    url = f"{GRAPH_BASE}/me/messages"
    params = {
        "$search": f'"{query}"',
        "$top": max_results,
        "$orderby": "receivedDateTime desc",
        "$select": "id,from,subject,receivedDateTime,bodyPreview",
    }

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(url, headers=_headers(access_token), params=params)

    if resp.status_code != 200:
        print(f"M365 Email search error: {resp.status_code} {resp.text[:200]}")
        return []

    emails = []
    for msg in resp.json().get("value", []):
        from_addr = msg.get("from", {}).get("emailAddress", {})
        emails.append({
            "id": msg.get("id", ""),
            "from": f"{from_addr.get('name', '')} <{from_addr.get('address', '')}>",
            "subject": msg.get("subject", ""),
            "date": msg.get("receivedDateTime", ""),
            "snippet": (msg.get("bodyPreview", "") or "")[:200],
        })

    print(f"M365 EMAIL: Búsqueda '{query}' → {len(emails)} resultados")
    return emails


async def m365_email_read(
    access_token: str,
    message_id: str,
) -> Dict:
    """Lee contenido completo de un email M365."""
    url = f"{GRAPH_BASE}/me/messages/{message_id}"
    params = {
        "$select": "id,from,toRecipients,subject,receivedDateTime,body",
    }

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(url, headers=_headers(access_token), params=params)

    if resp.status_code != 200:
        print(f"M365 Email read error: {resp.status_code} {resp.text[:200]}")
        return {"error": f"Error leyendo email: {resp.status_code}"}

    msg = resp.json()
    from_addr = msg.get("from", {}).get("emailAddress", {})
    to_addrs = [
        r.get("emailAddress", {}).get("address", "")
        for r in msg.get("toRecipients", [])
    ]

    # Limpiar HTML si viene en formato HTML
    body_obj = msg.get("body", {})
    body_content = body_obj.get("content", "")
    if body_obj.get("contentType", "").lower() == "html":
        body_content = re.sub(r"<[^>]+>", " ", body_content)
        body_content = re.sub(r"\s+", " ", body_content).strip()

    return {
        "id": message_id,
        "from": f"{from_addr.get('name', '')} <{from_addr.get('address', '')}>",
        "to": ", ".join(to_addrs),
        "subject": msg.get("subject", ""),
        "date": msg.get("receivedDateTime", ""),
        "body": body_content[:5000],
    }


async def m365_email_draft(
    access_token: str,
    to: str,
    subject: str,
    body: str,
    cc: str = "",
) -> Dict:
    """Crea borrador en Outlook M365. NO lo envía."""
    message = {
        "subject": subject,
        "body": {"contentType": "Text", "content": body},
        "toRecipients": [{"emailAddress": {"address": to}}],
    }

    if cc:
        message["ccRecipients"] = [{"emailAddress": {"address": cc}}]

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"{GRAPH_BASE}/me/messages",
            headers=_headers(access_token),
            json=message,
        )

    if resp.status_code not in (200, 201):
        print(f"M365 Email draft error: {resp.status_code} {resp.text[:200]}")
        return {"error": f"Error creando borrador: {resp.status_code}"}

    draft = resp.json()
    print(f"M365 EMAIL: Draft creado → {draft.get('id')} para {to}")
    return {
        "draft_id": draft.get("id"),
        "to": to,
        "subject": subject,
        "status": "draft_created",
        "message": f"Borrador creado para {to}: '{subject}'. ¿Lo envío?",
    }


async def m365_email_send(
    access_token: str,
    draft_id: str,
) -> Dict:
    """Envía un borrador existente en Outlook M365."""
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"{GRAPH_BASE}/me/messages/{draft_id}/send",
            headers=_headers(access_token),
        )

    if resp.status_code not in (200, 202):
        print(f"M365 Email send error: {resp.status_code} {resp.text[:200]}")
        return {"error": f"Error enviando email: {resp.status_code}"}

    print(f"M365 EMAIL: Email enviado → {draft_id}")
    return {
        "message_id": draft_id,
        "status": "sent",
        "message": "Email enviado exitosamente.",
    }


# ─── Drive Tools ─────────────────────────────────────────────

async def m365_drive_list(
    access_token: str,
    path: str = "",
) -> List[Dict]:
    """Lista archivos en OneDrive."""
    if path and path != "/":
        url = f"{GRAPH_BASE}/me/drive/root:/{path.strip('/')}:/children"
    else:
        url = f"{GRAPH_BASE}/me/drive/root/children"

    params = {
        "$select": "id,name,size,lastModifiedDateTime,file,folder,webUrl",
        "$top": 50,
    }

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(url, headers=_headers(access_token), params=params)

    if resp.status_code != 200:
        print(f"M365 Drive list error: {resp.status_code} {resp.text[:200]}")
        return []

    files = []
    for item in resp.json().get("value", []):
        is_folder = "folder" in item
        mime_type = item.get("file", {}).get("mimeType", "") if not is_folder else "folder"

        files.append({
            "id": item.get("id", ""),
            "name": item.get("name", ""),
            "size": item.get("size", 0),
            "modified": item.get("lastModifiedDateTime", ""),
            "mime_type": mime_type,
            "is_folder": is_folder,
            "web_url": item.get("webUrl", ""),
        })

    print(f"M365 DRIVE: {len(files)} items en '{path or '/'}'")
    return files


# ─── Tool Registry ───────────────────────────────────────────

def get_tools() -> List[Dict]:
    """Retorna definiciones de tools para MCP."""
    return [
        {
            "name": "m365_calendar_list",
            "description": "Lista eventos del calendario Microsoft 365",
            "parameters": {"days_ahead": "int", "max_results": "int"},
        },
        {
            "name": "m365_calendar_search",
            "description": "Busca eventos en calendario Microsoft 365",
            "parameters": {"query": "str", "days_ahead": "int"},
        },
        {
            "name": "m365_calendar_create",
            "description": "Crea evento en calendario Microsoft 365",
            "parameters": {
                "summary": "str", "start_datetime": "str", "end_datetime": "str",
                "description": "str", "location": "str", "attendees": "list",
                "timezone": "str",
            },
        },
        {
            "name": "m365_calendar_update",
            "description": "Actualiza evento en calendario Microsoft 365",
            "parameters": {
                "event_id": "str", "summary": "str", "start_datetime": "str",
                "end_datetime": "str", "description": "str", "location": "str",
                "timezone": "str",
            },
        },
        {
            "name": "m365_calendar_delete",
            "description": "Elimina evento del calendario Microsoft 365",
            "parameters": {"event_id": "str"},
        },
        {
            "name": "m365_email_search",
            "description": "Busca emails en Outlook Microsoft 365",
            "parameters": {"query": "str", "max_results": "int"},
        },
        {
            "name": "m365_email_read",
            "description": "Lee email completo de Outlook Microsoft 365",
            "parameters": {"message_id": "str"},
        },
        {
            "name": "m365_email_draft",
            "description": "Crea borrador en Outlook Microsoft 365",
            "parameters": {"to": "str", "subject": "str", "body": "str", "cc": "str"},
        },
        {
            "name": "m365_email_send",
            "description": "Envía borrador de Outlook Microsoft 365",
            "parameters": {"draft_id": "str"},
        },
        {
            "name": "m365_drive_list",
            "description": "Lista archivos en OneDrive Microsoft 365",
            "parameters": {"path": "str"},
        },
    ]


# Mapa de routing interno
TOOL_MAP = {
    "m365_calendar_list": m365_calendar_list,
    "m365_calendar_search": m365_calendar_search,
    "m365_calendar_create": m365_calendar_create,
    "m365_calendar_update": m365_calendar_update,
    "m365_calendar_delete": m365_calendar_delete,
    "m365_email_search": m365_email_search,
    "m365_email_read": m365_email_read,
    "m365_email_draft": m365_email_draft,
    "m365_email_send": m365_email_send,
    "m365_drive_list": m365_drive_list,
}


async def handle_tool_call(tool_name: str, arguments: dict, access_token: str) -> Any:
    """Entry point para MCP Host — ejecuta tool por nombre."""
    fn = TOOL_MAP.get(tool_name)
    if not fn:
        return {"error": f"Tool '{tool_name}' no encontrada en microsoft365 server"}

    return await fn(access_token=access_token, **arguments)
