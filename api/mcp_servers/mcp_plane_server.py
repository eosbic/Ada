"""
MCP Server — Plane.so
Protocolo MCP estándar con tools expuestas.

Tools: plane_list_projects, plane_list_issues, plane_create_issue, plane_update_issue
"""

import json
import asyncio
import httpx
from typing import Any


# ─── PLANE TOOLS ─────────────────────────────────────────

async def plane_list_projects(api_key: str, base_url: str, workspace: str) -> list:
    url = f"{base_url}/workspaces/{workspace}/projects/"
    headers = {"X-Api-Key": api_key, "Content-Type": "application/json"}

    async with httpx.AsyncClient() as client:
        resp = await client.get(url, headers=headers, timeout=15)

    if resp.status_code != 200:
        return [{"error": f"Plane API error: {resp.status_code}"}]

    data = resp.json()
    results = data.get("results", data) if isinstance(data, dict) else data

    return [{
        "id": p.get("id"), "name": p.get("name"),
        "description": p.get("description", "")[:200],
        "status": p.get("network", ""),
    } for p in results]


STATE_FILTERS = {
    "pending": ["backlog", "todo", "unstarted"],
    "pendiente": ["backlog", "todo", "unstarted"],
    "in_progress": ["in progress", "started"],
    "en progreso": ["in progress", "started"],
    "done": ["done", "completed", "cancelled"],
    "completada": ["done", "completed", "cancelled"],
    "ejecutada": ["done", "completed", "cancelled"],
}


async def plane_list_issues(
    api_key: str, base_url: str, workspace: str, project_id: str,
    max_results: int = 20, state_filter: str = None, assignee_filter: str = None,
) -> list:
    url = f"{base_url}/workspaces/{workspace}/projects/{project_id}/issues/"
    headers = {"X-Api-Key": api_key, "Content-Type": "application/json"}

    async with httpx.AsyncClient() as client:
        resp = await client.get(url, headers=headers, params={
            "per_page": max_results,
            "expand": "assignees,state",
        }, timeout=15)

    if resp.status_code != 200:
        return []

    data = resp.json()
    results = data.get("results", data) if isinstance(data, dict) else data

    issues = []
    for i in results:
        state_detail = i.get("state_detail", {}) if isinstance(i.get("state_detail"), dict) else {}
        state_name = state_detail.get("name", "")
        state_group = state_detail.get("group", "")

        # Extraer assignee - cubrir multiples formatos de la API de Plane
        assignee_name = ""
        # Formato 1: assignee_detail (objeto)
        assignee_detail = i.get("assignee_detail") or {}
        if isinstance(assignee_detail, dict) and assignee_detail:
            assignee_name = assignee_detail.get("display_name", "") or assignee_detail.get("first_name", "")
        # Formato 2: assignees_detail (lista de objetos)
        if not assignee_name:
            assignees_detail = i.get("assignees_detail") or i.get("assignees") or []
            if isinstance(assignees_detail, list):
                names = []
                for a in assignees_detail:
                    if isinstance(a, dict):
                        n = a.get("display_name", "") or a.get("first_name", "")
                        if n:
                            names.append(n)
                assignee_name = ", ".join(names)
        # Formato 3: assignee como string directo
        if not assignee_name and isinstance(i.get("assignee"), str) and i["assignee"]:
            assignee_name = i["assignee"]

        issues.append({
            "id": i.get("id"), "name": i.get("name"),
            "description": i.get("description_stripped", "")[:200],
            "state": state_name,
            "state_group": state_group,
            "priority": i.get("priority", "none"),
            "due_date": i.get("target_date", ""),
            "assignee": assignee_name,
        })

    # Filtrar por estado
    if state_filter:
        allowed_states = STATE_FILTERS.get(state_filter.lower(), [])
        if allowed_states:
            issues = [
                i for i in issues
                if i["state"].lower() in allowed_states or i["state_group"].lower() in allowed_states
            ]

    # Filtrar por asignado
    if assignee_filter:
        assignee_lower = assignee_filter.lower()
        issues = [i for i in issues if (
            assignee_lower in i.get("assignee", "").lower() or
            assignee_lower in i.get("name", "").lower() or
            assignee_lower in i.get("description", "").lower()
        )]

    return issues


