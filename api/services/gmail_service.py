"""
Gmail Service — Conexión directa a Gmail API.
Referencia: ADA_MIGRACION_V5_PART1.md §4.4

Tools: search, read, draft, send
Send requiere aprobación humana (human-in-the-loop).
"""

import os
import base64
from typing import Optional, List
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build


def _get_gmail_service(empresa_id: str = ""):
    """Crea servicio Gmail con credenciales de la empresa."""
    from api.services.tenant_credentials import get_google_credentials
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    creds_data = get_google_credentials(empresa_id, "gmail")

    creds = Credentials(
        token=creds_data.get("access_token"),
        refresh_token=creds_data.get("refresh_token"),
        client_id=creds_data.get("client_id"),
        client_secret=creds_data.get("client_secret"),
        token_uri="https://oauth2.googleapis.com/token",
    )
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def gmail_search(query: str, max_results: int = 10, empresa_id: str = "") -> list:
    """Busca emails por query. Retorna lista de {id, from, subject, date, snippet}."""
    try:
        service = _get_gmail_service(empresa_id)
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


def gmail_read(message_id: str, empresa_id: str = "") -> dict:
    """Lee contenido completo de un email por ID."""
    try:
        service = _get_gmail_service(empresa_id)
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


def gmail_draft(to: str, subject: str, body: str, cc: str = "", empresa_id: str = "") -> dict:
    """Crea borrador de email. NO lo envía."""
    try:
        service = _get_gmail_service(empresa_id)

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


def gmail_send(draft_id: str, empresa_id: str = "") -> dict:
    """Envía un borrador existente. REQUIERE aprobación previa."""
    try:
        service = _get_gmail_service(empresa_id)
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


def gmail_reply(message_id: str, body: str, empresa_id: str = "") -> dict:
    """Responde a un email existente."""
    try:
        service = _get_gmail_service(empresa_id)

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