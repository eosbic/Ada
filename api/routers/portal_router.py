"""
Portal Router — Sirve el frontend SPA del portal.

NOTA: Este archivo existe para que el endpoint /portal NO se pierda
en cada merge de Claude Code. Al estar en routers/, se incluye
automáticamente en el api_router.
"""

import os
from fastapi import APIRouter
from fastapi.responses import FileResponse

router = APIRouter()

PORTAL_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "portal", "index.html")
)


@router.get("/portal")
async def serve_portal():
    """Sirve el portal web SPA."""
    if not os.path.exists(PORTAL_PATH):
        return {"error": "Portal not found", "path": PORTAL_PATH}
    return FileResponse(PORTAL_PATH)
