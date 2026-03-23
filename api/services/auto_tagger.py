"""
Auto Tagger — Asigna tags de taxonomia controlada a reportes.
Usa Gemini Flash (gratis) via selector.get_model("routing").
"""

import json
from sqlalchemy import text as sql_text
from api.database import sync_engine
from models.selector import selector


# Taxonomia fija — el LLM NO puede inventar tags fuera de esta lista
TAXONOMY = [
    "ventas", "cartera", "inventario", "clientes", "productos",
    "proveedores", "margenes", "vendedores", "geografia",
    "financiero", "riesgo", "oportunidad", "tendencia",
    "prospecto", "reunion", "proyecto", "operaciones",
]


async def auto_tag_report(report_id: str, text: str) -> list:
    """
    Asigna 2-5 tags de TAXONOMY a un reporte.
    Retorna la lista de tags asignados.
    """
    model, _ = selector.get_model("routing")  # Gemini Flash, gratis

    response = await model.ainvoke([
        {"role": "system", "content": (
            f"Asigna entre 2 y 5 tags de ESTA lista exacta: {json.dumps(TAXONOMY)}\n"
            "Responde SOLO un JSON array de strings. Sin markdown, sin explicacion.\n"
            "Ejemplo: [\"ventas\", \"clientes\", \"riesgo\"]\n"
            "SOLO usa tags de la lista. NO inventes tags nuevos."
        )},
        {"role": "user", "content": text[:2000]},
    ])

    try:
        raw = response.content.strip().replace("```json", "").replace("```", "").strip()
        tags = json.loads(raw)
        if not isinstance(tags, list):
            tags = []
        # Filtrar solo tags validos de la taxonomia
        tags = [t for t in tags if t in TAXONOMY]
        if not tags:
            tags = ["operaciones"]
    except Exception as e:
        print(f"AUTO_TAGGER: Error parseando tags: {e}")
        tags = ["operaciones"]

    # Guardar en DB
    try:
        with sync_engine.connect() as conn:
            conn.execute(
                sql_text("UPDATE ada_reports SET tags = :tags WHERE id = :id"),
                {"tags": tags, "id": report_id}
            )
            conn.commit()
        print(f"AUTO_TAGGER: Reporte {report_id[:8]}... -> tags: {tags}")
    except Exception as e:
        print(f"AUTO_TAGGER: Error guardando tags: {e}")

    return tags