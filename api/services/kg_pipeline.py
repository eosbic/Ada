"""
Knowledge Graph Pipeline — Helper reutilizable para todos los agentes.
Ejecuta auto_tag + extract_entities + weave_links en thread aislado.
"""

import threading


def run_kg_pipeline(report_id: str, empresa_id: str, content: str, alerts: str = "") -> None:
    """Ejecuta auto_tag + extract_entities + weave_links en thread aislado. No-bloqueante."""
    if not report_id or not empresa_id:
        return

    def _run():
        import asyncio
        from api.services.auto_tagger import auto_tag_report
        from api.services.entity_extractor import extract_entities
        from api.services.link_weaver import weave_links

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(auto_tag_report(report_id, content))
            ents = loop.run_until_complete(extract_entities(content, alerts))
            loop.run_until_complete(weave_links(report_id, empresa_id, ents, content))
            print(f"KG PIPELINE OK: {report_id[:8]}...")
        except Exception as e:
            print(f"KG PIPELINE error ({report_id[:8]}): {e}")
        finally:
            loop.close()

    try:
        t = threading.Thread(target=_run)
        t.start()
        t.join(timeout=30)
    except Exception as e:
        print(f"KG PIPELINE thread error: {e}")
