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


def _extract_chart_data(metrics):
    if not metrics or not isinstance(metrics, dict):
        return None
    numeric = {k: v for k, v in metrics.items()
               if isinstance(v, (int, float)) and not k.startswith("_")}
    if len(numeric) < 2:
        return None
    totals = {k: v for k, v in numeric.items() if "total" in k.lower()}
    chart = totals if len(totals) >= 2 else numeric
    items = list(chart.items())[:10]
    return {
        "labels": [_format_metric_label(k) for k, _ in items],
        "values": [v for _, v in items],
        "count": len(items),
    }


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


def _render_chart(metrics):
    chart_data = _extract_chart_data(metrics)
    if not chart_data or chart_data["count"] < 2:
        return ""
    labels_json = json.dumps(chart_data["labels"], ensure_ascii=False)
    values_json = json.dumps(chart_data["values"])
    return """
    <div class="section">
        <h2 class="section-title">Visualizacion</h2>
        <div class="chart-container"><canvas id="mainChart"></canvas></div>
    </div>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
    <script>
    document.addEventListener('DOMContentLoaded', function() {
        var isDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
        new Chart(document.getElementById('mainChart').getContext('2d'), {
            type: 'bar',
            data: {
                labels: """ + labels_json + """,
                datasets: [{
                    label: 'Valor',
                    data: """ + values_json + """,
                    backgroundColor: isDark
                        ? ['#7F77DD','#1D9E75','#378ADD','#D85A30','#D4537E','#BA7517','#639922','#E24B4A','#888780','#534AB7']
                        : ['#AFA9EC','#5DCAA5','#85B7EB','#F0997B','#ED93B1','#FAC775','#97C459','#F09595','#B4B2A9','#CECBF6'],
                    borderRadius: 6, borderSkipped: false
                }]
            },
            options: {
                responsive: true, maintainAspectRatio: false,
                plugins: { legend: { display: false } },
                scales: {
                    y: { beginAtZero: true, grid: { color: isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)' }, ticks: { color: isDark ? '#9c9a92' : '#73726c', callback: function(v) { return v.toLocaleString(); } } },
                    x: { grid: { display: false }, ticks: { color: isDark ? '#9c9a92' : '#73726c', maxRotation: 45, autoSkip: false } }
                }
            }
        });
    });
    </script>"""


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
    chart_html = _render_chart(metrics)
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