async def plane_create_issue(api_key: str, base_url: str, workspace: str,
                              project_id: str, name: str, description: str = "",
                              priority: str = "medium", due_date: str = None) -> dict:

    # ── Resolver nombre de proyecto → ID real ──
    projects = await plane_list_projects(api_key, base_url, workspace)

    real_project_id = None
    for p in projects:
        if p["id"] == project_id or p["name"].lower() == project_id.lower():
            real_project_id = p["id"]
            break

    if not real_project_id:
        return {"error": f"Proyecto '{project_id}' no encontrado"}

    # ── Crear issue ──
    url = f"{base_url}/workspaces/{workspace}/projects/{real_project_id}/issues/"
    headers = {"X-Api-Key": api_key, "Content-Type": "application/json"}

    body = {"name": name, "priority": priority}

    if description:
        body["description_html"] = f"<p>{description}</p>"

    if due_date:
        body["target_date"] = due_date

    async with httpx.AsyncClient() as client:
        resp = await client.post(url, headers=headers, json=body, timeout=15)

    if resp.status_code not in (200, 201):
        return {"error": f"Error: {resp.text[:200]}"}

    data = resp.json()

    return {
        "id": data.get("id"),
        "project_id": real_project_id,
        "name": name,
        "status": "created"
    }


async def plane_update_issue(api_key: str, base_url: str, workspace: str,
                              project_id: str, issue_id: str,
                              name: str = None, priority: str = None,
                              state_id: str = None, due_date: str = None) -> dict:
    url = f"{base_url}/workspaces/{workspace}/projects/{project_id}/issues/{issue_id}/"
    headers = {"X-Api-Key": api_key, "Content-Type": "application/json"}

    body = {}
    if name: body["name"] = name
    if priority: body["priority"] = priority
    if state_id: body["state"] = state_id
    if due_date: body["target_date"] = due_date

    async with httpx.AsyncClient() as client:
        resp = await client.patch(url, headers=headers, json=body, timeout=15)

    if resp.status_code != 200:
        return {"error": f"Error: {resp.text[:200]}"}

    return {"id": issue_id, "status": "updated"}


# ─── MCP TOOL DEFINITIONS ────────────────────────────────
TOOLS = [
    {
        "name": "plane_list_projects",
        "description": "Lista proyectos existentes en Plane. Usar solo cuando el usuario quiera ver proyectos o encontrar el nombre de un proyecto.",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "plane_list_issues",
        "description": "Lista tareas de un proyecto. Puede filtrar por estado (pending/in_progress/done) y por persona asignada.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "Nombre o ID del proyecto. Usar 'all' para todos."},
                "max_results": {"type": "integer", "default": 20},
                "state_filter": {"type": "string", "description": "Filtrar por estado: pending, in_progress, done, o null para todos"},
                "assignee_filter": {"type": "string", "description": "Filtrar por nombre de persona asignada"}
            },
            "required": ["project_id"]
        }
    },
    {
        "name": "plane_create_issue",
        "description": "CREA una nueva tarea (issue) en un proyecto. Usar cuando el usuario diga crear tarea, nueva tarea, crear issue o agregar tarea.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "Nombre o ID del proyecto"},
                "name": {"type": "string", "description": "Nombre de la tarea"},
                "description": {"type": "string"},
                "priority": {"type": "string", "enum": ["urgent","high","medium","low","none"]},
                "due_date": {"type": "string"}
            },
            "required": ["project_id","name"]
        }
    },
    {
        "name": "plane_update_issue",
        "description": "Actualiza una tarea existente.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string"},
                "issue_id": {"type": "string"},
                "name": {"type": "string"},
                "priority": {"type": "string"},
                "due_date": {"type": "string"}
            },
            "required": ["project_id","issue_id"]
        }
    }
]

# ─── MCP HANDLER ─────────────────────────────────────────

async def handle_tool_call(tool_name: str, arguments: dict, api_key: str, base_url: str, workspace: str) -> Any:
    """Ejecuta una tool MCP de Plane."""
    if tool_name == "plane_list_projects":
        return await plane_list_projects(api_key, base_url, workspace)
    elif tool_name == "plane_list_issues":
        return await plane_list_issues(api_key, base_url, workspace,
                                        arguments["project_id"], arguments.get("max_results", 20),
                                        arguments.get("state_filter"), arguments.get("assignee_filter"))
    elif tool_name == "plane_create_issue":
        return await plane_create_issue(api_key, base_url, workspace,
                                         arguments["project_id"], arguments["name"],
                                         arguments.get("description", ""),
                                         arguments.get("priority", "medium"),
                                         arguments.get("due_date"))
    elif tool_name == "plane_update_issue":
        return await plane_update_issue(api_key, base_url, workspace,
                                         arguments["project_id"], arguments["issue_id"],
                                         arguments.get("name"), arguments.get("priority"),
                                         arguments.get("state_id"), arguments.get("due_date"))
    else:
        return {"error": f"Tool '{tool_name}' no encontrada"}


def get_tools() -> list:
    return TOOLS