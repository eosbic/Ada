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

## EJEMPLOS:
- "busca el último correo" → {"action": "search", "params": {"query": "newer_than:1d", "max_results": 1}}
- "correos de hoy" → {"action": "search", "params": {"query": "newer_than:1d", "max_results": 3}}
- "emails de Carlos" → {"action": "search", "params": {"query": "from:carlos", "max_results": 5}}
- "correos no leídos" → {"action": "search", "params": {"query": "is:unread", "max_results": 5}}
- "lee el correo de María" → {"action": "search", "params": {"query": "from:maria", "max_results": 1}}
- "dame los 2 últimos correos" → {"action": "search", "params": {"query": "newer_than:1d", "max_results": 2}}
- "escribe email a juan@x.com sobre la reunión" → {"action": "draft", "params": {"to": "juan@x.com", "subject": "Reunión", "body": "..."}}
- "envíalo" → {"action": "send", "params": {"draft_id": ""}}

Responde SOLO JSON válido, sin markdown, sin explicación:
{"action": "...", "params": {...}}"""


async def classify_email_action(state: EmailState) -> dict:
    """Clasifica qué acción de email quiere el usuario."""
    model, model_name = selector.get_model("chat_with_tools")

    response = await model.ainvoke([
        {"role": "system", "content": EMAIL_SYSTEM_PROMPT},
        {"role": "user", "content": state["message"]},
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

    elif action == "draft":
        to = params.get("to", "")
        subject = params.get("subject", "")
        body = params.get("body", "")

        if not to:
            return {"response": "Necesito la dirección de email del destinatario. ¿A quién le envío?"}

        # Si no hay subject o body, generar con LLM
        if not subject or not body:
            model, _ = selector.get_model("email_draft")
            gen = await model.ainvoke([
                {"role": "system", "content": "Genera un email profesional en español. Responde JSON: {\"subject\": \"...\", \"body\": \"...\"}"},
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

        return {
            "response": (
                f"✉️ Borrador creado:\n\n"
                f"**Para:** {to}\n"
                f"**Asunto:** {subject}\n"
                f"**Cuerpo:** {body[:200]}...\n\n"
                f"¿Lo envío? Responde 'sí' para confirmar."
            ),
            "needs_approval": True,
            "draft_id": result["draft_id"],
            "action_result": result,
        }

    elif action == "send":
        draft_id = params.get("draft_id", "") or state.get("draft_id", "")
        if not draft_id:
            return {"response": "No hay borrador para enviar. Primero crea uno."}

        result = gmail_send(draft_id, empresa_id=empresa_id, user_id=user_id)
        if "error" in result:
            return {"response": f"Error enviando: {result['error']}"}

        return {
            "response": "✅ Email enviado exitosamente.",
            "action_result": result,
        }

    else:
        return {"response": f"No entendí la acción '{action}'. Puedo buscar, leer, redactar o enviar emails."}


# ─── Compilar grafo ──────────────────────────────────────
graph = StateGraph(EmailState)
graph.add_node("classify", classify_email_action)
graph.add_node("execute", execute_email_action)
graph.set_entry_point("classify")
graph.add_edge("classify", "execute")
graph.add_edge("execute", END)
email_agent = graph.compile()