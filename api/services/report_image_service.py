"""
Report Image Service — Genera imágenes PNG de informes para Telegram.
Usa Pillow para crear tablas visuales legibles.
"""

import re
import textwrap
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont


# Colores
BG_COLOR = "#0d1117"
HEADER_BG = "#161b22"
ROW_EVEN = "#0d1117"
ROW_ODD = "#161b22"
TEXT_COLOR = "#e6edf3"
HEADER_TEXT = "#58a6ff"
ACCENT = "#3fb950"
BORDER = "#30363d"

# Fuentes
_FONT_DIR = "/usr/share/fonts/truetype/dejavu"


def _load_font(bold: bool = False, size: int = 14) -> ImageFont.FreeTypeFont:
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    try:
        return ImageFont.truetype(f"{_FONT_DIR}/{name}", size)
    except Exception:
        return ImageFont.load_default()


def generate_table_image(
    title: str,
    headers: list[str],
    rows: list[list[str]],
    width: int = 800,
) -> BytesIO:
    """Genera una imagen PNG con una tabla formateada."""
    title_font = _load_font(bold=True, size=20)
    header_font = _load_font(bold=True, size=14)
    body_font = _load_font(bold=False, size=13)

    row_height = 40
    header_height = 50
    title_height = 60
    padding = 15
    total_height = title_height + header_height + (len(rows) * row_height) + padding * 2

    img = Image.new("RGB", (width, total_height), BG_COLOR)
    draw = ImageDraw.Draw(img)

    y = padding

    # Título
    draw.text((padding, y), title, fill=ACCENT, font=title_font)
    y += title_height

    # Header
    col_width = (width - padding * 2) // max(len(headers), 1)
    draw.rectangle([padding, y, width - padding, y + header_height], fill=HEADER_BG)
    for i, header in enumerate(headers):
        x = padding + i * col_width + 10
        draw.text((x, y + 15), header[:25], fill=HEADER_TEXT, font=header_font)
    y += header_height

    # Línea separadora
    draw.line([padding, y, width - padding, y], fill=BORDER, width=1)

    # Filas
    for row_idx, row in enumerate(rows):
        bg = ROW_EVEN if row_idx % 2 == 0 else ROW_ODD
        draw.rectangle([padding, y, width - padding, y + row_height], fill=bg)

        for i, cell in enumerate(row):
            x = padding + i * col_width + 10
            cell_text = str(cell)[:30]
            draw.text((x, y + 12), cell_text, fill=TEXT_COLOR, font=body_font)

        y += row_height

    bio = BytesIO()
    bio.name = "report.png"
    img.save(bio, "PNG")
    bio.seek(0)
    return bio


def generate_summary_image(
    title: str,
    sections: list[dict],
    width: int = 800,
) -> BytesIO:
    """Genera imagen de resumen ejecutivo.
    sections: [{"emoji": "📋", "title": "...", "content": "..."}]
    """
    title_font = _load_font(bold=True, size=22)
    section_font = _load_font(bold=True, size=16)
    body_font = _load_font(bold=False, size=14)

    line_height = 25
    section_spacing = 40
    total_lines = sum(len(textwrap.wrap(s.get("content", ""), width=80)) + 2 for s in sections)
    total_height = 80 + total_lines * line_height + len(sections) * section_spacing

    img = Image.new("RGB", (width, max(total_height, 200)), BG_COLOR)
    draw = ImageDraw.Draw(img)

    y = 20
    draw.text((20, y), title, fill=ACCENT, font=title_font)
    y += 50

    for section in sections:
        header_text = f"{section.get('emoji', '')} {section.get('title', '')}"
        draw.text((20, y), header_text, fill=HEADER_TEXT, font=section_font)
        y += 30

        content = section.get("content", "")
        wrapped = textwrap.wrap(content, width=85)
        for line in wrapped:
            draw.text((30, y), line, fill=TEXT_COLOR, font=body_font)
            y += line_height

        y += 15

    bio = BytesIO()
    bio.name = "report.png"
    img.save(bio, "PNG")
    bio.seek(0)
    return bio


def extract_tables_from_markdown(text: str) -> list[dict]:
    """Extrae tablas Markdown del texto. Retorna lista de {title, headers, rows}."""
    tables = []
    lines = text.split("\n")
    i = 0

    while i < len(lines):
        stripped = lines[i].strip()

        # Detectar inicio de tabla: línea con pipes
        if stripped.startswith("|") and stripped.endswith("|") and stripped.count("|") >= 3:
            # Header
            headers = [c.strip() for c in stripped.split("|")[1:-1]]

            # Buscar título en la línea anterior
            title = ""
            if i > 0:
                prev = lines[i - 1].strip()
                if prev and not prev.startswith("|"):
                    title = prev.replace("**", "").replace("#", "").strip()

            i += 1
            # Saltar separador (|---|---|)
            if i < len(lines):
                sep = lines[i].strip()
                if sep.startswith("|") and "-" in sep:
                    i += 1

            # Leer filas
            rows = []
            while i < len(lines):
                row_line = lines[i].strip()
                if row_line.startswith("|") and row_line.endswith("|"):
                    cells = [c.strip().replace("**", "") for c in row_line.split("|")[1:-1]]
                    rows.append(cells)
                    i += 1
                else:
                    break

            if headers and rows:
                tables.append({"title": title or "Datos", "headers": headers, "rows": rows})
        else:
            i += 1

    return tables


def text_has_tables(text: str) -> bool:
    """Detecta si el texto contiene tablas Markdown."""
    return bool(re.search(r'\|.+\|.+\|', text))
