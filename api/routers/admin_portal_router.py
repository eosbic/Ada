"""
Admin Portal Router — Sirve el admin SPA en /admin.
"""

import os
from fastapi import APIRouter
from fastapi.responses import FileResponse

router = APIRouter()

ADMIN_PORTAL_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "portal", "admin.html")
)


@router.get("/admin")
async def serve_admin_portal():
    """Sirve el portal de administracion SPA."""
    if not os.path.exists(ADMIN_PORTAL_PATH):
        return {"error": "Admin portal not found", "path": ADMIN_PORTAL_PATH}
    return FileResponse(ADMIN_PORTAL_PATH)
