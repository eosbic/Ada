"""
Email Service — Conexión a Email API (Gmail / Outlook M365).
Provider routing automático vía provider_router.
Referencia: ADA_MIGRACION_V5_PART1.md §4.4

Tools: search, read, draft, send
Send requiere aprobación humana (human-in-the-loop).
"""

import os
import asyncio
import base64
from typing import Optional, List
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build


def _get_provider_family(empresa_id: str, user_id: str = "") -> str:
    """Determina familia de provider (google/microsoft) para email."""
    try:
        from api.services.provider_router import get_provider
        _, family = get_provider(empresa_id, "email")
        return family if family != "none" else "google"
    except Exception:
        return "google"


def _get_m365_token(empresa_id: str, user_id: str = "") -> str:
    """Obtiene access_token de Microsoft 365 para email."""
    from api.services.tenant_credentials import get_microsoft_credentials
    creds = get_microsoft_credentials(empresa_id, "outlook_email", user_id=user_id)
    if "error" in creds:
        raise RuntimeError(creds["error"])
    return creds["access_token"]


def _get_gmail_service(empresa_id: str = "", user_id: str = ""):
    """Crea servicio Gmail con credenciales de la empresa/usuario."""
    from api.services.tenant_credentials import get_google_credentials
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    creds_data = get_google_credentials(empresa_id, "gmail", user_id=user_id)

    creds = Credentials(
        token=creds_data.get("access_token"),
        refresh_token=creds_data.get("refresh_token"),
        client_id=creds_data.get("client_id"),
        client_secret=creds_data.get("client_secret"),
        token_uri="https://oauth2.googleapis.com/token",
    )
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def gmail_search(query: str, max_results: int = 10, empresa_id: str = "", user_id: str = "") -> list:
    """Busca emails por query. Retorna lista de {id, from, subject, date, snippet}."""
    if _get_provider_family(empresa_id, user_id=user_id) == "microsoft":
        return _m365_email_search(empresa_id, query, max_results, user_id=user_id)

    try:
        service = _get_gmail_service(empresa_id, user_id=user_id)
        results = service.users().messages().list(
            userId="me", q=query, maxResults=max_results
        ).execute()

        messages = results.get("messages", [])
        emails = []

        for msg in messages:
            detail = service.users().messages().get(
                userId="me", id=msg["id"], format="metadata",
                metadataHeaders=["From", "Subject", "Date"]
            ).execute()

            headers = {h["name"]: h["value"] for h in detail.get("payload", {}).get("headers", [])}
            emails.append({
                "id": msg["id"],
                "from": headers.get("From", ""),
                "subject": headers.get("Subject", ""),
                "date": headers.get("Date", ""),
                "snippet": detail.get("snippet", ""),
            })

        print(f"GMAIL: Búsqueda '{query}' → {len(emails)} resultados")
        return emails

    except Exception as e:
        print(f"ERROR Gmail search: {e}")
        return []


def gmail_read(message_id: str, empresa_id: str = "", user_id: str = "") -> dict:
    """Lee contenido completo de un email por ID."""
    if _get_provider_family(empresa_id, user_id=user_id) == "microsoft":
        return _m365_email_read(empresa_id, message_id, user_id=user_id)

    try:
        service = _get_gmail_service(empresa_id, user_id=user_id)
        msg = service.users().messages().get(
            userId="me", id=message_id, format="full"
        ).execute()

        headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}

        # Extraer cuerpo del mensaje
        body = ""
        payload = msg.get("payload", {})

        if "parts" in payload:
            for part in payload["parts"]:
                if part.get("mimeType") == "text/plain":
                    data = part.get("body", {}).get("data", "")
                    if data:
                        body = base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
                        break
        else:
            data = payload.get("body", {}).get("data", "")
            if data:
                body = base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")

        return {
            "id": message_id,
            "from": headers.get("From", ""),
            "to": headers.get("To", ""),
            "subject": headers.get("Subject", ""),
            "date": headers.get("Date", ""),
            "body": body[:5000],  # Limitar a 5000 chars
        }

    except Exception as e:
        print(f"ERROR Gmail read: {e}")
        return {"error": str(e)}


def gmail_draft(to: str, subject: str, body: str, cc: str = "", empresa_id: str = "", user_id: str = "") -> dict:
    """Crea borrador de email. NO lo envía."""
    if _get_provider_family(empresa_id, user_id=user_id) == "microsoft":
        return _m365_email_draft(empresa_id, to, subject, body, cc, user_id=user_id)

    try:
        service = _get_gmail_service(empresa_id, user_id=user_id)

        message = MIMEMultipart()
        message["to"] = to
        message["subject"] = subject
        if cc:
            message["cc"] = cc
        message.attach(MIMEText(body, "plain"))

        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        draft = service.users().drafts().create(
            userId="me", body={"message": {"raw": raw}}
        ).execute()

        print(f"GMAIL: Draft creado → {draft['id']} para {to}")
        return {
            "draft_id": draft["id"],
            "to": to,
            "subject": subject,
            "status": "draft_created",
            "message": f"Borrador creado para {to}: '{subject}'. ¿Lo envío?",
        }

    except Exception as e:
        print(f"ERROR Gmail draft: {e}")
        return {"error": str(e)}


