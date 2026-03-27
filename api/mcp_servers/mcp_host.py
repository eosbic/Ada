"""
MCPHost — Orquestador central de MCP Servers.
Referencia: ADA_MIGRACION_V5_PART1.md §4.3

Responsabilidades:
1. Registrar MCP Servers disponibles
2. Tool Selection por intent (máximo 5 tools por request)
3. Inyectar credenciales por empresa
4. Ejecutar tools y retornar resultados
"""

import json
from typing import Dict, List, Any
from api.services.tenant_credentials import get_service_credentials, get_microsoft_credentials
from api.mcp_servers.mcp_notion_server import (
    handle_tool_call as notion_handle,
    get_tools as notion_tools,
)
from api.mcp_servers.mcp_plane_server import (
    handle_tool_call as plane_handle,
    get_tools as plane_tools,
)
from api.mcp_servers.mcp_microsoft365_server import (
    handle_tool_call as m365_handle,
    get_tools as m365_tools,
)
from api.mcp_servers.mcp_asana_server import (
    handle_tool_call as asana_handle,
    get_tools as asana_tools,
)


# ─── MCP Server Registry ─────────────────────────────────

MCP_SERVERS = {
    "notion": {
        "credential_type": "notion",
        "category": "project_management",
        "tools_fn": notion_tools,
        "handler_fn": notion_handle,
    },
    "plane": {
        "credential_type": "plane",
        "category": "project_management",
        "tools_fn": plane_tools,
        "handler_fn": plane_handle,
    },
    "microsoft365": {
        "credential_type": "outlook_calendar",
        "category": "productivity",
        "tools_fn": m365_tools,
        "handler_fn": m365_handle,
    },
    "asana": {
        "credential_type": "asana",
        "category": "generic_pm",
        "tools_fn": asana_tools,
        "handler_fn": asana_handle,
    },
}

# Qué MCP servers usar por intent
INTENT_MCP_MAP = {
    "notion": ["notion"],
    "project": ["plane"],
    "data_query": ["notion"],
    "action": ["notion", "plane"],
    "calendar": ["microsoft365"],
    "email": ["microsoft365"],
}


class MCPHost:
    """Orquestador central de MCP Servers."""

    def __init__(self):
        self.servers = MCP_SERVERS

    def get_tools_for_intent(self, intent: str) -> List[dict]:
        """Retorna tools relevantes para un intent (máx 5)."""
        server_names = INTENT_MCP_MAP.get(intent, [])
        tools = []

        for name in server_names:
            if name in self.servers:
                server_tools = self.servers[name]["tools_fn"]()
                for tool in server_tools:
                    tool["_mcp_server"] = name
                    tools.append(tool)

        return tools[:5]

    def get_all_tools(self) -> List[dict]:
        """Retorna todas las tools de todos los servers."""
        tools = []
        for name, server in self.servers.items():
            for tool in server["tools_fn"]():
                tool["_mcp_server"] = name
                tools.append(tool)
        return tools

    async def call_tool(
        self, server_name: str, tool_name: str,
        arguments: dict, empresa_id: str, user_id: str = ""
    ) -> Any:
        """Ejecuta una tool con credenciales de la empresa/usuario."""

        if server_name not in self.servers:
            return {"error": f"MCP Server '{server_name}' no registrado"}

        server = self.servers[server_name]

        # Obtener credenciales según el servidor
        if server_name == "microsoft365":
            # Determinar provider por tool_name
            if "calendar" in tool_name:
                m365_service = "outlook_calendar"
            elif "email" in tool_name:
                m365_service = "outlook_email"
            elif "drive" in tool_name:
                m365_service = "onedrive"
            else:
                m365_service = "outlook_calendar"
            creds = get_microsoft_credentials(empresa_id, m365_service, user_id=user_id)
        else:
            creds = get_service_credentials(empresa_id, server["credential_type"], user_id=user_id)

        if "error" in creds:
            return creds

        # Ejecutar según el servidor
        if server_name == "microsoft365":
            access_token = creds.get("access_token", "")
            if not access_token:
                return {"error": "Microsoft 365 access_token no encontrado"}
            result = await server["handler_fn"](tool_name, arguments, access_token)

        elif server_name == "notion":
            api_key = creds.get("api_key", "")
            if not api_key:
                return {"error": "Notion API key no encontrada"}
            result = await server["handler_fn"](tool_name, arguments, api_key)

        elif server_name == "plane":
            api_key = creds.get("api_key", "")
            base_url = creds.get("base_url", "https://api.plane.so/api/v1")
            workspace = creds.get("workspace", "")
            print("PLANE CREDS:", api_key, base_url, workspace)
            if not api_key or not workspace:
                return {"error": "Plane API key o workspace no configurados"}
            result = await server["handler_fn"](tool_name, arguments, api_key, base_url, workspace)
            print(f"MCP PLANE RESULT: {result}")

        elif server.get("category") == "generic_pm":
            # PM genéricos reciben credentials dict completo
            result = await server["handler_fn"](tool_name, arguments, creds)

        else:
            return {"error": f"Handler para '{server_name}' no implementado"}

        print(f"MCP: {server_name}.{tool_name} → OK")
        return result

    def get_empresa_pm_provider(self, empresa_id: str) -> str:
        """Retorna nombre del PM server genérico conectado para la empresa, o None."""
        try:
            from api.database import sync_engine
            from sqlalchemy import text as sql_text

            for server_name, server in self.servers.items():
                if server.get("category") != "generic_pm":
                    continue
                with sync_engine.connect() as conn:
                    result = conn.execute(
                        sql_text("""
                            SELECT 1 FROM tenant_credentials
                            WHERE empresa_id = :eid AND provider = :provider AND is_active = TRUE
                            LIMIT 1
                        """),
                        {"eid": empresa_id, "provider": server["credential_type"]},
                    )
                    if result.fetchone():
                        return server_name
        except Exception as e:
            print(f"MCP get_empresa_pm_provider error: {e}")
        return None

    async def call_generic_pm_tool(self, tool_name: str, arguments: dict, empresa_id: str, user_id: str = "") -> Any:
        """Resuelve qué PM server genérico usar por empresa y ejecuta."""
        from api.database import sync_engine
        from sqlalchemy import text as sql_text

        for server_name, server in self.servers.items():
            if server.get("category") != "generic_pm":
                continue
            try:
                with sync_engine.connect() as conn:
                    result = conn.execute(
                        sql_text("""
                            SELECT 1 FROM tenant_credentials
                            WHERE empresa_id = :eid AND provider = :provider AND is_active = TRUE
                            LIMIT 1
                        """),
                        {"eid": empresa_id, "provider": server["credential_type"]},
                    )
                    if result.fetchone():
                        return await self.call_tool(server_name, tool_name, arguments, empresa_id, user_id=user_id)
            except Exception as e:
                print(f"MCP call_generic_pm_tool error for {server_name}: {e}")

        return {"error": "No hay herramienta de proyectos genérica conectada"}

    async def call_tool_by_name(self, tool_name: str, arguments: dict, empresa_id: str, user_id: str = "") -> Any:
        """Busca el server correcto por nombre de tool y ejecuta."""
        for name, server in self.servers.items():
            tool_names = [t["name"] for t in server["tools_fn"]()]
            if tool_name in tool_names:
                return await self.call_tool(name, tool_name, arguments, empresa_id, user_id=user_id)

        return {"error": f"Tool '{tool_name}' no encontrada en ningún MCP Server"}


# Instancia global
mcp_host = MCPHost()