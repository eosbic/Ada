"""
Email Agent — Busca, lee, redacta y envía emails via Gmail.
Referencia: ADA_MIGRACION_V5_PART1.md §8.5

Flujo:
1. Interpreta intención del usuario
2. Ejecuta acción Gmail (search/read/draft/send)
3. Para ENVÍO: requiere aprobación del usuario

Tools disponibles: gmail_search, gmail_read, gmail_draft, gmail_send
"""

import json
from typing import TypedDict, Optional, List
from langgraph.graph import StateGraph, END
from models.selector import selector
from api.services.gmail_service import gmail_search, gmail_read, gmail_draft, gmail_send


class EmailState(TypedDict, total=False):
    message: str
    empresa_id: str
    user_id: str
    intent: str

    # Internos
    action: str  # search, read, draft, send
    action_params: dict
    action_result: dict
    needs_approval: bool
    draft_id: str
    original_draft: str

    # Output
    response: str
    model_used: str


EMAIL_SYSTEM_PROMPT = """Eres Ada, asistente ejecutiva experta en gestión de correo electrónico.

Tu trabajo es interpretar lo que el usuario necesita y generar los parámetros exactos para Gmail.

## REGLAS DE CANTIDAD:
- "el último correo" o "el más reciente" → max_results: 1
- "los últimos correos" o "correos recientes" → max_results: 3
- "busca correos de X" o "emails de X" → max_results: 5
- "todos los correos de X" → max_results: 10
- Si el usuario especifica cantidad ("dame 2 correos") → usar esa cantidad exacta

## QUERIES DE GMAIL:
- Últimos: "newer_than:1d" (hoy), "newer_than:3d" (3 días), "newer_than:7d" (semana)
- De alguien: "from:nombre" o "from:email@dominio.com"
- Para alguien: "to:nombre"
- Por asunto: "subject:texto"
- No leídos: "is:unread"
- Con adjunto: "has:attachment"
- Importantes: "is:important"
- Texto libre: "palabra clave"
- Combinados: "from:carlos subject:reunión newer_than:7d"

## ACCIONES DISPONIBLES:
- search: buscar emails
- read: leer un email específico (necesita message_id o buscar primero)
- draft: crear borrador (necesita to, subject, body)
- send: enviar borrador existente (necesita draft_id)
- need_info: falta información para crear borrador
- resolve_contact: buscar email de un contacto por nombre

## REGLA CRÍTICA — INFORMACIÓN INCOMPLETA:
- Si tienes destinatario pero NO contenido → {"action": "need_info", "params": {"to": "email@x.com", "missing": "body"}}
- Si no tienes destinatario → {"action": "need_info", "params": {"missing": "to"}}
- Si no tienes nada → {"action": "need_info", "params": {"missing": "to,body"}}
- SOLO usar action=draft cuando tienes: destinatario + tema + contenido claro
- NUNCA crear borrador con texto placeholder como "[Aquí iría el contenido]"

## REGLA — NOMBRES EN VEZ DE EMAILS:
- Si el usuario dice "escríbele a Oswaldo" o "mándale un mail a María" (nombre, no email):
  → {"action": "resolve_contact", "params": {"contact_name": "Oswaldo"}}
- Ada buscará el email en los contactos del usuario

## CONTEXTO CONVERSACIONAL:
Si en el historial reciente ya se mencionó un destinatario y el usuario ahora da contenido sin repetir el destinatario, USAR el destinatario del historial.
Si se resolvió un contacto por nombre previamente, usar ese email.

## EJEMPLOS:
- "busca el último correo" → {"action": "search", "params": {"query": "newer_than:1d", "max_results": 1}}
- "correos de hoy" → {"action": "search", "params": {"query": "newer_than:1d", "max_results": 3}}
- "emails de Carlos" → {"action": "search", "params": {"query": "from:carlos", "max_results": 5}}
- "correos no leídos" → {"action": "search", "params": {"query": "is:unread", "max_results": 5}}
- "lee el correo de María" → {"action": "search", "params": {"query": "from:maria", "max_results": 1}}
- "dame los 2 últimos correos" → {"action": "search", "params": {"query": "newer_than:1d", "max_results": 2}}
- "escribe email a juan@x.com sobre la reunión" → {"action": "draft", "params": {"to": "juan@x.com", "subject": "Reunión", "body": "..."}}
- "escríbele a Oswaldo" → {"action": "resolve_contact", "params": {"contact_name": "Oswaldo"}}
- "escribe a pedro@x.com" (sin contenido) → {"action": "need_info", "params": {"to": "pedro@x.com", "missing": "body"}}
- "envíalo" → {"action": "send", "params": {"draft_id": ""}}

Responde SOLO JSON válido, sin markdown, sin explicación:
{"action": "...", "params": {...}}"""


