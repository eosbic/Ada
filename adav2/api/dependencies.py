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

async def get_current_user(token: str = Depends(oauth2_scheme)):
    payload = decode_token(token)
    return payload