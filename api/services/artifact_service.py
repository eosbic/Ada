"""
Artifact Service — Genera PDFs profesionales con graficos, metricas y alertas.
"""

import json
import os
import re
import uuid
import unicodedata
from pathlib import Path
from datetime import datetime
from xml.sax.saxutils import escape

from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch, mm
from reportlab.lib.colors import HexColor, white, black
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle,
    KeepTogether, HRFlowable, PageBreak,
)
from reportlab.platypus.flowables import Flowable


ARTIFACTS_DIR = Path("generated_artifacts")
ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)

# Colors
C_BG = HexColor("#0c1220")
C_CARD = HexColor("#101828")
C_ACCENT = HexColor("#00e5ff")
C_TEXT = HexColor("#e0f4ff")
C_TEXT2 = HexColor("#7eafc9")
C_BORDER = HexColor("#1a2840")
C_GREEN = HexColor("#00ff9d")
C_RED = HexColor("#ff3d5a")
C_YELLOW = HexColor("#ffd60a")
C_ORANGE = HexColor("#ff6b35")
C_WHITE = white

ALERT_COLORS = {
    "critical": {"bg": HexColor("#2a1215"), "border": C_RED, "text": HexColor("#F09595"), "label": "CRITICO"},
    "warning": {"bg": HexColor("#2a2008"), "border": C_ORANGE, "text": HexColor("#FAC775"), "label": "ALERTA"},
    "info": {"bg": HexColor("#0c1a2e"), "border": C_ACCENT, "text": HexColor("#85B7EB"), "label": "INFO"},
}

TYPE_LABELS = {
    "excel_analysis": "Analisis de datos",
    "consolidated_analysis": "Analisis consolidado",
    "proactive_briefing": "Briefing ejecutivo",
    "document_analysis": "Analisis de documento",
    "image_analysis": "Analisis de imagen",
}


def wants_pdf(message: str) -> bool:
    """Detecta si el usuario quiere un PDF."""
    msg = (message or "").lower()
    msg = "".join(ch for ch in unicodedata.normalize("NFD", msg) if unicodedata.category(ch) != "Mn")
    return any(k in msg for k in ["pdf", "en pdf", "genera pdf", "exporta pdf", "informe pdf"])


def _get_styles():
    """Crea estilos personalizados para el PDF."""
    base = getSampleStyleSheet()

    styles = {
        "title": ParagraphStyle("PDFTitle", parent=base["Heading1"],
            fontSize=20, textColor=C_TEXT, spaceAfter=4, leading=24),
        "subtitle": ParagraphStyle("PDFSubtitle", parent=base["Normal"],
            fontSize=9, textColor=C_TEXT2, spaceAfter=12),
        "h2": ParagraphStyle("PDFH2", parent=base["Heading2"],
            fontSize=14, textColor=C_ACCENT, spaceBefore=16, spaceAfter=8, leading=18),
        "h3": ParagraphStyle("PDFH3", parent=base["Heading3"],
            fontSize=11, textColor=C_TEXT, spaceBefore=10, spaceAfter=6, leading=14),
        "body": ParagraphStyle("PDFBody", parent=base["Normal"],
            fontSize=9, textColor=C_TEXT, leading=14, spaceAfter=6),
        "body_small": ParagraphStyle("PDFBodySmall", parent=base["Normal"],
            fontSize=8, textColor=C_TEXT2, leading=12, spaceAfter=4),
        "metric_value": ParagraphStyle("MetricValue", parent=base["Normal"],
            fontSize=16, textColor=C_ACCENT, alignment=TA_CENTER, leading=20),
        "metric_label": ParagraphStyle("MetricLabel", parent=base["Normal"],
            fontSize=7, textColor=C_TEXT2, alignment=TA_CENTER, leading=10),
        "alert_label": ParagraphStyle("AlertLabel", parent=base["Normal"],
            fontSize=7, textColor=C_RED, leading=10),
        "alert_text": ParagraphStyle("AlertText", parent=base["Normal"],
            fontSize=8, textColor=C_TEXT, leading=12),
        "footer": ParagraphStyle("PDFFooter", parent=base["Normal"],
            fontSize=7, textColor=C_TEXT2, alignment=TA_CENTER),
    }
    return styles


