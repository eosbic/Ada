"""
Document Agent - parse -> sample -> analyze -> semantic tags -> store.
"""

import json
from typing import TypedDict, Optional, List, Dict
from langgraph.graph import StateGraph, END

from models.selector import selector
from api.services.document_parser import parse_document
from api.services.memory_service import store_memory, store_report, store_vector_knowledge
from api.services.semantic_tagger import semantic_tag_document


class DocState(TypedDict, total=False):
    empresa_id: str
    user_id: str
    file_bytes: bytes
    file_name: str
    user_instruction: str
    model_preference: Optional[str]

    text_content: str
    metadata: dict
    sample: str
    semantic_tags: dict

    response: str
    alerts: List[Dict]
    model_used: str
    sources_used: List[Dict]


def parse_doc(state: DocState) -> dict:
    file_bytes = state.get("file_bytes", b"")
    file_name = state.get("file_name", "documento")

    text, metadata = parse_document(file_bytes, file_name)

    if metadata.get("error"):
        return {"response": f"Error leyendo documento: {metadata['error']}", "alerts": []}

    if not text or len(text.strip()) < 10:
        return {"response": "El documento esta vacio o no se pudo extraer texto.", "alerts": []}

    return {"text_content": text, "metadata": metadata}


def sample_text(state: DocState) -> dict:
    text = state.get("text_content", "")
    if not text:
        return {"sample": ""}

    if len(text) <= 15000:
        return {"sample": text}

    chunk = 5000
    start = text[:chunk]
    mid = len(text) // 2
    middle = text[mid - chunk // 2: mid + chunk // 2]
    end = text[-chunk:]
    sample = (
        f"--- INICIO ---\n{start}\n\n"
        f"--- MEDIO ---\n{middle}\n\n"
        f"--- FINAL ---\n{end}"
    )
    return {"sample": sample}


def analyze_doc(state: DocState) -> dict:
    sample = state.get("sample", "")
    metadata = state.get("metadata", {})
    file_name = state.get("file_name", "documento")
    instruction = state.get("user_instruction", "") or "Analisis general del documento"

    if not sample:
        return {"response": "No hay contenido para analizar.", "alerts": []}

    model, model_name = selector.get_model("document_analysis", state.get("model_preference"))

    prompt = f"""Analiza este documento.

METADATA:
- Archivo: {file_name}
- Tipo: {metadata.get('type', 'desconocido')}
- Paginas: {metadata.get('pages', 'N/A')}
- Palabras: {metadata.get('words', 'N/A')}

CONTENIDO:
{sample[:12000]}

INSTRUCCION: {instruction}

Reglas:
1) Respuesta BLUF
2) Hallazgos con evidencia
3) Recomendaciones accionables
4) Citar fuente [{file_name}]
5) Al final indicar Fuente primaria y secundaria
"""

    response = model.invoke([
        {"role": "system", "content": "Eres analista documental senior. Responde en espanol."},
        {"role": "user", "content": prompt},
    ])

    return {
        "response": response.content,
        "model_used": model_name,
        "alerts": [],
        "sources_used": [{"name": "document_content", "detail": file_name, "confidence": 0.86}],
    }


def enrich_semantic_tags(state: DocState) -> dict:
    text = state.get("text_content", "")
    file_name = state.get("file_name", "documento")
    tags = semantic_tag_document(text[:20000], file_name)
    return {"semantic_tags": tags}


def store_doc_analysis(state: DocState) -> dict:
    from api.database import sync_engine
    from sqlalchemy import text as sql_text

    file_name = state.get("file_name", "documento")
    response = state.get("response", "")
    empresa_id = state.get("empresa_id", "")
    metadata = state.get("metadata", {})
    semantic_tags = state.get("semantic_tags", {})
    model_used = state.get("model_used", "unknown")
    text_content = state.get("text_content", "")

    if not response:
        return {}

    doc_type = metadata.get("type", "document")
    title = f"Analisis: {file_name}"

    enriched = {
        "metadata": metadata,
        "semantic_tags": semantic_tags,
    }

    report_id = None
    try:
        with sync_engine.connect() as conn:
            result = conn.execute(
                sql_text(
                    """
                    INSERT INTO ada_reports
                        (empresa_id, title, report_type, source_file,
                         markdown_content, metrics_summary, alerts,
                         generated_by, allowed_roles)
                    VALUES
                        (:empresa_id, :title, :report_type, :source_file,
                         :markdown, :metrics, :alerts,
                         :generated_by, :roles)
                    RETURNING id
                    """
                ),
                {
                    "empresa_id": empresa_id,
                    "title": title,
                    "report_type": f"{doc_type}_analysis",
                    "source_file": file_name,
                    "markdown": response,
                    "metrics": json.dumps(enriched, ensure_ascii=False, default=str),
                    "alerts": json.dumps([], ensure_ascii=False),
                    "generated_by": model_used,
                    "roles": ["administrador", "gerente", "analista"],
                },
            )
            row = result.fetchone()
            if row:
                report_id = str(row[0])

            if text_content:
                raw_enriched = {
                    "metadata": metadata,
                    "semantic_tags": semantic_tags,
                    "origin": "raw_content",
                }
                conn.execute(
                    sql_text(
                        """
                        INSERT INTO ada_reports
                            (empresa_id, title, report_type, source_file,
                             markdown_content, metrics_summary, alerts,
                             generated_by, allowed_roles)
                        VALUES
                            (:empresa_id, :title, :report_type, :source_file,
                             :markdown, :metrics, :alerts,
                             :generated_by, :roles)
                        """
                    ),
                    {
                        "empresa_id": empresa_id,
                        "title": f"Contenido original: {file_name}",
                        "report_type": f"{doc_type}_raw",
                        "source_file": file_name,
                        "markdown": text_content[:12000],
                        "metrics": json.dumps(raw_enriched, ensure_ascii=False, default=str),
                        "alerts": json.dumps([], ensure_ascii=False),
                        "generated_by": "raw_parser",
                        "roles": ["administrador", "gerente", "analista"],
                    },
                )
            conn.commit()
    except Exception as e:
        print(f"DOC AGENT db error: {e}")

    header = f"[Documento: {file_name} | Empresa: {empresa_id}]"
    store_memory(f"{header}\nRESUMEN:\n{response[:1500]}", empresa_id=empresa_id)

    # dual-store policy
    analysis_text = f"{header}\n{response[:2500]}"
    store_report(
        text=analysis_text,
        empresa_id=empresa_id,
        file_name=file_name,
        report_type=f"{doc_type}_analysis",
    )
    store_vector_knowledge(
        text=analysis_text,
        empresa_id=empresa_id,
        file_name=file_name,
        doc_type=f"{doc_type}_analysis",
        metadata=enriched,
    )

    # Indexa contenido original para recuperar claves exactas (codigos, IDs, nombres).
    if text_content:
        raw_text = f"{header}\nCONTENIDO_ORIGINAL:\n{text_content[:6000]}"
        store_report(
            text=raw_text,
            empresa_id=empresa_id,
            file_name=file_name,
            report_type=f"{doc_type}_raw",
        )
        store_vector_knowledge(
            text=raw_text,
            empresa_id=empresa_id,
            file_name=file_name,
            doc_type=f"{doc_type}_raw",
            metadata={"origin": "raw_content", "metadata": metadata},
        )

    if report_id and empresa_id:
        from api.services.kg_pipeline import run_kg_pipeline
        run_kg_pipeline(report_id, empresa_id, response, "")

    return {}


graph = StateGraph(DocState)
graph.add_node("parse", parse_doc)
graph.add_node("sample", sample_text)
graph.add_node("analyze", analyze_doc)
graph.add_node("tags", enrich_semantic_tags)
graph.add_node("store", store_doc_analysis)

graph.set_entry_point("parse")
graph.add_edge("parse", "sample")
graph.add_edge("sample", "analyze")
graph.add_edge("analyze", "tags")
graph.add_edge("tags", "store")
graph.add_edge("store", END)

document_agent = graph.compile()
