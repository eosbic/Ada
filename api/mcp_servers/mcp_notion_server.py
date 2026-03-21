"""
MCP Server — Notion
Protocolo MCP estándar con tools expuestas.
Corre como proceso separado, se comunica via stdio.

Tools: notion_search, notion_read_page, notion_create_page, notion_query_database
"""

import os
import sys
import json
import asyncio
import httpx
from typing import Any


NOTION_API_VERSION = "2022-06-28"
NOTION_BASE_URL = "https://api.notion.com/v1"


# ─── NOTION TOOLS ────────────────────────────────────────

def _headers(api_key: str) -> dict:
    return {
        "Authorization": f"Bearer {api_key}",
        "Notion-Version": NOTION_API_VERSION,
        "Content-Type": "application/json",
    }


async def notion_search(api_key: str, query: str, filter_type: str = None, max_results: int = 10) -> list:
    payload = {"query": query, "page_size": max_results}
    if filter_type in ("page", "database"):
        payload["filter"] = {"value": filter_type, "property": "object"}

    async with httpx.AsyncClient() as client:
        resp = await client.post(f"{NOTION_BASE_URL}/search", headers=_headers(api_key), json=payload, timeout=15)

    if resp.status_code != 200:
        return [{"error": f"Notion API error: {resp.status_code}"}]

    results = []
    for item in resp.json().get("results", []):
        obj_type = item.get("object", "")
        title = ""
        if obj_type == "page":
            for key, val in item.get("properties", {}).items():
                if val.get("type") == "title":
                    title = "".join(t.get("plain_text", "") for t in val.get("title", []))
                    break
        elif obj_type == "database":
            title = "".join(t.get("plain_text", "") for t in item.get("title", []))

        results.append({
            "id": item.get("id"), "type": obj_type,
            "title": title or "Sin título",
            "url": item.get("url", ""),
            "last_edited": item.get("last_edited_time", "")[:10],
        })
    return results


async def notion_read_page(api_key: str, page_id: str) -> dict:
    hdrs = _headers(api_key)

    async with httpx.AsyncClient() as client:
        page_resp = await client.get(f"{NOTION_BASE_URL}/pages/{page_id}", headers=hdrs, timeout=15)
        if page_resp.status_code != 200:
            return {"error": f"Error: {page_resp.status_code}"}

        blocks_resp = await client.get(f"{NOTION_BASE_URL}/blocks/{page_id}/children?page_size=100", headers=hdrs, timeout=15)

    page_data = page_resp.json()
    blocks = blocks_resp.json().get("results", []) if blocks_resp.status_code == 200 else []

    content_parts = []
    for block in blocks:
        bt = block.get("type", "")
        bd = block.get(bt, {})
        if "rich_text" in bd:
            text = "".join(t.get("plain_text", "") for t in bd["rich_text"])
            if text.strip():
                if bt.startswith("heading"):
                    content_parts.append(f"{'#' * int(bt[-1])} {text}")
                elif bt == "bulleted_list_item":
                    content_parts.append(f"- {text}")
                elif bt == "numbered_list_item":
                    content_parts.append(f"1. {text}")
                elif bt == "to_do":
                    checked = "✅" if bd.get("checked") else "⬜"
                    content_parts.append(f"{checked} {text}")
                else:
                    content_parts.append(text)

    title = ""
    for key, val in page_data.get("properties", {}).items():
        if val.get("type") == "title":
            title = "".join(t.get("plain_text", "") for t in val.get("title", []))
            break

    return {
        "id": page_id, "title": title or "Sin título",
        "url": page_data.get("url", ""),
        "content": "\n".join(content_parts),
    }


