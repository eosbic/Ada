"""
Image Agent - pipeline de vision + etiquetado semantico + vector store.
"""

import json
from typing import TypedDict, Optional, List, Dict
from langgraph.graph import StateGraph, END

from api.services.semantic_tagger import semantic_tag_document
from api.services.memory_service import store_image_report


class ImageState(TypedDict, total=False):
    empresa_id: str
    user_id: str
    file_bytes: bytes
    file_name: str
    mime_type: str
    user_instruction: str
    model_preference: Optional[str]

    # pipeline
    visual_analysis: str
    semantic_tags: Dict

    # output
    response: str
    alerts: List[Dict]
    model_used: str
    sources_used: List[Dict]


def parse_image(state: ImageState) -> dict:
    file_name = state.get("file_name", "image")
    file_bytes = state.get("file_bytes", b"")
    mime_type = state.get("mime_type", "")

    if not file_bytes:
        return {"response": "No se recibio imagen para analizar.", "alerts": []}

    if not mime_type:
        ext = file_name.rsplit(".", 1)[-1].lower() if "." in file_name else ""
        mime_type = {
            "png": "image/png",
            "jpg": "image/jpeg",
            "jpeg": "image/jpeg",
            "webp": "image/webp",
            "bmp": "image/bmp",
        }.get(ext, "image/jpeg")

    return {"mime_type": mime_type}


def analyze_image_with_vision(state: ImageState) -> dict:
    import os

    file_bytes = state.get("file_bytes", b"")
    file_name = state.get("file_name", "image")
    mime_type = state.get("mime_type", "image/jpeg")
    instruction = state.get("user_instruction", "") or "Analiza la imagen con foco de negocio."

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return {
            "response": "No hay GEMINI_API_KEY configurada para analisis visual.",
            "model_used": "unavailable",
            "alerts": [{"level": "warning", "message": "Gemini API key no configurada"}],
        }

    try:
        import google.generativeai as genai

        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-2.0-flash")

        prompt = (
            "Eres analista senior de documentos visuales. "
            "Entrega respuesta en formato BLUF, luego evidencia visual, luego acciones. "
            "No inventes datos que no aparezcan en la imagen.\n\n"
            f"Instruccion del usuario: {instruction}\n"
            f"Archivo: {file_name}"
        )

        resp = model.generate_content(
            [
                prompt,
                {"mime_type": mime_type, "data": file_bytes},
            ]
        )
        text = (getattr(resp, "text", "") or "").strip()
        if not text:
            text = "No se pudo obtener analisis visual."

        return {
            "visual_analysis": text,
            "response": text,
            "model_used": "gemini-2.0-flash-vision",
            "sources_used": [
                {"name": "gemini_vision", "detail": file_name, "confidence": 0.85},
            ],
        }

    except Exception as e:
        print(f"IMAGE AGENT vision error: {e}")
        return {
            "response": f"Error en analisis de imagen: {e}",
            "model_used": "error",
            "alerts": [{"level": "warning", "message": str(e)}],
        }


def build_semantic_tags(state: ImageState) -> dict:
    analysis = state.get("visual_analysis", "")
    file_name = state.get("file_name", "image")
    tags = semantic_tag_document(analysis, file_name)
    tags["categoria"] = tags.get("categoria") or "imagen"
    tags["tipo_doc"] = "imagen"
    return {"semantic_tags": tags}


def store_image_analysis(state: ImageState) -> dict:
    from api.database import sync_engine
    from sqlalchemy import text as sql_text

    empresa_id = state.get("empresa_id", "")
    file_name = state.get("file_name", "image")
    response = state.get("response", "")
    model_used = state.get("model_used", "unknown")
    tags = state.get("semantic_tags", {})

    if not empresa_id or not response:
        return {}

    try:
        with sync_engine.connect() as conn:
            conn.execute(
                sql_text(
                    """
                    INSERT INTO ada_reports
                        (empresa_id, title, report_type, source_file,
                         markdown_content, metrics_summary, alerts,
                         generated_by, allowed_roles)
                    VALUES
                        (:empresa_id, :title, 'image_analysis', :source_file,
                         :markdown, :metrics, :alerts, :generated_by, :roles)
                    """
                ),
                {
                    "empresa_id": empresa_id,
                    "title": f"Analisis visual: {file_name}",
                    "source_file": file_name,
                    "markdown": response,
                    "metrics": json.dumps(tags, ensure_ascii=False),
                    "alerts": json.dumps([], ensure_ascii=False),
                    "generated_by": model_used,
                    "roles": ["administrador", "gerente", "analista"],
                },
            )
            conn.commit()
    except Exception as e:
        print(f"IMAGE AGENT store DB error: {e}")

    try:
        store_image_report(
            text=f"[Imagen: {file_name}]\\n{response}",
            empresa_id=empresa_id,
            file_name=file_name,
            metadata=tags,
        )
    except Exception as e:
        print(f"IMAGE AGENT qdrant store error: {e}")

    return {}


graph = StateGraph(ImageState)
graph.add_node("parse", parse_image)
graph.add_node("vision", analyze_image_with_vision)
graph.add_node("tags", build_semantic_tags)
graph.add_node("store", store_image_analysis)

graph.set_entry_point("parse")
graph.add_edge("parse", "vision")
graph.add_edge("vision", "tags")
graph.add_edge("tags", "store")
graph.add_edge("store", END)

image_agent = graph.compile()
