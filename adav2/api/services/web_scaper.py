"""
Web Scraper — Extrae datos de sitios web para perfilamiento.
Usa httpx + BeautifulSoup para leer URLs reales.
"""

import re
import httpx
from typing import Optional


async def scrape_website(url: str, timeout: int = 15) -> dict:
    """Extrae datos básicos de un sitio web."""
    if not url or not url.startswith("http"):
        return {"error": "URL inválida", "url": url}

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return {"error": "beautifulsoup4 no instalado", "url": url}

    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "es-CO,es;q=0.9,en;q=0.8",
        }

        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, verify=False) as client:
            resp = await client.get(url, headers=headers)

        if resp.status_code >= 400:
            return {"error": f"HTTP {resp.status_code}", "url": url}

        soup = BeautifulSoup(resp.text, "html.parser")

        # Título
        title = ""
        if soup.title and soup.title.string:
            title = soup.title.string.strip()

        # Meta description
        description = ""
        meta_desc = soup.find("meta", attrs={"name": "description"})
        if meta_desc:
            description = meta_desc.get("content", "").strip()

        # Meta keywords
        keywords = ""
        meta_kw = soup.find("meta", attrs={"name": "keywords"})
        if meta_kw:
            keywords = meta_kw.get("content", "").strip()

        # Emails
        email_pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
        raw_emails = re.findall(email_pattern, resp.text)
        # Filtrar emails falsos (imágenes, scripts)
        emails = list(set([
            e for e in raw_emails
            if not any(x in e.lower() for x in ["example", "test", "png", "jpg", "svg", "woff", "sentry"])
        ]))[:5]

        # Teléfonos
        phone_pattern = r'[\+]?[\d][\d\s\-\(\)]{6,15}\d'
        raw_phones = re.findall(phone_pattern, resp.text)
        phones = list(set([p.strip() for p in raw_phones if len(p.strip()) >= 7]))[:5]

        # Redes sociales
        socials = {}
        for link in soup.find_all("a", href=True):
            href = link["href"].lower()
            if "linkedin.com" in href and "linkedin" not in socials:
                socials["linkedin"] = link["href"]
            if "instagram.com" in href and "instagram" not in socials:
                socials["instagram"] = link["href"]
            if "facebook.com" in href and "facebook" not in socials:
                socials["facebook"] = link["href"]
            if "twitter.com" in href or "x.com" in href:
                if "twitter" not in socials:
                    socials["twitter"] = link["href"]
            if "tiktok.com" in href and "tiktok" not in socials:
                socials["tiktok"] = link["href"]
            if "youtube.com" in href and "youtube" not in socials:
                socials["youtube"] = link["href"]

        # Texto principal (sin scripts ni estilos)
        for tag in soup(["script", "style", "noscript", "header", "footer", "nav"]):
            tag.decompose()
        body_text = soup.get_text(separator=" ", strip=True)
        # Limpiar espacios múltiples
        body_text = re.sub(r'\s+', ' ', body_text)[:3000]

        # Buscar dirección
        address = ""
        addr_tag = soup.find(attrs={"class": re.compile(r"address|direccion|location|ubicacion", re.I)})
        if addr_tag:
            address = addr_tag.get_text(strip=True)[:200]

        result = {
            "url": url,
            "title": title,
            "description": description,
            "keywords": keywords,
            "emails": emails,
            "phones": phones,
            "socials": socials,
            "address": address,
            "text_preview": body_text[:2000],
            "scraped": True,
        }

        print(f"WEB SCRAPER: {url} → title='{title[:50]}', emails={len(emails)}, phones={len(phones)}, socials={list(socials.keys())}")
        return result

    except httpx.TimeoutException:
        print(f"WEB SCRAPER: Timeout en {url}")
        return {"error": "Timeout — el sitio no respondió", "url": url}
    except Exception as e:
        print(f"WEB SCRAPER: Error en {url}: {e}")
        return {"error": str(e), "url": url}


async def scrape_multiple(urls: list) -> dict:
    """Scrape múltiples URLs y retorna resultados combinados."""
    results = {}
    for url in urls[:5]:
        if url and url.startswith("http"):
            results[url] = await scrape_website(url)
    return results


def format_scrape_for_llm(scrape_result: dict) -> str:
    """Formatea el resultado del scraping para incluir en el prompt del LLM."""
    if not scrape_result or scrape_result.get("error"):
        return f"⚠️ No se pudo acceder a {scrape_result.get('url', 'URL')}: {scrape_result.get('error', 'error desconocido')}"

    parts = []
    parts.append(f"## DATOS EXTRAÍDOS DE {scrape_result.get('url', '')}")

    if scrape_result.get("title"):
        parts.append(f"**Título:** {scrape_result['title']}")

    if scrape_result.get("description"):
        parts.append(f"**Descripción:** {scrape_result['description']}")

    if scrape_result.get("emails"):
        parts.append(f"**Emails encontrados:** {', '.join(scrape_result['emails'])}")

    if scrape_result.get("phones"):
        parts.append(f"**Teléfonos encontrados:** {', '.join(scrape_result['phones'])}")

    if scrape_result.get("socials"):
        social_lines = [f"  - {k}: {v}" for k, v in scrape_result["socials"].items()]
        parts.append(f"**Redes sociales:**\n" + "\n".join(social_lines))

    if scrape_result.get("address"):
        parts.append(f"**Dirección:** {scrape_result['address']}")

    if scrape_result.get("text_preview"):
        parts.append(f"**Contenido del sitio (extracto):**\n{scrape_result['text_preview'][:1500]}")

    return "\n".join(parts)