"""
Artifact Service — PDFs profesionales estilo propuesta empresarial.
Fondo blanco, tipografia Helvetica, metricas en cards grises, alertas con
borde lateral de color, graficos light, footer discreto.
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
from reportlab.lib.units import inch
from reportlab.lib.colors import HexColor, white, black
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle,
    HRFlowable,
)


ARTIFACTS_DIR = Path("generated_artifacts")
ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)

# ── Paleta corporativa ──────────────────────────────────────
C_BLACK = HexColor("#1a1a1a")
C_DARK = HexColor("#333333")
C_GRAY = HexColor("#666666")
C_GRAY_LIGHT = HexColor("#999999")
C_BORDER = HexColor("#d0d0cc")
C_CARD_BG = HexColor("#f5f5f0")
C_WHITE = white
C_ACCENT = HexColor("#2563eb")  # azul sobrio para enlaces / tipo de reporte

C_ALERT_CRITICAL_BORDER = HexColor("#dc2626")
C_ALERT_CRITICAL_BG = HexColor("#fef2f2")
C_ALERT_CRITICAL_TEXT = HexColor("#7f1d1d")

C_ALERT_WARNING_BORDER = HexColor("#d97706")
C_ALERT_WARNING_BG = HexColor("#fffbeb")
C_ALERT_WARNING_TEXT = HexColor("#78350f")

C_ALERT_INFO_BORDER = HexColor("#2563eb")
C_ALERT_INFO_BG = HexColor("#eff6ff")
C_ALERT_INFO_TEXT = HexColor("#1e3a5f")

ALERT_COLORS = {
    "critical": {"bg": C_ALERT_CRITICAL_BG, "border": C_ALERT_CRITICAL_BORDER, "text": C_ALERT_CRITICAL_TEXT, "label": "CRITICO"},
    "warning":  {"bg": C_ALERT_WARNING_BG,  "border": C_ALERT_WARNING_BORDER,  "text": C_ALERT_WARNING_TEXT,  "label": "ALERTA"},
    "info":     {"bg": C_ALERT_INFO_BG,     "border": C_ALERT_INFO_BORDER,     "text": C_ALERT_INFO_TEXT,     "label": "INFO"},
}

TYPE_LABELS = {
    "excel_analysis": "Analisis de Datos",
    "consolidated_analysis": "Analisis Consolidado",
    "proactive_briefing": "Briefing Ejecutivo",
    "document_analysis": "Analisis de Documento",
    "image_analysis": "Analisis de Imagen",
}


# ── Utilidades ──────────────────────────────────────────────

def wants_pdf(message: str) -> bool:
    """Detecta si el usuario quiere un PDF."""
    msg = (message or "").lower()
    msg = "".join(ch for ch in unicodedata.normalize("NFD", msg) if unicodedata.category(ch) != "Mn")
    return any(k in msg for k in ["pdf", "en pdf", "genera pdf", "exporta pdf", "informe pdf"])


def _format_metric_val(key: str, value, currency: str = "COP") -> str:
    """Formatea valor de metrica usando locale_formatter."""
    from api.services.locale_formatter import format_currency, format_number
    if not isinstance(value, (int, float)):
        return str(value)
    money_kw = ("total", "venta", "ingreso", "costo", "gasto", "precio", "valor", "factur", "revenue", "cost")
    if any(k in key.lower() for k in money_kw):
        return format_currency(value, currency)
    if "promedio" in key.lower() or "margen" in key.lower():
        return format_number(value, currency)
    if isinstance(value, float) and value != int(value):
        return f"{value:,.2f}"
    return f"{int(value):,}"


def _format_metric_label(key: str) -> str:
    return key.replace("_", " ").strip().capitalize()


# ── Estilos ─────────────────────────────────────────────────

def _get_styles() -> dict:
    """Estilos Helvetica, jerarquia clara, fondo blanco."""
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("PDFTitle", parent=base["Heading1"],
            fontName="Helvetica-Bold", fontSize=18, textColor=C_BLACK,
            spaceAfter=2, leading=22),
        "subtitle": ParagraphStyle("PDFSubtitle", parent=base["Normal"],
            fontName="Helvetica", fontSize=9, textColor=C_GRAY_LIGHT,
            spaceAfter=10, leading=12),
        "type_badge": ParagraphStyle("TypeBadge", parent=base["Normal"],
            fontName="Helvetica-Bold", fontSize=8, textColor=C_ACCENT,
            spaceAfter=6, leading=10),
        "h2": ParagraphStyle("PDFH2", parent=base["Heading2"],
            fontName="Helvetica-Bold", fontSize=14, textColor=C_BLACK,
            spaceBefore=18, spaceAfter=8, leading=17),
        "h3": ParagraphStyle("PDFH3", parent=base["Heading3"],
            fontName="Helvetica-Bold", fontSize=11, textColor=C_DARK,
            spaceBefore=12, spaceAfter=6, leading=14),
        "body": ParagraphStyle("PDFBody", parent=base["Normal"],
            fontName="Helvetica", fontSize=10, textColor=C_DARK,
            leading=15, spaceAfter=6),
        "body_small": ParagraphStyle("PDFSmall", parent=base["Normal"],
            fontName="Helvetica", fontSize=8, textColor=C_GRAY,
            leading=11, spaceAfter=3),
        "metric_value": ParagraphStyle("MetricVal", parent=base["Normal"],
            fontName="Helvetica-Bold", fontSize=16, textColor=C_BLACK,
            alignment=TA_CENTER, leading=20),
        "metric_label": ParagraphStyle("MetricLbl", parent=base["Normal"],
            fontName="Helvetica", fontSize=7, textColor=C_GRAY,
            alignment=TA_CENTER, leading=10, spaceAfter=0),
    }


# ── Secciones del PDF ──────────────────────────────────────

def _build_header(title: str, report_type: str, created_at,
                  generated_by: str, source_file: str, styles: dict) -> list:
    """Header: badge de tipo, titulo grande, metadata, linea divisora."""
    f = []
    type_label = TYPE_LABELS.get(report_type, report_type.replace("_", " ").title())
    f.append(Paragraph(escape(type_label.upper()), styles["type_badge"]))
    f.append(Paragraph(escape(title), styles["title"]))

    meta = []
    if created_at:
        from api.services.locale_formatter import format_date
        meta.append(format_date(created_at, long_format=True))
    if generated_by:
        meta.append(f"Modelo: {generated_by}")
    if source_file:
        meta.append(f"Fuente: {source_file}")
    if meta:
        f.append(Paragraph(escape("  \u2022  ".join(meta)), styles["subtitle"]))

    f.append(HRFlowable(width="100%", thickness=0.75, color=C_BORDER, spaceAfter=14))
    return f


def _build_metrics(metrics: dict, currency: str, styles: dict) -> list:
    """Metricas en cards con fondo gris claro, bordes sutiles."""
    if not metrics:
        return []
    numeric = {k: v for k, v in metrics.items()
               if isinstance(v, (int, float)) and not k.startswith("_")}
    if not numeric:
        return []

    items = list(numeric.items())[:8]
    f = [Paragraph("Metricas clave", styles["h2"])]

    cols = min(4, len(items))
    rows_data = []
    row = []
    for key, value in items:
        cell = [
            Paragraph(_format_metric_val(key, value, currency), styles["metric_value"]),
            Spacer(1, 2),
            Paragraph(escape(_format_metric_label(key)), styles["metric_label"]),
        ]
        row.append(cell)
        if len(row) >= cols:
            rows_data.append(row)
            row = []
    if row:
        while len(row) < cols:
            row.append([""])
        rows_data.append(row)

    if rows_data:
        cw = 6.5 * inch / cols
        t = Table(rows_data, colWidths=[cw] * cols)
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), C_CARD_BG),
            ("BOX", (0, 0), (-1, -1), 0.5, C_BORDER),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, C_BORDER),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 12),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ]))
        f.append(t)
        f.append(Spacer(1, 14))
    return f


def _build_alerts(alerts: list, styles: dict) -> list:
    """Alertas: fondo casi blanco, borde izquierdo de color, texto oscuro."""
    if not alerts:
        return []

    f = [Paragraph("Alertas y senales", styles["h2"])]
    order = {"critical": 0, "warning": 1, "info": 2}
    sorted_a = sorted(alerts, key=lambda a: order.get(a.get("level", "info"), 9))

    for alert in sorted_a[:15]:
        level = alert.get("level", "info")
        message = alert.get("message", "")
        ac = ALERT_COLORS.get(level, ALERT_COLORS["info"])

        label_s = ParagraphStyle("_al", fontName="Helvetica-Bold", fontSize=7,
                                 textColor=ac["border"], leading=10)
        text_s = ParagraphStyle("_at", fontName="Helvetica", fontSize=9,
                                textColor=ac["text"], leading=13)

        row = [[Paragraph(ac["label"], label_s), Paragraph(escape(message), text_s)]]
        t = Table(row, colWidths=[55, 6.5 * inch - 65])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), ac["bg"]),
            ("LINEBEFOREE", (0, 0), (0, -1), 3, ac["border"]),  # left border
            ("LEFTPADDING", (0, 0), (0, 0), 10),
            ("LEFTPADDING", (1, 0), (1, 0), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 7),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]))
        f.append(t)
        f.append(Spacer(1, 5))

    f.append(Spacer(1, 8))
    return f


def _build_charts(metrics: dict, markdown: str, styles: dict) -> tuple[list, list[str]]:
    """Genera graficos en modo claro e incrusta. Retorna (flowables, paths)."""
    f = []
    paths = []
    try:
        from api.services.chart_generator import generate_charts_from_metrics
        chart_paths = generate_charts_from_metrics(metrics, markdown, light_mode=True)
        if chart_paths:
            f.append(Paragraph("Visualizacion", styles["h2"]))
            for p in chart_paths:
                if os.path.exists(p):
                    paths.append(p)
                    img = Image(p, width=6.2 * inch, height=3.2 * inch)
                    f.append(img)
                    f.append(Spacer(1, 12))
    except Exception as e:
        print(f"PDF: Error generando graficos: {e}")
    return f, paths


def _build_content(markdown: str, styles: dict) -> list:
    """Convierte markdown a flowables de ReportLab."""
    if not markdown:
        return []
    f = [Paragraph("Analisis detallado", styles["h2"])]
    lines = re.sub(r"\n{3,}", "\n\n", (markdown or "").strip()).split("\n")
    buf = []

    def flush():
        if buf:
            block = " ".join(buf)
            block = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", block)
            block = re.sub(r"\*(.+?)\*", r"<i>\1</i>", block)
            block = escape(block).replace("&lt;b&gt;", "<b>").replace("&lt;/b&gt;", "</b>")
            block = block.replace("&lt;i&gt;", "<i>").replace("&lt;/i&gt;", "</i>")
            f.append(Paragraph(block, styles["body"]))
            buf.clear()

    for line in lines:
        s = line.strip()
        if not s:
            flush()
            f.append(Spacer(1, 4))
        elif s.startswith("### "):
            flush(); f.append(Paragraph(escape(s[4:]), styles["h3"]))
        elif s.startswith("## "):
            flush(); f.append(Paragraph(escape(s[3:]), styles["h2"]))
        elif s.startswith("# "):
            flush(); f.append(Paragraph(escape(s[2:]), styles["h2"]))
        elif s.startswith("- ") or s.startswith("* "):
            flush()
            bt = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s[2:])
            bt = escape(bt).replace("&lt;b&gt;", "<b>").replace("&lt;/b&gt;", "</b>")
            f.append(Paragraph(f"\u2022  {bt}", styles["body"]))
        elif re.match(r"^\d+\.\s", s):
            flush(); f.append(Paragraph(escape(s), styles["body"]))
        else:
            buf.append(s)
    flush()
    return f


def _page_footer(canvas, doc):
    """Footer discreto: ADA V5.0 en gris + numero de pagina."""
    canvas.saveState()
    # Linea fina superior
    canvas.setStrokeColor(HexColor("#d0d0cc"))
    canvas.setLineWidth(0.5)
    y = 35
    canvas.line(doc.leftMargin, y, LETTER[0] - doc.rightMargin, y)
    # Texto
    canvas.setFillColor(HexColor("#999999"))
    canvas.setFont("Helvetica", 7)
    canvas.drawString(doc.leftMargin, 22,
                      f"Generado por ADA V5.0  \u2014  {datetime.utcnow().strftime('%d/%m/%Y %H:%M UTC')}")
    canvas.drawRightString(LETTER[0] - doc.rightMargin, 22,
                           f"Pagina {canvas.getPageNumber()}")
    canvas.restoreState()


# ── Funcion principal ───────────────────────────────────────

def generate_professional_pdf(report_data: dict) -> dict:
    """
    Genera PDF profesional estilo propuesta de consultoria.

    Args:
        report_data: title, report_type, metrics_summary, alerts,
                     markdown_content, created_at, generated_by,
                     source_file, empresa_id (para locale)
    Returns:
        dict con ok, file_path, file_name, mime_type
    """
    title = report_data.get("title", "Reporte")
    report_type = report_data.get("report_type", "general")
    markdown = report_data.get("markdown_content", "")
    created_at = report_data.get("created_at")
    generated_by = report_data.get("generated_by", "")
    source_file = report_data.get("source_file", "")
    empresa_id = report_data.get("empresa_id", "")

    metrics = report_data.get("metrics_summary", {})
    if isinstance(metrics, str):
        try: metrics = json.loads(metrics)
        except Exception: metrics = {}

    alerts = report_data.get("alerts", [])
    if isinstance(alerts, str):
        try: alerts = json.loads(alerts)
        except Exception: alerts = []

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
            str(file_path), pagesize=LETTER,
            leftMargin=0.85 * inch, rightMargin=0.85 * inch,
            topMargin=0.65 * inch, bottomMargin=0.65 * inch,
        )

        story = []
        story.extend(_build_header(title, report_type, created_at, generated_by, source_file, styles))
        story.extend(_build_metrics(metrics, currency, styles))

        chart_f, chart_paths = _build_charts(metrics, markdown, styles)
        story.extend(chart_f)

        story.extend(_build_alerts(alerts, styles))
        story.extend(_build_content(markdown, styles))

        doc.build(story, onFirstPage=_page_footer, onLaterPages=_page_footer)

        return {
            "ok": True,
            "file_path": str(file_path.resolve()),
            "file_name": filename,
            "mime_type": "application/pdf",
        }
    except Exception as e:
        import traceback; traceback.print_exc()
        return {"ok": False, "error": f"Error generando PDF: {e}"}
    finally:
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
