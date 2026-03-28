"""
Prospect Search Service — Busca senales de mercado (Tavily) y leads (Apollo.io).
Implementa waterfall enrichment: Apollo -> web scraping.
"""

import json
import httpx
from api.services.tenant_credentials import get_service_credentials


# --- TAVILY: Senales de mercado ---

async def search_market_signals(
    empresa_id: str,
    sectors: list = None,
    regions: list = None,
    keywords: list = None,
    max_results_per_query: int = 3,
) -> list:
    """Busca senales de mercado con Tavily (noticias, vacantes, inversiones)."""
    creds = get_service_credentials(empresa_id, "tavily")
    if "error" in creds:
        print("PROSPECT SEARCH: Tavily no configurado")
        return []

    api_key = creds.get("api_key", "")
    if not api_key:
        return []

    queries = []
    if sectors:
        for sector in sectors[:3]:
            region_str = regions[0] if regions else "Colombia"
            queries.append(f"{sector} {region_str} inversion tecnologia automatizacion 2026")
            queries.append(f"{sector} {region_str} nuevos clientes oportunidad negocio")

    if keywords:
        for kw in keywords[:2]:
            queries.append(f"{kw} empresas Colombia 2026")

    if not queries:
        queries = ["empresas tecnologia automatizacion Colombia 2026"]

    signals = []
    for query in queries[:5]:
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    "https://api.tavily.com/search",
                    json={
                        "api_key": api_key,
                        "query": query,
                        "search_depth": "basic",
                        "max_results": max_results_per_query,
                    },
                )

            if resp.status_code == 200:
                results = resp.json().get("results", [])
                for r in results:
                    signals.append({
                        "title": r.get("title", ""),
                        "url": r.get("url", ""),
                        "content": r.get("content", "")[:500],
                        "query": query,
                    })
        except Exception as e:
            print(f"PROSPECT SEARCH: Tavily error for '{query[:30]}': {e}")

    print(f"PROSPECT SEARCH: Tavily -> {len(signals)} senales")
    return signals


# --- APOLLO.IO: Busqueda de leads ---

async def search_leads_apollo(
    empresa_id: str,
    company_name: str = "",
    company_domain: str = "",
    titles: list = None,
    location: str = "",
    max_results: int = 5,
) -> list:
    """Busca leads en Apollo.io por empresa, cargo y ubicacion."""
    creds = get_service_credentials(empresa_id, "apollo")
    if "error" in creds:
        print("PROSPECT SEARCH: Apollo no configurado")
        return []

    api_key = creds.get("api_key", "")
    if not api_key:
        return []

    if not titles:
        titles = ["CEO", "Gerente General", "Director", "Gerente de Operaciones"]

    try:
        payload = {
            "api_key": api_key,
            "page": 1,
            "per_page": max_results,
        }

        if company_name:
            payload["q_organization_name"] = company_name
        if company_domain:
            payload["q_organization_domains"] = company_domain
        if titles:
            payload["person_titles"] = titles
        if location:
            payload["person_locations"] = [location]

        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(
                "https://api.apollo.io/v1/mixed_people/search",
                headers={"Content-Type": "application/json"},
                json=payload,
            )

        if resp.status_code == 200:
            people = resp.json().get("people", [])
            leads = []
            for p in people[:max_results]:
                leads.append({
                    "full_name": p.get("name", ""),
                    "job_title": p.get("title", ""),
                    "company_name": p.get("organization", {}).get("name", ""),
                    "company_domain": p.get("organization", {}).get("website_url", ""),
                    "email": p.get("email", ""),
                    "phone": p.get("phone_numbers", [{}])[0].get("raw_number", "") if p.get("phone_numbers") else "",
                    "linkedin_url": p.get("linkedin_url", ""),
                    "photo_url": p.get("photo_url", ""),
                    "city": p.get("city", ""),
                    "country": p.get("country", ""),
                    "company_size": p.get("organization", {}).get("estimated_num_employees", ""),
                    "company_industry": p.get("organization", {}).get("industry", ""),
                })

            print(f"PROSPECT SEARCH: Apollo -> {len(leads)} leads")
            return leads
        else:
            print(f"PROSPECT SEARCH: Apollo error {resp.status_code}")
            return []

    except Exception as e:
        print(f"PROSPECT SEARCH: Apollo error: {e}")
        return []


# --- ENRIQUECIMIENTO: Web scraping basico ---

async def enrich_company_web(company_domain: str) -> dict:
    """Enriquece datos de empresa con scraping de su sitio web."""
    if not company_domain:
        return {}

    if not company_domain.startswith("http"):
        company_domain = f"https://{company_domain}"

    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            resp = await client.get(company_domain)

        if resp.status_code == 200:
            from html.parser import HTMLParser

            class TitleParser(HTMLParser):
                def __init__(self):
                    super().__init__()
                    self.in_title = False
                    self.title = ""
                    self.meta_description = ""

                def handle_starttag(self, tag, attrs):
                    if tag == "title":
                        self.in_title = True
                    if tag == "meta":
                        attr_dict = dict(attrs)
                        if attr_dict.get("name", "").lower() == "description":
                            self.meta_description = attr_dict.get("content", "")

                def handle_data(self, data):
                    if self.in_title:
                        self.title += data

                def handle_endtag(self, tag):
                    if tag == "title":
                        self.in_title = False

            parser = TitleParser()
            parser.feed(resp.text[:10000])

            return {
                "website_title": parser.title.strip(),
                "website_description": parser.meta_description[:300],
                "website_url": company_domain,
            }
    except Exception as e:
        print(f"PROSPECT SEARCH: Web enrich error for {company_domain}: {e}")

    return {}
