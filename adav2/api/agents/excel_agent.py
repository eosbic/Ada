"""
Excel Analyst — Smart Data Pipeline de 8 nodos.
Optimizado para archivos grandes (+5000 filas, +5 hojas).
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

# Límites para archivos grandes
MAX_ROWS_PER_SHEET = 10000
MAX_SHEETS = 8
SAMPLE_SIZE = 200
MAX_CALCS_CHARS = 12000
MAX_SAMPLE_CHARS = 10000
MAX_STORE_CHARS = 8000
MAX_RESPONSE_CHARS = 15000


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
    print(f"DEBUG PARSE: file_name={file_name}, len={len(data) if data else 0}")
    if not data or len(data) == 0:
        return {"response": "Error: archivo vacío.", "alerts": []}
    try:
        if file_name.endswith(".csv"):
            df = pd.read_csv(BytesIO(data), nrows=MAX_ROWS_PER_SHEET)
            df.columns = [str(c).strip() for c in df.columns]
            total_rows = len(df)
            raw = {"Sheet1": {
                "rows": total_rows,
                "columns": list(df.columns),
                "dtypes": {c: str(df[c].dtype) for c in df.columns},
                "data": df.to_dict(orient="records"),
                "truncated": False,
            }}
            return {"raw_data": raw}
        else:
            xls = pd.ExcelFile(BytesIO(data))
            all_sheets = xls.sheet_names
            raw = {}
            sheets_processed = 0
            for sheet in all_sheets:
                if sheets_processed >= MAX_SHEETS:
                    print(f"EXCEL PARSE: Límite de {MAX_SHEETS} hojas alcanzado, saltando {len(all_sheets) - sheets_processed} hojas restantes")
                    break
                try:
                    df = pd.read_excel(xls, sheet_name=sheet, nrows=MAX_ROWS_PER_SHEET).dropna(how="all")
                    df.columns = [str(c).strip() for c in df.columns]
                    if len(df) == 0:
                        print(f"EXCEL PARSE: Hoja '{sheet}' vacía, saltando")
                        continue
                    total_rows = len(df)
                    raw[sheet] = {
                        "rows": total_rows,
                        "columns": list(df.columns),
                        "dtypes": {c: str(df[c].dtype) for c in df.columns},
                        "data": df.to_dict(orient="records"),
                        "truncated": total_rows >= MAX_ROWS_PER_SHEET,
                    }
                    sheets_processed += 1
                    print(f"EXCEL PARSE: Hoja '{sheet}' -> {total_rows} filas, {len(df.columns)} columnas")
                except Exception as e:
                    print(f"EXCEL PARSE: Error en hoja '{sheet}': {e}")
                    continue

            if not raw:
                return {"response": "Error: el archivo no contiene hojas con datos válidos.", "alerts": []}

            print(f"DEBUG PARSE RAW: {len(raw)}/{len(all_sheets)} hojas procesadas")
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
            sheet_calcs[col] = {
                "total": round(float(s.sum()), 2),
                "promedio": round(float(s.mean()), 2),
                "mediana": round(float(s.median()), 2),
                "min": round(float(s.min()), 2),
                "max": round(float(s.max()), 2),
                "std": round(float(s.std()), 2),
                "count": int(len(s)),
                "negativos": int((s < 0).sum()),
            }
            if len(s) >= 4:
                mid = len(s) // 2
                h1, h2 = s.iloc[:mid].sum(), s.iloc[mid:].sum()
                if h1 != 0:
                    sheet_calcs[col]["variacion_pct"] = round((h2 - h1) / abs(h1) * 100, 2)
        industry = state.get("industry_type", "generic")
        if industry in ("retail", "distribucion"):
            sheet_calcs["_negocio"] = _retail_metrics(df)
        calcs[sheet] = sheet_calcs
    print(f"EXCEL: Métricas calculadas para {len(calcs)} hojas")
    return {"calculations": calcs}


def _retail_metrics(df) -> dict:
    m = {}
    cols = _fuzzy_match(df, {
        "venta": ["venta", "ventas", "total_venta", "valor_venta", "monto", "total", "valor_pagado"],
        "costo": ["costo", "costos", "costo_total", "valor_costo"],
        "cliente": ["cliente", "nombre_cliente", "razon_social"],
        "vendedor": ["vendedor", "asesor", "ejecutivo", "gestor_ventas"],
        "producto": ["producto", "item", "referencia", "sku", "descripcion", "curso"],
        "ciudad": ["ciudad", "municipio", "region", "departamento"],
    })
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
    if "ciudad" in cols and "venta" in cols:
        by_city = df.groupby(cols["ciudad"])[cols["venta"]].agg(["sum", "count"])
        by_city.columns = ["total_ventas", "num_transacciones"]
        by_city = by_city.sort_values("total_ventas", ascending=False)
        m["ventas_por_ciudad"] = {
            str(k): {"total": round(float(v["total_ventas"]), 2), "transacciones": int(v["num_transacciones"])}
            for k, v in by_city.head(15).iterrows()
        }
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
            q25 = float(s.quantile(0.25))
            q75 = float(s.quantile(0.75))
            iqr = q75 - q25
            sp[col] = {
                "mean": round(float(s.mean()), 2),
                "median": round(float(s.median()), 2),
                "std": round(float(s.std()), 2),
                "p25": round(q25, 2),
                "p75": round(q75, 2),
                "outliers_bajo": int((s < q25 - 1.5 * iqr).sum()),
                "outliers_alto": int((s > q75 + 1.5 * iqr).sum()),
            }
        profile[sheet] = sp
    return {"statistical_profile": profile}


def smart_sampling(state: ExcelState) -> dict:
    if not state.get("raw_data"):
        return {"sample": [], "anomalies": []}
    rows = []
    anomalies = []
    for sheet, sdata in state["raw_data"].items():
        df = pd.DataFrame(sdata["data"])
        if len(df) == 0: continue

        total = len(df)
        head_n = min(20, total)
        tail_n = min(15, total)
        random_n = min(50, total)

        for r in df.head(head_n).to_dict("records"):
            r["_src"] = f"{sheet}:head"
            rows.append(r)
        for r in df.tail(tail_n).to_dict("records"):
            r["_src"] = f"{sheet}:tail"
            rows.append(r)
        if total > head_n + tail_n:
            sample_df = df.sample(n=min(random_n, total), random_state=42)
            for r in sample_df.to_dict("records"):
                r["_src"] = f"{sheet}:random"
                rows.append(r)

        for col in df.select_dtypes(include=[np.number]).columns:
            s = df[col].dropna()
            if len(s) < 5: continue
            q25 = s.quantile(0.25)
            q75 = s.quantile(0.75)
            iqr = q75 - q25
            mask = (s < q25 - 1.5 * iqr) | (s > q75 + 1.5 * iqr)
            for r in df[mask].head(3).to_dict("records"):
                r["_src"] = f"{sheet}:outlier:{col}"
                rows.append(r)
                anomalies.append({"sheet": sheet, "column": col, "value": r.get(col), "type": "outlier"})

    print(f"EXCEL: Sample {len(rows)} filas (límite {SAMPLE_SIZE}), {len(anomalies)} anomalías")
    return {"sample": rows[:SAMPLE_SIZE], "anomalies": anomalies[:30]}


def analyze_with_llm(state: ExcelState) -> dict:
    from api.services.industry_protocols import build_sector_prompt

    model, model_name = selector.get_model("excel_analysis", state.get("model_preference"))
    instruction = state.get("user_instruction") or "Análisis general completo"
    industry = state.get("industry_type", "generic")
    file_name = state.get("file_name", "archivo")

    raw_data = state.get("raw_data", {})
    file_summary = []
    for sheet, sdata in raw_data.items():
        truncated = " (TRUNCADO - archivo tiene más filas)" if sdata.get("truncated") else ""
        file_summary.append(f"- Hoja '{sheet}': {sdata['rows']} filas, {len(sdata['columns'])} columnas{truncated}")
    file_summary_str = "\n".join(file_summary)

    calcs_str = json.dumps(state.get("calculations", {}), ensure_ascii=False, default=str)[:MAX_CALCS_CHARS]
    profile_str = json.dumps(state.get("statistical_profile", {}), ensure_ascii=False, default=str)[:4000]
    sample_str = json.dumps(state.get("sample", [])[:80], ensure_ascii=False, default=str)[:MAX_SAMPLE_CHARS]
    anomalies_str = json.dumps(state.get("anomalies", []), ensure_ascii=False, default=str)[:2000]

    sector_analysis = build_sector_prompt(industry)
    total_rows = sum(s['rows'] for s in raw_data.values())

    prompt = f"""Analiza estos datos empresariales.

