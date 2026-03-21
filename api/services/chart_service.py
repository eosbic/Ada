"""
Generacion de graficos estadisticos desde texto de respuesta.
"""

import json
import os
import re
import uuid
import unicodedata
from datetime import datetime
from pathlib import Path

from api.services.capability_installer import ensure_package


ARTIFACTS_DIR = Path("generated_artifacts")
ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)


def _charts_enabled() -> bool:
    value = os.getenv("ENABLE_AUTO_CHARTS", "true").strip().lower()
    return value in {"1", "true", "yes", "on"}


def wants_chart(message: str) -> bool:
    if not _charts_enabled():
        return False
    msg = (message or "").lower()
    msg = "".join(ch for ch in unicodedata.normalize("NFD", msg) if unicodedata.category(ch) != "Mn")
    markers = [
        "grafico",
        "grafica",
        "chart",
        "estadistica",
        "estadistico",
        "plot",
        "visualiza",
        "visualizacion",
    ]
    return any(k in msg for k in markers)


def _to_float(value) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).strip()
    text = text.replace("%", "").replace("$", "").replace(" ", "")
    text = text.replace(".", "").replace(",", ".") if text.count(",") == 1 and text.count(".") > 1 else text
    text = text.replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def _clean_label(label: str) -> str:
    text = (label or "").strip()
    text = re.sub(r"[*`_~#>\[\]]", "", text)
    text = re.sub(r"\s+", " ", text).strip(" :-")
    return text[:42] or "item"


def _normalize_markdown_line(line: str) -> str:
    cleaned = (line or "").strip()
    cleaned = re.sub(r"^\s*[-*]\s+", "", cleaned)
    cleaned = re.sub(r"^\s*\d+\.\s+", "", cleaned)
    cleaned = re.sub(r"[*`_~#>\[\]]", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _extract_json_blocks(text: str) -> list[str]:
    blocks = re.findall(r"```json\s*(.*?)```", text or "", flags=re.DOTALL | re.IGNORECASE)
    if blocks:
        return blocks
    generic = re.findall(r"```\s*(\[.*?\]|\{.*?\})\s*```", text or "", flags=re.DOTALL)
    return generic


def _points_from_payload(payload) -> list[tuple[str, float]]:
    points = []

    if isinstance(payload, dict):
        for key, value in payload.items():
            number = _to_float(value)
            if number is not None:
                points.append((_clean_label(str(key)), number))
        return points

    if isinstance(payload, list):
        for i, item in enumerate(payload):
            if isinstance(item, dict):
                label = item.get("label") or item.get("name") or item.get("categoria") or item.get("category") or item.get("x")
                value = item.get("value") or item.get("y") or item.get("total") or item.get("amount")
                number = _to_float(value)
                if label and number is not None:
                    points.append((_clean_label(str(label)), number))
            else:
                number = _to_float(item)
                if number is not None:
                    points.append((f"item_{i+1}", number))
    return points


def extract_stat_points(text: str, max_points: int = 12) -> list[tuple[str, float]]:
    seen = set()
    points: list[tuple[str, float]] = []

    for block in _extract_json_blocks(text):
        try:
            parsed = json.loads(block)
            for label, value in _points_from_payload(parsed):
                key = label.lower()
                if key not in seen:
                    seen.add(key)
                    points.append((label, value))
        except Exception:
            continue

    line_pattern = re.compile(
        r"^([A-Za-z0-9_À-ÿ /%()\-]{1,80})\s*[:=]\s*([-+]?\d+(?:[.,]\d+)?)\b",
        flags=re.IGNORECASE,
    )
    inline_pattern = re.compile(
        r"([A-Za-z0-9_À-ÿ /%()\-]{2,80})\s*[:=]\s*([-+]?\d+(?:[.,]\d+)?)",
        flags=re.IGNORECASE,
    )
    pair_pattern = re.compile(
        r"^\s*([-+]?\d+(?:[.,]\d+)?)\s*(?:de\s+)?([A-Za-z0-9_À-ÿ /%()\-]{2,40})\s*$",
        flags=re.IGNORECASE,
    )

    for raw_line in (text or "").splitlines():
        line = _normalize_markdown_line(raw_line)
        if not line:
            continue

        found = line_pattern.findall(line)
        if not found:
            found = inline_pattern.findall(line)

        if found:
            for label_raw, value_raw in found:
                label = _clean_label(label_raw)
                value = _to_float(value_raw)
                if value is None:
                    continue
                key = label.lower()
                if key not in seen:
                    seen.add(key)
                    points.append((label, value))
            continue

        # fallback: "2 aprobados"
        if re.match(r"^\s*[-+]?\d", line):
            compact_hits = pair_pattern.findall(line)
            for value_raw, label_raw in compact_hits:
                label = _clean_label(label_raw)
                value = _to_float(value_raw)
                if value is None:
                    continue
                key = label.lower()
                if key not in seen:
                    seen.add(key)
                    points.append((label, value))

    if len(points) < 2:
        return []
    return points[:max_points]


def generate_chart_from_text(content: str, title: str = "Grafico estadistico") -> dict:
    if not ensure_package("matplotlib", "matplotlib"):
        return {
            "ok": False,
            "error": "No se pudo instalar/usar matplotlib para generar grafico.",
        }

    points = extract_stat_points(content or "")
    if len(points) < 2:
        return {
            "ok": False,
            "error": "No hay suficientes datos numericos para generar grafico (minimo 2 puntos).",
        }

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        labels = [p[0] for p in points]
        values = [p[1] for p in points]

        fig, ax = plt.subplots(figsize=(8.5, 4.8), dpi=120)
        ax.bar(labels, values, color="#2E86AB")
        ax.set_title(title)
        ax.set_ylabel("Valor")
        ax.grid(axis="y", linestyle="--", alpha=0.35)
        plt.xticks(rotation=25, ha="right")
        fig.tight_layout()

        safe_title = re.sub(r"[^a-zA-Z0-9_-]+", "_", title)[:45] or "grafico"
        filename = f"{safe_title}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}.png"
        file_path = ARTIFACTS_DIR / filename
        fig.savefig(str(file_path), format="png")
        plt.close(fig)

        return {
            "ok": True,
            "type": "chart",
            "file_path": str(file_path.resolve()),
            "file_name": filename,
            "mime_type": "image/png",
            "points_count": len(points),
        }
    except Exception as e:
        return {
            "ok": False,
            "error": f"Error generando grafico: {e}",
        }
