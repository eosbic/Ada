"""
Link Weaver — Crea enlaces bidireccionales entre reportes.
Post-store: busca reportes relacionados por entidades compartidas y crea links.
Usa Gemini Flash para clasificar el tipo de relacion entre reportes.
"""

import json
from sqlalchemy import text as sql_text
from api.database import sync_engine
from models.selector import selector


# Tipos de enlace semantico
LINK_TYPES = {
    "mentions_same_entity": "Comparten cliente/producto/persona",
    "updates": "Actualiza datos de un reporte anterior",
    "contradicts": "Datos contradictorios con reporte previo",
    "extends": "Amplia o complementa analisis previo",
    "related": "Relacion tematica general",
}


async def _classify_link_type(new_text: str, existing_text: str) -> str:
    """Clasifica el tipo de relacion entre dos reportes usando Gemini Flash."""
    model, _ = selector.get_model("routing")

    try:
        response = await model.ainvoke([
            {"role": "system", "content": (
                "Clasifica la relacion entre dos reportes de negocio.\n"
                f"Opciones: {list(LINK_TYPES.keys())}\n"
                "Responde SOLO el string del tipo. Sin explicacion."
            )},
            {"role": "user", "content": (
                f"REPORTE NUEVO (extracto):\n{new_text[:800]}\n\n"
                f"REPORTE EXISTENTE (extracto):\n{existing_text[:800]}"
            )},
        ])
        link_type = response.content.strip().strip('"').strip("'")
        if link_type not in LINK_TYPES:
            link_type = "related"
    except Exception:
        link_type = "related"

    return link_type


async def weave_links(
    report_id: str,
    empresa_id: str,
    entities: list,
    report_text: str,
    max_links: int = 10,
) -> list:
    """
    Busca reportes relacionados por entidades compartidas y crea enlaces bidireccionales.
    Retorna lista de links creados.
    """
    if not entities or not empresa_id or not report_id:
        return []

    links_created = []
    seen_ids = set()

    try:
        with sync_engine.connect() as conn:
            for entity in entities:
                if len(links_created) >= max_links:
                    break

                # Buscar reportes que mencionan la misma entidad
                rows = conn.execute(
                    sql_text("""
                        SELECT id, title, markdown_content
                        FROM ada_reports
                        WHERE empresa_id = :eid
                        AND id != :rid
                        AND is_archived = FALSE
                        AND (
                            title ILIKE :like
                            OR markdown_content ILIKE :like
                        )
                        ORDER BY created_at DESC
                        LIMIT 5
                    """),
                    {"eid": empresa_id, "rid": report_id, "like": f"%{entity}%"}
                ).fetchall()

                for row in rows:
                    target_id = str(row.id)
                    if target_id in seen_ids:
                        continue
                    seen_ids.add(target_id)

                    if len(links_created) >= max_links:
                        break

                    # Clasificar tipo de enlace con Gemini Flash
                    link_type = await _classify_link_type(
                        report_text[:1000],
                        row.markdown_content[:1000] if row.markdown_content else ""
                    )

                    # Insertar enlace bidireccional: A -> B y B -> A
                    try:
                        conn.execute(
                            sql_text("""
                                INSERT INTO report_links
                                    (source_report_id, target_report_id, link_type)
                                VALUES (:s, :t, :lt)
                                ON CONFLICT (source_report_id, target_report_id) DO NOTHING
                            """),
                            {"s": report_id, "t": target_id, "lt": link_type}
                        )
                        conn.execute(
                            sql_text("""
                                INSERT INTO report_links
                                    (source_report_id, target_report_id, link_type)
                                VALUES (:s, :t, :lt)
                                ON CONFLICT (source_report_id, target_report_id) DO NOTHING
                            """),
                            {"s": target_id, "t": report_id, "lt": f"linked_from:{link_type}"}
                        )

                        links_created.append({
                            "target_id": target_id,
                            "target_title": row.title,
                            "link_type": link_type,
                            "matched_entity": entity,
                        })
                    except Exception as e:
                        print(f"LINK_WEAVER: Error insertando link: {e}")

            conn.commit()

    except Exception as e:
        print(f"LINK_WEAVER: Error general: {e}")
        import traceback
        traceback.print_exc()

    print(f"LINK_WEAVER: Reporte {report_id[:8]}... -> {len(links_created)} links creados")
    return links_created