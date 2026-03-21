"""
Notion Agent — Usa MCPHost para ejecutar tools de Notion.
LangGraph agent con tool calling via MCP.
"""

import json
from typing import TypedDict, Optional
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

    response: str
    model_used: str


NOTION_PROMPT = """Eres Ada, asistente ejecutiva. El usuario quiere algo sobre Notion.

TOOLS DISPONIBLES (MCP):
{tools}

Analiza el mensaje y elige la tool correcta.

Responde SOLO JSON:
{{"tool": "nombre_de_la_tool", "arguments": {{...}}}}
Sin markdown, sin explicación."""


async def select_notion_tool(state: NotionState) -> dict:
    """LLM selecciona qué tool MCP usar."""
    model, model_name = selector.get_model("routing")

    # Obtener tools disponibles del MCPHost
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
    }


async def execute_notion_tool(state: NotionState) -> dict:
    """Ejecuta la tool via MCPHost con credenciales de la empresa."""
    tool_name = state.get("tool_name", "")
    tool_args = state.get("tool_args", {})
    empresa_id = state.get("empresa_id", "")

    result = await mcp_host.call_tool_by_name(tool_name, tool_args, empresa_id)

    if isinstance(result, dict) and "error" in result:
        return {"response": f"⚠️ {result['error']}"}

    # Formatear respuesta según la tool
    if tool_name == "notion_search":
        if not result:
            return {"response": "No encontré nada en Notion."}
        formatted = "\n".join([
            f"📄 **{r.get('title', 'Sin título')}** ({r.get('type', '')}) — {r.get('last_edited', '')}\n   🔗 {r.get('url', '')}"
            for r in result
        ])
        return {"response": f"Encontré {len(result)} resultados en Notion:\n\n{formatted}"}

    elif tool_name == "notion_read_page":
        if isinstance(result, dict) and result.get("content"):
            return {"response": f"📄 **{result.get('title', '')}**\n🔗 {result.get('url', '')}\n\n{result['content'][:3000]}"}
        return {"response": "No pude leer el contenido de la página."}

    elif tool_name == "notion_create_page":
        if isinstance(result, dict) and result.get("status") == "created":
            return {"response": f"✅ Página creada en Notion:\n📄 **{result.get('title', '')}**\n🔗 {result.get('url', '')}"}
        return {"response": f"Error creando página: {json.dumps(result)}"}

    elif tool_name == "notion_query_database":
        if not result:
            return {"response": "Base de datos vacía."}
        formatted = "\n".join([
            " | ".join(f"{k}: {v}" for k, v in row.items() if k != "id")
            for row in result[:10]
        ])
        return {"response": f"📊 Base de datos ({len(result)} registros):\n\n{formatted}"}

    else:
        return {"response": json.dumps(result, ensure_ascii=False, default=str)[:2000]}


graph = StateGraph(NotionState)
graph.add_node("select_tool", select_notion_tool)
graph.add_node("execute_tool", execute_notion_tool)
graph.set_entry_point("select_tool")
graph.add_edge("select_tool", "execute_tool")
graph.add_edge("execute_tool", END)
notion_agent = graph.compile()