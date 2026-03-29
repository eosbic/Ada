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


# --- APOLLO.IO: Busqueda y enriquecimiento de empresas ---

async def search_and_enrich_companies(
    empresa_id: str,
    company_name: str = "",
    company_domain: str = "",
    location: str = "",
    industry_keywords: list = None,
    max_results: int = 5,
) -> list:
    """Busca y enriquece empresas con Apollo.io (free tier compatible)."""
    creds = get_service_credentials(empresa_id, "apollo")
    if "error" in creds:
        print("PROSPECT SEARCH: Apollo no configurado")
        return []

    api_key = creds.get("api_key", "")
    if not api_key:
        return []

    companies = []

    try:
        # Paso 1: Buscar organizaciones
        payload = {
            "page": 1,
            "per_page": max_results,
        }
        if company_name:
            payload["q_organization_name"] = company_name
        if location:
            payload["organization_locations"] = [location]
        if industry_keywords:
            payload["q_organization_keyword_tags"] = industry_keywords

        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(
                "https://api.apollo.io/api/v1/organizations/search",
                headers={"Content-Type": "application/json", "X-Api-Key": api_key},
                json=payload,
            )

        if resp.status_code == 200:
            orgs = resp.json().get("organizations", [])
            for org in orgs[:max_results]:
                companies.append({
                    "company_name": org.get("name", ""),
                    "company_domain": org.get("website_url", ""),
                    "industry": org.get("industry", ""),
                    "company_size": org.get("estimated_num_employees", ""),
                    "city": org.get("city", ""),
                    "country": org.get("country", ""),
                    "linkedin_url": org.get("linkedin_url", ""),
                    "phone": org.get("phone", ""),
                    "founded_year": org.get("founded_year", ""),
                    "keywords": org.get("keywords", []),
                })

        print(f"PROSPECT SEARCH: Apollo -> {len(companies)} companies found")

        # Paso 2: Enriquecer la primera empresa si tiene domain
        if companies and companies[0].get("company_domain"):
            domain = companies[0]["company_domain"].replace("https://", "").replace("http://", "").strip("/")
            try:
                async with httpx.AsyncClient(timeout=15) as client:
                    enrich_resp = await client.get(
                        "https://api.apollo.io/api/v1/organizations/enrich",
                        headers={"X-Api-Key": api_key},
                        params={"domain": domain},
                    )
                if enrich_resp.status_code == 200:
                    enrich_data = enrich_resp.json().get("organization", {})
                    if enrich_data:
                        companies[0]["description"] = enrich_data.get("short_description", "")
                        companies[0]["annual_revenue"] = enrich_data.get("annual_revenue_printed", "")
                        companies[0]["technologies"] = enrich_data.get("current_technologies", [])[:5]
                        companies[0]["seo_description"] = enrich_data.get("seo_description", "")
                        print(f"PROSPECT SEARCH: Apollo enriched {companies[0]['company_name']}")
            except Exception as e:
                print(f"PROSPECT SEARCH: Enrich error: {e}")

        return companies

    except Exception as e:
        print(f"PROSPECT SEARCH: Apollo error: {e}")
        return []


# Alias for backwards compatibility
search_leads_apollo = search_and_enrich_companies


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
