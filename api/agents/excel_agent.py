"""
Excel Analyst — Smart Data Pipeline de 8 nodos.
"""

import json
import numpy as np
import pandas as pd
from io import BytesIO
from typing import TypedDict, Optional, List, Dict
from langgraph.graph import StateGraph, END
from models.selector import selector
from api.services.memory_service import store_memory, store_report, store_vector_knowledge
from api.services.semantic_tagger import semantic_tag_document
from api.services.industry_protocols import build_sector_prompt
from api.services.dna_loader import load_company_dna


class ExcelState(TypedDict, total=False):
    empresa_id: str
    user_id: str
    file_bytes: bytes
    file_name: str
    user_instruction: str
    industry_type: str
    model_preference: Optional[str]
    raw_data: Optional[Dict]
    calculations: Optional[Dict]
    statistical_profile: Optional[Dict]
    sample: Optional[List[Dict]]
    anomalies: Optional[List[Dict]]
    response: str
    alerts: List[Dict]
    model_used: str


def parse_file(state: ExcelState) -> dict:
    data = state.get("file_bytes")
    file_name = state.get("file_name", "archivo")
    print(f"DEBUG PARSE: file_name={file_name}, file_bytes type={type(data)}, len={len(data) if data else 0}")
    if not data or len(data) == 0:
        return {"response": "Error: archivo vacío.", "alerts": []}
    try:
        if file_name.endswith(".csv"):
            df = pd.read_csv(BytesIO(data))
            df.columns = [str(c).strip() for c in df.columns]
            raw = {"Sheet1": {"rows": len(df), "columns": list(df.columns), "dtypes": {c: str(df[c].dtype) for c in df.columns}, "data": df.to_dict(orient="records")}}
            return {"raw_data": raw}
        else:
            xls = pd.ExcelFile(BytesIO(data))
            raw = {}
            for sheet in xls.sheet_names:
                df = pd.read_excel(xls, sheet_name=sheet).dropna(how="all")
                df.columns = [str(c).strip() for c in df.columns]
                raw[sheet] = {"rows": len(df), "columns": list(df.columns), "dtypes": {c: str(df[c].dtype) for c in df.columns}, "data": df.to_dict(orient="records")}
            print(f"DEBUG PARSE RAW: {len(raw)} hojas, keys={list(raw.keys())}")
            return {"raw_data": raw}
    except Exception as e:
        print(f"ERROR PARSE: {str(e)}")
        import traceback; traceback.print_exc()
        return {"response": f"Error leyendo archivo: {str(e)}", "alerts": []}


def calculate_metrics(state: ExcelState) -> dict:
    if not state.get("raw_data"):
        return {"calculations": {}}
    calcs = {}
    for sheet, sdata in state["raw_data"].items():
        df = pd.DataFrame(sdata["data"])
        sheet_calcs = {}
        for col in df.select_dtypes(include=[np.number]).columns:
            s = df[col].dropna()
            if len(s) == 0: continue
            sheet_calcs[col] = {"total": round(float(s.sum()), 2), "promedio": round(float(s.mean()), 2), "mediana": round(float(s.median()), 2), "min": round(float(s.min()), 2), "max": round(float(s.max()), 2), "std": round(float(s.std()), 2), "count": int(len(s)), "negativos": int((s < 0).sum())}
            if len(s) >= 4:
                mid = len(s) // 2
                h1, h2 = s.iloc[:mid].sum(), s.iloc[mid:].sum()
                if h1 != 0: sheet_calcs[col]["variacion_pct"] = round((h2 - h1) / abs(h1) * 100, 2)
        industry = state.get("industry_type", "generic")
        if industry in ("retail", "distribucion"):
            sheet_calcs["_negocio"] = _retail_metrics(df)
        calcs[sheet] = sheet_calcs
    print(f"EXCEL: Métricas calculadas para {len(calcs)} hojas")
    return {"calculations": calcs}


