"""
MCP Server — Plane.so
Protocolo MCP estándar con tools expuestas.
"""

import json
import asyncio
import httpx
from typing import Any


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


async def _get_workspace_members(api_key: str, base_url: str, workspace: str) -> dict:
    """
    Retorna mapa {user_id: nombre_real} y {display_name_lower: nombre_real}
    para resolver tanto UUIDs como usernames a nombres reales.
    """
    url = f"{base_url}/workspaces/{workspace}/members/"
    headers = {"X-Api-Key": api_key, "Content-Type": "application/json"}
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, headers=headers, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            members = data.get("results", data) if isinstance(data, dict) else data
            result = {}
            for m in members:
                print(f"PLANE MEMBERS: Resolviendo {m}")
                member = m.get("member") or m
                uid = member.get("id", "")

                # Preferir nombre completo real sobre display_name/username
                first = member.get("first_name", "").strip()
                last = member.get("last_name", "").strip()
                full_name = f"{first} {last}".strip() if (first or last) else ""
                display = member.get("display_name", "").strip()
                email = member.get("email", "")

                # Nombre final: nombre real > display_name > email > uid
                name = full_name if full_name else (display or email or uid)

                if uid:
                    result[uid] = name

                # Alias por display_name en minúsculas (ej: "ogutierrez61" → "Oswaldo Gutierrez Cardenas")
                if display and display.lower() != name.lower():
                    result[display.lower()] = name

                # Alias por email local (ej: "ogutierrez61" de ogutierrez61@gmail.com)
                if email and "@" in email:
                    email_local = email.split("@")[0].lower()
                    result[email_local] = name

            print(f"PLANE MEMBERS: {len([k for k in result if '-' in k])} miembros resueltos")
            return result
    except Exception as e:
        print(f"PLANE MEMBERS ERROR: {e}")
    return {}


async def plane_list_issues(api_key: str, base_url: str, workspace: str, project_id: str, max_results: int = 50) -> list:
    url = f"{base_url}/workspaces/{workspace}/projects/{project_id}/issues/"
    headers = {"X-Api-Key": api_key, "Content-Type": "application/json"}

    async with httpx.AsyncClient() as client:
        resp = await client.get(url, headers=headers, params={"per_page": max_results}, timeout=15)

    if resp.status_code != 200:
        return []

    data = resp.json()
    results = data.get("results", data) if isinstance(data, dict) else data

    # Cargar states
    state_map = {}
    try:
        states_url = f"{base_url}/workspaces/{workspace}/projects/{project_id}/states/"
        async with httpx.AsyncClient() as client:
            states_resp = await client.get(states_url, headers=headers, timeout=10)
        if states_resp.status_code == 200:
            states_data = states_resp.json()
            states_list = states_data.get("results", states_data) if isinstance(states_data, dict) else states_data
            for s in states_list:
                state_map[s.get("id", "")] = s.get("name", "")
    except Exception as e:
        print(f"PLANE: No pudo cargar states: {e}")

    # Cargar miembros con nombres reales
    member_map = await _get_workspace_members(api_key, base_url, workspace)

    issues = []
    for i in results:
        # Resolver estado
        state_id = i.get("state", "")
        state_name = ""
        if isinstance(i.get("state_detail"), dict):
            state_name = i["state_detail"].get("name", "")
        if not state_name and state_id:
            state_name = state_map.get(state_id, state_id)

        # Resolver assignees con nombres reales
        assignees_raw = i.get("assignees") or []
        assignees = []
        for a in assignees_raw:
            if isinstance(a, dict):
                uid = a.get("id", "")
                # Buscar nombre real en member_map por UUID
                real_name = member_map.get(uid, "")
                if not real_name:
                    # Fallback a display_name del objeto
                    real_name = a.get("display_name", "") or a.get("email", "") or uid
                assignees.append({
                    "id": uid,
                    "display_name": real_name,
                    "email": a.get("email", ""),
                })
            else:
                uid = str(a)
                real_name = member_map.get(uid, uid)
                assignees.append({"id": uid, "display_name": real_name, "email": ""})

        issues.append({
            "id": i.get("id"),
            "name": i.get("name"),
            "description": (i.get("description_stripped") or "")[:200],
            "state": state_name,
            "state_id": state_id,
            "priority": i.get("priority", "none"),
            "due_date": i.get("target_date", ""),
            "assignees": assignees,
        })

    print(f"PLANE ISSUES: {len(issues)} tareas | states: {state_map} | members: {len([k for k in member_map if '-' in k])}")
    return issues


async def plane_create_issue(api_key: str, base_url: str, workspace: str,
                              project_id: str, name: str, description: str = "",
                              priority: str = "medium", due_date: str = None) -> dict:
    projects = await plane_list_projects(api_key, base_url, workspace)
    real_project_id = None
    for p in projects:
        if p["id"] == project_id or p["name"].lower() == project_id.lower():
            real_project_id = p["id"]
            break
    if not real_project_id:
        return {"error": f"Proyecto '{project_id}' no encontrado"}

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
    return {"id": data.get("id"), "project_id": real_project_id, "name": name, "status": "created"}


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


TOOLS = [
    {
        "name": "plane_list_projects",
        "description": "Lista proyectos existentes en Plane. Usar solo cuando el usuario quiera ver proyectos.",
        "inputSchema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "plane_list_issues",
        "description": "Lista tareas de un proyecto. Usar cuando el usuario quiera ver tareas existentes.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "Nombre o ID del proyecto"},
                "max_results": {"type": "integer", "default": 50}
            },
            "required": ["project_id"]
        }
    },
    {
        "name": "plane_create_issue",
        "description": "CREA una nueva tarea en un proyecto.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string"},
                "name": {"type": "string"},
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


async def handle_tool_call(tool_name: str, arguments: dict, api_key: str, base_url: str, workspace: str) -> Any:
    if tool_name == "plane_list_projects":
        return await plane_list_projects(api_key, base_url, workspace)
    elif tool_name == "plane_list_issues":
        return await plane_list_issues(api_key, base_url, workspace,
                                        arguments["project_id"], arguments.get("max_results", 50))
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