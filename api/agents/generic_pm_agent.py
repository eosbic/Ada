"""
Generic PM Agent — Agente PM agnóstico via tools estándar.
No sabe qué tool usa la empresa. Usa las 4 tools de mcp_pm_base.
Soporta encadenamiento: pm_list_projects → pm_list_tasks automático.
"""

import json
from typing import TypedDict, Optional, List
from langgraph.graph import StateGraph, END
from models.selector import selector
from api.mcp_servers.mcp_host import mcp_host


class GenericPMState(TypedDict, total=False):
    message: str
    empresa_id: str
    user_id: str
    intent: str

    pm_provider: str
    tool_name: str
    tool_args: dict
    tool_result: object

    response: str
    model_used: str
    sources_used: list


# Palabras que sugieren que el usuario quiere ver tareas, no solo proyectos
TASK_KEYWORDS = [
    "tarea", "tareas", "task", "tasks", "pendiente", "pendientes",
    "sprint", "backlog", "issue", "issues",
]

PM_PROMPT = """Eres Ada, asistente ejecutiva. El usuario quiere gestionar proyectos o tareas.
La empresa usa {pm_provider} como herramienta de proyectos.

TOOLS DISPONIBLES:
- pm_list_projects (sin argumentos)
- pm_list_tasks (project_id requerido, filtros opcionales: state_filter con valores pending/in_progress/done, assignee_filter con nombre de persona, max_results default 20)
- pm_create_task (project_id y name requeridos, opcionales: description, priority urgent/high/medium/low/none, due_date ISO, assignee)
- pm_update_task (project_id y task_id requeridos, opcionales: name, state, priority, due_date, assignee)

Si el usuario no especifica proyecto, primero usa pm_list_projects para encontrarlo.
Responde SOLO JSON: {{"tool": "nombre", "arguments": {{...}}}}"""

# Emojis de prioridad
_PRIORITY_EMOJI = {
    "urgent": "\U0001f534",  # rojo
    "high": "\U0001f7e0",    # naranja
    "medium": "\U0001f7e1",  # amarillo
    "low": "\U0001f7e2",     # verde
    "none": "\u26aa",        # blanco
}

# Emojis de estado
_STATE_EMOJI = {
    "done": "\u2705",        # check
    "in_progress": "\U0001f504",  # refresh
    "pending": "\u2b1c",     # cuadrado
}


async def discover_pm_provider(state: GenericPMState) -> dict:
    """Descubre qué PM genérico tiene conectado la empresa."""
    empresa_id = state.get("empresa_id", "")
    provider = mcp_host.get_empresa_pm_provider(empresa_id)

    if not provider:
        return {
            "pm_provider": "",
            "response": (
                "No tienes herramienta de gestion de proyectos conectada. "
                "Conecta Asana, Monday, Trello, ClickUp o Jira desde configuracion."
            ),
        }

    print(f"GENERIC PM: empresa={empresa_id} usa provider={provider}")
    return {"pm_provider": provider}


async def select_tool(state: GenericPMState) -> dict:
    """LLM selecciona qué tool PM usar."""
    model, model_name = selector.get_model("routing")
    pm_provider = state.get("pm_provider", "desconocido")
    prompt = PM_PROMPT.format(pm_provider=pm_provider)

    response = await model.ainvoke([
        {"role": "system", "content": prompt},
        {"role": "user", "content": state["message"]},
    ])

    try:
        raw = response.content.strip().replace("```json", "").replace("```", "")
        result = json.loads(raw)
        tool_name = result.get("tool", "pm_list_projects")
        tool_args = result.get("arguments", {})
    except Exception:
        tool_name = "pm_list_projects"
        tool_args = {}

    print(f"GENERIC PM: tool={tool_name}, args={tool_args}")
    return {"tool_name": tool_name, "tool_args": tool_args, "model_used": model_name}


