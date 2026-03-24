"""
DNA Generator — Genera agent_configs a partir del Company DNA.
Usa Gemini Flash (gratis) para generar configuraciones.
Incluye análisis web y de competidores.
"""

import json
from typing import Optional


async def generate_agent_configs(empresa_id: str) -> dict:
    """Genera configuraciones específicas por agente basadas en el DNA."""
    from api.services.dna_loader import load_company_dna, save_agent_configs
    from models.selector import selector

    dna = load_company_dna(empresa_id)
    if not dna or not dna.get("company_name"):
        return {}

    model, _ = selector.get_model("routing")

    dna_str = json.dumps(dna, ensure_ascii=False, indent=2, default=str)[:6000]

    prompt = f"""Basandote en el DNA de esta empresa, genera un JSON con configuraciones para cada agente de Ada.

DNA DE LA EMPRESA:
{dna_str}

GENERA un JSON con estas claves exactas:

1. "excel_analysis": {{"industry_context": "str", "priority_metrics": ["lista"], "analysis_prompt_addon": "str", "alert_thresholds": {{"metrica": valor}}}}
2. "prospecting": {{"search_keywords": ["lista"], "target_titles": ["cargos"], "target_sectors": ["lista"], "approach_tone": "str"}}
3. "marketing": {{"brand_voice": "str", "content_pillars": ["lista"], "preferred_platforms": ["lista"], "visual_style": "str"}}
4. "meeting_intelligence": {{"key_topics": ["lista"], "follow_up_priority": "high|medium|low"}}
5. "briefing": {{"priority_modules": ["lista"], "alert_thresholds": {{}}}}
6. "agent_priority_weights": {{"commercial_intelligence": 0.0-1.0, "marketing": 0.0-1.0, "meeting_intelligence": 0.0-1.0, "excel_analysis": 0.0-1.0}}

RESPONDE SOLO EL JSON. Sin markdown."""

    response = await model.ainvoke([
        {"role": "system", "content": "Genera configuraciones de agentes basadas en el perfil empresarial. Responde SOLO JSON valido."},
        {"role": "user", "content": prompt},
    ])

    try:
        raw = response.content.strip().replace("```json", "").replace("```", "")
        configs = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        print(f"DNA_GENERATOR: Error parseando configs para {empresa_id[:8]}")
        return {}

    save_agent_configs(empresa_id, configs)
    print(f"DNA_GENERATOR: agent_configs generados para {empresa_id[:8]}")
    return configs


async def scrape_and_analyze_web(empresa_id: str, url: str) -> dict:
    """Scrapea el sitio web de la empresa y genera website_summary."""
    from api.services.dna_loader import update_dna_field
    from models.selector import selector
    import httpx

    if not url or not empresa_id:
        return {"error": "empresa_id y url son requeridos"}

    update_dna_field(empresa_id, "website_url", url)

    # Scrape básico
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(url, headers={"User-Agent": "Ada/1.0 (Business Assistant)"})
        if resp.status_code != 200:
            return {"error": f"No se pudo acceder al sitio: HTTP {resp.status_code}"}

        html = resp.text[:10000]
        # Extraer texto básico sin dependencias externas
        import re
        title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
        title = title_match.group(1).strip() if title_match else ""
        desc_match = re.search(r'<meta[^>]*name=["\']description["\'][^>]*content=["\'](.*?)["\']', html, re.IGNORECASE)
        description = desc_match.group(1).strip() if desc_match else ""
        text_clean = re.sub(r"<[^>]+>", " ", html)
        text_clean = re.sub(r"\s+", " ", text_clean).strip()[:3000]

        # Extraer redes sociales
        socials = {}
        social_patterns = {
            "linkedin": r"linkedin\.com/(?:company|in)/[^\s\"']+",
            "instagram": r"instagram\.com/[^\s\"']+",
            "facebook": r"facebook\.com/[^\s\"']+",
            "twitter": r"(?:twitter|x)\.com/[^\s\"']+",
        }
        for platform, pattern in social_patterns.items():
            match = re.search(pattern, html, re.IGNORECASE)
            if match:
                socials[platform] = f"https://{match.group(0)}"

    except Exception as e:
        return {"error": f"Error scrapeando: {str(e)}"}

    # Generar resumen con LLM
    model, _ = selector.get_model("routing")
    response = await model.ainvoke([
        {"role": "system", "content": "Resume en 3-5 oraciones que hace esta empresa. Español. Sin markdown."},
        {"role": "user", "content": f"Titulo: {title}\nDescripcion: {description}\nContenido: {text_clean[:2000]}"},
    ])

    summary = response.content.strip()
    update_dna_field(empresa_id, "website_summary", summary)
    if socials:
        update_dna_field(empresa_id, "social_urls", socials)

    return {
        "summary": summary,
        "socials": socials,
        "title": title,
        "description": description,
    }


async def analyze_competitors(empresa_id: str, competitor_names: list) -> list:
    """Investiga competidores y guarda análisis."""
    from api.services.dna_loader import update_dna_field
    from models.selector import selector
    import httpx

    analyses = []
    model, _ = selector.get_model("routing")

    for competitor in competitor_names[:5]:
        try:
            # Buscar URL del competidor via search
            search_url = f"https://www.google.com/search?q={competitor}+empresa+sitio+web"
            comp_url = ""

            # Intentar acceder al sitio si parece URL
            if "." in competitor and " " not in competitor:
                comp_url = competitor if competitor.startswith("http") else f"https://{competitor}"

            if comp_url:
                try:
                    async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
                        resp = await client.get(comp_url, headers={"User-Agent": "Ada/1.0"})
                    if resp.status_code == 200:
                        import re
                        text_clean = re.sub(r"<[^>]+>", " ", resp.text[:5000])
                        text_clean = re.sub(r"\s+", " ", text_clean).strip()[:1500]

                        response = await model.ainvoke([
                            {"role": "system", "content": "Analiza brevemente este competidor: fortalezas, debilidades, diferenciadores. 3-4 oraciones. Español."},
                            {"role": "user", "content": f"Competidor: {competitor}\nContenido web: {text_clean}"},
                        ])
                        analyses.append({"name": competitor, "url": comp_url, "analysis": response.content.strip()})
                        continue
                except Exception:
                    pass

            # Si no se pudo scrapear, analisis basado en nombre
            response = await model.ainvoke([
                {"role": "system", "content": "Basandote en el nombre de esta empresa, infiere brevemente su probable sector, fortalezas y posición. 2-3 oraciones. Español. Marca claramente que es [INFERIDO]."},
                {"role": "user", "content": f"Empresa competidora: {competitor}"},
            ])
            analyses.append({"name": competitor, "url": comp_url, "analysis": response.content.strip()})

        except Exception as e:
            analyses.append({"name": competitor, "url": "", "analysis": f"No se pudo analizar: {str(e)}"})

    update_dna_field(empresa_id, "main_competitors", analyses)
    print(f"DNA_GENERATOR: {len(analyses)} competidores analizados para {empresa_id[:8]}")
    return analyses
