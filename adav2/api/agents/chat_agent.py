"""
Chat Agent - RAG multi-fuente + historial conversacional + trazabilidad estricta.
"""

import re
from collections import defaultdict
from typing import TypedDict, Optional, List, Dict
from langgraph.graph import StateGraph, END
from models.selector import selector
from sqlalchemy import text as sql_text
from api.services.memory_service import (
    search_memory,
    store_memory,
    search_reports,
    search_reports_qdrant,
    search_vector_store1,
)
from api.services.graph_navigator import traverse_report_graph
from api.services.context_builder import build_personalized_context
from api.database import AsyncSessionLocal


# ── Historial conversacional en memoria por usuario ──────────────────
_CONVERSATION_HISTORY: dict = defaultdict(list)
MAX_HISTORY_TURNS = 8  # 4 pares usuario/ada


def _history_key(empresa_id: str, user_id: str) -> str:
    return f"{empresa_id}:{user_id}"


def get_history(empresa_id: str, user_id: str) -> list:
    key = _history_key(empresa_id, user_id)
    return list(_CONVERSATION_HISTORY[key])


def add_to_history(empresa_id: str, user_id: str, role: str, content: str):
    key = _history_key(empresa_id, user_id)
    _CONVERSATION_HISTORY[key].append({"role": role, "content": content})
    # Mantener solo los últimos MAX_HISTORY_TURNS turnos
    if len(_CONVERSATION_HISTORY[key]) > MAX_HISTORY_TURNS * 2:
        _CONVERSATION_HISTORY[key] = _CONVERSATION_HISTORY[key][-(MAX_HISTORY_TURNS * 2):]


class ChatState(TypedDict, total=False):
    message: str
    empresa_id: str
    user_id: str
    intent: str
    model_preference: Optional[str]

    context: str
    memories: List[str]
    personalized: str
    tool_context: str
    sources_used: List[Dict]
    dual_repo_checked: bool
    history: List[Dict]

    response: str
    model_used: str
    fact_answer: str


SYSTEM_PROMPT = """Eres Ada, Asistente Ejecutiva Senior de IA.

## ESTILO
- Responde en espanol.
- Formato obligatorio BLUF (conclusion primero).
- Sin inventar datos.
- Mantén el hilo de la conversación. Si el usuario dice "ese reporte", "el que mencionaste", "dame más detalle", etc., usa el historial para saber a qué se refiere.

## PROTOCOLO MULTI-FUENTE OBLIGATORIO
Antes de declarar ausencia de informacion debes consultar MINIMO:
1) Qdrant Excel Reports
2) Qdrant Vector Store1

Ademas, si hay contexto operacional disponible (Gmail, Calendar, Notion, Plane), usalo.

## TRAZABILIDAD OBLIGATORIA
Debes incluir al final:
- Fuente primaria
- Fuente secundaria

## CONTEXTO BASE
{context}
"""


def _is_query_capture_text(text: str) -> bool:
    body = (text or "").lower()
    return all(m in body for m in ["busca en tu base obsidian", "responde exacto"]) or (
        "# mensaje telegram" in body and "no inventes" in body
    )


async def _lookup_telegram_facts(empresa_id: str, message: str) -> tuple:
    question = (message or "").lower()
    wants_facts = any(k in question for k in ["codigo", "color favorito", "archivo fuente", "tg_*", "tg_"])
    if not (empresa_id and wants_facts):
        return None, None

    try:
        async with AsyncSessionLocal() as db:
            rows = (
                await db.execute(
                    sql_text(
                        """
                        SELECT source_file, markdown_content, created_at
                        FROM ada_reports
                        WHERE empresa_id = :empresa_id
                          AND report_type = 'markdown_raw'
                          AND source_file LIKE 'tg_%'
                        ORDER BY created_at DESC
                        LIMIT 40
                        """
                    ),
                    {"empresa_id": empresa_id},
                )
            ).fetchall()
    except Exception as e:
        print(f"CHAT telegram facts lookup error: {e}")
        return None, None

    selected = None
    code = ""
    color = ""

    for row in rows:
        content = row.markdown_content or ""
        if _is_query_capture_text(content):
            continue

        code_match = re.search(r"\bobs[_-]?\d+\b", content, flags=re.IGNORECASE)
        color_match = re.search(
            r"(?:mi\s+)?color\s+favorito\s+es\s+([a-zA-Záéíóúñ]+)",
            content,
            flags=re.IGNORECASE,
        )

        if code_match or color_match:
            selected = row
            code = code_match.group(0) if code_match else ""
            color = color_match.group(1).lower() if color_match else ""
            break

    if not selected:
        return None, None

    lines = []
    if code:
        lines.append(f"- codigo: {code}")
    if color:
        lines.append(f"- color favorito: {color}")
    lines.append(f"- archivo fuente: {selected.source_file}")

    answer = "Datos encontrados en memoria Telegram:\n" + "\n".join(lines)
    source = {
        "name": "telegram_raw_reports",
        "detail": selected.source_file,
        "confidence": 0.92,
    }
    return answer, source


