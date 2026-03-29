"""
RBAC Middleware — Decoradores para proteger endpoints del portal.
"""

from functools import wraps
from fastapi import HTTPException
from api.services.rbac_service import get_user_permissions


def require_permission(*required_perms: str):
    """
    Verifica que el usuario tenga al menos uno de los permisos requeridos.
    Admin tiene acceso total.

    Uso:
        @router.get("/reports/{empresa_id}")
        @require_permission("can_view_sales", "can_view_finance")
        async def get_reports(empresa_id: str, user: dict = Depends(get_current_user)):
            ...
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            empresa_id = kwargs.get("empresa_id", "")
            user = kwargs.get("user", {})
            user_id = user.get("user_id", "") if isinstance(user, dict) else ""

            if not empresa_id or not user_id:
                raise HTTPException(status_code=403, detail="Acceso denegado")

            rbac = get_user_permissions(empresa_id, user_id)

            if rbac.get("is_admin"):
                return await func(*args, **kwargs)

            perms = rbac.get("permissions", {})
            has_any = any(perms.get(p) for p in required_perms)

            if not has_any:
                raise HTTPException(
                    status_code=403,
                    detail="No tienes permiso para acceder a este recurso."
                )

            return await func(*args, **kwargs)
        return wrapper
    return decorator


def require_admin():
    """Solo admin puede acceder."""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            empresa_id = kwargs.get("empresa_id", "")
            user = kwargs.get("user", {})
            user_id = user.get("user_id", "") if isinstance(user, dict) else ""

            if not empresa_id or not user_id:
                raise HTTPException(status_code=403, detail="Acceso denegado")

            rbac = get_user_permissions(empresa_id, user_id)

            if not rbac.get("is_admin"):
                raise HTTPException(status_code=403, detail="Solo administradores.")

            return await func(*args, **kwargs)
        return wrapper
    return decorator
