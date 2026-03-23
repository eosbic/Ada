"""
MCP Server — Asana API REST (https://app.asana.com/api/1.0)
Primer PM server genérico. Implementa PMServerBase.
"""

from typing import Any, Dict, List, Optional

import httpx

from api.mcp_servers.mcp_pm_base import PMServerBase, normalize_state, normalize_priority


ASANA_BASE = "https://app.asana.com/api/1.0"


def _headers(access_token: str) -> dict:
    """Headers estándar para Asana API."""
    return {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }


def _get_token(credentials: dict) -> str:
    """Extrae access_token de credentials dict."""
    return credentials.get("access_token", credentials.get("api_key", ""))


class AsanaPMServer(PMServerBase):
    """Implementación de PMServerBase para Asana."""

    async def pm_list_projects(self, credentials: dict) -> list:
        """Lista proyectos del workspace Asana."""
        token = _get_token(credentials)
        workspace_gid = credentials.get("workspace_gid", "")
        if not workspace_gid:
            return [{"error": "workspace_gid no configurado en credenciales Asana"}]

        url = f"{ASANA_BASE}/workspaces/{workspace_gid}/projects"
        params = {
            "opt_fields": "gid,name,notes,current_status_update.status_type",
            "limit": 50,
        }

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url, headers=_headers(token), params=params)

        if resp.status_code != 200:
            print(f"ASANA list_projects error: {resp.status_code} {resp.text[:200]}")
            return []

        projects = []
        for p in resp.json().get("data", []):
            status_update = p.get("current_status_update") or {}
            projects.append({
                "id": p.get("gid", ""),
                "name": p.get("name", ""),
                "description": (p.get("notes", "") or "")[:200],
                "status": status_update.get("status_type", ""),
            })

        print(f"ASANA: {len(projects)} proyectos")
        return projects

    async def pm_list_tasks(
        self,
        credentials: dict,
        project_id: str,
        max_results: int = 20,
        state_filter: str = None,
        assignee_filter: str = None,
    ) -> list:
        """Lista tareas de un proyecto Asana."""
        token = _get_token(credentials)

        url = f"{ASANA_BASE}/projects/{project_id}/tasks"
        params = {
            "opt_fields": "gid,name,assignee.name,due_on,completed,memberships.section.name",
            "limit": 100,
        }

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url, headers=_headers(token), params=params)

        if resp.status_code != 200:
            print(f"ASANA list_tasks error: {resp.status_code} {resp.text[:200]}")
            return []

        tasks = []
        for t in resp.json().get("data", []):
            # Determinar estado
            if t.get("completed"):
                raw_state = "done"
            else:
                # Inferir in_progress por section name
                section_name = ""
                for m in t.get("memberships", []):
                    section = m.get("section", {})
                    if section:
                        section_name = (section.get("name", "") or "").lower()
                        break
                if "progress" in section_name or "doing" in section_name or "in progress" in section_name:
                    raw_state = "in_progress"
                else:
                    raw_state = "pending"

            state = normalize_state(raw_state)
            assignee_name = ""
            assignee_obj = t.get("assignee")
            if assignee_obj and isinstance(assignee_obj, dict):
                assignee_name = assignee_obj.get("name", "")

            # Filtros
            if state_filter and state != state_filter:
                continue
            if assignee_filter and assignee_filter.lower() not in assignee_name.lower():
                continue

            tasks.append({
                "id": t.get("gid", ""),
                "name": t.get("name", ""),
                "state": state,
                "priority": "medium",  # Asana no tiene prioridad nativa en API REST básica
                "due_date": t.get("due_on", ""),
                "assignee": assignee_name,
            })

            if len(tasks) >= max_results:
                break

        print(f"ASANA: {len(tasks)} tareas en proyecto {project_id}")
        return tasks

    async def pm_create_task(
        self,
        credentials: dict,
        project_id: str,
        name: str,
        description: str = "",
        priority: str = "medium",
        due_date: str = None,
        assignee: str = None,
    ) -> dict:
        """Crea tarea en proyecto Asana."""
        token = _get_token(credentials)

        data = {
            "name": name,
            "notes": description,
            "projects": [project_id],
        }
        if due_date:
            data["due_on"] = due_date
        if assignee:
            data["assignee"] = assignee

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{ASANA_BASE}/tasks",
                headers=_headers(token),
                json={"data": data},
            )

        if resp.status_code not in (200, 201):
            print(f"ASANA create_task error: {resp.status_code} {resp.text[:200]}")
            return {"error": f"Error creando tarea en Asana: {resp.status_code}"}

        task = resp.json().get("data", {})
        gid = task.get("gid", "")
        print(f"ASANA: Tarea creada → {gid}: {name}")
        return {
            "id": gid,
            "name": name,
            "status": "created",
            "url": f"https://app.asana.com/0/{project_id}/{gid}",
        }

    async def pm_update_task(
        self,
        credentials: dict,
        project_id: str,
        task_id: str,
        name: str = None,
        state: str = None,
        priority: str = None,
        due_date: str = None,
        assignee: str = None,
    ) -> dict:
        """Actualiza tarea en Asana."""
        token = _get_token(credentials)

        data = {}
        if name is not None:
            data["name"] = name
        if state is not None:
            if state == "done":
                data["completed"] = True
            elif state in ("pending", "in_progress"):
                data["completed"] = False
        if due_date is not None:
            data["due_on"] = due_date
        if assignee is not None:
            data["assignee"] = assignee
        if priority is not None:
            print(f"ASANA: Prioridad '{priority}' ignorada — Asana no soporta prioridad nativa en API REST")

        if not data:
            return {"id": task_id, "status": "updated", "message": "Sin cambios"}

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.put(
                f"{ASANA_BASE}/tasks/{task_id}",
                headers=_headers(token),
                json={"data": data},
            )

        if resp.status_code != 200:
            print(f"ASANA update_task error: {resp.status_code} {resp.text[:200]}")
            return {"error": f"Error actualizando tarea en Asana: {resp.status_code}"}

        print(f"ASANA: Tarea actualizada → {task_id}")
        return {"id": task_id, "status": "updated"}


# Singleton
asana_server = AsanaPMServer()


# Funciones de conveniencia para mcp_host
def get_tools() -> list:
    """Retorna tool definitions de Asana."""
    return asana_server.get_tools()


async def handle_tool_call(tool_name: str, arguments: dict, credentials: dict) -> Any:
    """Ejecuta tool de Asana. credentials es dict completo."""
    return await asana_server.handle_tool_call(tool_name, arguments, credentials)