## EMPRESA: {state.get('empresa_id', '')} | DOMINIO: {industry}

## ESTRUCTURA DEL ARCHIVO
{file_summary_str}

## MÉTRICAS PRE-CALCULADAS (exactas, NO recalcular)
{calcs_str}

## PERFIL ESTADÍSTICO
{profile_str}

## MUESTRA ({len(state.get('sample', []))} filas representativas de {total_rows} totales)
{sample_str}

## ANOMALÍAS DETECTADAS
{anomalies_str}

## INSTRUCCIÓN DEL USUARIO: {instruction}

PROTOCOLO:

1. VEREDICTO EJECUTIVO (3 líneas máximo)
   La conclusión más importante. Sin rodeos.

2. DASHBOARD DE MÉTRICAS CRÍTICAS
   Tabla con los 5-7 KPIs vitales. USA métricas pre-calculadas. NO inventes números.

3. ANÁLISIS POR DIMENSIÓN (solo las que existan en los datos)
   - Por producto/SKU | Por vendedor | Por cliente | Por ciudad | Por período

4. {sector_analysis}

5. ALERTAS Y ANOMALÍAS
   🔴 Crítico | 🟠 Alto | 🟡 Medio

6. SIMULACIÓN Y PROYECCIÓN
   Solo si hay datos suficientes para proyectar.

