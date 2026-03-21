"""
Email Agent — Busca, lee, redacta y envía emails via Gmail.

Flujo:
1. Interpreta intención del usuario en lenguaje natural
2. Ejecuta acción Gmail (search/read/draft/send)
3. Para ENVÍO: requiere aprobación del usuario
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

    action: str
    action_params: dict
    action_result: dict
    needs_approval: bool
    draft_id: str

    response: str
    model_used: str


EMAIL_SYSTEM_PROMPT = """Eres Ada, asistente ejecutiva experta en gestión de correo electrónico.

Tu trabajo es INTERPRETAR el lenguaje natural del usuario y convertirlo en la búsqueda Gmail más inteligente posible.

## INTERPRETACIÓN DE LENGUAJE NATURAL:

Cuando el usuario describe el CONTENIDO o TEMA del email (no el remitente exacto), usa búsqueda por palabras clave en el asunto y cuerpo:
- "donde me felicitan" → query: "felicitaciones OR felicidades OR congratulations OR felicitate"
- "donde me dan la bienvenida" → query: "bienvenida OR welcome OR bienvenido"
- "donde me ofrecen algo" → query: "oferta OR propuesta OR oportunidad"
- "donde me piden algo" → query: "solicitud OR pedido OR por favor OR necesito"
- "donde hablan de una reunion" → query: "reunion OR meeting OR cita OR llamada"
- "donde me mandan una factura" → query: "factura OR invoice OR cobro OR pago"
- "donde me confirman algo" → query: "confirmacion OR confirmado OR confirmed"
- "donde contabo me felicita" → query: "from:contabo felicitaciones OR from:contabo congratulations OR from:contabo welcome"
- "correos de soporte" → query: "support OR soporte OR ayuda OR help"
- "donde me avisan de algo importante" → query: "is:important OR urgente OR importante OR alerta"

## REGLAS DE CANTIDAD:
- "el último" o "el más reciente" → max_results: 1
- "los últimos" o "recientes" → max_results: 3
- "busca" o "dame" sin cantidad → max_results: 5
- "todos" → max_results: 10
- Si especifica cantidad exacta → usar esa cantidad

## QUERIES DE GMAIL DISPONIBLES:
- De alguien: "from:nombre" o "from:email@dominio.com"
- Para alguien: "to:nombre"
- Por asunto: "subject:texto"
- No leídos: "is:unread"
- Con adjunto: "has:attachment"
- Importantes: "is:important"
- Fecha: "newer_than:1d" (hoy), "newer_than:7d" (semana), "newer_than:30d" (mes)
- Texto libre en cuerpo/asunto: escribir las palabras directamente
- Combinados con OR: "palabra1 OR palabra2"
- Combinados con AND implícito: "from:carlos reunion" (de carlos Y sobre reunion)

## ACCIONES DISPONIBLES:
- search: buscar emails
- read: leer un email específico
- draft: crear borrador (necesita to, subject, body)
- send: enviar borrador existente (necesita draft_id)

## EJEMPLOS COMPLETOS:
- "busca el último correo" → {"action": "search", "params": {"query": "newer_than:1d", "max_results": 1}}
- "correos de hoy" → {"action": "search", "params": {"query": "newer_than:1d", "max_results": 5}}
- "emails de Carlos" → {"action": "search", "params": {"query": "from:carlos", "max_results": 5}}
- "correos no leídos" → {"action": "search", "params": {"query": "is:unread", "max_results": 5}}
- "donde me felicitan" → {"action": "search", "params": {"query": "felicitaciones OR felicidades OR congratulations OR bienvenida", "max_results": 5}}
- "donde contabo me felicita" → {"action": "search", "params": {"query": "from:contabo felicitaciones OR from:contabo congratulations OR from:contabo welcome", "max_results": 5}}
- "donde me dan la bienvenida" → {"action": "search", "params": {"query": "bienvenida OR welcome OR bienvenido", "max_results": 5}}
- "correos sobre facturas" → {"action": "search", "params": {"query": "factura OR invoice OR cobro", "max_results": 5}}
- "emails importantes de esta semana" → {"action": "search", "params": {"query": "is:important newer_than:7d", "max_results": 5}}
- "escribe email a juan@x.com sobre la reunión" → {"action": "draft", "params": {"to": "juan@x.com", "subject": "Reunión", "body": "..."}}
- "envíalo" → {"action": "send", "params": {"draft_id": ""}}