class RoundedRect(Flowable):
    """Fondo redondeado para secciones."""
    def __init__(self, width, height, color=C_CARD, radius=6):
        Flowable.__init__(self)
        self.width = width
        self.height = height
        self.color = color
        self.radius = radius

    def draw(self):
        self.canv.setFillColor(self.color)
        self.canv.roundRect(0, 0, self.width, self.height, self.radius, fill=1, stroke=0)


def _format_metric_val(key: str, value, currency: str = "COP") -> str:
    """Formatea valor de metrica usando locale_formatter."""
    from api.services.locale_formatter import format_currency, format_number
    if not isinstance(value, (int, float)):
        return str(value)
    money_keywords = ("total", "venta", "ingreso", "costo", "gasto", "precio", "valor", "factur", "revenue", "cost")
    if any(k in key.lower() for k in money_keywords):
        return format_currency(value, currency)
    if "promedio" in key.lower() or "margen" in key.lower():
        return format_number(value, currency)
    if isinstance(value, float) and value != int(value):
        return f"{value:,.2f}"
    return f"{int(value):,}"


def _format_metric_label(key: str) -> str:
    return key.replace("_", " ").strip().capitalize()


def _clean_markdown(text: str) -> str:
    """Limpia markdown para uso en ReportLab."""
    clean = (text or "").strip()
    clean = re.sub(r"\n{3,}", "\n\n", clean)
    return clean


def _md_to_paragraphs(text: str, styles: dict) -> list:
    """Convierte markdown a lista de flowables de ReportLab."""
    flowables = []
    lines = _clean_markdown(text).split("\n")
    buffer = []

    def flush_buffer():
        if buffer:
            block = " ".join(buffer)
            block = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", block)
            block = re.sub(r"\*(.+?)\*", r"<i>\1</i>", block)
            block = escape(block).replace("&lt;b&gt;", "<b>").replace("&lt;/b&gt;", "</b>")
            block = block.replace("&lt;i&gt;", "<i>").replace("&lt;/i&gt;", "</i>")
            flowables.append(Paragraph(block, styles["body"]))
            buffer.clear()

    for line in lines:
        stripped = line.strip()
        if not stripped:
            flush_buffer()
            flowables.append(Spacer(1, 4))
            continue
        if stripped.startswith("### "):
            flush_buffer()
            flowables.append(Paragraph(escape(stripped[4:]), styles["h3"]))
        elif stripped.startswith("## "):
            flush_buffer()
            flowables.append(Paragraph(escape(stripped[3:]), styles["h2"]))
        elif stripped.startswith("# "):
            flush_buffer()
            flowables.append(Paragraph(escape(stripped[2:]), styles["h2"]))
        elif stripped.startswith("- ") or stripped.startswith("* "):
            flush_buffer()
            bullet_text = stripped[2:]
            bullet_text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", bullet_text)
            bullet_text = escape(bullet_text).replace("&lt;b&gt;", "<b>").replace("&lt;/b&gt;", "</b>")
            flowables.append(Paragraph(f"\u2022 {bullet_text}", styles["body"]))
        elif re.match(r"^\d+\.\s", stripped):
            flush_buffer()
            flowables.append(Paragraph(escape(stripped), styles["body"]))
        else:
            buffer.append(stripped)

    flush_buffer()
    return flowables


