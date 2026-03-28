"""
Prospect Scout Worker — Monitoreo continuo de oportunidades.
Revisa configuraciones activas y busca senales + leads automaticamente.
Notifica al CEO por Telegram cuando encuentra algo relevante.
"""

import os
import json
import asyncio
from api.database import sync_engine
from sqlalchemy import text

ENABLE_PROSPECT_SCOUT = os.getenv("ENABLE_PROSPECT_SCOUT", "true").lower() in ("true", "1", "yes")
CHECK_INTERVAL_SECONDS = int(os.getenv("PROSPECT_SCOUT_INTERVAL", "3600"))
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_API", "")


async def _send_telegram(chat_id: str, text_msg: str):
    """Envia notificacion por Telegram."""
    if not TELEGRAM_BOT_TOKEN or not chat_id:
        return
    try:
        import httpx
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                json={"chat_id": chat_id, "text": text_msg[:4000], "parse_mode": "HTML"},
            )
            if not resp.json().get("ok"):
                await client.post(
                    f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                    json={"chat_id": chat_id, "text": text_msg[:4000]},
                )
    except Exception as e:
        print(f"PROSPECT SCOUT: Telegram error: {e}")


async def _get_active_configs() -> list:
    """Obtiene configuraciones de monitoreo activas que toca ejecutar."""
    try:
        with sync_engine.connect() as conn:
            rows = conn.execute(
                text("""
                    SELECT pwc.*, u.telegram_id, u.nombre as user_name
                    FROM prospect_watch_config pwc
                    JOIN usuarios u ON u.id = pwc.user_id
                    WHERE pwc.is_active = TRUE
                    AND (
                        pwc.last_scan_at IS NULL
                        OR pwc.last_scan_at < NOW() - (pwc.frequency_hours || ' hours')::INTERVAL
                    )
                """)
            ).fetchall()
        return [dict(r._mapping) for r in rows]
    except Exception as e:
        print(f"PROSPECT SCOUT: Error getting configs: {e}")
        return []


async def _run_scan(config: dict):
    """Ejecuta un scan de oportunidades para una configuracion."""
    from api.services.prospect_search_service import search_market_signals, search_and_enrich_companies
    from api.services.agent_status_service import update_agent_last_run

    empresa_id = str(config["empresa_id"])
    user_id = str(config["user_id"])
    sectors = config.get("sectors", [])
    if isinstance(sectors, str):
        sectors = json.loads(sectors)
    regions = config.get("regions", [])
    if isinstance(regions, str):
        regions = json.loads(regions)
    keywords = config.get("keywords", [])
    if isinstance(keywords, str):
        keywords = json.loads(keywords)

    print(f"PROSPECT SCOUT: Scanning for {empresa_id[:8]} — sectors={sectors}, regions={regions}")

    # 1. Buscar senales
    signals = await search_market_signals(
        empresa_id=empresa_id,
        sectors=sectors,
        regions=regions,
        keywords=keywords,
        max_results_per_query=2,
    )

    # 2. Si hay senales, buscar leads
    leads_found = []
    if signals:
        from models.selector import selector
        model, _ = selector.get_model("routing")

        signals_text = "\n".join(f"- {s['title']}" for s in signals[:5])
        try:
            resp = await model.ainvoke([
                {"role": "system", "content": 'Extrae nombres de empresas de estas noticias. JSON: {"companies": [{"name": ""}]} Sin markdown.'},
                {"role": "user", "content": signals_text},
            ])
            raw = (resp.content or "").strip().replace("```json", "").replace("```", "")
            companies = json.loads(raw).get("companies", [])
        except Exception:
            companies = []

        for company in companies[:2]:
            results = await search_and_enrich_companies(
                empresa_id=empresa_id,
                company_name=company.get("name", ""),
                location=regions[0] if regions else "",
                max_results=2,
            )
            leads_found.extend(results)

    # 3. Actualizar last_scan
    try:
        with sync_engine.connect() as conn:
            conn.execute(
                text("""
                    UPDATE prospect_watch_config
                    SET last_scan_at = NOW(),
                        total_leads_found = total_leads_found + :count
                    WHERE id = :id
                """),
                {"id": str(config["id"]), "count": len(leads_found)}
            )
            conn.commit()
    except Exception:
        pass

    # 4. Actualizar agent status
    result_text = f"{len(signals)} senales, {len(leads_found)} leads"
    update_agent_last_run(empresa_id, "prospect_scout", result_text)

    # 5. Notificar al CEO si encontro algo
    telegram_id = config.get("telegram_id", "")
    user_name = config.get("user_name", "")

    if (signals or leads_found) and telegram_id:
        notification = "<b>🎯 Oportunidades detectadas</b>\n\n"

        if signals:
            notification += f"📰 <b>{len(signals)} senales de mercado:</b>\n"
            for s in signals[:3]:
                notification += f"  🔹 {s['title'][:80]}\n"

        if leads_found:
            notification += f"\n🏢 <b>{len(leads_found)} empresas encontradas:</b>\n"
            for l in leads_found[:3]:
                size = l.get("company_size", "")
                size_str = f" ({size} emp.)" if size else ""
                notification += f"  🔹 {l.get('company_name', 'N/D')} — {l.get('industry', '')}{size_str}\n"

        notification += '\n💡 Escribe "perfila [nombre]" para mas detalles.'

        await _send_telegram(telegram_id, notification)
        print(f"PROSPECT SCOUT: Notified {user_name} — {len(signals)} signals, {len(leads_found)} leads")
    else:
        print(f"PROSPECT SCOUT: No opportunities found for {empresa_id[:8]}")


async def prospect_scout_worker_loop():
    """Loop principal del prospect scout."""
    if not ENABLE_PROSPECT_SCOUT:
        print("PROSPECT SCOUT: Deshabilitado (ENABLE_PROSPECT_SCOUT != true)")
        return

    print(f"PROSPECT SCOUT: Worker iniciado, check interval={CHECK_INTERVAL_SECONDS}s")

    await asyncio.sleep(120)

    while True:
        try:
            configs = await _get_active_configs()

            if configs:
                print(f"PROSPECT SCOUT: {len(configs)} configuraciones activas para escanear")

            for config in configs:
                try:
                    await _run_scan(config)
                except Exception as e:
                    print(f"PROSPECT SCOUT: Error scanning {str(config.get('empresa_id', ''))[:8]}: {e}")

                await asyncio.sleep(5)

        except asyncio.CancelledError:
            print("PROSPECT SCOUT: Worker cancelado")
            break
        except Exception as e:
            print(f"PROSPECT SCOUT: Error en loop: {e}")

        await asyncio.sleep(CHECK_INTERVAL_SECONDS)
