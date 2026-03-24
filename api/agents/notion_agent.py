"""
Notion Agent — Usa MCPHost para ejecutar tools de Notion.
LangGraph agent con tool calling via MCP.
Soporta encadenamiento: search → query_database para mostrar tareas reales.
"""

import json
from typing import TypedDict, Optional, List
from langgraph.graph import StateGraph, END
from models.selector import selector
from api.mcp_servers.mcp_host import mcp_host


class NotionState(TypedDict, total=False):
    message: str
    empresa_id: str
    user_id: str
    intent: str

    action: str
    tool_name: str
    tool_args: dict
    tool_result: object

    needs_chain: bool
    chain_tool_name: str
    chain_tool_args: dict

    response: str
    model_used: str


# Palabras que indican que el usuario quiere ver contenido, no solo titulos
CONTENT_KEYWORDS = [
    "tarea", "tareas", "items", "contenido", "registros", "filas",
    "muestra", "mostrar", "ver", "dame", "lista", "pendiente",
    "tablero", "board", "sprint", "backlog", "proyecto",
]

NOTION_PROMPT = """Eres Ada, asistente ejecutiva. El usuario quiere algo sobre Notion.

TOOLS DISPONIBLES (MCP):
{tools}

ESTRATEGIA:
- "tareas en notion" / "tablero de proyectos" → notion_search con query relevante
  (Ada encadenara automaticamente a query_database si encuentra una database)
- "lee la pagina de onboarding" → notion_read_page con page_id
- "crea una pagina con..." → notion_create_page
- "consulta la base de datos X" → notion_query_database con database_id

Si no tienes un ID especifico, usa notion_search primero.

Responde SOLO JSON:
{{"tool": "nombre_de_la_tool", "arguments": {{...}}}}
Sin markdown, sin explicacion."""


async def select_notion_tool(state: NotionState) -> dict:
    """LLM selecciona que tool MCP usar."""
    model, model_name = selector.get_model("routing")

    tools = mcp_host.get_tools_for_intent("notion")
    tools_desc = "\n".join([
        f"- {t['name']}: {t['description']} | args: {json.dumps(list(t['inputSchema'].get('properties', {}).keys()))}"
        for t in tools
    ])

    prompt = NOTION_PROMPT.format(tools=tools_desc)

    response = await model.ainvoke([
        {"role": "system", "content": prompt},
        {"role": "user", "content": state["message"]},
    ])

    try:
        raw = response.content.strip().replace("```json", "").replace("```", "")
        result = json.loads(raw)
        tool_name = result.get("tool", "notion_search")
        tool_args = result.get("arguments", {})
    except Exception:
        tool_name = "notion_search"
        tool_args = {"query": state["message"]}

    print(f"NOTION AGENT: tool={tool_name}, args={tool_args}")

    return {
        "tool_name": tool_name,
        "tool_args": tool_args,
        "model_used": model_name,
        "needs_chain": False,
    }


async def execute_notion_tool(state: NotionState) -> dict:
    """Ejecuta la tool via MCPHost con credenciales de la empresa."""
    tool_name = state.get("tool_name", "")
    tool_args = state.get("tool_args", {})
    empresa_id = state.get("empresa_id", "")

    result = await mcp_host.call_tool_by_name(tool_name, tool_args, empresa_id)

    try:
        from api.services.trail_service import leave_notion_trail
        if empresa_id and tool_name == "notion_search" and isinstance(result, list) and result:
            leave_notion_trail(empresa_id, result, search_query=tool_args.get("query", ""))
        elif empresa_id and tool_name == "notion_query_database" and isinstance(result, list) and result:
            leave_notion_trail(empresa_id, [{"title": str(r), "type": "database_row"} for r in result[:10]], search_query="database query")
    except Exception:
        pass

    if isinstance(result, dict) and "error" in result:
        return {"response": f"Error: {result['error']}", "tool_result": result}

    # Formatear respuesta segun la tool
    if tool_name == "notion_search":
        if not result:
            return {"response": "No encontre nada en Notion.", "tool_result": []}

        formatted = "\n".join([
            f"**{r.get('title', 'Sin titulo')}** ({r.get('type', '')}) — {r.get('last_edited', '')}"
            for r in result
        ])
        return {
            "response": f"Encontre {len(result)} resultados en Notion:\n\n{formatted}",
            "tool_result": result,
        }

    elif tool_name == "notion_read_page":
        if isinstance(result, dict) and result.get("content"):
            return {
                "response": f"**{result.get('title', '')}**\n{result.get('url', '')}\n\n{result['content'][:3000]}",
                "tool_result": result,
            }
        return {"response": "No pude leer el contenido de la pagina.", "tool_result": result}

    elif tool_name == "notion_create_page":
        if isinstance(result, dict) and result.get("status") == "created":
            return {
                "response": f"Pagina creada en Notion:\n**{result.get('title', '')}**\n{result.get('url', '')}",
                "tool_result": result,
            }
        return {"response": f"Error creando pagina: {json.dumps(result)}", "tool_result": result}

    elif tool_name == "notion_query_database":
        if not result:
            return {"response": "Base de datos vacia.", "tool_result": []}
        return {
            "response": _format_database_results(result),
            "tool_result": result,
        }

    else:
        return {
            "response": json.dumps(result, ensure_ascii=False, default=str)[:2000],
            "tool_result": result,
        }