def _build_header(title: str, report_type: str, created_at, generated_by: str,
                  source_file: str, styles: dict) -> list:
    """Construye header del PDF."""
    flowables = []
    type_label = TYPE_LABELS.get(report_type, report_type.replace("_", " ").title())
    flowables.append(Paragraph(f"<font color='#00e5ff' size='8'>{escape(type_label.upper())}</font>", styles["body_small"]))
    flowables.append(Spacer(1, 4))
    flowables.append(Paragraph(escape(title), styles["title"]))

    meta_parts = []
    if created_at:
        from api.services.locale_formatter import format_date
        meta_parts.append(format_date(created_at, long_format=True))
    if generated_by:
        meta_parts.append(f"Modelo: {generated_by}")
    if source_file:
        meta_parts.append(f"Fuente: {source_file}")
    if meta_parts:
        flowables.append(Paragraph(escape(" \u2022 ".join(meta_parts)), styles["subtitle"]))

    flowables.append(HRFlowable(width="100%", thickness=1, color=C_BORDER, spaceAfter=12))
    return flowables


def _build_metrics_section(metrics: dict, currency: str, styles: dict) -> list:
    """Construye seccion de metricas como cards."""
    if not metrics:
        return []

    numeric = {k: v for k, v in metrics.items() if isinstance(v, (int, float)) and not k.startswith("_")}
    if not numeric:
        return []

    items = list(numeric.items())[:8]
    flowables = [Paragraph("METRICAS CLAVE", styles["h2"])]

    # Build metric cards as a table (2-4 per row)
    cols = min(4, len(items))
    rows_data = []
    current_row = []

    for key, value in items:
        cell_content = [
            Paragraph(_format_metric_val(key, value, currency), styles["metric_value"]),
            Paragraph(escape(_format_metric_label(key)), styles["metric_label"]),
        ]
        current_row.append(cell_content)
        if len(current_row) >= cols:
            rows_data.append(current_row)
            current_row = []

    if current_row:
        while len(current_row) < cols:
            current_row.append([""])
        rows_data.append(current_row)

    if rows_data:
        col_width = 6.5 * inch / cols
        table = Table(rows_data, colWidths=[col_width] * cols)
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), C_CARD),
            ("BOX", (0, 0), (-1, -1), 0.5, C_BORDER),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, C_BORDER),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 10),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ]))
        flowables.append(table)
        flowables.append(Spacer(1, 12))

    return flowables


def _build_alerts_section(alerts: list, styles: dict) -> list:
    """Construye seccion de alertas con colores por severidad."""
    if not alerts:
        return []

    flowables = [Paragraph("ALERTAS Y SENALES", styles["h2"])]
    order = {"critical": 0, "warning": 1, "info": 2}
    sorted_alerts = sorted(alerts, key=lambda a: order.get(a.get("level", "info"), 9))

    for alert in sorted_alerts[:15]:
        level = alert.get("level", "info")
        message = alert.get("message", "")
        colors = ALERT_COLORS.get(level, ALERT_COLORS["info"])

        label_style = ParagraphStyle("al", fontSize=7, textColor=colors["border"],
                                     fontName="Helvetica-Bold", leading=10)
        text_style = ParagraphStyle("at", fontSize=8, textColor=colors["text"], leading=12)

        row = [[
            Paragraph(colors["label"], label_style),
            Paragraph(escape(message), text_style),
        ]]
        t = Table(row, colWidths=[60, 6.5 * inch - 70])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors["bg"]),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]))
        flowables.append(t)
        flowables.append(Spacer(1, 4))

    flowables.append(Spacer(1, 8))
    return flowables


def _build_charts_section(metrics: dict, markdown: str, styles: dict) -> tuple[list, list[str]]:
    """Genera e incrusta graficos. Retorna (flowables, chart_paths para cleanup)."""
    flowables = []
    chart_paths = []

    try:
        from api.services.chart_generator import generate_charts_from_metrics
        paths = generate_charts_from_metrics(metrics, markdown)
        if paths:
            flowables.append(Paragraph("VISUALIZACION", styles["h2"]))
            for path in paths:
                if os.path.exists(path):
                    chart_paths.append(path)
                    img = Image(path, width=6.2 * inch, height=3.2 * inch)
                    flowables.append(img)
                    flowables.append(Spacer(1, 10))
    except Exception as e:
        print(f"PDF: Error generando graficos: {e}")

    return flowables, chart_paths