def gmail_send(draft_id: str, empresa_id: str = "", user_id: str = "") -> dict:
    """Envía un borrador existente. REQUIERE aprobación previa."""
    if _get_provider_family(empresa_id, user_id=user_id) == "microsoft":
        return _m365_email_send(empresa_id, draft_id, user_id=user_id)

    try:
        service = _get_gmail_service(empresa_id, user_id=user_id)
        result = service.users().drafts().send(
            userId="me", body={"id": draft_id}
        ).execute()

        print(f"GMAIL: Email enviado → {result.get('id')}")
        return {
            "message_id": result.get("id"),
            "status": "sent",
            "message": "Email enviado exitosamente.",
        }

    except Exception as e:
        print(f"ERROR Gmail send: {e}")
        return {"error": str(e)}


def gmail_reply(message_id: str, body: str, empresa_id: str = "", user_id: str = "") -> dict:
    """Responde a un email existente."""
    try:
        service = _get_gmail_service(empresa_id, user_id=user_id)

        # Obtener email original para headers
        original = service.users().messages().get(
            userId="me", id=message_id, format="metadata",
            metadataHeaders=["From", "Subject", "Message-ID"]
        ).execute()

        headers = {h["name"]: h["value"] for h in original.get("payload", {}).get("headers", [])}

        message = MIMEText(body)
        message["to"] = headers.get("From", "")
        message["subject"] = "Re: " + headers.get("Subject", "")
        message["In-Reply-To"] = headers.get("Message-ID", "")
        message["References"] = headers.get("Message-ID", "")

        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        result = service.users().messages().send(
            userId="me", body={"raw": raw, "threadId": original.get("threadId")}
        ).execute()

        print(f"GMAIL: Reply enviado → {result.get('id')}")
        return {
            "message_id": result.get("id"),
            "status": "sent",
            "message": f"Respuesta enviada a {headers.get('From', '')}.",
        }

    except Exception as e:
        print(f"ERROR Gmail reply: {e}")
        return {"error": str(e)}


# ─── Gmail Attachments ─────────────────────────────────────

def gmail_get_attachments(message_id: str, empresa_id: str = "", user_id: str = "") -> list:
    """Descarga attachments de un email. Retorna lista de {filename, content, mime_type}."""
    try:
        service = _get_gmail_service(empresa_id, user_id=user_id)
        msg = service.users().messages().get(
            userId="me", id=message_id, format="full"
        ).execute()

        attachments = []
        payload = msg.get("payload", {})
        parts = payload.get("parts", [])

        for part in parts:
            filename = part.get("filename", "")
            if not filename:
                # Revisar sub-parts (multipart)
                sub_parts = part.get("parts", [])
                for sub in sub_parts:
                    sub_filename = sub.get("filename", "")
                    if sub_filename:
                        att_data = _download_attachment(service, message_id, sub)
                        if att_data:
                            attachments.append({
                                "filename": sub_filename,
                                "content": att_data,
                                "mime_type": sub.get("mimeType", ""),
                            })
            else:
                att_data = _download_attachment(service, message_id, part)
                if att_data:
                    attachments.append({
                        "filename": filename,
                        "content": att_data,
                        "mime_type": part.get("mimeType", ""),
                    })

        print(f"GMAIL: {len(attachments)} attachments encontrados en {message_id}")
        return attachments

    except Exception as e:
        print(f"ERROR Gmail attachments: {e}")
        return []


def _download_attachment(service, message_id: str, part: dict) -> str:
    """Descarga un attachment específico y retorna el contenido como texto."""
    try:
        body = part.get("body", {})
        att_id = body.get("attachmentId", "")

        if att_id:
            att = service.users().messages().attachments().get(
                userId="me", messageId=message_id, id=att_id
            ).execute()
            data = att.get("data", "")
        else:
            data = body.get("data", "")

        if data:
            decoded = base64.urlsafe_b64decode(data)
            try:
                return decoded.decode("utf-8", errors="replace")
            except Exception:
                return decoded.decode("latin-1", errors="replace")

        return ""
    except Exception as e:
        print(f"GMAIL: Error descargando attachment: {e}")
        return ""


# ─── Microsoft 365 Sync Wrappers ────────────────────────────

def _m365_email_search(empresa_id: str, query: str, max_results: int = 10, user_id: str = "") -> list:
    try:
        from api.mcp_servers.mcp_microsoft365_server import m365_email_search
        token = _get_m365_token(empresa_id, user_id=user_id)
        return asyncio.run(m365_email_search(token, query=query, max_results=max_results))
    except Exception as e:
        print(f"ERROR M365 Email search: {e}")
        return []


def _m365_email_read(empresa_id: str, message_id: str, user_id: str = "") -> dict:
    try:
        from api.mcp_servers.mcp_microsoft365_server import m365_email_read
        token = _get_m365_token(empresa_id, user_id=user_id)
        return asyncio.run(m365_email_read(token, message_id=message_id))
    except Exception as e:
        print(f"ERROR M365 Email read: {e}")
        return {"error": str(e)}


def _m365_email_draft(empresa_id: str, to: str, subject: str, body: str, cc: str = "", user_id: str = "") -> dict:
    try:
        from api.mcp_servers.mcp_microsoft365_server import m365_email_draft
        token = _get_m365_token(empresa_id, user_id=user_id)
        return asyncio.run(m365_email_draft(token, to=to, subject=subject, body=body, cc=cc))
    except Exception as e:
        print(f"ERROR M365 Email draft: {e}")
        return {"error": str(e)}


def _m365_email_send(empresa_id: str, draft_id: str, user_id: str = "") -> dict:
    try:
        from api.mcp_servers.mcp_microsoft365_server import m365_email_send
        token = _get_m365_token(empresa_id, user_id=user_id)
        return asyncio.run(m365_email_send(token, draft_id=draft_id))
    except Exception as e:
        print(f"ERROR M365 Email send: {e}")
        return {"error": str(e)}