async def classify_email_action(state: EmailState) -> dict:
    """Clasifica qué acción de email quiere el usuario."""
    model, model_name = selector.get_model("chat_with_tools")

    # Agregar historial reciente para contexto
    history_context = ""
    if state.get("empresa_id") and state.get("user_id"):
        try:
            from api.agents.chat_agent import get_history
            history = get_history(state["empresa_id"], state["user_id"])
            if history:
                recent = history[-4:]
                history_context = "\n\nCONVERSACIÓN RECIENTE:\n" + "\n".join(
                    f"{m.get('role','user')}: {m.get('content','')[:200]}"
                    for m in recent
                )
        except Exception:
            pass

    response = await model.ainvoke([
        {"role": "system", "content": EMAIL_SYSTEM_PROMPT},
        {"role": "user", "content": state["message"] + history_context},
    ])

    try:
        raw = response.content.strip().replace("```json", "").replace("```", "")
        result = json.loads(raw)
        action = result.get("action", "search")
        params = result.get("params", {})
    except (json.JSONDecodeError, AttributeError):
        action = "search"
        params = {"query": state["message"]}

    print(f"EMAIL AGENT: acción={action}, params={params}")

    return {
        "action": action,
        "action_params": params,
        "model_used": model_name,
    }


async def execute_email_action(state: EmailState) -> dict:
    """Ejecuta la acción de Gmail."""
    action = state.get("action", "")
    params = state.get("action_params", {})
    empresa_id = state.get("empresa_id", "")

    user_id = state.get("user_id", "")

    if action == "search":
        query = params.get("query", "")
        max_results = params.get("max_results", 3)
        results = gmail_search(query, max_results=max_results, empresa_id=empresa_id, user_id=user_id)
        if results:
            formatted = "\n".join([
                f"📧 **{e['subject']}** — de {e['from']} ({e['date'][:16]})\n   {e['snippet'][:100]}"
                for e in results
            ])
            return {
                "response": f"Encontré {len(results)} emails:\n\n{formatted}",
                "action_result": {"emails": results},
            }
        else:
            return {"response": f"No encontré emails con '{query}'."}

    elif action == "read":
        message_id = params.get("message_id", "")
        if not message_id:
            # Si no hay ID, buscar primero
            query = params.get("query", state["message"])
            results = gmail_search(query, max_results=1, empresa_id=empresa_id, user_id=user_id)
            if results:
                message_id = results[0]["id"]
            else:
                return {"response": "No encontré el email para leer."}

        email = gmail_read(message_id, empresa_id=empresa_id, user_id=user_id)
        if "error" in email:
            return {"response": f"Error leyendo email: {email['error']}"}

        return {
            "response": (
                f"📧 **{email['subject']}**\n"
                f"De: {email['from']}\n"
                f"Para: {email['to']}\n"
                f"Fecha: {email['date']}\n\n"
                f"{email['body'][:2000]}"
            ),
            "action_result": email,
        }

    elif action == "need_info":
        to = params.get("to", "")
        missing = params.get("missing", "body")
        if "to" in missing and "body" in missing:
            return {"response": "¿A quién le escribo y qué quieres que le diga?"}
        elif "body" in missing:
            return {"response": f"Tengo el destinatario ({to}). ¿Qué quieres que le diga?"}
        elif "to" in missing:
            return {"response": "¿A quién le envío el correo?"}
        else:
            return {"response": "¿Qué necesitas que diga el correo?"}

    elif action == "resolve_contact":
        contact_name = params.get("contact_name", "")
        if not contact_name:
            return {"response": "¿A quién le envío el correo?"}

        contacts = _search_contacts(empresa_id, user_id, contact_name)

        if not contacts:
            return {"response": f"No encontré a '{contact_name}' en tus contactos. ¿Me das el email directamente?"}
        elif len(contacts) == 1:
            email = contacts[0]["email"]
            name = contacts[0]["name"]
            return {
                "response": f"Encontré a **{name}** ({email}). ¿Qué quieres que le diga?",
                "resolved_email": email,
            }
        else:
            options = "\n".join(
                f"{i+1}. **{c['name']}** — {c.get('org', '')} ({c['email']})"
                for i, c in enumerate(contacts)
            )
            return {
                "response": f"Encontré varios contactos con ese nombre:\n{options}\n\n¿A cuál te refieres?",
            }

    elif action == "draft":
        to = params.get("to", "")
        subject = params.get("subject", "")
        body = params.get("body", "")

        if not to:
            return {"response": "Necesito la dirección de email del destinatario. ¿A quién le envío?"}

        # Buscar preferencias de escritura para este contacto
        contact_prefs = ""
        if to and empresa_id and user_id:
            try:
                from api.services.user_memory_service import get_contact_preferences
                contact_prefs = get_contact_preferences(empresa_id, user_id, to)
            except Exception:
                pass

        # Cargar preferencias generales de escritura
        writing_prefs = ""
        if empresa_id and user_id:
            try:
                from api.services.user_memory_service import load_user_memories
                all_memories = load_user_memories(empresa_id, user_id)
                if all_memories:
                    writing_lines = [l for l in all_memories.split("\n") if any(kw in l.lower() for kw in ["escrit", "email", "tono", "formal", "informal", "corto", "largo"])]
                    if writing_lines:
                        writing_prefs = "\nPREFERENCIAS GENERALES DE ESCRITURA DEL USUARIO:\n" + "\n".join(writing_lines)
            except Exception:
                pass

        # Cargar nombre del remitente para firma correcta
        sender_name = ""
        sender_hint = ""
        if empresa_id and user_id:
            try:
                from api.database import sync_engine
                from sqlalchemy import text as _sql_email
                with sync_engine.connect() as _conn:
                    _u = _conn.execute(
                        _sql_email("SELECT nombre, apellido FROM usuarios WHERE id = :uid"),
                        {"uid": user_id}
                    ).fetchone()
                    if _u and _u.nombre:
                        sender_name = f"{_u.nombre} {_u.apellido or str()}".strip()
                        sender_hint = f"El remitente se llama {sender_name}. Firma como {sender_name}, NO como Ada."
            except Exception as e:
                print(f"EMAIL: Error loading sender info: {e}")

        # Si no hay subject o body, generar con LLM
        if not subject or not body:
            model, _ = selector.get_model("email_draft")
            draft_system = """Genera un email en español. Responde JSON: {"subject": "...", "body": "..."}

REGLAS DE REDACCIÓN:
- Si hay preferencias para este contacto, APLÍCALAS (tono, tratamiento, formalidad)
- Si NO hay preferencias, usar tono profesional pero cálido (NO "Estimado/a" genérico)
- Usar el nombre del destinatario si lo conoces
- Emails cortos y directos — máximo 4-5 líneas para el cuerpo
- Ir al punto rápido, sin relleno cortés excesivo
- FIRMA: Firmar con el nombre REAL del remitente (NO como Ada). Despedida acorde al genero (Atento/Atenta)"""
            if contact_prefs:
                draft_system += f"\n\nPREFERENCIAS PARA ESTE CONTACTO:\n{contact_prefs}\nAplica estas preferencias al tono y formato del email."
            if writing_prefs:
                draft_system += writing_prefs
            if sender_hint:
                draft_system += "\n\n" + sender_hint
            gen = await model.ainvoke([
                {"role": "system", "content": draft_system},
                {"role": "user", "content": f"Para: {to}. Contexto: {state['message']}"},
            ])
            try:
                parsed = json.loads(gen.content.strip().replace("```json", "").replace("```", ""))
                subject = subject or parsed.get("subject", "")
                body = body or parsed.get("body", "")
            except Exception:
                pass

        if not subject:
            subject = "Sin asunto"
        if not body:
            body = state["message"]

        result = gmail_draft(to=to, subject=subject, body=body, empresa_id=empresa_id, user_id=user_id)

        if "error" in result:
            return {"response": f"Error creando borrador: {result['error']}"}

        original_draft_text = f"Para: {to}\nAsunto: {subject}\n\n{body}"
        print(f"EMAIL AGENT: Draft created, draft_id={result.get('draft_id')}, needs_approval=True")

        return {
            "response": (
                f"✉️ **Borrador creado:**\n\n"
                f"📬 **Para:** {to}\n"
                f"📝 **Asunto:** {subject}\n\n"
                f"💬 **Cuerpo:**\n{body[:300]}\n\n"
                f"---\n¿Lo envío? Responde **sí** para confirmar o **no** para cancelar."
            ),
            "needs_approval": True,
            "draft_id": result["draft_id"],
            "original_draft": original_draft_text,
            "action_result": result,
        }

    elif action == "send":
        draft_id = params.get("draft_id", "") or state.get("draft_id", "")
        if not draft_id:
            return {"response": "No hay borrador para enviar. Primero crea uno."}

        result = gmail_send(draft_id, empresa_id=empresa_id, user_id=user_id)
        if "error" in result:
            return {"response": f"Error enviando: {result['error']}"}

        try:
            from api.services.audit_service import log_access
            log_access(empresa_id, user_id, "send_email", "email", detail={"draft_id": draft_id})
        except Exception:
            pass

        return {
            "response": "✅ Email enviado exitosamente.",
            "action_result": result,
        }

    else:
        return {"response": f"No entendí la acción '{action}'. Puedo buscar, leer, redactar o enviar emails."}