async def notion_create_page(api_key: str, title: str, content: str = "", parent_page_id: str = None, database_id: str = None) -> dict:
    if database_id:
        parent = {"database_id": database_id}
        properties = {"Name": {"title": [{"text": {"content": title}}]}}
    elif parent_page_id:
        parent = {"page_id": parent_page_id}
        properties = {"title": {"title": [{"text": {"content": title}}]}}
    else:
        return {"error": "Se necesita parent_page_id o database_id"}

    body = {"parent": parent, "properties": properties}
    if content:
        body["children"] = [
            {"object": "block", "type": "paragraph",
             "paragraph": {"rich_text": [{"type": "text", "text": {"content": p.strip()}}]}}
            for p in content.split("\n")[:50] if p.strip()
        ]

    async with httpx.AsyncClient() as client:
        resp = await client.post(f"{NOTION_BASE_URL}/pages", headers=_headers(api_key), json=body, timeout=15)

    if resp.status_code != 200:
        return {"error": f"Error creando: {resp.text[:200]}"}

    data = resp.json()
    return {"id": data.get("id"), "title": title, "url": data.get("url", ""), "status": "created"}


async def notion_query_database(api_key: str, database_id: str, max_results: int = 20) -> list:
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{NOTION_BASE_URL}/databases/{database_id}/query",
            headers=_headers(api_key), json={"page_size": max_results}, timeout=15
        )

    if resp.status_code != 200:
        return []

    results = []
    for page in resp.json().get("results", []):
        row = {"id": page.get("id")}
        for key, val in page.get("properties", {}).items():
            vt = val.get("type", "")
            if vt == "title":
                row[key] = "".join(t.get("plain_text", "") for t in val.get("title", []))
            elif vt == "rich_text":
                row[key] = "".join(t.get("plain_text", "") for t in val.get("rich_text", []))
            elif vt == "number":
                row[key] = val.get("number")
            elif vt == "select":
                row[key] = val.get("select", {}).get("name", "") if val.get("select") else ""
            elif vt == "date":
                row[key] = val.get("date", {}).get("start", "") if val.get("date") else ""
            elif vt == "checkbox":
                row[key] = val.get("checkbox", False)
        results.append(row)
    return results


# ─── MCP TOOL DEFINITIONS ────────────────────────────────

TOOLS = [
    {
        "name": "notion_search",
        "description": "Busca páginas y bases de datos en Notion del usuario",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Texto a buscar"},
                "filter_type": {"type": "string", "enum": ["page", "database"], "description": "Filtrar por tipo"},
                "max_results": {"type": "integer", "default": 10},
            },
            "required": ["query"]
        }
    },
    {
        "name": "notion_read_page",
        "description": "Lee el contenido completo de una página de Notion",
        "inputSchema": {
            "type": "object",
            "properties": {
                "page_id": {"type": "string", "description": "ID de la página"},
            },
            "required": ["page_id"]
        }
    },
    {
        "name": "notion_create_page",
        "description": "Crea una nueva página en Notion",
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "content": {"type": "string", "default": ""},
                "parent_page_id": {"type": "string"},
                "database_id": {"type": "string"},
            },
            "required": ["title"]
        }
    },
    {
        "name": "notion_query_database",
        "description": "Consulta una base de datos de Notion",
        "inputSchema": {
            "type": "object",
            "properties": {
                "database_id": {"type": "string"},
                "max_results": {"type": "integer", "default": 20},
            },
            "required": ["database_id"]
        }
    },
]


# ─── MCP HANDLER ─────────────────────────────────────────

async def handle_tool_call(tool_name: str, arguments: dict, api_key: str) -> Any:
    """Ejecuta una tool MCP de Notion."""
    if tool_name == "notion_search":
        return await notion_search(api_key, arguments["query"],
                                    arguments.get("filter_type"), arguments.get("max_results", 10))
    elif tool_name == "notion_read_page":
        return await notion_read_page(api_key, arguments["page_id"])
    elif tool_name == "notion_create_page":
        return await notion_create_page(api_key, arguments["title"],
                                         arguments.get("content", ""),
                                         arguments.get("parent_page_id"),
                                         arguments.get("database_id"))
    elif tool_name == "notion_query_database":
        return await notion_query_database(api_key, arguments["database_id"],
                                            arguments.get("max_results", 20))
    else:
        return {"error": f"Tool '{tool_name}' no encontrada"}


def get_tools() -> list:
    """Retorna definiciones de tools MCP."""
    return TOOLS