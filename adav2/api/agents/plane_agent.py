"""
Plane Agent — Usa MCPHost para ejecutar tools de Plane.so.
LangGraph agent con tool calling via MCP.
"""

import json
import re
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
Si el usuario pide tareas, issues, pendientes, o menciona una persona, usa plane_list_issues.
Si el usuario pide proyectos explicitamente, usa plane_list_projects.
Prioridades: urgent, high, medium, low, none

Responde SOLO JSON:
{{"tool": "nombre_de_la_tool", "arguments": {{...}}}}
Sin markdown."""


STATE_MAP = {
    "done":        ["done","hecho","terminado","completado","finalizado","terminadas","hechas","completadas"],
    "in_progress": ["in progress","en curso","en proceso","en desarrollo","en ejecucion","activo","activas"],
    "todo":        ["todo","por hacer","pendiente","pendientes","sin iniciar","backlog"],
    "cancelled":   ["cancelled","cancelado","cancelada","cancelados","canceladas"],
}

TASK_KEYWORDS = [
    "tarea", "tareas", "issue", "issues",
    "pendiente", "pendientes", "done", "hecho",
    "participando", "participa", "participo",
    "asignada", "asignado", "asignadas", "asignados",
    "responsable", "busca tareas", "que tiene",
    "que esta haciendo", "en que trabaja",
]


async def select_plane_tool(state: PlaneState) -> dict:
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

    # Corregir si el LLM eligio proyectos pero el mensaje pide tareas o menciona persona
    msg_lower = state.get("message", "").lower()
    if tool_name == "plane_list_projects" and any(kw in msg_lower for kw in TASK_KEYWORDS):
        tool_name = "plane_list_issues"
        print(f"PLANE AGENT: Corrigiendo tool a plane_list_issues por keywords")

    print(f"PLANE AGENT: tool={tool_name}, args={tool_args}")
    return {"tool_name": tool_name, "tool_args": tool_args, "model_used": model_name}


async def execute_plane_tool(state: PlaneState) -> dict:
    tool_name = state.get("tool_name", "")
    tool_args = state.get("tool_args", {})
    empresa_id = state.get("empresa_id", "")
    message = state.get("message", "").lower()

    if isinstance(tool_args, list):
        tool_args = tool_args[0] if tool_args else {}
    if not isinstance(tool_args, dict):
        tool_args = {}

    # Detectar filtro por estado
    desired_state = None
    for state_key, keywords in STATE_MAP.items():
        if any(kw in message for kw in keywords):
            desired_state = state_key
            break

    # Detectar filtro por persona
    person_filter = None
    name_matches = re.findall(r'\b[A-ZÁÉÍÓÚ][a-záéíóú]+(?: [A-ZÁÉÍÓÚ][a-záéíóú]+)+', state.get("message", ""))
    if name_matches:
        person_filter = name_matches[0].lower()

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
            print(f"PLANE AGENT: Resolvio '{project_name}' -> {project['id']}")
        else:
            return {"response": "No encontre proyectos en Plane.so. Verifica la conexion."}

    result = await mcp_host.call_tool_by_name(tool_name, tool_args, empresa_id)

    if isinstance(result, dict) and "error" in result:
        return {"response": f"Error: {result['error']}"}

    if tool_name == "plane_list_projects":
        if not result:
            return {"response": "No hay proyectos."}
        formatted = "\n".join([
            f"- {p.get('name', '')} ({p.get('status', '')})\n  {p.get('description', '')[:80]}"
            for p in result
        ])
        return {
            "response": f"Proyectos ({len(result)}):\n\n{formatted}",
            "sources_used": [{"name": "plane", "detail": "list_projects", "confidence": 0.9}],
        }

    elif tool_name == "plane_list_issues":
        if not result:
            return {
                "response": "No hay tareas.",
                "sources_used": [{"name": "plane", "detail": "list_issues", "confidence": 0.9}],
            }

        issues = result if isinstance(result, list) else []

        # DEBUG TEMPORAL - borrar después
        if issues:
            print(f"PLANE DEBUG issue[0] keys: {list(issues[0].keys())}")
            print(f"PLANE DEBUG issue[0] state: {issues[0].get('state')}")
            print(f"PLANE DEBUG issue[0] state_detail: {issues[0].get('state_detail')}")
            print(f"PLANE DEBUG issue[0] assignees: {issues[0].get('assignees')}")
            

        # Filtrar por estado
        if desired_state:
            filtered = [
                i for i in issues
                if desired_state.lower() in str(i.get("state", "")).lower()
                or desired_state.lower() in str((i.get("state_detail") or {}).get("name", "")).lower()
            ]
            if filtered:
                issues = filtered
                print(f"PLANE AGENT: Filtrado por estado '{desired_state}' -> {len(issues)} tareas")

        # Filtrar por persona
        if person_filter:
            filtered = [
                i for i in issues
                if person_filter in str(i.get("assignees", "")).lower()
                or person_filter in str(i.get("assignee", "")).lower()
                or any(person_filter in str(a).lower() for a in (i.get("assignees") or []))
            ]
            if filtered:
                issues = filtered
                print(f"PLANE AGENT: Filtrado por persona '{person_filter}' -> {len(issues)} tareas")

        if not issues:
            desc = []
            if desired_state:
                desc.append(f"estado '{desired_state}'")
            if person_filter:
                desc.append(f"asignadas a '{person_filter.title()}'")
            return {
                "response": f"No encontre tareas con {' y '.join(desc) if desc else 'ese criterio'}.",
                "sources_used": [{"name": "plane", "detail": "list_issues_filtered", "confidence": 0.9}],
            }

        def format_issue(i):
            assignees = i.get("assignees") or []
            assignee_str = ""
            if assignees:
                if isinstance(assignees[0], dict):
                    names = [a.get("display_name") or a.get("email", "") for a in assignees]
                else:
                    names = [str(a) for a in assignees]
                assignee_str = f"\n  Responsable: {', '.join(n for n in names if n)}"
            state_name = i.get("state") or (i.get("state_detail") or {}).get("name", "")
            prio_map = {"urgent": "Urgente", "high": "Alto", "medium": "Medio", "low": "Bajo", "none": ""}
            prio = prio_map.get(i.get("priority", "none"), "")
            prio_str = f" [{prio}]" if prio else ""
            return (
                f"- {i.get('name', '')} [{state_name}]{prio_str}"
                f"\n  Fecha: {i.get('due_date') or 'Sin fecha'}"
                f"{assignee_str}"
            )

        formatted = "\n".join([format_issue(i) for i in issues])
        filter_info = ""
        if desired_state:
            filter_info += f" | Estado: {desired_state}"
        if person_filter:
            filter_info += f" | Persona: {person_filter.title()}"

        return {
            "response": f"Tareas ({len(issues)}){filter_info}:\n\n{formatted}",
            "sources_used": [{"name": "plane", "detail": "list_issues", "confidence": 0.9}],
        }

    elif tool_name == "plane_create_issue":
        if isinstance(result, dict) and result.get("status") == "created":
            return {
                "response": f"Tarea creada: {result.get('name', '')}",
                "sources_used": [{"name": "plane", "detail": "create_issue", "confidence": 0.9}],
            }
        return {"response": f"Error creando tarea: {json.dumps(result)}"}

    elif tool_name == "plane_update_issue":
        if isinstance(result, dict) and result.get("status") == "updated":
            return {
                "response": "Tarea actualizada.",
                "sources_used": [{"name": "plane", "detail": "update_issue", "confidence": 0.9}],
            }
        return {"response": f"Error actualizando: {json.dumps(result)}"}

    else:
        return {
            "response": json.dumps(result, ensure_ascii=False, default=str)[:2000],
            "sources_used": [{"name": "plane", "detail": tool_name, "confidence": 0.85}],
        }


graph = StateGraph(PlaneState)
graph.add_node("select_tool", select_plane_tool)
graph.add_node("execute_tool", execute_plane_tool)
graph.set_entry_point("select_tool")
graph.add_edge("select_tool", "execute_tool")
graph.add_edge("execute_tool", END)
plane_agent = graph.compile()