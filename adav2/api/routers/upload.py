"""
Upload Router - endpoint para subir archivos multimodales.
"""

from fastapi import APIRouter, UploadFile, File, Form
from typing import Optional

from api.agents.excel_agent import excel_agent
from api.agents.document_agent import document_agent
from api.agents.image_agent import image_agent

router = APIRouter()

EXCEL_EXTENSIONS = {".xlsx", ".xls", ".csv"}
DOC_EXTENSIONS = {".pdf", ".txt", ".md", ".markdown", ".docx", ".doc"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
ALL_EXTENSIONS = EXCEL_EXTENSIONS | DOC_EXTENSIONS | IMAGE_EXTENSIONS
MAX_FILE_SIZE = 25 * 1024 * 1024  # 25MB


@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    empresa_id: str = Form(...),
    instruction: Optional[str] = Form(None),
    industry_type: Optional[str] = Form("generic"),
):
    file_name = file.filename or "archivo"
    ext = "." + file_name.rsplit(".", 1)[-1].lower() if "." in file_name else ""

    # Auto-detectar industry_type del perfil de la empresa
    if not industry_type or industry_type == "generic":
        try:
            from api.database import sync_engine
            from sqlalchemy import text as sql_text
            with sync_engine.connect() as conn:
                row = conn.execute(
                    sql_text("SELECT industry_type FROM ada_company_profile WHERE empresa_id = :eid"),
                    {"eid": empresa_id}
                ).fetchone()
                if row and row.industry_type:
                    industry_type = row.industry_type
                    print(f"UPLOAD: industry_type from profile → {industry_type}")
        except Exception as e:
            print(f"UPLOAD: Could not fetch industry_type: {e}")
            

    if ext not in ALL_EXTENSIONS:
        return {
            "error": f"Formato no soportado: {ext}. Formatos validos: {', '.join(sorted(ALL_EXTENSIONS))}"
        }

    contents = await file.read()
    if not contents:
        file.file.seek(0)
        contents = file.file.read()

    print(f"UPLOAD: {file_name} ({len(contents) // 1024}KB), ext={ext}")

    if len(contents) == 0:
        return {"error": "Archivo vacio"}

    if len(contents) > MAX_FILE_SIZE:
        return {"error": f"Archivo muy grande ({len(contents) // 1024 // 1024}MB). Maximo 25MB."}

    try:
        if ext in EXCEL_EXTENSIONS:
            result = excel_agent.invoke({
                "file_bytes": contents,
                "file_name": file_name,
                "empresa_id": empresa_id,
                "user_id": "",
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
            result = document_agent.invoke({
                "file_bytes": contents,
                "file_name": file_name,
                "empresa_id": empresa_id,
                "user_id": "",
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
            result = image_agent.invoke({
                "file_bytes": contents,
                "file_name": file_name,
                "mime_type": file.content_type or "",
                "empresa_id": empresa_id,
                "user_id": "",
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
