"""
Generacion de artefactos (PDF) desde respuestas del agente.
"""

import re
import uuid
import unicodedata
from pathlib import Path
from datetime import datetime
from xml.sax.saxutils import escape

from api.services.capability_installer import ensure_package


ARTIFACTS_DIR = Path("generated_artifacts")
ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)


def wants_pdf(message: str) -> bool:
    msg = (message or "").lower()
    msg = "".join(ch for ch in unicodedata.normalize("NFD", msg) if unicodedata.category(ch) != "Mn")
    return any(k in msg for k in ["pdf", "en pdf", "genera pdf", "exporta pdf", "informe pdf"])


def _clean_text_for_pdf(text: str) -> str:
    # Quita bloques de trazabilidad duplicados al final si existen multiples.
    clean = (text or "").strip()
    clean = re.sub(r"\n{3,}", "\n\n", clean)
    return clean


def generate_pdf_from_text(content: str, title: str = "Reporte Ada", image_paths: list[str] | None = None) -> dict:
    """
    Genera un PDF en disco y retorna metadata.
    """
    if not ensure_package("reportlab", "reportlab"):
        return {
            "ok": False,
            "error": "No se pudo instalar/usar reportlab para generar PDF.",
        }

    from reportlab.lib.pagesizes import LETTER
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image

    safe_title = re.sub(r"[^a-zA-Z0-9_-]+", "_", title)[:50] or "reporte"
    filename = f"{safe_title}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}.pdf"
    file_path = ARTIFACTS_DIR / filename

    try:
        doc = SimpleDocTemplate(str(file_path), pagesize=LETTER)
        styles = getSampleStyleSheet()
        body_style = styles["BodyText"]
        title_style = styles["Heading1"]

        story = [
            Paragraph(title, title_style),
            Spacer(1, 12),
        ]

        text = _clean_text_for_pdf(content)
        for block in text.split("\n\n"):
            escaped = escape(block).replace("\n", "<br/>")
            story.append(Paragraph(escaped, body_style))
            story.append(Spacer(1, 8))

        for img_path in image_paths or []:
            p = Path(img_path)
            if not p.exists():
                continue
            try:
                story.append(Spacer(1, 10))
                story.append(Paragraph("Grafico estadistico", styles["Heading3"]))
                chart = Image(str(p))
                chart.drawWidth = 6.8 * inch
                chart.drawHeight = 3.8 * inch
                story.append(chart)
                story.append(Spacer(1, 10))
            except Exception as e:
                story.append(Paragraph(f"No se pudo incrustar imagen: {escape(str(e))}", body_style))
                story.append(Spacer(1, 8))

        doc.build(story)
        return {
            "ok": True,
            "file_path": str(file_path.resolve()),
            "file_name": filename,
            "mime_type": "application/pdf",
        }
    except Exception as e:
        return {
            "ok": False,
            "error": f"Error generando PDF: {e}",
        }
