"""
Consolidation Agent — Analisis multi-reporte con LangGraph.
Agrega datos de multiples periodos y genera analisis consolidado.
"""

import json
from typing import TypedDict, Optional, List, Dict
from langgraph.graph import StateGraph, END
from models.selector import selector
from api.services.report_consolidator import (
    parse_period,
    fetch_reports_for_period,
    consolidate_metrics,
    format_consolidation_for_llm,
)
from api.services.memory_service import store_memory


class ConsolidationState(TypedDict, total=False):
    message: str
    empresa_id: str
    user_id: str
    model_preference: Optional[str]
    period_start: str
    period_end: str
    source_filter: Optional[str]
    consolidated: Optional[Dict]
    reports: Optional[List[Dict]]
    formatted_context: str
    report_count: int
    response: str
    model_used: str
    input_tokens: int
    output_tokens: int


async def parse_request(state: ConsolidationState) -> dict:
    """Usa Gemini Flash para extraer periodo, filtro y tipo de analisis del mensaje."""
    message = state.get("message", "")
    model, _ = selector.get_model("routing")

    response = await model.ainvoke([
        {"role": "system", "content": (
            "Extrae del mensaje del usuario la informacion para un reporte consolidado.\n"
            "Responde SOLO JSON:\n"
            '{"period_text": "...", "source_filter": null, "analysis_type": "general"}\n\n'
            "- period_text: el periodo mencionado tal cual (ej: 'año 2025', 'Q1 2026', 'ultimos 6 meses', 'marzo')\n"
            "- source_filter: si menciona un tipo de archivo o area especifica (ej: 'ventas', 'cartera'), poner la palabra clave. Si no, null.\n"
            "- analysis_type: 'general', 'tendencias', 'comparativo', 'resumen'\n"
            "Sin markdown, sin explicacion."
        )},
        {"role": "user", "content": message},
    ])

    try:
        raw = response.content.strip().replace("```json", "").replace("```", "").strip()
        parsed = json.loads(raw)
    except Exception:
        parsed = {"period_text": message, "source_filter": None, "analysis_type": "general"}

    period_text = parsed.get("period_text", message)
    source_filter = parsed.get("source_filter")

    start, end = parse_period(period_text)

    print(f"CONSOLIDATION: parsed -> period={start}..{end}, filter={source_filter}")

    return {
        "period_start": start,
        "period_end": end,
        "source_filter": source_filter,
    }


def load_and_consolidate(state: ConsolidationState) -> dict:
    """Carga reportes del periodo y consolida metricas."""
    empresa_id = state.get("empresa_id", "")
    period_start = state.get("period_start", "")
    period_end = state.get("period_end", "")
    source_filter = state.get("source_filter")

    pattern = f"%{source_filter}%" if source_filter else None
    reports = fetch_reports_for_period(
        empresa_id=empresa_id,
        period_start=period_start,
        period_end=period_end,
        source_file_pattern=pattern,
    )

    # Si el filtro no encuentra nada, reintentar sin filtro
    if not reports and source_filter:
        print(f"CONSOLIDATION: Sin resultados con filtro '{source_filter}', reintentando sin filtro")
        reports = fetch_reports_for_period(
            empresa_id=empresa_id,
            period_start=period_start,
            period_end=period_end,
        )

    if not reports:
        return {
            "response": (
                f"No encontre reportes para el periodo {period_start} a {period_end}. "
                "Verifica que existan analisis guardados en ese rango de fechas."
            ),
            "report_count": 0,
            "consolidated": {},
            "reports": [],
            "formatted_context": "",
        }

    consolidated = consolidate_metrics(reports)
    formatted = format_consolidation_for_llm(consolidated, reports)

    print(f"CONSOLIDATION: {len(reports)} reportes consolidados, {len(consolidated.get('months_covered', []))} meses")

    return {
        "consolidated": consolidated,
        "reports": reports,
        "formatted_context": formatted,
        "report_count": len(reports),
    }


