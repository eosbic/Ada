"""
Image Agent - classify -> vision -> tags -> store.
Clasificación automática + prompts especializados por tipo de imagen.
"""

import json
from typing import TypedDict, Optional, List, Dict
from langgraph.graph import StateGraph, END

from api.services.semantic_tagger import semantic_tag_document
from api.services.memory_service import store_image_report
from api.services.dna_loader import load_company_dna
from api.services.image_protocols import build_image_prompt, infer_type_from_instruction
from api.services.industry_protocols import get_protocol


class ImageState(TypedDict, total=False):
    empresa_id: str
    user_id: str
    file_bytes: bytes
    file_name: str
    mime_type: str
    user_instruction: str
    model_preference: Optional[str]

    # pipeline
    image_type: str
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


def classify_image(state: ImageState) -> dict:
    """Clasifica la imagen: primero por instrucción, luego por visión Gemini."""
    import os

    instruction = state.get("user_instruction", "")

    # 1) Inferir desde la instrucción del usuario
    inferred = infer_type_from_instruction(instruction)
    if inferred:
        print(f"IMAGE AGENT: tipo inferido de instrucción -> {inferred}")
        return {"image_type": inferred}

    # 2) Si no hay instrucción clara, clasificar con Gemini (llamada mínima)
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return {"image_type": "general"}

    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-2.0-flash")

        file_bytes = state.get("file_bytes", b"")
        mime_type = state.get("mime_type", "image/jpeg")

        resp = model.generate_content(
            [
                "Clasifica esta imagen en UNA de estas categorías: "
                "documento_fisico | grafica_metricas | pieza_marketing | "
                "persona_equipo | producto | captura_pantalla | general\n"
                "Responde SOLO con la categoría, nada más.",
                {"mime_type": mime_type, "data": file_bytes},
            ]
        )
        raw = (getattr(resp, "text", "") or "").strip().lower().replace(" ", "_")
        valid_types = {
            "documento_fisico", "grafica_metricas", "pieza_marketing",
            "persona_equipo", "producto", "captura_pantalla", "general",
        }
        image_type = raw if raw in valid_types else "general"
        print(f"IMAGE AGENT: tipo clasificado por Gemini -> {image_type}")
        return {"image_type": image_type}

    except Exception as e:
        print(f"IMAGE AGENT classify error: {e}")
        return {"image_type": "general"}


def analyze_image_with_vision(state: ImageState) -> dict:
    import os

    file_bytes = state.get("file_bytes", b"")
    file_name = state.get("file_name", "image")
    mime_type = state.get("mime_type", "image/jpeg")
    instruction = state.get("user_instruction", "") or "Analiza la imagen con foco de negocio."
    image_type = state.get("image_type", "general")

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

        empresa_id = state.get("empresa_id", "")
        industry_type = "generic"
        custom_prompt = ""
        kpis_sector = ""
        if empresa_id:
            dna = load_company_dna(empresa_id)
            industry_type = dna.get("industry_type", "generic") or "generic"
            custom_prompt = dna.get("custom_prompt", "")
            kpis_sector = ", ".join(get_protocol(industry_type).get("kpis", []))

        prompt = build_image_prompt(
            image_type=image_type,
            industry_type=industry_type,
            custom_prompt=custom_prompt,
            user_instruction=instruction,
            file_name=file_name,
            kpis_sector=kpis_sector,
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
    tags["image_type"] = state.get("image_type", "general")
    return {"semantic_tags": tags}


def store_image_analysis(state: ImageState) -> dict:
    from api.database import sync_engine
    from sqlalchemy import text as sql_text

    empresa_id = state.get("empresa_id", "")
    file_name = state.get("file_name", "image")
    response = state.get("response", "")
    model_used = state.get("model_used", "unknown")
    tags = state.get("semantic_tags", {})
    user_instruction = state.get("user_instruction", "")

    if not empresa_id or not response:
        return {}

    if user_instruction and len(user_instruction) > 5:
        title = user_instruction[:50]
    else:
        title = f"Análisis visual: {file_name}"

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
                    "title": title,
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
graph.add_node("classify", classify_image)
graph.add_node("vision", analyze_image_with_vision)
graph.add_node("tags", build_semantic_tags)
graph.add_node("store", store_image_analysis)

graph.set_entry_point("parse")
graph.add_edge("parse", "classify")
graph.add_edge("classify", "vision")
graph.add_edge("vision", "tags")
graph.add_edge("tags", "store")
graph.add_edge("store", END)

image_agent = graph.compile()
