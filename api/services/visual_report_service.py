"""
Visual Report Service — Genera reportes HTML interactivos desde ada_reports.
"""

import json
import re
import logging
from typing import Optional

logger = logging.getLogger("ada.visual_report")

ALERT_COLORS = {
    "critical": {"bg": "#2a1215", "border": "#E24B4A", "text": "#F09595", "label": "CRITICO"},
    "warning":  {"bg": "#2a2008", "border": "#EF9F27", "text": "#FAC775", "label": "ALERTA"},
    "info":     {"bg": "#0c1a2e", "border": "#378ADD", "text": "#85B7EB", "label": "INFO"},
}


def _format_metric_value(key, value):
    if not isinstance(value, (int, float)):
        return str(value)
    if "promedio" in key.lower():
        return f"{value:,.2f}"
    if "margen" in key.lower() or "percentage" in key.lower():
        return f"{value:.1f}%"
    if isinstance(value, float) and abs(value) >= 1000:
        return f"{value:,.0f}"
    if isinstance(value, float):
        return f"{value:,.2f}"
    return f"{value:,}"


def _format_metric_label(key):
    return key.replace("_", " ").strip().capitalize()


def _markdown_to_html(md):
    html = md or ""
    html = re.sub(r"^### (.+)$", r"<h4>\1</h4>", html, flags=re.MULTILINE)
    html = re.sub(r"^## (.+)$", r"<h3>\1</h3>", html, flags=re.MULTILINE)
    html = re.sub(r"^# (.+)$", r"<h2>\1</h2>", html, flags=re.MULTILINE)
    html = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", html)
    html = re.sub(r"\*(.+?)\*", r"<em>\1</em>", html)
    html = re.sub(r"^- (.+)$", r"<li>\1</li>", html, flags=re.MULTILINE)
    html = re.sub(r"(<li>.*?</li>\n?)+", lambda m: "<ul>" + m.group(0) + "</ul>", html)
    html = re.sub(r"(?<!\n)\n(?!\n)", "<br>", html)
    html = re.sub(r"\n{2,}", "</p><p>", html)
    return "<p>" + html + "</p>"


def _parse_number(text: str) -> Optional[float]:
    """Convierte texto tipo '$1,234.56' o '1.234,56' a float."""
    clean = (text or "").strip()
    clean = re.sub(r"[%$€\s]", "", clean)
    if not clean:
        return None
    if "," in clean and "." in clean:
        if clean.rindex(",") > clean.rindex("."):
            clean = clean.replace(".", "").replace(",", ".")
        else:
            clean = clean.replace(",", "")
    elif "," in clean and "." not in clean:
        if clean.count(",") == 1 and len(clean.split(",")[1]) <= 2:
            clean = clean.replace(",", ".")
        else:
            clean = clean.replace(",", "")
    try:
        return float(clean)
    except ValueError:
        return None


def _extract_rankings_from_markdown(content: str) -> list[dict]:
    """Busca secciones tipo ranking (top vendedores, clientes, productos) en markdown."""
    rankings: list[dict] = []
    if not content:
        return rankings
    section_pattern = re.compile(
        r"(?:#+\s*|(?:\*\*))?((?:top|ranking|mejores|principales)\s+\d*\s*"
        r"(?:vendedor|cliente|producto|categor|sucursal|region|empleado|proveedor)"
        r"[^\n]*?)(?:\*\*)?[\n:]",
        flags=re.IGNORECASE,
    )
    item_pattern = re.compile(
        r"(?:^\s*[-*]\s*|\d+\.\s*)"
        r"[*]*([A-Za-z0-9À-ÿ\s/.&]+?)[*]*"
        r"\s*[:—–-]+\s*"
        r"[\$]?\s*([\d,.]+)",
        flags=re.MULTILINE,
    )
    sections = list(section_pattern.finditer(content))
    for i, match in enumerate(sections):
        title = match.group(1).strip().rstrip("*: ")
        start = match.end()
        end = sections[i + 1].start() if i + 1 < len(sections) else start + 1500
        block = content[start:end]
        items = item_pattern.findall(block)
        if len(items) >= 2:
            labels = [it[0].strip()[:35] for it in items[:15]]
            values = [_parse_number(it[1]) for it in items[:15]]
            if all(v is not None for v in values):
                chart_id = re.sub(r"\W+", "_", title.lower())[:30]
                rankings.append({
                    "id": chart_id,
                    "title": title,
                    "labels": labels,
                    "values": values,
                    "type": "horizontalBar",
                })
    return rankings