def _retail_metrics(df) -> dict:
    m = {}
    cols = _fuzzy_match(df, {"venta": ["venta", "ventas", "total_venta", "valor_venta", "monto", "total", "valor_pagado"], "costo": ["costo", "costos", "costo_total", "valor_costo"], "cliente": ["cliente", "nombre_cliente", "razon_social"], "vendedor": ["vendedor", "asesor", "ejecutivo", "gestor_ventas"], "producto": ["producto", "item", "referencia", "sku", "descripcion", "curso"]})
    if "venta" in cols and "costo" in cols:
        df["_margen"] = df[cols["venta"]] - df[cols["costo"]]
        margen_pct = (df["_margen"] / df[cols["venta"]] * 100).replace([np.inf, -np.inf], np.nan)
        m["margen_promedio_pct"] = round(float(margen_pct.mean()), 2)
        negativos = df[df["_margen"] < 0]
        if "producto" in cols and len(negativos) > 0:
            m["productos_margen_negativo"] = negativos[cols["producto"]].unique().tolist()[:10]
    if "cliente" in cols and "venta" in cols:
        top = df.groupby(cols["cliente"])[cols["venta"]].sum().nlargest(10)
        m["top_10_clientes"] = {str(k): round(float(v), 2) for k, v in top.items()}
    if "vendedor" in cols and "venta" in cols:
        ranking = df.groupby(cols["vendedor"])[cols["venta"]].sum().sort_values(ascending=False)
        m["ranking_vendedores"] = {str(k): round(float(v), 2) for k, v in ranking.items()}
    return m


def _fuzzy_match(df, mapping) -> dict:
    result = {}
    for key, opts in mapping.items():
        for col in df.columns:
            if col.lower().strip() in [o.lower() for o in opts]:
                result[key] = col
                break
    return result


def build_profile(state: ExcelState) -> dict:
    if not state.get("raw_data"):
        return {"statistical_profile": {}}
    profile = {}
    for sheet, sdata in state["raw_data"].items():
        df = pd.DataFrame(sdata["data"])
        sp = {}
        for col in df.select_dtypes(include=[np.number]).columns:
            s = df[col].dropna()
            if len(s) < 5: continue
            q25 = float(s.quantile(0.25)); q75 = float(s.quantile(0.75)); iqr = q75 - q25
            sp[col] = {"mean": round(float(s.mean()), 2), "median": round(float(s.median()), 2), "std": round(float(s.std()), 2), "p25": round(q25, 2), "p75": round(q75, 2), "outliers_bajo": int((s < q25 - 1.5 * iqr).sum()), "outliers_alto": int((s > q75 + 1.5 * iqr).sum())}
        profile[sheet] = sp
    return {"statistical_profile": profile}


def smart_sampling(state: ExcelState) -> dict:
    if not state.get("raw_data"):
        return {"sample": [], "anomalies": []}
    rows = []; anomalies = []
    for sheet, sdata in state["raw_data"].items():
        df = pd.DataFrame(sdata["data"])
        if len(df) == 0: continue
        for r in df.head(15).to_dict("records"): r["_src"] = f"{sheet}:head"; rows.append(r)
        for r in df.tail(10).to_dict("records"): r["_src"] = f"{sheet}:tail"; rows.append(r)
        n = min(25, len(df))
        for r in df.sample(n=n, random_state=42).to_dict("records"): r["_src"] = f"{sheet}:random"; rows.append(r)
        for col in df.select_dtypes(include=[np.number]).columns:
            s = df[col].dropna()
            if len(s) < 5: continue
            q25 = s.quantile(0.25); q75 = s.quantile(0.75); iqr = q75 - q25
            mask = (s < q25 - 1.5 * iqr) | (s > q75 + 1.5 * iqr)
            for r in df[mask].head(5).to_dict("records"):
                r["_src"] = f"{sheet}:outlier:{col}"; rows.append(r)
                anomalies.append({"sheet": sheet, "column": col, "value": r.get(col), "type": "outlier"})
    print(f"EXCEL: Sample {len(rows)} filas, {len(anomalies)} anomalías")
    return {"sample": rows[:100], "anomalies": anomalies[:20]}


