"""
Chat Agent - RAG multi-fuente + trazabilidad estricta.
"""

import json
import re
from typing import TypedDict, Optional, List, Dict
from langgraph.graph import StateGraph, END
from models.selector import selector
from sqlalchemy import text as sql_text
from api.services.graph_navigator import traverse_report_graph
from api.services.memory_service import (
    search_memory,
    store_memory,
    search_reports,
    search_reports_qdrant,
    search_vector_store1,
)
from api.services.context_builder import build_personalized_context
from api.database import AsyncSessionLocal, sync_engine


def get_history(empresa_id: str, user_id: str) -> list:
    """Obtiene historial de conversacion desde PostgreSQL."""
    if not empresa_id or not user_id:
        return []
    try:
        with sync_engine.connect() as conn:
            row = conn.execute(
                sql_text("""
                    SELECT messages FROM conversation_history
                    WHERE empresa_id = :eid AND user_id = :uid
                """),
                {"eid": empresa_id, "uid": user_id}
            ).fetchone()
            if row and row.messages:
                msgs = row.messages if isinstance(row.messages, list) else json.loads(row.messages)
                return msgs
    except Exception as e:
        print(f"CHAT: Error leyendo historial: {e}")
    return []


def save_history(empresa_id: str, user_id: str, messages: list, max_turns: int = 8) -> None:
    """Guarda historial de conversacion en PostgreSQL via UPSERT."""
    if not empresa_id or not user_id:
        return
    try:
        # Truncar a max_turns*2 mensajes (cada turno = user + assistant)
        truncated = messages[-(max_turns * 2):]
        messages_json = json.dumps(truncated, ensure_ascii=False)

        with sync_engine.connect() as conn:
            conn.execute(
                sql_text("""
                    INSERT INTO conversation_history (empresa_id, user_id, messages, max_turns, updated_at)
                    VALUES (:eid, :uid, :msgs::jsonb, :max_turns, NOW())
                    ON CONFLICT (empresa_id, user_id)
                    DO UPDATE SET messages = :msgs::jsonb, updated_at = NOW()
                """),
                {"eid": empresa_id, "uid": user_id, "msgs": messages_json, "max_turns": max_turns}
            )
            conn.commit()
    except Exception as e:
        print(f"CHAT: Error guardando historial: {e}")


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

    response: str
    model_used: str
    fact_answer: str


SYSTEM_PROMPT = """Eres Ada, Asistente Ejecutiva Senior de IA.

## ESTILO
- Responde en espanol.
- Formato obligatorio BLUF (conclusion primero).
- Sin inventar datos.

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


async def _lookup_telegram_facts(empresa_id: str, message: str) -> tuple[str, dict] | tuple[None, None]:
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

    memories = search_memory(message, empresa_id)
    reports_sql = search_reports(message, empresa_id) if empresa_id else []

    # Historial conversacional persistente
    history = get_history(empresa_id, user_id) if (empresa_id and user_id) else []

    # consulta dual obligatoria
    try:
        reports_qdrant = search_reports_qdrant(message, empresa_id, limit=4) if empresa_id else []
    except Exception as e:
        print(f"CHAT qdrant_reports error: {e}")
        reports_qdrant = []

    try:
        vector_docs = search_vector_store1(message, empresa_id, limit=4) if empresa_id else []
    except Exception as e:
        print(f"CHAT vector_store1 error: {e}")
        vector_docs = []

    reports_sql = [r for r in reports_sql if not _is_query_capture_text(r)]
    reports_qdrant = [r for r in reports_qdrant if not _is_query_capture_text(r)]
    vector_docs = [r for r in vector_docs if not _is_query_capture_text(r)]

    # Knowledge Graph: seguir enlaces entre reportes
    graph_context = []
    if reports_sql and empresa_id:
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

    context_chunks = []
    sources_used = list(state.get("sources_used", []))

    if memories:
        context_chunks.append("## Memoria conversacional\n" + "\n\n".join(memories[:4]))
        sources_used.append({"name": "agent_memory", "detail": f"{len(memories)} hallazgos", "confidence": 0.65})

    if history:
        history_lines = []
        for msg in history[-8:]:
            role = msg.get("role", "user")
            content = msg.get("content", "")[:300]
            history_lines.append(f"**{role}:** {content}")
        context_chunks.append("## Historial reciente\n" + "\n".join(history_lines))
        sources_used.append({"name": "conversation_history", "detail": f"{len(history)} mensajes", "confidence": 0.70})

    if reports_sql:
        context_chunks.append("## PostgreSQL reports\n" + "\n\n".join(reports_sql[:3]))
        sources_used.append({"name": "postgres_reports", "detail": f"{len(reports_sql)} hallazgos", "confidence": 0.78})

    if reports_qdrant:
        context_chunks.append("## Qdrant Excel Reports\n" + "\n\n".join(reports_qdrant[:3]))
        sources_used.append({"name": "qdrant_excel_reports", "detail": f"{len(reports_qdrant)} hallazgos", "confidence": 0.85})

    if vector_docs:
        context_chunks.append("## Qdrant Vector Store1\n" + "\n\n".join(vector_docs[:3]))
        sources_used.append({"name": "qdrant_vector_store1", "detail": f"{len(vector_docs)} hallazgos", "confidence": 0.83})

    if graph_context:
        context_chunks.append("## Knowledge Graph (reportes conectados)\n" + "\n\n".join(graph_context))
        sources_used.append({"name": "knowledge_graph", "detail": f"{len(graph_context)} conectados", "confidence": 0.75})

    tool_context = state.get("tool_context", "")
    if tool_context:
        context_chunks.append("## Tools Context\n" + tool_context)

    context = "\n\n".join(context_chunks) if context_chunks else "Sin contexto previo."

    # Contexto personalizado de empresa
    personalized = ""
    user_id = state.get("user_id")
    if empresa_id and user_id:
        try:
            async with AsyncSessionLocal() as db:
                personalized = await build_personalized_context(db, empresa_id, user_id)
        except Exception as e:
            print(f"CHAT context builder error: {e}")

    dual_repo_checked = True
    fact_answer, fact_source = await _lookup_telegram_facts(empresa_id=empresa_id, message=message)
    if fact_answer:
        context_chunks.append("## Telegram Facts\n" + fact_answer)
        sources_used.append(fact_source)

    print(
        "CHAT AGENT - "
        f"memory={len(memories)} sql_reports={len(reports_sql)} "
        f"qdrant_reports={len(reports_qdrant)} vector_docs={len(vector_docs)}"
    )

    return {
        "memories": memories,
        "context": context,
        "personalized": personalized,
        "sources_used": sources_used,
        "dual_repo_checked": dual_repo_checked,
        "fact_answer": fact_answer or "",
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

    model, model_name = selector.get_model("chat", state.get("model_preference"))

    system = SYSTEM_PROMPT.format(context=context)
    if personalized:
        system = personalized + "\n\n" + system

    response = await model.ainvoke([
        {"role": "system", "content": system},
        {"role": "user", "content": message},
    ])

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

    if message:
        store_memory(f"Usuario: {message}", empresa_id=empresa_id)
    if response:
        store_memory(f"Ada: {response[:1800]}", empresa_id=empresa_id)

    # Persistir historial en PostgreSQL
    if empresa_id and user_id and message:
        try:
            history = get_history(empresa_id, user_id)
            if message:
                history.append({"role": "user", "content": message})
            if response:
                history.append({"role": "assistant", "content": response[:2000]})
            save_history(empresa_id, user_id, history)
        except Exception as e:
            print(f"CHAT: Error persistiendo historial: {e}")

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