7. FUGA DE CAPITAL IDENTIFICADA
   Monto monetario estimado de ineficiencias detectadas.

8. PLAN DE ACCIÓN (máximo 5 decisiones)
   Concretas, con responsable sugerido y plazo.

REGLAS:
- [Fuente: {file_name}]
- Si no hay datos para una sección, OMÍTELA. No digas "no disponible".
- Nombres exactos: SKUs, clientes, vendedores, capítulos.
- Tono de junta directiva. Sin suavizar malas noticias.
- Si el archivo fue TRUNCADO, mencionarlo y analizar lo disponible.
"""

    response = model.invoke([
        {"role": "system", "content": (
            "Eres un Senior Principal Auditor & Strategic Controller con 20 años de experiencia. "
            "Tu misión es auditoría forense y simulación predictiva basada en datos verificados. "
            "Respondes en español con terminología corporativa técnica. "
            "No eres un asistente; eres un consultor de alta dirección."
        )},
        {"role": "user", "content": prompt},
    ])
    print(f"EXCEL: Análisis generado con {model_name} (protocolo: {industry})")
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
    for sheet, sdata in state.get("raw_data", {}).items():
        if sdata.get("truncated"):
            alerts.append({"level": "warning", "message": f"⚠️ Hoja '{sheet}': archivo grande, análisis sobre primeras {MAX_ROWS_PER_SHEET} filas"})
    for a in state.get("anomalies", [])[:5]:
        alerts.append({"level": "info", "message": f"📊 Outlier en '{a['column']}' (hoja {a['sheet']}): {a['value']}"})
    print(f"EXCEL: {len(alerts)} alertas generadas")
    return {"alerts": alerts}


def store_analysis(state: ExcelState) -> dict:
    from api.database import sync_engine
    from sqlalchemy import text as sql_text
    from datetime import datetime
    import re as _re

    file_name = state.get("file_name", "archivo")
    response = state.get("response", "")
    empresa_id = state.get("empresa_id", "")
    calculations = state.get("calculations", {})
    alerts = state.get("alerts", [])
    industry_type = state.get("industry_type", "generic")
    model_used = state.get("model_used", "unknown")
    if not response:
        return {}

    metrics_summary = {}
    for sheet, calcs in calculations.items():
        for col, stats in calcs.items():
            if col.startswith("_"):
                if isinstance(stats, dict):
                    for k, v in stats.items():
                        if isinstance(v, (int, float)):
                            metrics_summary[k] = v
            elif isinstance(stats, dict):
                metrics_summary[f"{col}_total"] = stats.get("total", 0)
                metrics_summary[f"{col}_promedio"] = stats.get("promedio", 0)

    title = "Analisis " + ("Retail" if industry_type == "retail" else "General") + ": " + file_name
    alerts_json = [{"level": a.get("level", "info"), "message": a.get("message", "")} for a in alerts]

    def _generate_tags():
        now = datetime.now()
        t = []
        ext = file_name.rsplit(".", 1)[-1].lower() if "." in file_name else "unknown"
        t.append("tipo:" + ext)
        if industry_type and industry_type != "generic":
            t.append("industria:" + industry_type)
        t.append("q" + str((now.month - 1) // 3 + 1) + "-" + str(now.year))
        t.append(now.strftime("%B").lower() + "-" + str(now.year))
        if alerts_json:
            t.append("tiene-alertas")
            if any(a["level"] == "critical" for a in alerts_json):
                t.append("critico")
            if any(a["level"] == "warning" for a in alerts_json):
                t.append("advertencia")
        for sheet_calcs in calculations.values():
            neg = sheet_calcs.get("_negocio", {})
            if neg.get("productos_margen_negativo"):
                t.append("margen-negativo")
            if neg.get("top_10_clientes"):
                t.append("tiene-ranking-clientes")
            if neg.get("ranking_vendedores"):
                t.append("tiene-ranking-vendedores")
            if neg.get("ventas_por_ciudad"):
                t.append("tiene-analisis-geografico")
        entities = _re.findall(r"[A-Z][a-z]+(?: [A-Z][a-z]+)+", response[:2000])
        for ent in list(set(entities))[:5]:
            t.append("entidad:" + ent.lower().replace(" ", "-"))
        return list(set(t))

    auto_tags = _generate_tags()

    # VERSIONADO
    report_id = None
    version = 1
    parent_id = None

    try:
        with sync_engine.connect() as conn:
            existing = conn.execute(
                sql_text("""
                    SELECT id, version FROM ada_reports
                    WHERE empresa_id = :eid AND source_file = :fn
                    ORDER BY version DESC LIMIT 1
                """),
                {"eid": empresa_id, "fn": file_name},
            ).fetchone()

            if existing:
                version = existing.version + 1
                parent_id = str(existing.id)

            result = conn.execute(
                sql_text("""
                    INSERT INTO ada_reports (
                        empresa_id, title, report_type, source_file,
                        markdown_content, metrics_summary, alerts,
                        generated_by, requires_action, allowed_roles,
                        tags, version, parent_report_id
                    )
                    VALUES (
                        :empresa_id, :title, :report_type, :source_file,
                        :markdown, :metrics, :alerts,
                        :generated_by, FALSE, :roles,
                        :tags, :version, :parent_id
                    )
                    RETURNING id
                """),
                {
                    "empresa_id": empresa_id,
                    "title": title,
                    "report_type": "excel_analysis",
                    "source_file": file_name,
                    "markdown": response[:MAX_RESPONSE_CHARS],
                    "metrics": json.dumps(metrics_summary, ensure_ascii=False, default=str),
                    "alerts": json.dumps(alerts_json, ensure_ascii=False),
                    "generated_by": model_used,
                    "roles": ["administrador", "gerente", "analista"],
                    "tags": auto_tags,
                    "version": version,
                    "parent_id": parent_id,
                },
            )
            row = result.fetchone()
            if row:
                report_id = str(row[0])
            conn.commit()

        print("EXCEL: Reporte v" + str(version) + " guardado -> " + str(report_id))
    except Exception as e:
        print("ERROR guardando en ada_reports: " + str(e))
        import traceback
        traceback.print_exc()

    if report_id:
        _link_related_reports(report_id, empresa_id, response)

    header = "[Reporte: " + file_name + " | Empresa: " + empresa_id + "]"

    chunk_size = MAX_STORE_CHARS
    response_chunks = [response[i:i+chunk_size] for i in range(0, min(len(response), chunk_size * 3), chunk_size)]
    for idx, chunk in enumerate(response_chunks):
        chunk_label = f" [parte {idx+1}/{len(response_chunks)}]" if len(response_chunks) > 1 else ""
        store_memory(header + chunk_label + "\nANALISIS:\n" + chunk)

    if metrics_summary:
        metrics_text = header + "\nMETRICAS:\n"
        for k, v in metrics_summary.items():
            metrics_text += "- " + str(k) + ": " + str(v) + "\n"
        store_memory(metrics_text)

    if alerts_json:
        alerts_text = header + "\nALERTAS:\n"
        for a in alerts_json:
            alerts_text += "- [" + a["level"] + "] " + a["message"] + "\n"
        store_memory(alerts_text)

    store_memory(header + "\nArchivo '" + file_name + "' analizado. Tipo: " + industry_type +
                 ". Alertas: " + str(len(alerts_json)) + ". ID: " + str(report_id) +
                 ". Tags: " + ", ".join(auto_tags[:5]))

    tags_meta = semantic_tag_document(response[:12000], file_name)
    tags_meta["categoria"] = tags_meta.get("categoria") or "excel_analysis"
    tags_meta["tipo_doc"] = "excel"

    store_report(
        text=header + "\n" + response[:MAX_STORE_CHARS],
        empresa_id=empresa_id,
        file_name=file_name,
        report_type="excel_analysis",
    )
    store_vector_knowledge(
        text=header + "\n" + response[:MAX_STORE_CHARS],
        empresa_id=empresa_id,
        file_name=file_name,
        doc_type="excel_analysis",
        metadata={
            "metrics_summary": metrics_summary,
            "semantic_tags": tags_meta,
            "alerts_count": len(alerts_json),
            "auto_tags": auto_tags,
            "version": version,
        },
    )

    print("EXCEL: " + file_name + " v" + str(version) + " -> DB + Qdrant | tags: " + str(auto_tags[:4]))
    return {
        "sources_used": [
            {"name": "excel_pipeline", "detail": file_name, "confidence": 0.9},
            {"name": "qdrant_excel_reports", "detail": "upsert", "confidence": 0.82},
        ]
    }


def _link_related_reports(report_id: str, empresa_id: str, response: str):
    from api.database import sync_engine
    from sqlalchemy import text as sql_text
    import re as _re

    try:
        entities = _re.findall(r"[A-Z][a-z]+(?: [A-Z][a-z]+)+", response)
        unique_entities = list(set(entities))[:10]

        with sync_engine.connect() as conn:
            for entity in unique_entities:
                if len(entity) < 5:
                    continue
                result = conn.execute(
                    sql_text("""
                        SELECT id FROM ada_reports
                        WHERE empresa_id = :eid AND id != :rid
                        AND is_archived = FALSE
                        AND (markdown_content ILIKE :q OR title ILIKE :q)
                        LIMIT 3
                    """),
                    {"eid": empresa_id, "rid": report_id, "q": "%" + entity + "%"},
                )
                for row in result.fetchall():
                    conn.execute(
                        sql_text("""
                            INSERT INTO report_links (source_report_id, target_report_id, link_type)
                            VALUES (:src, :tgt, 'entity_match')
                            ON CONFLICT DO NOTHING
                        """),
                        {"src": report_id, "tgt": str(row.id)},
                    )
            conn.commit()
            print("EXCEL LINKS: " + report_id + " -> " + str(len(unique_entities)) + " entidades vinculadas")
    except Exception as e:
        print("EXCEL LINKS ERROR: " + str(e))


def trigger_briefing(state) -> dict:
    import asyncio
    from api.agents.briefing_agent import briefing_agent
    response = state.get("response", "")
    alerts = state.get("alerts", [])
    empresa_id = state.get("empresa_id", "")
    user_id = state.get("user_id", "")
    file_name = state.get("file_name", "")
    if not alerts and len(response) < 200:
        print("BRIEFING: Sin alertas ni análisis sustancial, saltando")
        return {}
    try:
        loop = asyncio.new_event_loop()
        briefing_result = loop.run_until_complete(briefing_agent.ainvoke({
            "empresa_id": empresa_id, "user_id": user_id, "trigger": "excel_analysis",
            "analysis": response, "alerts": alerts, "file_name": file_name,
        }))
        loop.close()
        briefing_text = briefing_result.get("response", "")
        if briefing_text:
            combined = state.get("response", "") + "\n\n---\n\n## 🧠 BRIEFING PROACTIVO DE ADA\n*Ada cruzó automáticamente tus datos con tu agenda, emails y documentos:*\n\n" + briefing_text
            print(f"BRIEFING: Proactivo generado exitosamente")
            return {"response": combined}
    except Exception as e:
        print(f"BRIEFING: Error: {e}")
        import traceback; traceback.print_exc()
    return {}


# ─── Grafo: 8 nodos ──────────────────────────────────────

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