"""
Upload Router - endpoint para subir archivos multimodales.
"""

from fastapi import APIRouter, UploadFile, File, Form, Depends, HTTPException
from typing import Optional

from api.agents.excel_agent import excel_agent
from api.agents.document_agent import document_agent
from api.agents.image_agent import image_agent
from api.dependencies import get_current_user

router = APIRouter()

EXCEL_EXTENSIONS = {".xlsx", ".xls", ".csv"}
DOC_EXTENSIONS = {".pdf", ".txt", ".md", ".markdown", ".docx", ".doc"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
ALL_EXTENSIONS = EXCEL_EXTENSIONS | DOC_EXTENSIONS | IMAGE_EXTENSIONS
MAX_FILE_SIZE = 25 * 1024 * 1024  # 25MB


@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    instruction: Optional[str] = Form(None),
    industry_type: Optional[str] = Form("generic"),
    current_user: dict = Depends(get_current_user),
):
    file_name = file.filename or "archivo"
    ext = "." + file_name.rsplit(".", 1)[-1].lower() if "." in file_name else ""

    if ext not in ALL_EXTENSIONS:
        return {
            "error": f"Formato no soportado: {ext}. Formatos validos: {', '.join(sorted(ALL_EXTENSIONS))}"
        }

    contents = await file.read()
    if not contents:
        file.file.seek(0)
        contents = file.file.read()

    empresa_id = current_user["empresa_id"]
    user_id = current_user["user_id"]

    # RBAC: verificar permiso can_upload_files
    from api.services.rbac_service import get_user_permissions
    rbac = get_user_permissions(empresa_id, user_id)
    if not rbac["is_admin"] and not rbac["permissions"].get("can_upload_files", False):
        raise HTTPException(status_code=403, detail="No tienes permiso para subir archivos. Contacta a tu administrador.")

    print(f"UPLOAD: {file_name} ({len(contents) // 1024}KB), ext={ext}")

    if len(contents) == 0:
        return {"error": "Archivo vacio"}

    if len(contents) > MAX_FILE_SIZE:
        return {"error": f"Archivo muy grande ({len(contents) // 1024 // 1024}MB). Maximo 25MB."}

    try:
        if ext in EXCEL_EXTENSIONS:
            result = await excel_agent.ainvoke({
                "file_bytes": contents,
                "file_name": file_name,
                "empresa_id": empresa_id,
                "user_id": user_id,
                "user_instruction": instruction or "",
                "industry_type": industry_type or "generic",
            })

            return {
                "file_name": file_name,
                "file_type": "excel",
                "response": result.get("response", "No se pudo generar analisis"),
                "alerts": result.get("alerts", []),
                "model_used": result.get("model_used", "unknown"),
                "sources_used": result.get("sources_used", []),
            }

        if ext in DOC_EXTENSIONS:
            result = await document_agent.ainvoke({
                "file_bytes": contents,
                "file_name": file_name,
                "empresa_id": empresa_id,
                "user_id": user_id,
                "user_instruction": instruction or "",
            })

            return {
                "file_name": file_name,
                "file_type": ext.replace(".", ""),
                "response": result.get("response", "No se pudo generar analisis"),
                "alerts": result.get("alerts", []),
                "model_used": result.get("model_used", "unknown"),
                "sources_used": result.get("sources_used", []),
            }

        if ext in IMAGE_EXTENSIONS:
            result = await image_agent.ainvoke({
                "file_bytes": contents,
                "file_name": file_name,
                "mime_type": file.content_type or "",
                "empresa_id": empresa_id,
                "user_id": user_id,
                "user_instruction": instruction or "",
            })

            return {
                "file_name": file_name,
                "file_type": "image",
                "response": result.get("response", "No se pudo generar analisis"),
                "alerts": result.get("alerts", []),
                "model_used": result.get("model_used", "unknown"),
                "sources_used": result.get("sources_used", []),
            }

    except Exception as e:
        print(f"ERROR Upload: {str(e)}")
        import traceback
        traceback.print_exc()
        return {"error": f"Error analizando archivo: {str(e)}"}