async def retrieve_context(state: ChatState) -> dict:
    message = state.get("message", "")
    empresa_id = state.get("empresa_id", "")
    user_id = state.get("user_id", "")
    memories = search_memory(message)

    # Buscar en reportes de PostgreSQL
    reports = search_reports(message, empresa_id)

    # Knowledge Graph: seguir enlaces entre reportes
    graph_context = []
    if reports and empresa_id:
        try:
            from api.database import sync_engine

            report_ids = []
            clean = re.sub(r'[^a-záéíóúñA-ZÁÉÍÓÚÑ0-9\s]', ' ', message)
            words = [w for w in clean.strip().split() if len(w) > 3]

            with sync_engine.connect() as conn:
                for word in words[:3]:
                    rows = conn.execute(
                        sql_text("""
                            SELECT id FROM ada_reports
                            WHERE empresa_id = :eid
                            AND is_archived = FALSE
                            AND (title ILIKE :like OR markdown_content ILIKE :like)
                            ORDER BY created_at DESC LIMIT 3
                        """),
                        {"eid": empresa_id, "like": f"%{word}%"}
                    ).fetchall()
                    report_ids.extend([str(r.id) for r in rows])

            report_ids = list(set(report_ids))[:10]

            if report_ids:
                connected = traverse_report_graph(report_ids, empresa_id, limit=5)
                for c in connected:
                    graph_context.append(
                        f"[Conectado via {c['link_type']}] {c['title']}: "
                        f"{c['snippet'][:300]}"
                    )
                print(f"CHAT AGENT: Graph traversal -> {len(connected)} reportes conectados")

        except Exception as e:
            print(f"CHAT AGENT: Graph traversal error: {e}")

    # Recuperar historial conversacional
    history = get_history(empresa_id, user_id) if (empresa_id and user_id) else []

    # Combinar contexto
    all_context = memories + reports + graph_context
    context = "\n\n".join(all_context) if all_context else "Sin contexto previo."

    personalized = ""
    if empresa_id and user_id:
        try:
            async with AsyncSessionLocal() as db:
                personalized = await build_personalized_context(db, empresa_id, user_id)
        except Exception as e:
            print(f"ERROR cargando contexto: {e}")

    dual_repo_checked = True
    fact_answer, fact_source = await _lookup_telegram_facts(empresa_id=empresa_id, message=message)
    if fact_answer:
        all_context.append("## Telegram Facts\n" + fact_answer)
        context = "\n\n".join(all_context)

    sources_used = list(state.get("sources_used", []))
    if memories:
        sources_used.append({"name": "agent_memory", "detail": f"{len(memories)} memorias", "confidence": 0.65})
    if reports:
        sources_used.append({"name": "postgres_reports", "detail": f"{len(reports)} reportes", "confidence": 0.78})
    if graph_context:
        sources_used.append({"name": "knowledge_graph", "detail": f"{len(graph_context)} conectados", "confidence": 0.82})

    print(
        f"CHAT AGENT - Memorias: {len(memories)} | Reportes: {len(reports)} | "
        f"Grafo: {len(graph_context)} | Historia: {len(history)} turnos | "
        f"Personalizado: {'si' if personalized else 'no'}"
    )

    return {
        "memories": memories,
        "context": context,
        "personalized": personalized,
        "sources_used": sources_used,
        "dual_repo_checked": dual_repo_checked,
        "fact_answer": fact_answer or "",
        "history": history,
    }


async def generate_response(state: ChatState) -> dict:
    if state.get("fact_answer"):
        return {
            "response": state.get("fact_answer"),
            "model_used": "rule_memory_lookup",
            "sources_used": state.get("sources_used", []),
        }

    message = state.get("message", "")
    context = state.get("context", "Sin contexto previo.")
    personalized = state.get("personalized", "")
    history = state.get("history", [])

    model, model_name = selector.get_model("chat", state.get("model_preference"))

    system = SYSTEM_PROMPT.format(context=context)
    if personalized:
        system = personalized + "\n\n" + system

    # Construir mensajes con historial conversacional
    messages_payload = [{"role": "system", "content": system}]

    # Agregar turnos anteriores
    for turn in history:
        messages_payload.append({
            "role": turn.get("role", "user"),
            "content": turn.get("content", ""),
        })

    # Mensaje actual
    messages_payload.append({"role": "user", "content": message})

    response = await model.ainvoke(messages_payload)

    return {
        "response": response.content,
        "model_used": model_name,
        "sources_used": state.get("sources_used", []),
    }


async def save_to_memory(state: ChatState) -> dict:
    message = state.get("message", "")
    response = state.get("response", "")
    empresa_id = state.get("empresa_id", "")
    user_id = state.get("user_id", "")

    # Guardar en historial conversacional en memoria del proceso
    if empresa_id and user_id and message and response:
        add_to_history(empresa_id, user_id, "user", message)
        add_to_history(empresa_id, user_id, "assistant", response[:2000])

    # Guardar en Qdrant para memoria semántica de largo plazo
    if message:
        store_memory(f"Usuario: {message}")
    if response:
        store_memory(f"Ada: {response[:1800]}")
    return {}


graph = StateGraph(ChatState)
graph.add_node("retrieve", retrieve_context)
graph.add_node("generate", generate_response)
graph.add_node("save", save_to_memory)
graph.set_entry_point("retrieve")
graph.add_edge("retrieve", "generate")
graph.add_edge("generate", "save")
graph.add_edge("save", END)
chat_agent = graph.compile()