IMPORTANTE: Cuando el usuario describe una SITUACION o SENTIMIENTO (felicitar, dar bienvenida, avisar, pedir, confirmar), 
convierte eso en palabras clave relevantes en español E inglés porque Gmail puede tener emails en ambos idiomas.

Responde SOLO JSON válido, sin markdown, sin explicación:
{"action": "...", "params": {...}}"""


async def classify_email_action(state: EmailState) -> dict:
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
    action = state.get("action", "")
    params = state.get("action_params", {})
    empresa_id = state.get("empresa_id", "")

    if action == "search":
        query = params.get("query", "")
        max_results = params.get("max_results", 5)
        results = gmail_search(query, max_results=max_results, empresa_id=empresa_id)

        if results:
            formatted = "\n".join([
                f"📧 **{e['subject']}** — de {e['from']} ({e['date'][:16]})\n   {e['snippet'][:120]}"
                for e in results
            ])
            return {
                "response": f"Encontré {len(results)} emails:\n\n{formatted}",
                "action_result": {"emails": results},
                "sources_used": [{"name": "gmail", "detail": f"query: {query}", "confidence": 0.9}],
            }
        else:
            # Fallback: intentar con query más simple si no encontró nada
            simple_query = query.split(" OR ")[0].split(" AND ")[0].strip()
            if simple_query != query:
                results_fallback = gmail_search(simple_query, max_results=max_results, empresa_id=empresa_id)
                if results_fallback:
                    formatted = "\n".join([
                        f"📧 **{e['subject']}** — de {e['from']} ({e['date'][:16]})\n   {e['snippet'][:120]}"
                        for e in results_fallback
                    ])
                    return {
                        "response": f"No encontré con la búsqueda exacta, pero encontré {len(results_fallback)} emails relacionados:\n\n{formatted}",
                        "action_result": {"emails": results_fallback},
                        "sources_used": [{"name": "gmail", "detail": f"fallback query: {simple_query}", "confidence": 0.75}],
                    }
            return {
                "response": f"No encontré emails con ese criterio. Intenta con otras palabras clave.",
                "sources_used": [{"name": "gmail", "detail": f"query: {query} - sin resultados", "confidence": 0.9}],
            }

    elif action == "read":
        message_id = params.get("message_id", "")
        if not message_id:
            query = params.get("query", state["message"])
            results = gmail_search(query, max_results=1, empresa_id=empresa_id)
            if results:
                message_id = results[0]["id"]
            else:
                return {
                    "response": "No encontré el email para leer.",
                    "sources_used": [{"name": "gmail", "detail": "read - not found", "confidence": 0.9}],
                }

        email = gmail_read(message_id, empresa_id=empresa_id)
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
            "sources_used": [{"name": "gmail", "detail": "read email", "confidence": 0.95}],
        }

    elif action == "draft":
        to = params.get("to", "")
        subject = params.get("subject", "")
        body = params.get("body", "")

        if not to:
            return {"response": "Necesito la dirección de email del destinatario. ¿A quién le envío?"}

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

        result = gmail_draft(to=to, subject=subject, body=body, empresa_id=empresa_id)

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
            "sources_used": [{"name": "gmail", "detail": "draft created", "confidence": 0.95}],
        }

    elif action == "send":
        draft_id = params.get("draft_id", "") or state.get("draft_id", "")
        if not draft_id:
            return {"response": "No hay borrador para enviar. Primero crea uno."}

        result = gmail_send(draft_id, empresa_id=empresa_id)
        if "error" in result:
            return {"response": f"Error enviando: {result['error']}"}

        return {
            "response": "✅ Email enviado exitosamente.",
            "action_result": result,
            "sources_used": [{"name": "gmail", "detail": "email sent", "confidence": 0.95}],
        }

    else:
        return {"response": f"No entendí la acción '{action}'. Puedo buscar, leer, redactar o enviar emails."}


graph = StateGraph(EmailState)
graph.add_node("classify", classify_email_action)
graph.add_node("execute", execute_email_action)
graph.set_entry_point("classify")
graph.add_edge("classify", "execute")
graph.add_edge("execute", END)
email_agent = graph.compile()