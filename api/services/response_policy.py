"""
Respuesta transversal con BLUF + trazabilidad de fuentes.
"""

from typing import Dict, List
import re


def _normalize_sources(raw_sources: List[Dict]) -> List[Dict]:
    normalized = []
    for s in raw_sources or []:
        if not isinstance(s, dict):
            continue
        name = str(s.get("name", "")).strip() or "desconocida"
        detail = str(s.get("detail", "")).strip()
        confidence = float(s.get("confidence", 0.0))
        normalized.append({"name": name, "detail": detail, "confidence": confidence})
    return normalized


def _pick_primary_secondary(sources: List[Dict]) -> Dict:
    if not sources:
        return {"primary": "desconocida", "secondary": "desconocida"}

    ordered = sorted(sources, key=lambda x: x.get("confidence", 0.0), reverse=True)
    primary = ordered[0]["name"]
    secondary = ordered[1]["name"] if len(ordered) > 1 else ordered[0]["name"]
    return {"primary": primary, "secondary": secondary}


def _confidence_label(confidence: float) -> str:
    c = float(confidence or 0.0)
    if c >= 0.8:
        return "alta"
    if c >= 0.55:
        return "media"
    return "baja"


def _clean_response_text(text: str) -> str:
    body = (text or "").strip()
    if not body:
        return body

    # Quita marcador BLUF visible para salida final.
    body = re.sub(r"(?im)^\s*bluf\s*:\s*", "", body)

    # Limpia markdown comun para salida mas ejecutiva.
    body = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", body)           # headers
    body = re.sub(r"\*\*(.*?)\*\*", r"\1", body, flags=re.DOTALL)  # bold
    body = re.sub(r"__(.*?)__", r"\1", body, flags=re.DOTALL)       # bold alt
    body = re.sub(r"(?m)^\s*\*\s+", "- ", body)                     # bullets * -> -
    body = re.sub(r"(?m)^\s*-\s{2,}", "- ", body)                   # normaliza sangria bullets
    body = body.replace("*", "")                                     # quita asteriscos residuales

    # Elimina trazabilidad embebida para dejar solo el bloque canonico final.
    body = re.sub(r"(?im)^\s*trazabilidad\s*:\s*$", "", body)
    body = re.sub(r"(?im)^\s*[-]?\s*fuente primaria\s*:\s*.*$", "", body)
    body = re.sub(r"(?im)^\s*[-]?\s*fuente secundaria\s*:\s*.*$", "", body)

    body = re.sub(r"\n{3,}", "\n\n", body).strip()
    return body


def enforce_response_contract(response: str, sources_used: List[Dict], confidence: float = 0.0) -> Dict:
    text = _clean_response_text(response)
    sources = _normalize_sources(sources_used)
    picks = _pick_primary_secondary(sources)
    confidence_value = float(confidence or 0.0)
    confidence_text = _confidence_label(confidence_value)

    # Cierre condicional segun confianza.
    if confidence_text == "baja":
        text += "\n\nNota: confianza baja. Se recomienda validar con una fuente adicional."

    # Bloque de evidencia obligatorio.
    evidence = (
        "\n\n---\n"
        f"Fuentes:\n- Primaria: {picks['primary']}\n- Secundaria: {picks['secondary']}\n"
        f"Confianza: {round(confidence_value, 2)} ({confidence_text})"
    )

    return {
        "response": text + evidence,
        "traceability": {
            "primary_source": picks["primary"],
            "secondary_source": picks["secondary"],
            "sources_used": sources,
            "confidence": confidence_value,
            "confidence_label": confidence_text,
        },
    }