async def analyze_consolidated(state: ConsolidationState) -> dict:
    """Genera analisis consolidado con el LLM."""
    # Si ya hay respuesta (error de no reportes), saltar
    if state.get("response"):
        return {}

    formatted = state.get("formatted_context", "")
    message = state.get("message", "")
    consolidated = state.get("consolidated", {})
    report_count = state.get("report_count", 0)

    if not formatted:
        return {"response": "No hay datos suficientes para consolidar."}

    model, model_name = selector.get_model("excel_analysis", state.get("model_preference"))

    prompt = f"""Analiza estos datos consolidados de {report_count} reportes de negocio.

{formatted}

## SOLICITUD DEL USUARIO: {message}

INSTRUCCIONES:
1. BLUF: hallazgo mas importante primero (3 lineas max)
2. RESUMEN EJECUTIVO: panorama general del periodo
3. METRICAS CLAVE: los numeros mas relevantes con contexto
4. EVOLUCION MENSUAL: como cambiaron las metricas mes a mes
5. TENDENCIAS: que sube, que baja, que se mantiene (usar flechas ↑↓→)
6. ALERTAS ACUMULADAS: patrones recurrentes de alerta
7. RECOMENDACIONES: maximo 5, concretas y accionables

REGLAS:
- NO inventar datos. Solo usar lo proporcionado.
- Formato numerico: separador de miles con punto, decimales con coma (formato colombiano)
- Citar archivos fuente cuando sea posible
- Tono de junta directiva. Sin suavizar malas noticias.
- Si datos incompletos, decirlo explicitamente.
"""

    response = await model.ainvoke([
        {"role": "system", "content": (
            "Eres un analista financiero senior especializado en consolidacion de reportes. "
            "Respondes en español. Tu trabajo es cruzar multiples reportes y encontrar "
            "patrones, tendencias y riesgos que no son visibles en reportes individuales."
        )},
        {"role": "user", "content": prompt},
    ])

    # Extraer tokens si disponibles
    input_tokens = 0
    output_tokens = 0
    try:
        meta = getattr(response, "response_metadata", {}) or {}
        usage = meta.get("usage", {})
        input_tokens = usage.get("input_tokens", len(prompt) // 4)
        output_tokens = usage.get("output_tokens", len(response.content) // 4)
    except Exception:
        input_tokens = len(prompt) // 4
        output_tokens = len(response.content) // 4

    print(f"CONSOLIDATION: Analisis generado con {model_name}")

    return {
        "response": response.content,
        "model_used": model_name,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
    }


def store_consolidated_report(state: ConsolidationState) -> dict:
    """Guarda el reporte consolidado en ada_reports y Qdrant."""
    response = state.get("response", "")
    empresa_id = state.get("empresa_id", "")
    report_count = state.get("report_count", 0)
    consolidated = state.get("consolidated", {})
    period_start = state.get("period_start", "")
    period_end = state.get("period_end", "")

    if not response or not empresa_id or report_count == 0:
        return {}

    title = f"Consolidado {period_start} a {period_end} ({report_count} reportes)"
    model_used = state.get("model_used", "unknown")

    metrics_summary = consolidated.get("global_totals", {})
    metrics_summary["_consolidation"] = {
        "total_reports": report_count,
        "months_covered": consolidated.get("months_covered", []),
        "period": consolidated.get("period", ""),
    }

    try:
        from api.database import sync_engine
        from sqlalchemy import text as sql_text

        with sync_engine.connect() as conn:
            conn.execute(
                sql_text("""
                    INSERT INTO ada_reports
                        (empresa_id, title, report_type, source_file,
                         markdown_content, metrics_summary, generated_by,
                         requires_action, allowed_roles)
                    VALUES
                        (:eid, :title, 'consolidated_analysis', :source,
                         :markdown, :metrics, :generated_by,
                         FALSE, :roles)
                """),
                {
                    "eid": empresa_id,
                    "title": title,
                    "source": f"consolidation_{period_start}_{period_end}",
                    "markdown": response,
                    "metrics": json.dumps(metrics_summary, ensure_ascii=False, default=str),
                    "generated_by": model_used,
                    "roles": ["administrador", "gerente", "analista"],
                }
            )
            conn.commit()
        print(f"CONSOLIDATION: Reporte consolidado guardado en ada_reports")
    except Exception as e:
        print(f"CONSOLIDATION: Error guardando en DB: {e}")

    # Guardar resumen en Qdrant
    try:
        header = f"[Consolidado: {period_start} a {period_end} | {report_count} reportes | Empresa: {empresa_id}]"
        store_memory(f"{header}\n{response[:1500]}")
    except Exception as e:
        print(f"CONSOLIDATION: Error guardando en Qdrant: {e}")

    return {}


graph = StateGraph(ConsolidationState)
graph.add_node("parse_request", parse_request)
graph.add_node("load_and_consolidate", load_and_consolidate)
graph.add_node("analyze_consolidated", analyze_consolidated)
graph.add_node("store_consolidated_report", store_consolidated_report)

graph.set_entry_point("parse_request")
graph.add_edge("parse_request", "load_and_consolidate")
graph.add_edge("load_and_consolidate", "analyze_consolidated")
graph.add_edge("analyze_consolidated", "store_consolidated_report")
graph.add_edge("store_consolidated_report", END)

consolidation_agent = graph.compile()
