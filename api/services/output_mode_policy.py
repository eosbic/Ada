"""
Politica centralizada de salida multimodal.

Decide si la respuesta debe salir como texto o voz.
"""

import unicodedata


def _normalize(text: str) -> str:
    raw = (text or "").lower()
    return "".join(ch for ch in unicodedata.normalize("NFD", raw) if unicodedata.category(ch) != "Mn")


def decide_output_mode(message: str, source: str = "api") -> str:
    """
    Retorna:
    - "voice" cuando la intencion del usuario/entrada sugiere audio
    - "text" en el resto de casos
    """
    src = (source or "api").lower().strip()
    msg = _normalize(message)

    # Si el input ya vino por voz, prioriza salida por voz.
    if src in {"telegram_voice", "voice"}:
        return "voice"

    voice_markers = [
        "responde en audio",
        "en audio",
        "#audio",
        "/audio",
        "mensaje de voz",
        "voz",
    ]
    if any(k in msg for k in voice_markers):
        return "voice"

    return "text"