def analyze_with_llm(state: ExcelState) -> dict:
    model, model_name = selector.get_model("excel_analysis", state.get("model_preference"))
    instruction = state.get("user_instruction") or "Análisis general completo"
    industry = state.get("industry_type", "generic")
    empresa_id = state.get("empresa_id", "")
    custom_prompt = ""
    if empresa_id:
        dna = load_company_dna(empresa_id)
        custom_prompt = dna.get("custom_prompt", "")
        if not industry or industry == "generic":
            industry = dna.get("industry_type", "generic") or "generic"
    sector_prompt = build_sector_prompt(industry)
    calcs_str = json.dumps(state.get("calculations", {}), ensure_ascii=False, default=str)[:8000]
    profile_str = json.dumps(state.get("statistical_profile", {}), ensure_ascii=False, default=str)[:3000]
    sample_str = json.dumps(state.get("sample", [])[:50], ensure_ascii=False, default=str)[:8000]
    anomalies_str = json.dumps(state.get("anomalies", []), ensure_ascii=False, default=str)
    prompt = f"""Analiza estos datos de una empresa ({industry}).

## MÉTRICAS CALCULADAS (exactas, NO recalcular)
{calcs_str}

## PERFIL ESTADÍSTICO
{profile_str}

## MUESTRA ({len(state.get('sample', []))} filas representativas)
{sample_str}

## ANOMALÍAS DETECTADAS
{anomalies_str}

## INSTRUCCIÓN DEL USUARIO: {instruction}

REGLAS:
1. BLUF: hallazgo más importante primero
2. Usa las métricas calculadas (son exactas, NO las recalcules)
3. Máximo 5 recomendaciones accionables
4. ⚠️ para riesgos, 💡 para oportunidades
5. Si datos incompletos o sospechosos, dilo explícitamente
6. Citar fuente: [Fuente: {state.get('file_name', 'archivo')}]

SECCIONES OBLIGATORIAS — incluir TODAS si los datos las respaldan. No esperes a que te pregunten:

⚠️ ALERTAS CRÍTICAS (lo que está mal y requiere acción HOY)
- Márgenes negativos, cartera vencida, stock estancado, concentración peligrosa

📊 RESUMEN EJECUTIVO (los 5 números más importantes)
- Ventas totales, margen promedio, cartera total, días de mora promedio, inventario en meses

🏆 TOP PERFORMERS (lo mejor)
- Mejores vendedores, mejores productos, mejores ciudades

🔴 BAJO RENDIMIENTO (lo peor)
- Peores vendedores, productos con margen negativo, ciudades con baja penetración

📈 OPORTUNIDADES (lo que se puede mejorar con acciones concretas)
- Si los vendedores bajos suben X%, impacto en ventas de $Y
- Si se reduce mora a N días, se liberan $Z en flujo de caja

No omitas ninguna sección. El CEO necesita ver el panorama COMPLETO en la primera respuesta, no descubrirlo preguntando.

{sector_prompt}
"""
    system_msg = "Eres un analista de negocios senior con 15 años de experiencia. Respondes en español."
    if custom_prompt:
        system_msg += f"\n\nINSTRUCCIONES PERSONALIZADAS DE LA EMPRESA:\n{custom_prompt}"
    response = model.invoke([
        {"role": "system", "content": system_msg},
        {"role": "user", "content": prompt},
    ])
    print(f"EXCEL: Análisis generado con {model_name}")
    return {"response": response.content, "model_used": model_name}


