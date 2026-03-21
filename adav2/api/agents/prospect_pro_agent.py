"""
Prospecting Pro Agent — Perfila empresas y prospectos con web scraping real.

Flujo:
1. Extrae datos del mensaje del usuario
2. Si faltan datos críticos, PREGUNTA antes de perfilar
3. Si hay URLs, las SCRAPEA para extraer datos reales
4. LLM genera perfil con datos REALES, no inventados
5. Guarda perfil en memoria + ada_reports
"""

import json
import re
from typing import TypedDict, Optional, List
from langgraph.graph import StateGraph, END
from models.selector import selector
from api.services.memory_service import search_memory, store_memory


class ProspectState(TypedDict, total=False):
    message: str
    empresa_id: str
    user_id: str
    intent: str

    prospect_data: dict
    needs_more_info: bool
    memory_context: str
    web_data: str

    response: str
    model_used: str


EXTRACT_PROMPT = """Eres Ada, asistente ejecutiva. El usuario quiere perfilar un prospecto/cliente.

Extrae toda la información disponible del mensaje:
{
    "nombre_contacto": "nombre de la persona",
    "cargo": "gerente, jefe de compras, CEO, etc.",
    "empresa": "nombre de la empresa",
    "sector": "industria o sector",
    "url_empresa": "sitio web si lo mencionó",
    "linkedin_empresa": "URL LinkedIn de la empresa si lo mencionó",
    "linkedin_persona": "URL LinkedIn de la persona si lo mencionó",
    "instagram": "URL Instagram si lo mencionó",
    "facebook": "URL Facebook si lo mencionó",
    "tiktok": "URL TikTok si lo mencionó",
    "telefono": "teléfono si lo mencionó",
    "email_prospecto": "email del prospecto si lo mencionó",
    "contexto": "contexto adicional (cómo lo conoció, qué necesita, etc.)",
    "missing": ["lista de datos que FALTAN y son importantes pedir"]
}

REGLAS:
- Si el usuario SOLO dice "perfila a empresa X" sin más datos, agrega a missing: nombre_contacto, url_empresa, linkedin_empresa, sector
- Si no hay URL del sitio web, SIEMPRE agregar "url_empresa" a missing
- Si no hay nombre de contacto, SIEMPRE agregar "nombre_contacto" a missing
- Responde SOLO JSON, sin markdown."""


PROFILE_PROMPT = """Genera un PERFIL COMERCIAL PROFESIONAL de este prospecto.

## DATOS PROPORCIONADOS POR EL USUARIO:
{prospect_data}

## DATOS EXTRAÍDOS DE SITIOS WEB (REALES):
{web_data}

## CONTEXTO PREVIO EN MEMORIA:
{memory_context}

## INSTRUCCIONES:

### 1. FICHA DEL PROSPECTO
Presenta toda la info en formato de ficha:
- 👤 Contacto: nombre y cargo
- 🏢 Empresa: nombre y sector
- 🌐 Web: URL
- 📧 Email: extraído del sitio web o proporcionado
- 📞 Teléfono: extraído del sitio web o proporcionado
- 📱 Redes: LinkedIn, Instagram, Facebook, TikTok

### 2. ANÁLISIS DE LA EMPRESA
Basado en los datos REALES del sitio web:
- Qué hace la empresa (productos/servicios reales)
- Tamaño estimado
- Propuesta de valor que comunican
- Clientes o casos de éxito visibles

### 3. ESTRATEGIA DE ACERCAMIENTO
3 pasos concretos:
- Primer contacto: canal, mensaje de apertura personalizado
- Propuesta de valor: qué ofrecer según lo que necesitan
- Siguiente paso: reunión, demo, cotización

### 4. PREGUNTAS DE DESCUBRIMIENTO
5 preguntas para la primera reunión:
- 2 sobre su negocio actual
- 2 sobre dolores/necesidades
- 1 sobre presupuesto/timeline

### 5. SEÑALES DE OPORTUNIDAD
- 💰 Alta: pidió cotización, referido, segunda reunión
- 📊 Media: mostró interés, respondió
- ❄️ Baja: primer contacto frío

### 6. DATOS QUE FALTAN
Listar información que el CEO debe conseguir.

REGLAS ANTI-ALUCINACIÓN:
1. USA los datos extraídos de los sitios web — son REALES
2. Si el scraping falló para una URL, dilo explícitamente
3. NO inventes nombres, emails, teléfonos ni cargos que no estén en los datos
4. Marca cada dato: [WEB] si viene del scraping, [PROPORCIONADO] si lo dio el usuario, [INFERIDO] si es suposición
5. NUNCA cambies las URLs que el usuario proporcionó
"""


