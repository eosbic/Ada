"""
Plane Agent — Usa MCPHost para ejecutar tools de Plane.so.
LangGraph agent con tool calling via MCP.
"""

import json
from typing import TypedDict, Optional
from langgraph.graph import StateGraph, END
from models.selector import selector
from ..mcp_servers.mcp_host import mcp_host

class PlaneState(TypedDict, total=False):
    message: str
    empresa_id: str
    user_id: str
    intent: str

    tool_name: str
    tool_args: dict

    response: str
    model_used: str


PLANE_PROMPT = """Eres Ada, asistente ejecutiva. El usuario quiere gestionar proyectos o tareas en Plane.so.

TOOLS DISPONIBLES (MCP):
{tools}

Analiza el mensaje y elige la tool correcta.
Prioridades: urgent, high, medium, low, none

FILTROS DE ESTADO para plane_list_issues:
- "tareas pendientes" → state_filter: "pending"
- "tareas completadas" / "ejecutadas" → state_filter: "done"
- "tareas en progreso" → state_filter: "in_progress"
- "tareas de Carlos" → assignee_filter: "Carlos"
- "tareas pendientes de Carlos" → state_filter: "pending", assignee_filter: "Carlos"
- Sin filtro → no incluir state_filter (muestra todas)

Si el usuario no especifica proyecto, usa project_id: "all".

Responde SOLO JSON:
{{"tool": "nombre_de_la_tool", "arguments": {{...}}}}
Sin markdown."""


async def select_plane_tool(state: PlaneState) -> dict:
    """LLM selecciona qué tool MCP usar."""
    model, model_name = selector.get_model("routing")

    tools = mcp_host.get_tools_for_intent("project")
    tools_desc = "\n".join([
        f"- {t['name']}: {t['description']} | args: {json.dumps(list(t['inputSchema'].get('properties', {}).keys()))}"
        for t in tools
    ])

    prompt = PLANE_PROMPT.format(tools=tools_desc)

    response = await model.ainvoke([
        {"role": "system", "content": prompt},
        {"role": "user", "content": state["message"]},
    ])

    try:
        raw = response.content.strip().replace("```json", "").replace("```", "")
        result = json.loads(raw)
        tool_name = result.get("tool", "plane_list_projects")
        tool_args = result.get("arguments", {})
    except Exception:
        tool_name = "plane_list_projects"
        tool_args = {}

    print(f"PLANE AGENT: tool={tool_name}, args={tool_args}")

    return {"tool_name": tool_name, "tool_args": tool_args, "model_used": model_name}


async def execute_plane_tool(state: PlaneState) -> dict:
    """Ejecuta la tool via MCPHost."""
    import re
    tool_name = state.get("tool_name", "")
    tool_args = state.get("tool_args", {})
    empresa_id = state.get("empresa_id", "")

    if isinstance(tool_args, list):
        tool_args = tool_args[0] if tool_args else {}
    if not isinstance(tool_args, dict):
        tool_args = {}

    # Validar si project_id es UUID real o es un nombre
    uuid_pattern = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.I)
    pid = tool_args.get("project_id", "")

    if tool_name in ("plane_list_issues", "plane_create_issue", "plane_update_issue") and (not pid or not uuid_pattern.match(pid)):
        project_name = tool_args.pop("project_id", "") or tool_args.pop("project_name", "")
        projects = await mcp_host.call_tool_by_name("plane_list_projects", {}, empresa_id)

        if isinstance(projects, list) and projects:
            project = None
            for p in projects:
                if project_name and project_name.lower() in p.get("name", "").lower():
                    project = p
                    break
            if not project:
                project = projects[0]
            tool_args["project_id"] = project["id"]
            print(f"PLANE AGENT: Resolvió '{project_name}' → {project['id']}")
        else:
            return {"response": "No encontré proyectos en Plane.so. Verifica la conexión."}

    result = await mcp_host.call_tool_by_name(tool_name, tool_args, empresa_id)

    if isinstance(result, dict) and "error" in result:
        return {"response": f"⚠️ {result['error']}"}

    if tool_name == "plane_list_projects":
        if not result:
            return {"response": "No hay proyectos."}
        formatted = "\n".join([
            f"📋 **{p.get('name', '')}** — {p.get('status', '')}\n   {p.get('description', '')[:100]}"
            for p in result
        ])
        return {"response": f"Tus proyectos ({len(result)}):\n\n{formatted}"}

    elif tool_name == "plane_list_issues":
        if not result:
            filter_msg = ""
            sf = tool_args.get("state_filter")
            af = tool_args.get("assignee_filter")
            if sf:
                filter_msg += f" con estado '{sf}'"
            if af:
                filter_msg += f" asignadas a '{af}'"
            return {"response": f"No hay tareas{filter_msg} en este proyecto."}

        emoji = {"urgent": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢", "none": "⚪"}
        state_emoji = {
            "backlog": "📋", "todo": "📋", "unstarted": "📋",
            "in progress": "🔄", "started": "🔄",
            "done": "✅", "completed": "✅", "cancelled": "❌",
        }

        # Agrupar por estado si no hay filtro
        sf = tool_args.get("state_filter")
        if not sf:
            groups = {}
            for i in result:
                state = i.get("state", "Sin estado")
                groups.setdefault(state, []).append(i)

            parts = []
            for state, issues in groups.items():
                se = state_emoji.get(state.lower(), "📌")
                parts.append(f"\n**{se} {state}** ({len(issues)})")
                for i in issues:
                    pe = emoji.get(i.get("priority", "none"), "⚪")
                    assignee = f" — {i['assignee']}" if i.get("assignee") else ""
                    due = f" | 📅 {i['due_date']}" if i.get("due_date") else ""
                    parts.append(f"  {pe} {i.get('name', '')}{assignee}{due}")

            return {"response": f"Tareas ({len(result)}):\n" + "\n".join(parts)}
        else:
            formatted = "\n".join([
                f"{emoji.get(i.get('priority', 'none'), '⚪')} **{i.get('name', '')}** — {i.get('state', '')}"
                f"{' — ' + i['assignee'] if i.get('assignee') else ''}"
                f"\n   📅 {i.get('due_date') or 'Sin fecha'}"
                for i in result
            ])
            return {"response": f"Tareas {sf} ({len(result)}):\n\n{formatted}"}

    elif tool_name == "plane_create_issue":
        if isinstance(result, dict) and result.get("status") == "created":
            return {"response": f"✅ Tarea creada: **{result.get('name', '')}**"}
        return {"response": f"Error creando tarea: {json.dumps(result)}"}

    elif tool_name == "plane_update_issue":
        if isinstance(result, dict) and result.get("status") == "updated":
            return {"response": "✅ Tarea actualizada."}
        return {"response": f"Error actualizando: {json.dumps(result)}"}

    else:
        return {"response": json.dumps(result, ensure_ascii=False, default=str)[:2000]}


graph = StateGraph(PlaneState)
graph.add_node("select_tool", select_plane_tool)
graph.add_node("execute_tool", execute_plane_tool)
graph.set_entry_point("select_tool")
graph.add_edge("select_tool", "execute_tool")
graph.add_edge("execute_tool", END)
plane_agent = graph.compile()