async def execute_tool(state: GenericPMState) -> dict:
    """Ejecuta tool PM vía mcp_host.call_generic_pm_tool."""
    tool_name = state.get("tool_name", "")
    tool_args = state.get("tool_args", {})
    empresa_id = state.get("empresa_id", "")
    pm_provider = state.get("pm_provider", "")

    result = await mcp_host.call_generic_pm_tool(tool_name, tool_args, empresa_id)

    if isinstance(result, dict) and "error" in result:
        return {"response": f"Error: {result['error']}", "tool_result": result}

    # Formatear según tool
    if tool_name == "pm_list_projects" and isinstance(result, list):
        if not result:
            return {"response": "No encontre proyectos.", "tool_result": []}
        lines = []
        for p in result:
            status = f" ({p['status']})" if p.get("status") else ""
            lines.append(f"\U0001f4c1 **{p.get('name', '')}**{status}")
        formatted = f"Proyectos ({len(result)}):\n\n" + "\n".join(lines)
        return {
            "response": formatted,
            "tool_result": result,
            "sources_used": [{"name": pm_provider, "detail": tool_name, "confidence": 0.82}],
        }

    elif tool_name == "pm_list_tasks" and isinstance(result, list):
        if not result:
            return {"response": "No hay tareas.", "tool_result": []}
        return {
            "response": _format_tasks(result, state.get("tool_args", {}).get("state_filter")),
            "tool_result": result,
            "sources_used": [{"name": pm_provider, "detail": tool_name, "confidence": 0.82}],
        }

    elif tool_name == "pm_create_task" and isinstance(result, dict):
        if result.get("status") == "created":
            url_part = f"\n{result['url']}" if result.get("url") else ""
            return {
                "response": f"\u2705 Tarea creada: **{result.get('name', '')}**{url_part}",
                "tool_result": result,
                "sources_used": [{"name": pm_provider, "detail": tool_name, "confidence": 0.82}],
            }
        return {"response": json.dumps(result, ensure_ascii=False)[:2000], "tool_result": result}

    elif tool_name == "pm_update_task" and isinstance(result, dict):
        if result.get("status") == "updated":
            return {
                "response": f"\u2705 Tarea actualizada: {result.get('id', '')}",
                "tool_result": result,
                "sources_used": [{"name": pm_provider, "detail": tool_name, "confidence": 0.82}],
            }
        return {"response": json.dumps(result, ensure_ascii=False)[:2000], "tool_result": result}

    else:
        return {
            "response": json.dumps(result, ensure_ascii=False, default=str)[:2000],
            "tool_result": result,
            "sources_used": [{"name": pm_provider, "detail": tool_name, "confidence": 0.82}],
        }


def _format_tasks(tasks: list, state_filter: str = None) -> str:
    """Formatea tareas con emojis de prioridad y estado."""
    if state_filter:
        # Sin agrupar, ya están filtradas
        lines = []
        for t in tasks:
            lines.append(_format_task_line(t))
        header = f"Tareas ({len(tasks)}):"
        return header + "\n\n" + "\n".join(lines)

    # Agrupar por estado
    groups = {"in_progress": [], "pending": [], "done": []}
    for t in tasks:
        s = t.get("state", "pending")
        if s in groups:
            groups[s].append(t)
        else:
            groups.setdefault("pending", []).append(t)

    lines = []
    group_labels = {
        "in_progress": "\U0001f504 En progreso",
        "pending": "\u2b1c Pendientes",
        "done": "\u2705 Completadas",
    }
    for state_key in ("in_progress", "pending", "done"):
        group = groups.get(state_key, [])
        if group:
            lines.append(f"\n**{group_labels[state_key]}** ({len(group)}):")
            for t in group:
                lines.append(_format_task_line(t))

    return f"Tareas ({len(tasks)}):" + "\n".join(lines)


def _format_task_line(task: dict) -> str:
    """Formatea una línea de tarea con emojis."""
    priority = task.get("priority", "medium")
    state = task.get("state", "pending")
    p_emoji = _PRIORITY_EMOJI.get(priority, "\u26aa")
    s_emoji = _STATE_EMOJI.get(state, "\u2b1c")

    parts = [f"{s_emoji}{p_emoji} **{task.get('name', '')}**"]
    if task.get("assignee"):
        parts.append(f"— {task['assignee']}")
    if task.get("due_date"):
        parts.append(f"| {task['due_date']}")
    return " ".join(parts)


# ─── Condicional: resolver proyecto automáticamente ──────────

def _needs_resolve(state: GenericPMState) -> str:
    """Si list_projects y el usuario quiere tareas, encadenar a pm_list_tasks."""
    tool_name = state.get("tool_name", "")
    tool_result = state.get("tool_result")
    message = (state.get("message", "") or "").lower()

    if tool_name != "pm_list_projects":
        return "end"
    if not isinstance(tool_result, list) or not tool_result:
        return "end"

    wants_tasks = any(kw in message for kw in TASK_KEYWORDS)
    if not wants_tasks:
        return "end"

    return "resolve"


async def resolve_project(state: GenericPMState) -> dict:
    """Toma el primer proyecto y lista sus tareas."""
    tool_result = state.get("tool_result", [])
    first_project = tool_result[0] if tool_result else {}
    project_id = first_project.get("id", "")

    print(f"GENERIC PM: Encadenando list_projects → list_tasks para '{first_project.get('name', '')}' ({project_id})")

    return {
        "tool_name": "pm_list_tasks",
        "tool_args": {"project_id": project_id},
    }


# ─── Grafo ───────────────────────────────────────────────────

def _after_discover(state: GenericPMState) -> str:
    """Si no hay provider, terminar. Si hay, seguir a select_tool."""
    if not state.get("pm_provider"):
        return "end"
    return "select_tool"


graph = StateGraph(GenericPMState)
graph.add_node("discover", discover_pm_provider)
graph.add_node("select_tool", select_tool)
graph.add_node("execute_tool", execute_tool)
graph.add_node("resolve_project", resolve_project)

graph.set_entry_point("discover")
graph.add_conditional_edges("discover", _after_discover, {"select_tool": "select_tool", "end": END})
graph.add_edge("select_tool", "execute_tool")
graph.add_conditional_edges("execute_tool", _needs_resolve, {"resolve": "resolve_project", "end": END})
graph.add_edge("resolve_project", "execute_tool")

generic_pm_agent = graph.compile()
