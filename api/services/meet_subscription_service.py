"""
Meet Subscription Service — Crea suscripciones a eventos de Google Meet y Microsoft Teams.
Se ejecuta cuando un usuario conecta OAuth, para recibir webhooks instantaneos.
"""

import os
import httpx

API_BASE_URL = os.getenv("API_BASE_URL", "https://backend-ada.duckdns.org")
GOOGLE_PUBSUB_TOPIC = os.getenv("GOOGLE_PUBSUB_TOPIC", "")


async def subscribe_google_meet_events(empresa_id: str, user_id: str) -> dict:
    """Crea suscripcion a eventos de Google Meet para un usuario.

    Requiere:
    1. Google Cloud Pub/Sub topic creado
    2. Workspace Events API habilitada
    3. El usuario tenga scope meetings.space.readonly
    """
    if not GOOGLE_PUBSUB_TOPIC:
        print("MEET SUB: GOOGLE_PUBSUB_TOPIC not configured, skipping")
        return {"status": "not_configured"}

    try:
        from api.services.tenant_credentials import get_raw_google_credentials
        creds = get_raw_google_credentials(empresa_id, user_id=user_id)

        if not creds:
            return {"error": "No Google credentials"}

        # Obtener el user resource name
        from googleapiclient.discovery import build
        people_service = build("people", "v1", credentials=creds, cache_discovery=False)
        me = people_service.people().get(
            resourceName="people/me", personFields="names,emailAddresses"
        ).execute()

        resource_name = me.get("resourceName", "")
        user_id_google = resource_name.replace("people/", "") if resource_name else ""

        if not user_id_google:
            return {"error": "Could not get user ID"}

        import requests as requests_lib

        session = requests_lib.Session()
        session.headers["Authorization"] = f"Bearer {creds.token}"

        body = {
            "targetResource": f"//cloudidentity.googleapis.com/users/{user_id_google}",
            "eventTypes": [
                "google.workspace.meet.conference.v2.started",
                "google.workspace.meet.conference.v2.ended",
                "google.workspace.meet.transcript.v2.fileGenerated",
            ],
            "payloadOptions": {"includeResource": False},
            "notificationEndpoint": {"pubsubTopic": GOOGLE_PUBSUB_TOPIC},
            "ttl": "604800s",  # 7 dias
        }

        response = session.post(
            "https://workspaceevents.googleapis.com/v1/subscriptions",
            json=body,
        )

        if response.status_code in (200, 201):
            sub_data = response.json()
            print(f"MEET SUB: Google subscription created: {sub_data.get('name', '')}")
            return {"status": "subscribed", "subscription": sub_data.get("name", "")}
        else:
            print(f"MEET SUB: Google subscription failed: {response.status_code} {response.text[:200]}")
            return {"error": f"Subscription failed: {response.status_code}"}

    except Exception as e:
        print(f"MEET SUB: Google error: {e}")
        return {"error": str(e)}


async def subscribe_teams_transcript_events(empresa_id: str, user_id: str) -> dict:
    """Crea suscripcion a Microsoft Graph para notificaciones de transcripts de Teams."""
    from api.services.tenant_credentials import get_microsoft_credentials

    creds = get_microsoft_credentials(empresa_id, "outlook_email", user_id=user_id)
    if "error" in creds:
        creds = get_microsoft_credentials(empresa_id, "microsoft365", user_id=user_id)
    if "error" in creds:
        return {"error": "No Microsoft credentials"}

    access_token = creds.get("access_token", "")
    if not access_token:
        return {"error": "No access token"}

    try:
        from datetime import datetime, timedelta

        body = {
            "changeType": "created",
            "notificationUrl": f"{API_BASE_URL}/webhooks/meet/microsoft",
            "resource": "communications/onlineMeetings/getAllTranscripts",
            "expirationDateTime": (datetime.utcnow() + timedelta(days=2)).isoformat() + "Z",
            "clientState": f"ada_{empresa_id[:8]}",
        }

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                "https://graph.microsoft.com/v1.0/subscriptions",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                json=body,
            )

        if resp.status_code in (200, 201):
            sub_data = resp.json()
            print(f"TEAMS SUB: Subscription created: {sub_data.get('id', '')}")
            return {"status": "subscribed", "subscription_id": sub_data.get("id", "")}
        else:
            print(f"TEAMS SUB: Subscription failed: {resp.status_code} {resp.text[:200]}")
            return {"error": f"Subscription failed: {resp.status_code}"}

    except Exception as e:
        print(f"TEAMS SUB: Error: {e}")
        return {"error": str(e)}