# ─── NODO 1: Extraer datos + Scraping ────────────────────

async def extract_and_scrape(state: ProspectState) -> dict:
    """Extrae datos del mensaje y scrapea URLs encontradas."""
    model, model_name = selector.get_model("chat_with_tools")

    # Extraer datos del mensaje con LLM
    response = await model.ainvoke([
        {"role": "system", "content": EXTRACT_PROMPT},
        {"role": "user", "content": state["message"]},
    ])

    try:
        raw = response.content.strip().replace("```json", "").replace("```", "")
        prospect_data = json.loads(raw)
    except Exception:
        prospect_data = {
            "empresa": state["message"],
            "missing": ["nombre_contacto", "cargo", "url_empresa", "linkedin_empresa"],
        }

    # Recopilar URLs para scraping
    urls_to_scrape = []
    for key in ["url_empresa", "linkedin_empresa", "linkedin_persona", "instagram", "facebook"]:
        url = prospect_data.get(key, "")
        if url and url.startswith("http"):
            urls_to_scrape.append(url)

    # También extraer URLs directamente del mensaje
    url_pattern = r'https?://[^\s<>"\')\]]+' 
    message_urls = re.findall(url_pattern, state.get("message", ""))
    for u in message_urls:
        if u not in urls_to_scrape:
            urls_to_scrape.append(u)

    # Scraping real de todas las URLs
    web_data = ""
    if urls_to_scrape:
        try:
            from api.services.web_scaper import scrape_website, format_scrape_for_llm

            scrape_parts = []
            for url in urls_to_scrape[:4]:
                print(f"PROSPECT PRO: Scraping {url}...")
                result = await scrape_website(url)
                formatted = format_scrape_for_llm(result)
                scrape_parts.append(formatted)

                # Extraer datos del scraping al prospect_data
                if result.get("scraped"):
                    if result.get("emails") and not prospect_data.get("email_prospecto"):
                        prospect_data["email_prospecto"] = result["emails"][0]
                        prospect_data["emails_encontrados"] = result["emails"]
                    if result.get("phones") and not prospect_data.get("telefono"):
                        prospect_data["telefono"] = result["phones"][0]
                        prospect_data["telefonos_encontrados"] = result["phones"]
                    if result.get("socials"):
                        for social_key, social_url in result["socials"].items():
                            if not prospect_data.get(social_key):
                                prospect_data[social_key] = social_url
                    if result.get("title") and not prospect_data.get("empresa_titulo_web"):
                        prospect_data["empresa_titulo_web"] = result["title"]
                    if result.get("description"):
                        prospect_data["empresa_descripcion_web"] = result["description"]

            web_data = "\n\n".join(scrape_parts)
            print(f"PROSPECT PRO: Scraping completado — {len(scrape_parts)} URLs procesadas")

        except Exception as e:
            print(f"PROSPECT PRO: Error en scraping: {e}")
            web_data = f"⚠️ Error accediendo a los sitios web: {e}"
    else:
        web_data = "No se proporcionaron URLs para investigar."

    # Buscar en memoria
    search_terms = prospect_data.get("empresa", "") or prospect_data.get("nombre_contacto", "")
    memories = search_memory(search_terms) if search_terms else []
    memory_context = "\n".join(memories[:3]) if memories else "Sin historial previo."

    # Determinar si necesita más info
    missing = prospect_data.get("missing", [])
    has_empresa = bool(prospect_data.get("empresa"))
    has_url = bool(urls_to_scrape)
    has_contacto = bool(prospect_data.get("nombre_contacto"))

    # Solo preguntar si no tiene NI empresa NI URLs
    #needs_more = not has_empresa and not has_url
    
    # Preguntar si no tiene NI URLs NI contacto — solo nombre de empresa no es suficiente
    needs_more = not has_url and not has_contacto

    print(f"PROSPECT PRO: empresa={prospect_data.get('empresa')}, urls={len(urls_to_scrape)}, contacto={has_contacto}, needs_more={needs_more}")

    return {
        "prospect_data": prospect_data,
        "memory_context": memory_context,
        "web_data": web_data,
        "needs_more_info": needs_more,
        "model_used": model_name,
    }