def _extract_tables_from_markdown(content: str) -> list[dict]:
    """Extrae tablas markdown simples con 2+ filas numericas."""
    charts: list[dict] = []
    if not content:
        return charts
    table_pattern = re.compile(
        r"(\|[^\n]+\|\n\|[-:\s|]+\|\n(?:\|[^\n]+\|\n?)+)",
        flags=re.MULTILINE,
    )
    for idx, match in enumerate(table_pattern.finditer(content)):
        lines = match.group(0).strip().split("\n")
        if len(lines) < 3:
            continue
        headers = [h.strip() for h in lines[0].split("|") if h.strip()]
        if len(headers) < 2:
            continue
        labels = []
        values = []
        for line in lines[2:]:
            cells = [c.strip() for c in line.split("|") if c.strip()]
            if len(cells) >= 2:
                label = re.sub(r"[*`]", "", cells[0]).strip()[:35]
                for cell in cells[1:]:
                    num = _parse_number(cell)
                    if num is not None:
                        labels.append(label)
                        values.append(num)
                        break
        if len(labels) >= 2:
            title = headers[0] if headers else f"Tabla {idx + 1}"
            chart_id = f"tabla_{idx}"
            chart_type = "horizontalBar" if len(labels) >= 4 else "bar"
            charts.append({
                "id": chart_id, "title": title,
                "labels": labels, "values": values, "type": chart_type,
            })
    return charts


_FINANCIAL_KW = ("total", "venta", "ingreso", "abono", "saldo", "iva", "subtotal",
                 "utilidad", "costo", "gasto", "precio", "valor", "factur", "revenue", "cost")
_PERCENT_KW = ("margen", "variacion", "pct", "porcentaje", "descuento", "percent", "ratio")
_COUNT_KW = ("cantidad", "count", "registros", "transacciones", "clientes", "productos",
             "items", "unidades", "numero", "num_")
MAX_BARS = 8


def _classify_metric(key: str) -> str:
    """Clasifica una metrica en: financial, percent, count, other."""
    k = key.lower()
    if any(w in k for w in _PERCENT_KW):
        return "percent"
    if any(w in k for w in _FINANCIAL_KW):
        return "financial"
    if any(w in k for w in _COUNT_KW):
        return "count"
    return "other"