def _search_contacts(empresa_id: str, user_id: str, name: str) -> list:
    """Busca contactos por nombre en Google Contacts del usuario."""
    try:
        from api.services.tenant_credentials import get_google_credentials

        creds = get_google_credentials(empresa_id, "google_contacts", user_id=user_id)
        if not creds or "error" in creds:
            creds = get_google_credentials(empresa_id, "google_contacts")
            if not creds or "error" in creds:
                return []

        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        credentials = Credentials(
            token=creds.get("access_token"),
            refresh_token=creds.get("refresh_token"),
            token_uri="https://oauth2.googleapis.com/token",
            client_id=creds.get("client_id"),
            client_secret=creds.get("client_secret"),
        )

        service = build("people", "v1", credentials=credentials, cache_discovery=False)

        results = service.people().searchContacts(
            query=name,
            readMask="names,emailAddresses,organizations",
            pageSize=5,
        ).execute()

        contacts = []
        for person in results.get("results", []):
            p = person.get("person", {})
            names = p.get("names", [{}])
            emails = p.get("emailAddresses", [])
            orgs = p.get("organizations", [])

            if emails:
                contacts.append({
                    "name": names[0].get("displayName", name) if names else name,
                    "email": emails[0].get("value", ""),
                    "org": orgs[0].get("name", "") if orgs else "",
                })

        return contacts

    except Exception as e:
        print(f"EMAIL: Error buscando contactos: {e}")
        return []


# ─── Compilar grafo ──────────────────────────────────────
graph = StateGraph(EmailState)
graph.add_node("classify", classify_email_action)
graph.add_node("execute", execute_email_action)
graph.set_entry_point("classify")
graph.add_edge("classify", "execute")
graph.add_edge("execute", END)
email_agent = graph.compile()