# ─── NODO 2: Preguntar o Generar perfil ──────────────────

async def generate_profile_or_ask(state: ProspectState) -> dict:
    """Genera perfil completo o pide datos críticos."""
    prospect_data = state.get("prospect_data", {})
    memory_context = state.get("memory_context", "")
    web_data = state.get("web_data", "")
    needs_more = state.get("needs_more_info", False)

    # Si no tiene suficiente info, preguntar
    if needs_more:
        return {
            "response": (
                "Para hacer un perfilamiento completo, necesito la siguiente información:\n\n"
                "1. 🏢 **Nombre de la empresa**\n"
                "2. 🌐 **Sitio web de la empresa** (URL)\n"
                "3. 👤 **Nombre del gerente o contacto principal**\n"
                "4. 💼 **LinkedIn de la empresa** (URL)\n"
                "5. 💼 **LinkedIn del gerente** (URL)\n"
                "6. 📸 **Redes sociales** (Instagram, Facebook, TikTok)\n"
                "7. 📰 **Noticias recientes** de la empresa o del gerente\n\n"
                "Dame toda la información que tengas y yo me encargo de investigar "
                "los sitios web para extraer datos reales. Mientras más URLs me des, "
                "más completo será el perfil.\n\n"
                "**Ejemplo:**\n"
                "\"Perfila a USEIT, web: https://useit.co/, LinkedIn: https://linkedin.com/company/useit, "
                "el CEO es Pablo Pantoja, su LinkedIn: https://linkedin.com/in/pablo-pantoja\""
            ),
        }

    # Generar perfil con datos reales
    model, model_name = selector.get_model("chat_with_tools")

    prompt = PROFILE_PROMPT.format(
        prospect_data=json.dumps(prospect_data, ensure_ascii=False, indent=2),
        web_data=web_data,
        memory_context=memory_context,
    )

    response = await model.ainvoke([
        {"role": "system", "content": (
            "Eres Ada, la mejor asesora comercial B2B de Latinoamérica. "
            "Tu trabajo es darle al CEO toda la inteligencia necesaria para "
            "cerrar un negocio. Sé estratégica, concreta y accionable. "
            "TIENES datos reales extraídos de los sitios web — ÚSALOS. "
            "Marca cada dato con su fuente: [WEB], [PROPORCIONADO] o [INFERIDO]."
        )},
        {"role": "user", "content": prompt},
    ])

    # Guardar en memoria
    empresa_name = prospect_data.get("empresa", "prospecto")
    store_memory(f"Perfil prospecto {empresa_name}: {response.content[:1000]}")
    store_memory(f"Datos prospecto {empresa_name}: {json.dumps(prospect_data, ensure_ascii=False)}")

    # Guardar en ada_reports
    try:
        from api.database import sync_engine
        from sqlalchemy import text as sql_text

        empresa_id = state.get("empresa_id", "")
        if empresa_id:
            with sync_engine.connect() as conn:
                conn.execute(
                    sql_text("""
                        INSERT INTO ada_reports
                            (empresa_id, title, report_type, markdown_content,
                             metrics_summary, alerts, generated_by, allowed_roles)
                        VALUES (:eid, :title, 'prospect_profile', :content,
                                :metrics, '[]', :model, :roles)
                    """),
                    {
                        "eid": empresa_id,
                        "title": f"Perfil: {empresa_name}",
                        "content": response.content,
                        "metrics": json.dumps(prospect_data, ensure_ascii=False),
                        "model": model_name,
                        "roles": ["administrador", "gerente", "vendedor"],
                    },
                )
                conn.commit()
            print(f"PROSPECT PRO: Perfil guardado en ada_reports")
    except Exception as e:
        print(f"PROSPECT PRO: Error guardando en DB: {e}")

    print(f"PROSPECT PRO: Perfil generado con {model_name}")

    return {
        "response": response.content,
        "model_used": model_name,
    }


# ─── Compilar grafo ──────────────────────────────────────

graph = StateGraph(ProspectState)
graph.add_node("extract_and_scrape", extract_and_scrape)
graph.add_node("profile", generate_profile_or_ask)
graph.set_entry_point("extract_and_scrape")
graph.add_edge("extract_and_scrape", "profile")
graph.add_edge("profile", END)
prospect_pro_agent = graph.compile()