def _format_database_results(results: list) -> str:
    """Formatea registros de database para mostrar al usuario."""
    if not results:
        return "Base de datos vacia."

    lines = []
    for row in results[:20]:
        # Buscar campos comunes
        name = ""
        state = ""
        assignee = ""
        date_val = ""
        checked = None

        for key, val in row.items():
            if key == "id":
                continue
            key_lower = key.lower()

            if not name and ("name" in key_lower or "nombre" in key_lower or "titulo" in key_lower or "title" in key_lower or "tarea" in key_lower):
                name = str(val) if val else ""
            elif "estado" in key_lower or "status" in key_lower or "state" in key_lower:
                state = str(val) if val else ""
            elif "asignado" in key_lower or "assignee" in key_lower or "responsable" in key_lower or "persona" in key_lower:
                assignee = str(val) if val else ""
            elif "fecha" in key_lower or "date" in key_lower or "due" in key_lower or "vencimiento" in key_lower:
                date_val = str(val) if val else ""
            elif isinstance(val, bool):
                checked = val

        if not name:
            # Tomar el primer campo no-id que tenga valor string
            for key, val in row.items():
                if key != "id" and val and isinstance(val, str):
                    name = val
                    break

        if not name:
            continue

        # Construir linea
        icon = "✅" if checked or (state and state.lower() in ("done", "completed", "completada")) else "⬜"
        parts = [f"{icon} **{name}**"]
        if state:
            parts.append(f"— {state}")
        if assignee:
            parts.append(f"— {assignee}")
        if date_val:
            parts.append(f"| {date_val}")

        lines.append(" ".join(parts))

    total = len(results)
    shown = min(total, 20)
    header = f"Registros ({shown}"
    if total > 20:
        header += f" de {total}"
    header += "):"

    return header + "\n\n" + "\n".join(lines)


async def maybe_chain_tool(state: NotionState) -> dict:
    """
    Evalua si debe encadenar una segunda llamada.
    Si search retorno databases y el usuario quiere ver contenido,
    encadena automaticamente a query_database.
    """
    tool_name = state.get("tool_name", "")
    tool_result = state.get("tool_result")
    message = (state.get("message", "") or "").lower()

    # Solo encadenar si fue un search
    if tool_name != "notion_search":
        return {"needs_chain": False}

    if not isinstance(tool_result, list) or not tool_result:
        return {"needs_chain": False}

    # Buscar databases en los resultados
    databases = [r for r in tool_result if r.get("type") == "database"]
    if not databases:
        return {"needs_chain": False}

    # Verificar si el usuario quiere ver contenido
    wants_content = any(kw in message for kw in CONTENT_KEYWORDS)
    if not wants_content:
        return {"needs_chain": False}

    # Encadenar: usar la primera database encontrada
    db = databases[0]
    print(f"NOTION AGENT: Encadenando search → query_database para '{db.get('title', '')}' ({db['id']})")

    return {
        "needs_chain": True,
        "tool_name": "notion_query_database",
        "tool_args": {"database_id": db["id"], "max_results": 20},
    }


def _should_chain(state: NotionState) -> str:
    """Decide si ejecutar otra tool o terminar."""
    if state.get("needs_chain"):
        return "execute_tool"
    return "end"


graph = StateGraph(NotionState)
graph.add_node("select_tool", select_notion_tool)
graph.add_node("execute_tool", execute_notion_tool)
graph.add_node("maybe_chain", maybe_chain_tool)
graph.set_entry_point("select_tool")
graph.add_edge("select_tool", "execute_tool")
graph.add_edge("execute_tool", "maybe_chain")
graph.add_conditional_edges("maybe_chain", _should_chain, {"execute_tool": "execute_tool", "end": END})
notion_agent = graph.compile()