def generate_alerts(state: ExcelState) -> dict:
    alerts = []
    for sheet, calcs in state.get("calculations", {}).items():
        negocio = calcs.get("_negocio", {})
        for p in negocio.get("productos_margen_negativo", []):
            alerts.append({"level": "critical", "message": f"🔴 {p}: margen negativo"})
        for col, stats in calcs.items():
            if col.startswith("_"): continue
            if isinstance(stats, dict) and stats.get("negativos", 0) > 0:
                alerts.append({"level": "warning", "message": f"⚠️ '{col}': {stats['negativos']} valores negativos"})
    for a in state.get("anomalies", [])[:5]:
        alerts.append({"level": "info", "message": f"📊 Outlier en '{a['column']}' (hoja {a['sheet']}): {a['value']}"})
    print(f"EXCEL: {len(alerts)} alertas generadas")
    return {"alerts": alerts}


def store_analysis(state: ExcelState) -> dict:
    from api.database import sync_engine
    from sqlalchemy import text as sql_text
    file_name = state.get("file_name", "archivo")
    response = state.get("response", "")
    empresa_id = state.get("empresa_id", "")
    calculations = state.get("calculations", {})
    alerts = state.get("alerts", [])
    industry_type = state.get("industry_type", "generic")
    model_used = state.get("model_used", "unknown")
    if not response: return {}
    metrics_summary = {}
    for sheet, calcs in calculations.items():
        for col, stats in calcs.items():
            if col.startswith("_"):
                if isinstance(stats, dict):
                    for k, v in stats.items():
                        if isinstance(v, (int, float)): metrics_summary[k] = v
            elif isinstance(stats, dict):
                metrics_summary[f"{col}_total"] = stats.get("total", 0)
                metrics_summary[f"{col}_promedio"] = stats.get("promedio", 0)
    title = f"Análisis {'Retail' if industry_type == 'retail' else 'General'}: {file_name}"
    alerts_json = [{"level": a.get("level", "info"), "message": a.get("message", "")} for a in alerts]
    report_id = None
    try:
        with sync_engine.connect() as conn:
            result = conn.execute(sql_text("""
                INSERT INTO ada_reports (empresa_id, title, report_type, source_file, markdown_content, metrics_summary, alerts, generated_by, requires_action, allowed_roles)
                VALUES (:empresa_id, :title, :report_type, :source_file, :markdown, :metrics, :alerts, :generated_by, FALSE, :roles)
                RETURNING id
            """), {"empresa_id": empresa_id, "title": title, "report_type": "excel_analysis", "source_file": file_name, "markdown": response, "metrics": json.dumps(metrics_summary, ensure_ascii=False, default=str), "alerts": json.dumps(alerts_json, ensure_ascii=False), "generated_by": model_used, "roles": ["administrador", "gerente", "analista"]})
            row = result.fetchone()
            if row: report_id = str(row[0])
            conn.commit()
        print(f"EXCEL: Reporte guardado en ada_reports → {report_id}")
    except Exception as e:
        print(f"ERROR guardando en ada_reports: {e}")
        import traceback; traceback.print_exc()
    header = f"[Reporte: {file_name} | Empresa: {empresa_id}]"
    store_memory(f"{header}\nRESUMEN:\n{response[:1500]}", empresa_id=empresa_id)
    if metrics_summary:
        metrics_text = f"{header}\nMÉTRICAS:\n"
        for k, v in metrics_summary.items(): metrics_text += f"- {k}: {v}\n"
        store_memory(metrics_text, empresa_id=empresa_id)
    if alerts_json:
        alerts_text = f"{header}\nALERTAS:\n"
        for a in alerts_json: alerts_text += f"- [{a['level']}] {a['message']}\n"
        store_memory(alerts_text, empresa_id=empresa_id)
    store_memory(f"{header}\nArchivo '{file_name}' analizado. Tipo: {industry_type}. Alertas: {len(alerts_json)}. ID reporte: {report_id}", empresa_id=empresa_id)

    # Semantic tagging enriquecido y doble almacenamiento vectorial
    tags = semantic_tag_document(response[:12000], file_name)
    tags["categoria"] = tags.get("categoria") or "excel_analysis"
    tags["tipo_doc"] = "excel"

    store_report(
        text=f"{header}\n{response[:2500]}",
        empresa_id=empresa_id,
        file_name=file_name,
        report_type="excel_analysis",
    )
    store_vector_knowledge(
        text=f"{header}\n{response[:2500]}",
        empresa_id=empresa_id,
        file_name=file_name,
        doc_type="excel_analysis",
        metadata={
            "metrics_summary": metrics_summary,
            "semantic_tags": tags,
            "alerts_count": len(alerts_json),
        },
    )

    print(f"EXCEL: Reporte de {file_name} guardado en DB + Qdrant")

    # Knowledge Graph pipeline post-store
    if report_id and empresa_id:
        from api.services.kg_pipeline import run_kg_pipeline
        alerts_text = "\n".join([a.get("message", "") for a in alerts])
        run_kg_pipeline(report_id, empresa_id, response, alerts_text)

    return {
        "report_id": report_id,
        "sources_used": [
            {"name": "excel_pipeline", "detail": file_name, "confidence": 0.9},
            {"name": "qdrant_excel_reports", "detail": "upsert", "confidence": 0.82},
        ]
    }