def _build_footer_func(title: str):
    """Retorna funcion para dibujar footer en cada pagina."""
    def _footer(canvas, doc):
        canvas.saveState()
        canvas.setFillColor(C_BORDER)
        canvas.rect(0, 0, LETTER[0], 30, fill=1, stroke=0)
        canvas.setFillColor(C_TEXT2)
        canvas.setFont("Helvetica", 7)
        canvas.drawString(doc.leftMargin, 12,
                          f"Generado por ADA V5.0 \u2014 {datetime.utcnow().strftime('%d/%m/%Y %H:%M UTC')}")
        canvas.drawRightString(LETTER[0] - doc.rightMargin, 12,
                               f"Pag. {canvas.getPageNumber()}")
        canvas.restoreState()
    return _footer


def generate_professional_pdf(report_data: dict) -> dict:
    """
    Genera un PDF profesional desde datos de reporte.

    Args:
        report_data: dict con keys: title, report_type, metrics_summary,
                     alerts, markdown_content, created_at, generated_by,
                     source_file, empresa_id (opcional, para locale)

    Returns:
        dict con ok, file_path, file_name, mime_type
    """
    title = report_data.get("title", "Reporte Ada")
    report_type = report_data.get("report_type", "general")
    markdown = report_data.get("markdown_content", "")
    created_at = report_data.get("created_at")
    generated_by = report_data.get("generated_by", "")
    source_file = report_data.get("source_file", "")
    empresa_id = report_data.get("empresa_id", "")

    metrics = report_data.get("metrics_summary", {})
    if isinstance(metrics, str):
        try:
            metrics = json.loads(metrics)
        except Exception:
            metrics = {}

    alerts = report_data.get("alerts", [])
    if isinstance(alerts, str):
        try:
            alerts = json.loads(alerts)
        except Exception:
            alerts = []

    # Locale
    currency = "COP"
    if empresa_id:
        try:
            from api.services.locale_formatter import get_currency_for_empresa
            currency = get_currency_for_empresa(empresa_id)
        except Exception:
            pass

    styles = _get_styles()

    safe_title = re.sub(r"[^a-zA-Z0-9_-]+", "_", title)[:45] or "reporte"
    filename = f"{safe_title}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}.pdf"
    file_path = ARTIFACTS_DIR / filename

    chart_paths = []

    try:
        doc = SimpleDocTemplate(
            str(file_path),
            pagesize=LETTER,
            leftMargin=0.75 * inch,
            rightMargin=0.75 * inch,
            topMargin=0.6 * inch,
            bottomMargin=0.6 * inch,
        )

        story = []

        # Header
        story.extend(_build_header(title, report_type, created_at, generated_by, source_file, styles))

        # Metrics
        story.extend(_build_metrics_section(metrics, currency, styles))

        # Charts
        chart_flowables, chart_paths = _build_charts_section(metrics, markdown, styles)
        story.extend(chart_flowables)

        # Alerts
        story.extend(_build_alerts_section(alerts, styles))

        # Content
        if markdown:
            story.append(Paragraph("ANALISIS DETALLADO", styles["h2"]))
            story.extend(_md_to_paragraphs(markdown, styles))

        # Build
        footer_func = _build_footer_func(title)
        doc.build(story, onFirstPage=footer_func, onLaterPages=footer_func)

        return {
            "ok": True,
            "file_path": str(file_path.resolve()),
            "file_name": filename,
            "mime_type": "application/pdf",
        }

    except Exception as e:
        import traceback
        traceback.print_exc()
        return {
            "ok": False,
            "error": f"Error generando PDF: {e}",
        }
    finally:
        # Cleanup chart temp files
        from api.services.chart_generator import cleanup_charts
        cleanup_charts(chart_paths)


# Legacy compatibility
def generate_pdf_from_text(content: str, title: str = "Reporte Ada", image_paths: list[str] | None = None) -> dict:
    """Wrapper legacy: genera PDF basico desde texto plano."""
    return generate_professional_pdf({
        "title": title,
        "markdown_content": content,
        "metrics_summary": {},
        "alerts": [],
    })
