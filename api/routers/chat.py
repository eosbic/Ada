from fastapi import APIRouter, Depends
from api.services.agent_runner import run_agent
from api.dependencies import get_current_user

router = APIRouter()


@router.post("/chat")
async def chat(data: dict, current_user: dict = Depends(get_current_user)):
    message = data.get("message")
    empresa_id = current_user["empresa_id"]
    user_id = current_user["user_id"]
    has_file = bool(data.get("has_file", False))
    file_type = data.get("file_type")
    source = data.get("source", "api")

    if not message:
        return {"error": "message required"}

    result = await run_agent(
        message=message,
        empresa_id=empresa_id,
        user_id=user_id,
        has_file=has_file,
        file_type=file_type,
        source=source,
    )

    return result