def trigger_briefing(state) -> dict:
    import threading
    from api.agents.briefing_agent import briefing_agent
    response = state.get("response", "")
    alerts = state.get("alerts", [])
    empresa_id = state.get("empresa_id", "")
    user_id = state.get("user_id", "")
    file_name = state.get("file_name", "")
    if not alerts and len(response) < 200:
        print("BRIEFING: Sin alertas ni análisis sustancial, saltando")
        return {}

    briefing_result_container = [None]

    def _run_briefing_in_thread(state_data):
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            briefing_result_container[0] = loop.run_until_complete(
                briefing_agent.ainvoke(state_data)
            )
        except Exception as e:
            print(f"BRIEFING thread error: {e}")
        finally:
            loop.close()

    try:
        briefing_data = {
            "empresa_id": empresa_id, "user_id": user_id, "trigger": "excel_analysis",
            "analysis": response, "alerts": alerts, "file_name": file_name,
        }
        thread = threading.Thread(target=_run_briefing_in_thread, args=(briefing_data,))
        thread.start()
        thread.join(timeout=30)

        briefing_result = briefing_result_container[0]
        if briefing_result:
            briefing_text = briefing_result.get("response", "")
            if briefing_text:
                combined = state.get("response", "") + "\n\n---\n\n## BRIEFING PROACTIVO DE ADA\n*Ada cruzo automaticamente tus datos con tu agenda, emails y documentos:*\n\n" + briefing_text
                print(f"BRIEFING: Proactivo generado exitosamente")
                return {"response": combined}
    except Exception as e:
        print(f"BRIEFING: Error: {e}")
        import traceback; traceback.print_exc()
    return {}


graph = StateGraph(ExcelState)
graph.add_node("parse", parse_file)
graph.add_node("calculate", calculate_metrics)
graph.add_node("profile", build_profile)
graph.add_node("sample", smart_sampling)
graph.add_node("analyze", analyze_with_llm)
graph.add_node("alerts", generate_alerts)
graph.add_node("store", store_analysis)
graph.add_node("briefing", trigger_briefing)

graph.set_entry_point("parse")
graph.add_edge("parse", "calculate")
graph.add_edge("calculate", "profile")
graph.add_edge("profile", "sample")
graph.add_edge("sample", "analyze")
graph.add_edge("analyze", "alerts")
graph.add_edge("alerts", "store")
graph.add_edge("store", "briefing")
graph.add_edge("briefing", END)

excel_agent = graph.compile()
