"""
PMServerBase — Interfaz estándar para PM servers genéricos.
Define 4 tools estándar: pm_list_projects, pm_list_tasks, pm_create_task, pm_update_task.
Todos los PM genéricos (Asana, Monday, Trello, ClickUp, Jira) extienden esta clase.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


# Mapeo de estados normalizados
STANDARD_STATES = {
    "pending": ["backlog", "todo", "unstarted", "not started", "open"],
    "in_progress": ["in progress", "started", "doing", "active"],
    "done": ["done", "completed", "closed", "cancelled"],
}

# Mapeo de prioridades normalizadas
_PRIORITY_MAP = {
    "urgent": ["urgent", "critical", "p0", "highest"],
    "high": ["high", "p1", "important"],
    "medium": ["medium", "normal", "p2", "default"],
    "low": ["low", "p3", "minor"],
    "none": ["none", "p4", "trivial", ""],
}


def normalize_state(raw_state: str, state_map: dict = None) -> str:
    """Normaliza estado raw a pending/in_progress/done. Retorna raw si no matchea."""
    if not raw_state:
        return "pending"
    mapping = state_map or STANDARD_STATES
    raw_lower = raw_state.strip().lower()
    for standard, variants in mapping.items():
        if raw_lower == standard or raw_lower in [v.lower() for v in variants]:
            return standard
    return raw_state


def normalize_priority(raw_priority: str) -> str:
    """Normaliza prioridad a urgent/high/medium/low/none. Default: medium."""
    if not raw_priority:
        return "medium"
    raw_lower = raw_priority.strip().lower()
    for standard, variants in _PRIORITY_MAP.items():
        if raw_lower == standard or raw_lower in variants:
            return standard
    return "medium"


class PMServerBase(ABC):
    """Clase abstracta para PM servers genéricos."""

    @abstractmethod
    async def pm_list_projects(self, credentials: dict) -> list:
        """Retorna lista de proyectos: [{id, name, description, status}]."""
        ...

    @abstractmethod
    async def pm_list_tasks(
        self,
        credentials: dict,
        project_id: str,
        max_results: int = 20,
        state_filter: str = None,
        assignee_filter: str = None,
    ) -> list:
        """Retorna lista de tareas: [{id, name, state, priority, due_date, assignee}]."""
        ...

    @abstractmethod
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
        """Crea tarea. Retorna {id, name, status: "created", url}."""
        ...

    @abstractmethod
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
        """Actualiza tarea. Retorna {id, status: "updated"}."""
        ...

    def get_tools(self) -> list:
        """Retorna las 4 tool definitions en formato MCP."""
        return [
            {
                "name": "pm_list_projects",
                "description": "Lista todos los proyectos disponibles",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            },
            {
                "name": "pm_list_tasks",
                "description": "Lista tareas de un proyecto con filtros opcionales",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project_id": {"type": "string", "description": "ID del proyecto"},
                        "max_results": {"type": "integer", "description": "Máximo de resultados", "default": 20},
                        "state_filter": {"type": "string", "description": "Filtrar por estado: pending, in_progress, done"},
                        "assignee_filter": {"type": "string", "description": "Filtrar por nombre de persona asignada"},
                    },
                    "required": ["project_id"],
                },
            },
            {
                "name": "pm_create_task",
                "description": "Crea una nueva tarea en un proyecto",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project_id": {"type": "string", "description": "ID del proyecto"},
                        "name": {"type": "string", "description": "Nombre de la tarea"},
                        "description": {"type": "string", "description": "Descripción de la tarea"},
                        "priority": {"type": "string", "description": "Prioridad: urgent, high, medium, low, none"},
                        "due_date": {"type": "string", "description": "Fecha límite ISO (YYYY-MM-DD)"},
                        "assignee": {"type": "string", "description": "Persona asignada"},
                    },
                    "required": ["project_id", "name"],
                },
            },
            {
                "name": "pm_update_task",
                "description": "Actualiza una tarea existente",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project_id": {"type": "string", "description": "ID del proyecto"},
                        "task_id": {"type": "string", "description": "ID de la tarea"},
                        "name": {"type": "string", "description": "Nuevo nombre"},
                        "state": {"type": "string", "description": "Nuevo estado: pending, in_progress, done"},
                        "priority": {"type": "string", "description": "Nueva prioridad"},
                        "due_date": {"type": "string", "description": "Nueva fecha límite"},
                        "assignee": {"type": "string", "description": "Nueva persona asignada"},
                    },
                    "required": ["project_id", "task_id"],
                },
            },
        ]

    async def handle_tool_call(self, tool_name: str, arguments: dict, credentials: dict) -> Any:
        """Rutea a los 4 métodos según tool_name."""
        if tool_name == "pm_list_projects":
            return await self.pm_list_projects(credentials)
        elif tool_name == "pm_list_tasks":
            return await self.pm_list_tasks(
                credentials,
                project_id=arguments.get("project_id", ""),
                max_results=arguments.get("max_results", 20),
                state_filter=arguments.get("state_filter"),
                assignee_filter=arguments.get("assignee_filter"),
            )
        elif tool_name == "pm_create_task":
            return await self.pm_create_task(
                credentials,
                project_id=arguments.get("project_id", ""),
                name=arguments.get("name", ""),
                description=arguments.get("description", ""),
                priority=arguments.get("priority", "medium"),
                due_date=arguments.get("due_date"),
                assignee=arguments.get("assignee"),
            )
        elif tool_name == "pm_update_task":
            return await self.pm_update_task(
                credentials,
                project_id=arguments.get("project_id", ""),
                task_id=arguments.get("task_id", ""),
                name=arguments.get("name"),
                state=arguments.get("state"),
                priority=arguments.get("priority"),
                due_date=arguments.get("due_date"),
                assignee=arguments.get("assignee"),
            )
        else:
            return {"error": f"Tool '{tool_name}' no existe en PM server"}
