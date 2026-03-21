"""
Etiquetado semantico enriquecido para ingesta documental.
"""

import json
import re
from typing import Dict, Any
from models.selector import selector


EMPTY_TAGS = {
    "tema": "general",
    "categoria": "general",
    "entidades": [],
    "keywords": [],
    "tipo_doc": "documento",
    "resumen": "",
    "fecha_doc": None,
    "montos": [],
}


def _heuristic_tags(text: str, file_name: str = "") -> Dict[str, Any]:
    out = dict(EMPTY_TAGS)
    out["tipo_doc"] = (file_name.rsplit(".", 1)[-1].lower() if "." in file_name else "documento")
    out["resumen"] = (text or "")[:280]

    money = re.findall(r"\$?\s?\d[\d\.\,]{2,}", text or "")
    if money:
        out["montos"] = money[:10]

    entities = re.findall(r"\b[A-Z][a-zA-Z]{2,}\b", text or "")
    if entities:
        out["entidades"] = list(dict.fromkeys(entities))[:20]

    words = re.findall(r"[a-zA-Z]{4,}", (text or "").lower())
    if words:
        freq = {}
        for w in words:
            freq[w] = freq.get(w, 0) + 1
        out["keywords"] = [k for k, _ in sorted(freq.items(), key=lambda kv: kv[1], reverse=True)[:12]]

    return out


def semantic_tag_document(text: str, file_name: str = "") -> Dict[str, Any]:
    snippet = (text or "")[:12000]
    if not snippet.strip():
        return _heuristic_tags(text, file_name)

    try:
        model, _ = selector.get_model("chat_with_tools")
        prompt = (
            "Extrae metadata semantica del documento y responde SOLO JSON con este contrato:\n"
            "{"
            "\"tema\": \"...\","
            "\"categoria\": \"...\","
            "\"entidades\": [\"...\"],"
            "\"keywords\": [\"...\"],"
            "\"tipo_doc\": \"...\","
            "\"resumen\": \"...\","
            "\"fecha_doc\": \"YYYY-MM-DD|null\","
            "\"montos\": [\"...\"]"
            "}\n"
            "No inventes datos."
        )
        resp = model.invoke(
            [
                {"role": "system", "content": prompt},
                {"role": "user", "content": f"Archivo: {file_name}\n\nTexto:\n{snippet}"},
            ]
        )
        raw = (resp.content or "").strip().replace("```json", "").replace("```", "")
        data = json.loads(raw)
        out = dict(EMPTY_TAGS)
        out.update({k: data.get(k, v) for k, v in EMPTY_TAGS.items()})
        return out
    except Exception as e:
        print(f"SEMANTIC TAGGER fallback: {e}")
        return _heuristic_tags(text, file_name)
