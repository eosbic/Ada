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
from api.services.tenant_credentials import get_service_credentials
from api.mcp_servers.mcp_notion_server import (
    handle_tool_call as notion_handle,
    get_tools as notion_tools,
)
from api.mcp_servers.mcp_plane_server import (
    handle_tool_call as plane_handle,
    get_tools as plane_tools,
)


# ─── MCP Server Registry ─────────────────────────────────

MCP_SERVERS = {
    "notion": {
        "credential_type": "notion",
        "tools_fn": notion_tools,
        "handler_fn": notion_handle,
    },
    "plane": {
        "credential_type": "plane",
        "tools_fn": plane_tools,
        "handler_fn": plane_handle,
    },
}

# Qué MCP servers usar por intent
INTENT_MCP_MAP = {
    "notion": ["notion"],
    "project": ["plane"],
    "data_query": ["notion"],
    "action": ["notion", "plane"],
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
        arguments: dict, empresa_id: str
    ) -> Any:
        """Ejecuta una tool con credenciales de la empresa."""

        if server_name not in self.servers:
            return {"error": f"MCP Server '{server_name}' no registrado"}

        server = self.servers[server_name]
        creds = get_service_credentials(empresa_id, server["credential_type"])

        if "error" in creds:
            return creds

        # Ejecutar según el servidor
        if server_name == "notion":
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

        else:
            return {"error": f"Handler para '{server_name}' no implementado"}

        print(f"MCP: {server_name}.{tool_name} → OK")
        return result

    async def call_tool_by_name(self, tool_name: str, arguments: dict, empresa_id: str) -> Any:
        """Busca el server correcto por nombre de tool y ejecuta."""
        for name, server in self.servers.items():
            tool_names = [t["name"] for t in server["tools_fn"]()]
            if tool_name in tool_names:
                return await self.call_tool(name, tool_name, arguments, empresa_id)

        return {"error": f"Tool '{tool_name}' no encontrada en ningún MCP Server"}


# Instancia global
mcp_host = MCPHost()