def _extract_chart_data(metrics, markdown_content=""):
    """
    Retorna una LISTA de charts desde metrics_summary y markdown.
    PRIORIDAD: Si el LLM genero _chart_specs, usarlos directamente.
    FALLBACK: Agrupacion por keywords para reportes viejos sin _chart_specs.
    Cada chart: {id, title, labels, values, type: 'bar'|'horizontalBar'|'doughnut'|'line'}
    """
    charts: list[dict] = []
    metrics = metrics or {}

    # PRIORIDAD: Usar chart_specs del LLM si existen
    llm_specs = metrics.get("_chart_specs")
    if isinstance(llm_specs, list) and len(llm_specs) > 0:
        for spec in llm_specs:
            if isinstance(spec, dict) and spec.get("labels") and spec.get("values"):
                charts.append({
                    "id": spec.get("id", re.sub(r"\W+", "_", spec.get("title", "chart").lower())[:25]),
                    "title": spec.get("title", "Grafico"),
                    "labels": spec["labels"][:MAX_BARS],
                    "values": spec["values"][:MAX_BARS],
                    "type": spec.get("type", "bar"),
                    "unit": spec.get("unit", ""),
                })
        if charts:
            # Tambien agregar rankings/tablas del markdown
            for r in _extract_rankings_from_markdown(markdown_content):
                charts.append(r)
            return charts

    # FALLBACK: Agrupacion por keywords (reportes sin _chart_specs)
    # Clasificar todas las metricas numericas
    groups: dict[str, dict[str, float]] = {
        "financial": {}, "percent": {}, "count": {}, "other": {}
    }
    rankings: dict[str, dict[str, float]] = {}

    for key, val in metrics.items():
        if key.startswith("_"):
            continue
        # Dicts son rankings (vendedores, clientes, etc.)
        if isinstance(val, dict):
            numeric_items = {k: float(v) for k, v in val.items() if isinstance(v, (int, float))}
            if len(numeric_items) >= 2:
                rankings[key] = numeric_items
            continue
        if not isinstance(val, (int, float)):
            continue
        cat = _classify_metric(key)
        groups[cat][key] = float(val)

    # Grafico 1 — Financieros (barras)
    fin = groups["financial"]
    if len(fin) >= 2:
        items = list(fin.items())[:MAX_BARS]
        charts.append({
            "id": "financieros", "title": "Metricas financieras",
            "labels": [_format_metric_label(k) for k, _ in items],
            "values": [v for _, v in items], "type": "bar",
        })

    # Grafico 2 — Porcentajes (doughnut)
    pct = groups["percent"]
    if len(pct) >= 2:
        items = list(pct.items())[:MAX_BARS]
        charts.append({
            "id": "porcentajes", "title": "Indicadores porcentuales",
            "labels": [_format_metric_label(k) for k, _ in items],
            "values": [abs(v) for _, v in items], "type": "doughnut",
        })

    # Grafico 3 — Conteos (barras)
    cnt = groups["count"]
    if len(cnt) >= 2:
        items = list(cnt.items())[:MAX_BARS]
        charts.append({
            "id": "conteos", "title": "Conteos y cantidades",
            "labels": [_format_metric_label(k) for k, _ in items],
            "values": [v for _, v in items], "type": "bar",
        })

    # Grafico 4 — Rankings (barras horizontales)
    for rank_key, rank_data in rankings.items():
        items = sorted(rank_data.items(), key=lambda x: x[1], reverse=True)[:MAX_BARS]
        chart_id = re.sub(r"\W+", "_", rank_key.lower())[:25]
        charts.append({
            "id": f"rank_{chart_id}", "title": _format_metric_label(rank_key),
            "labels": [_format_metric_label(k) for k, _ in items],
            "values": [v for _, v in items], "type": "horizontalBar",
        })

    # "other" solo si no hay nada mas de metricas y tiene 2+
    if not fin and not pct and not cnt and len(groups["other"]) >= 2:
        items = list(groups["other"].items())[:MAX_BARS]
        charts.append({
            "id": "metricas", "title": "Metricas clave",
            "labels": [_format_metric_label(k) for k, _ in items],
            "values": [v for _, v in items], "type": "bar",
        })

    # Rankings y tablas del markdown
    for r in _extract_rankings_from_markdown(markdown_content):
        charts.append(r)
    for tc in _extract_tables_from_markdown(markdown_content):
        if not any(c["id"] == tc["id"] for c in charts):
            charts.append(tc)

    return charts


def _render_header(title, report_type, created_at, generated_by, source_file):
    type_labels = {
        "excel_analysis": "Analisis de datos",
        "consolidated_analysis": "Analisis consolidado",
        "proactive_briefing": "Briefing ejecutivo",
        "document_analysis": "Analisis de documento",
        "image_analysis": "Analisis de imagen",
        "entity_360": "Vista 360",
        "prospecting": "Perfil de prospecto",
        "email_summary": "Resumen de correos",
        "calendar_event_summary": "Resumen de agenda",
        "pm_task_summary": "Resumen de tareas",
    }
    type_label = type_labels.get(report_type, report_type.replace("_", " ").title())
    date_str = str(created_at)[:19] if created_at else ""
    source_html = "<span>&middot;</span><span>Fuente: " + source_file + "</span>" if source_file else ""
    return '<div class="report-header"><div class="report-type-badge">' + type_label + '</div><h1 class="report-title">' + title + '</h1><div class="report-meta"><span>' + date_str + '</span><span>&middot;</span><span>Modelo: ' + (generated_by or "N/A") + '</span>' + source_html + '</div></div>'


def _render_metrics(metrics):
    if not metrics or not isinstance(metrics, dict):
        return ""
    numeric = {k: v for k, v in metrics.items()
               if isinstance(v, (int, float)) and not k.startswith("_")}
    if not numeric:
        return ""
    items = list(numeric.items())[:8]
    cards = ""
    for key, value in items:
        cards += '<div class="metric-card"><div class="metric-label">' + _format_metric_label(key) + '</div><div class="metric-value">' + _format_metric_value(key, value) + '</div></div>'
    return '<div class="section"><h2 class="section-title">Metricas clave</h2><div class="metrics-grid">' + cards + '</div></div>'


