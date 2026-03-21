"""
Entity Extractor — Extrae entidades clave de texto de negocio.
Reutilizado por link_weaver y briefing_agent.
Usa Gemini Flash (gratis) via selector.get_model("routing").
"""

import json
from models.selector import selector


async def extract_entities(text: str, alerts: list = None, max_entities: int = 5) -> list:
    """
    Extrae nombres de clientes, productos, proveedores, personas del texto.
    Retorna lista de strings.
    """
    model, _ = selector.get_model("routing")  # Gemini Flash, gratis

    alerts_text = ""
    if alerts:
        alerts_text = "\nALERTAS:\n" + "\n".join([a.get("message", "") for a in alerts])

    response = await model.ainvoke([
        {"role": "system", "content": (
            "Extrae entidades clave del siguiente analisis de negocio.\n"
            "Busca: nombres de clientes, productos, proveedores, personas, empresas.\n"
            "Responde SOLO JSON array de strings: [\"Galletas Festival\", \"Carlos Perez\", ...]\n"
            f"Maximo {max_entities} entidades mas relevantes. Sin markdown."
        )},
        {"role": "user", "content": f"ANALISIS:\n{text[:3000]}{alerts_text}"},
    ])

    try:
        raw = response.content.strip().replace("```json", "").replace("```", "").strip()
        entities = json.loads(raw)
        if not isinstance(entities, list):
            entities = []
    except Exception as e:
        print(f"ENTITY_EXTRACTOR: Error parseando entidades: {e}")
        entities = []

    print(f"ENTITY_EXTRACTOR: {len(entities)} entidades extraidas: {entities}")
    return entities[:max_entities]