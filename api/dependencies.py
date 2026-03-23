from fastapi import Header, HTTPException
from uuid import UUID
from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer
from api.security import decode_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")

async def get_tenant_id(x_tenant_id: str = Header(None)) -> UUID:
    if not x_tenant_id:
        raise HTTPException(
            status_code=400,
            detail="X-Tenant-ID header is required"
        )

    try:
        return UUID(x_tenant_id)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="Invalid tenant UUID"
        )

async def get_current_user(token: str = Depends(oauth2_scheme)) -> dict:
    """Extrae user_id y empresa_id del JWT."""
    payload = decode_token(token)
    user_id = payload.get("user_id")
    empresa_id = payload.get("empresa_id")
    if not user_id or not empresa_id:
        raise HTTPException(
            status_code=401,
            detail="Token missing user_id or empresa_id"
        )
    return {"user_id": user_id, "empresa_id": empresa_id}