def _render_alerts(alerts):
    if not alerts:
        return ""
    order = {"critical": 0, "warning": 1, "info": 2}
    sorted_alerts = sorted(alerts, key=lambda a: order.get(a.get("level", "info"), 9))
    items = ""
    for alert in sorted_alerts:
        level = alert.get("level", "info")
        message = alert.get("message", "")
        colors = ALERT_COLORS.get(level, ALERT_COLORS["info"])
        items += '<div class="alert-item" style="border-left-color: ' + colors["border"] + '; background: ' + colors["bg"] + ';"><span class="alert-label" style="color: ' + colors["border"] + ';">' + colors["label"] + '</span><span class="alert-message" style="color: ' + colors["text"] + ';">' + message + '</span></div>'
    critical_count = sum(1 for a in alerts if a.get("level") == "critical")
    warning_count = sum(1 for a in alerts if a.get("level") == "warning")
    info_count = sum(1 for a in alerts if a.get("level") == "info")
    summary = str(critical_count) + " criticas &middot; " + str(warning_count) + " alertas &middot; " + str(info_count) + " informativas"
    return '<div class="section"><h2 class="section-title">Alertas y senales</h2><div class="alert-summary">' + str(len(alerts)) + ' alertas detectadas &mdash; ' + summary + '</div><div class="alerts-list">' + items + '</div></div>'


def _render_chart(metrics, markdown_content=""):
    """Itera la lista de charts, crea un canvas por chart, horizontalBar para rankings, altura dinamica."""
    charts = _extract_chart_data(metrics, markdown_content)
    if not charts:
        return ""

    dark_colors = "['#7F77DD','#1D9E75','#378ADD','#D85A30','#D4537E','#BA7517','#639922','#E24B4A','#888780','#534AB7']"
    light_colors = "['#AFA9EC','#5DCAA5','#85B7EB','#F0997B','#ED93B1','#FAC775','#97C459','#F09595','#B4B2A9','#CECBF6']"
    green_dark = "['#1D9E75','#2AB58A','#34C896','#5DCAA5','#7FD4B5','#1D9E75','#2AB58A','#34C896','#5DCAA5','#7FD4B5']"
    green_light = "['#5DCAA5','#7FD4B5','#97DCC3','#B0E4D1','#C5EBDD','#5DCAA5','#7FD4B5','#97DCC3','#B0E4D1','#C5EBDD']"

    blocks = []
    for i, chart in enumerate(charts):
        canvas_id = f"chart_{chart.get('id', i)}"
        title = chart.get("title", f"Grafico {i + 1}")
        labels_json = json.dumps(chart.get("labels", []), ensure_ascii=False)
        values_json = json.dumps(chart.get("values", []))
        chart_type = chart.get("type", "bar")
        is_horizontal = chart_type == "horizontalBar"
        is_doughnut = chart_type == "doughnut"
        num_items = len(chart.get("labels", []))

        if is_doughnut:
            chart_height = 300
        elif is_horizontal:
            chart_height = max(250, num_items * 38 + 80)
        else:
            chart_height = max(280, num_items * 30 + 100)

        if is_doughnut:
            blocks.append(
                '<div class="section">'
                '<h2 class="section-title">' + title + '</h2>'
                '<div class="chart-container" style="height:' + str(chart_height) + 'px">'
                '<canvas id="' + canvas_id + '"></canvas></div></div>'
                '<script>'
                'document.addEventListener("DOMContentLoaded", function() {'
                '  var isDark = window.matchMedia("(prefers-color-scheme: dark)").matches;'
                '  new Chart(document.getElementById("' + canvas_id + '").getContext("2d"), {'
                '    type: "doughnut",'
                '    data: { labels: ' + labels_json + ', datasets: [{ data: ' + values_json + ','
                '      backgroundColor: isDark ? ' + dark_colors + ' : ' + light_colors + ','
                '      borderColor: isDark ? "#0c1220" : "#ffffff", borderWidth: 2 }] },'
                '    options: { responsive: true, maintainAspectRatio: false, cutout: "55%",'
                '      plugins: { legend: { position: "right", labels: { color: isDark ? "#9c9a92" : "#73726c", font: { size: 11 }, padding: 12,'
                '        generateLabels: function(chart) { var d=chart.data; return d.labels.map(function(l,i){ return {text: l+" ("+d.datasets[0].data[i].toLocaleString("es-CO")+"%)", fillStyle: d.datasets[0].backgroundColor[i], hidden: false, index: i}; }); }'
                '      } } }'
                '    }'
                '  });'
                '});'
                '</script>'
            )
        else:
            axis_config = "indexAxis: 'y'," if is_horizontal else ""
            bg_dark = green_dark if is_horizontal else dark_colors
            bg_light = green_light if is_horizontal else light_colors
            value_axis = "x" if is_horizontal else "y"
            label_axis = "y" if is_horizontal else "x"

            blocks.append(
                '<div class="section">'
                '<h2 class="section-title">' + title + '</h2>'
                '<div class="chart-container" style="height:' + str(chart_height) + 'px">'
                '<canvas id="' + canvas_id + '"></canvas></div></div>'
                '<script>'
                'document.addEventListener("DOMContentLoaded", function() {'
                '  var isDark = window.matchMedia("(prefers-color-scheme: dark)").matches;'
                '  new Chart(document.getElementById("' + canvas_id + '").getContext("2d"), {'
                '    type: "bar",'
                '    data: { labels: ' + labels_json + ', datasets: [{ label: "Valor", data: ' + values_json + ','
                '      backgroundColor: isDark ? ' + bg_dark + ' : ' + bg_light + ','
                '      borderRadius: 6, borderSkipped: false }] },'
                '    options: { ' + axis_config + ' responsive: true, maintainAspectRatio: false,'
                '      plugins: { legend: { display: false } },'
                '      scales: {'
                '        ' + value_axis + ': { beginAtZero: true, grid: { color: isDark ? "rgba(255,255,255,0.06)" : "rgba(0,0,0,0.06)" },'
                '          ticks: { color: isDark ? "#9c9a92" : "#73726c", callback: function(v) { return v.toLocaleString("es-CO"); } } },'
                '        ' + label_axis + ': { grid: { display: false }, ticks: { color: isDark ? "#9c9a92" : "#73726c", maxRotation: 45, autoSkip: false } }'
                '      }'
                '    }'
                '  });'
                '});'
                '</script>'
            )

    return (
        '<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>'
        + "\n".join(blocks)
    )


