"""
Backfill: Auto-tag y link reportes existentes.
Ejecutar UNA SOLA VEZ despues de desplegar los nuevos servicios.

Uso: python -m scripts.backfill_tags_links
"""

import asyncio
import json
from sqlalchemy import text as sql_text
from api.database import sync_engine
from api.services.auto_tagger import auto_tag_report
from api.services.entity_extractor import extract_entities
from api.services.link_weaver import weave_links


async def backfill():
    with sync_engine.connect() as conn:
        rows = conn.execute(
            sql_text("""
                SELECT id, empresa_id, markdown_content, alerts
                FROM ada_reports
                WHERE is_archived = FALSE
                AND (tags IS NULL OR tags = '{}')
                ORDER BY created_at DESC
                LIMIT 100
            """)
        ).fetchall()

    print(f"BACKFILL: {len(rows)} reportes sin tags")

    for row in rows:
        report_id = str(row.id)
        empresa_id = str(row.empresa_id)
        text = row.markdown_content or ""

        if not text:
            continue

        print(f"\nBACKFILL: Procesando {report_id[:8]}...")

        # 1. Auto-tag
        tags = await auto_tag_report(report_id, text)

        # 2. Extraer entidades
        alerts = []
        if row.alerts:
            try:
                alerts = json.loads(row.alerts) if isinstance(row.alerts, str) else row.alerts
            except Exception:
                alerts = []

        entities = await extract_entities(text, alerts)

        # 3. Tejer enlaces
        links = await weave_links(report_id, empresa_id, entities, text)

        print(f"  -> tags: {tags}, entities: {entities}, links: {len(links)}")

        # Rate limiting: esperar entre reportes para no saturar Gemini
        await asyncio.sleep(1)

    print(f"\nBACKFILL: Completado")


if __name__ == "__main__":
    asyncio.run(backfill())