def _render_content(markdown):
    if not markdown:
        return ""
    return '<div class="section"><h2 class="section-title">Analisis detallado</h2><div class="report-content">' + _markdown_to_html(markdown) + '</div></div>'


def generate_visual_report(report):
    title = report.get("title", "Reporte Ada")
    report_type = report.get("report_type", "general")
    markdown = report.get("markdown_content", "")
    created_at = report.get("created_at")
    generated_by = report.get("generated_by", "")
    source_file = report.get("source_file", "")

    metrics = report.get("metrics_summary", {})
    if isinstance(metrics, str):
        try:
            metrics = json.loads(metrics)
        except Exception:
            metrics = {}

    alerts = report.get("alerts", [])
    if isinstance(alerts, str):
        try:
            alerts = json.loads(alerts)
        except Exception:
            alerts = []

    header = _render_header(title, report_type, created_at, generated_by, source_file)
    metrics_html = _render_metrics(metrics)
    alerts_html = _render_alerts(alerts)
    chart_html = _render_chart(metrics, markdown)
    content_html = _render_content(markdown)

    if report_type in ("excel_analysis", "consolidated_analysis"):
        body = header + metrics_html + chart_html + alerts_html + content_html
    elif report_type == "proactive_briefing":
        body = header + alerts_html + content_html + metrics_html
    else:
        body = header + metrics_html + alerts_html + content_html + chart_html

    alert_count = len(alerts)
    critical_count = sum(1 for a in alerts if a.get("level") == "critical")
    critical_text = " (" + str(critical_count) + " criticas)" if critical_count else ""

    CSS = """
:root {
    --bg-primary: #ffffff; --bg-secondary: #f5f5f0; --bg-tertiary: #eaeae5;
    --text-primary: #1a1a1a; --text-secondary: #5f5e5a; --text-tertiary: #888780;
    --border-color: rgba(0,0,0,0.1); --accent: #378ADD;
    --success: #1D9E75; --warning: #EF9F27; --danger: #E24B4A;
}
@media (prefers-color-scheme: dark) {
    :root {
        --bg-primary: #1a1a18; --bg-secondary: #242422; --bg-tertiary: #2c2c2a;
        --text-primary: #e8e6de; --text-secondary: #9c9a92; --text-tertiary: #73726c;
        --border-color: rgba(255,255,255,0.08);
    }
}
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
    background: var(--bg-primary); color: var(--text-primary);
    line-height: 1.7; max-width: 800px; margin: 0 auto; padding: 2rem 1.5rem;
}
.report-header { margin-bottom: 2rem; padding-bottom: 1.5rem; border-bottom: 1px solid var(--border-color); }
.report-type-badge {
    display: inline-block; font-size: 12px; font-weight: 600;
    text-transform: uppercase; letter-spacing: 0.05em;
    padding: 4px 12px; border-radius: 6px;
    background: var(--bg-tertiary); color: var(--text-secondary); margin-bottom: 12px;
}
.report-title { font-size: 28px; font-weight: 700; line-height: 1.2; margin-bottom: 8px; }
.report-meta { display: flex; gap: 8px; font-size: 13px; color: var(--text-tertiary); flex-wrap: wrap; }
.section { margin-bottom: 2rem; }
.section-title { font-size: 18px; font-weight: 600; margin-bottom: 12px; }
.metrics-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 12px; }
.metric-card { background: var(--bg-secondary); border-radius: 10px; padding: 1rem; }
.metric-label { font-size: 12px; color: var(--text-secondary); margin-bottom: 4px; text-transform: uppercase; letter-spacing: 0.03em; }
.metric-value { font-size: 24px; font-weight: 600; }
.alert-summary { font-size: 13px; color: var(--text-secondary); margin-bottom: 12px; }
.alerts-list { display: flex; flex-direction: column; gap: 8px; }
.alert-item { display: flex; align-items: flex-start; gap: 12px; padding: 12px 16px; border-left: 3px solid; border-radius: 0 8px 8px 0; }
.alert-label { font-size: 11px; font-weight: 700; letter-spacing: 0.05em; white-space: nowrap; min-width: 60px; }
.alert-message { font-size: 14px; line-height: 1.5; }
.chart-container { position: relative; width: 100%; height: 300px; background: var(--bg-secondary); border-radius: 10px; padding: 1rem; }
.report-content { font-size: 15px; line-height: 1.8; }
.report-content h2 { font-size: 20px; font-weight: 600; margin: 1.5rem 0 0.5rem; }
.report-content h3 { font-size: 17px; font-weight: 600; margin: 1.2rem 0 0.4rem; }
.report-content h4 { font-size: 15px; font-weight: 600; margin: 1rem 0 0.3rem; }
.report-content p { margin-bottom: 0.8rem; }
.report-content ul { margin: 0.5rem 0 0.8rem 1.5rem; }
.report-content li { margin-bottom: 0.3rem; }
.footer {
    margin-top: 3rem; padding-top: 1.5rem; border-top: 1px solid var(--border-color);
    display: flex; justify-content: space-between; font-size: 12px; color: var(--text-tertiary);
}
@media (max-width: 600px) {
    body { padding: 1rem; }
    .report-title { font-size: 22px; }
    .metrics-grid { grid-template-columns: repeat(2, 1fr); }
    .metric-value { font-size: 20px; }
}
@media print { body { max-width: 100%; padding: 1rem; } .chart-container { break-inside: avoid; } }
"""

    return (
        "<!DOCTYPE html><html lang='es'><head>"
        "<meta charset='UTF-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1.0'>"
        "<title>" + title + " - Ada V5.0</title>"
        "<style>" + CSS + "</style>"
        "</head><body>"
        + body +
        '<div class="footer">'
        '<div><strong>ADA V5.0</strong> &mdash; Reporte generado automaticamente</div>'
        '<div>' + str(alert_count) + ' alertas' + critical_text + '</div>'
        '</div>'
        "</body></html>"
    )
