"""
Onboarding Agent — Configuración inicial solo para admin.

Flujo conversacional por pasos:
1. Welcome → 2. Admin Identity → 3. Nombre Ada → 4. Empresa →
5. Legal → 6. Propuesta de valor → 7. Productos → 8. Tamaño →
9. Ubicación → 10. Website → 11. ICP → 12. Competidores →
13. Marca → 14. Apps → 15. Intereses → 16. Estilo → 17. Confirmación →
18. Connect Telegram → 19. Connect OAuth → 20. Connect PM

Cada llamada al endpoint avanza un paso.
El estado se mantiene en memoria (dict por empresa_id).
"""

import json
import os
import re
import urllib.parse
from typing import Optional
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from models.selector import selector


_onboarding_sessions = {}

STEPS = [
    "welcome",
    "admin_identity",
    "ada_name",
    "company_info",
    "company_legal",
    "value_prop",
    "products",
    "size",
    "location",
    "website",
    "target_icp",
    "competitors",
    "brand",
    "apps",
    "interests",
    "style",
    "confirmation",
    "connect_telegram",
    "connect_oauth",
    "connect_pm",
]


async def process_onboarding(
    db: AsyncSession,
    empresa_id: str,
    user_id: str,
    user_name: str,
    user_response: str = "",
    source: str = "",
) -> dict:
    """Procesa un paso del onboarding. Retorna pregunta actual."""

    session = _onboarding_sessions.get(empresa_id, {
        "step": "welcome",
        "company_data": {"admin_data": {}},
        "source": source,
    })

    step = session["step"]
    company_data = session["company_data"]

    # ─── WELCOME ─────────────────────────────────────
    if step == "welcome":
        session["step"] = "admin_identity"
        session["source"] = source
        _onboarding_sessions[empresa_id] = session
        return {
            "step": "admin_identity",
            "message": (
                "👋 ¡Hola! Soy Ada, tu asistente ejecutiva de inteligencia artificial.\n\n"
                "Mi trabajo es ayudarte a gestionar tu negocio: analizo datos, "
                "manejo agenda, redacto correos, y te alerto cuando algo necesita "
                "tu atención.\n\n"
                "Como eres el administrador, necesito que me configures. "
                "Son unas pocas preguntas y toma menos de 5 minutos.\n\n"
                "Primero necesito saber quién eres.\n\n"
                "Dime tu **nombre completo** y tu **teléfono** (con indicativo de país).\n\n"
                "Ejemplo: \"William Salas, +57 3001234567\""
            ),
            "completed": False,
        }

    # ─── ADMIN IDENTITY ─────────────────────────────
    if step == "admin_identity":
        admin_data = company_data.get("admin_data", {})
        try:
            model, _ = selector.get_model("routing")
            parse_response = model.invoke([
                {"role": "system", "content": (
                    "Extrae nombre, apellido y teléfono del mensaje. "
                    "Responde SOLO JSON: {\"first_name\": \"\", \"last_name\": \"\", \"phone\": \"\", \"country_code\": \"\"}\n"
                    "Si no tiene indicativo, asume +57 (Colombia). "
                    "Si no dice teléfono, dejar vacío. Sin markdown."
                )},
                {"role": "user", "content": user_response},
            ])
            raw = parse_response.content.strip().replace("```json", "").replace("```", "")
            parsed = json.loads(raw)
            admin_data["first_name"] = parsed.get("first_name", "").strip()
            admin_data["last_name"] = parsed.get("last_name", "").strip()
            admin_data["phone"] = parsed.get("phone", "").strip()
            admin_data["country_code"] = parsed.get("country_code", "+57").strip()
        except Exception as e:
            print(f"ONBOARDING: Error parsing admin identity: {e}")
            full_name = user_response.split(",")[0].strip()
            parts = full_name.split()
            admin_data["first_name"] = parts[0] if parts else full_name
            admin_data["last_name"] = " ".join(parts[1:]) if len(parts) > 1 else ""
            admin_data["phone"] = ""
            admin_data["country_code"] = "+57"

        company_data["admin_data"] = admin_data
        session["step"] = "ada_name"
        session["company_data"] = company_data
        _onboarding_sessions[empresa_id] = session

        greeting = admin_data.get("first_name", "") or user_response.split(",")[0].strip()
        return {
            "step": "ada_name",
            "message": (
                f"¡Hola {greeting}! Un gusto conocerte.\n\n"
                f"Mi nombre es Ada, pero tú decides cómo me llama todo tu equipo. "
                f"¿Cómo quieres que me llame?"
            ),
            "completed": False,
        }

    # ─── ADA NAME ────────────────────────────────────
    if step == "ada_name":
        ada_name = user_response.strip() if user_response.strip() else "Ada"
        if len(ada_name) > 50:
            ada_name = "Ada"
        company_data["ada_name"] = ada_name
        session["step"] = "company_info"
        session["company_data"] = company_data
        _onboarding_sessions[empresa_id] = session
        return {
            "step": "company_info",
            "message": (
                f"Perfecto, soy {ada_name} desde ahora para todo el equipo.\n\n"
                "Cuéntame sobre tu empresa: ¿cuál es el nombre y a qué se dedican?\n\n"
                "Ejemplo: \"Distribuidora El Paisa, vendemos productos de "
                "consumo masivo en el Valle del Cauca\""
            ),
            "completed": False,
        }

    # ─── COMPANY INFO ────────────────────────────────
    if step == "company_info":
        model, _ = selector.get_model("routing")
        try:
            extraction = model.invoke([
                {"role": "system", "content": (
                    "Extrae nombre de empresa, clasifica industria, y detecta mision/vision/modelo si se mencionan.\n"
                    "Industrias: retail, servicios, manufactura, tecnologia, salud, "
                    "educacion, construccion, alimentos, transporte, consultoria, "
                    "restaurante, agricultura, inmobiliario, financiero, generic\n"
                    "JSON: {\"company_name\": \"...\", \"industry_type\": \"...\", "
                    "\"description\": \"...\", \"mission\": \"...\", \"vision\": \"...\", "
                    "\"business_model\": \"B2B|B2C|mayorista|retail|servicios|SaaS|mixto\"}\n"
                    "Si no se mencionan mission/vision/business_model, dejar string vacio.\n"
                    "Sin markdown, sin explicacion."
                )},
                {"role": "user", "content": user_response}
            ])
            parsed = json.loads(
                extraction.content.strip().replace("```json", "").replace("```", "")
            )
            company_data["company_name"] = parsed.get("company_name", user_response)
            company_data["industry_type"] = parsed.get("industry_type", "generic")
            company_data["business_description"] = parsed.get("description", user_response)
            company_data["mission"] = parsed.get("mission", "")
            company_data["vision"] = parsed.get("vision", "")
            company_data["business_model"] = parsed.get("business_model", "")
        except Exception:
            company_data["company_name"] = user_response
            company_data["industry_type"] = "generic"
            company_data["business_description"] = user_response

        session["step"] = "company_legal"
        session["company_data"] = company_data
        _onboarding_sessions[empresa_id] = session
        return {
            "step": "company_legal",
            "message": (
                f"Entendido, {company_data['company_name']}.\n\n"
                f"¿Cuál es el NIT o RUT de {company_data['company_name']}?\n\n"
                f"Ejemplo: \"900.123.456-7\"\n\n"
                f"Si no lo tienes a la mano, escribe **saltar**."
            ),
            "completed": False,
        }

    # ─── COMPANY LEGAL ───────────────────────────────
    if step == "company_legal":
        response_lower = user_response.lower().strip()
        if response_lower in ("saltar", "skip", "no tengo", "no se", "no sé"):
            company_data["tax_id"] = ""
        else:
            company_data["tax_id"] = user_response.strip()

        session["step"] = "value_prop"
        session["company_data"] = company_data
        _onboarding_sessions[empresa_id] = session
        return {
            "step": "value_prop",
            "message": (
                f"¿Cuál es la propuesta de valor de {company_data.get('company_name', 'tu empresa')}? "
                f"¿Por qué te eligen tus clientes en vez de a la competencia?"
            ),
            "completed": False,
        }

    # ─── VALUE PROPOSITION ─────────────────────────────
    if step == "value_prop":
        company_data["value_proposition"] = user_response.strip()
        session["step"] = "products"
        session["company_data"] = company_data
        _onboarding_sessions[empresa_id] = session
        return {
            "step": "products",
            "message": (
                f"¿Cuáles son los principales productos o servicios "
                f"de {company_data.get('company_name', 'tu empresa')}?\n\n"
                "Dime los más importantes separados por comas."
            ),
            "completed": False,
        }

    # ─── PRODUCTS ────────────────────────────────────
    if step == "products":
        products = [p.strip() for p in user_response.split(",") if p.strip()]
        if company_data.get("industry_type") in ["retail", "manufactura", "alimentos", "restaurante"]:
            company_data["main_products"] = products
        else:
            company_data["main_services"] = products

        session["step"] = "size"
        session["company_data"] = company_data
        _onboarding_sessions[empresa_id] = session
        return {
            "step": "size",
            "message": "¿Cuántos empleados tienen aproximadamente?",
            "completed": False,
        }

    # ─── SIZE ────────────────────────────────────────
    if step == "size":
        model, _ = selector.get_model("routing")
        try:
            extraction = model.invoke([
                {"role": "system", "content": (
                    "Del siguiente texto extrae el número de empleados.\n"
                    "JSON: {\"employees\": número_entero, \"size\": \"micro|small|medium|large\"}\n"
                    "micro: <10, small: 10-50, medium: 51-200, large: >200\n"
                    "Si dice '4 personas', employees = 4.\n"
                    "SOLO JSON, sin markdown."
                )},
                {"role": "user", "content": user_response}
            ])
            raw = extraction.content.strip().replace("```json", "").replace("```", "")
            parsed = json.loads(raw)
            employees = parsed.get("employees")
            if employees is not None:
                employees = int(employees)
            company_data["num_employees"] = employees
            company_data["company_size"] = parsed.get("size", "small")
        except Exception:
            numbers = re.findall(r'\d+', user_response)
            if numbers:
                employees = int(numbers[0])
                company_data["num_employees"] = employees
                if employees < 10:
                    company_data["company_size"] = "micro"
                elif employees <= 50:
                    company_data["company_size"] = "small"
                elif employees <= 200:
                    company_data["company_size"] = "medium"
                else:
                    company_data["company_size"] = "large"
            else:
                company_data["num_employees"] = None
                company_data["company_size"] = "small"

        session["step"] = "location"
        session["company_data"] = company_data
        _onboarding_sessions[empresa_id] = session
        return {
            "step": "location",
            "message": (
                "¿Dónde está ubicada tu empresa?\n\n"
                "Dime:\n"
                "• **País y ciudad**\n"
                "• **Dirección** (opcional)\n"
                "• **Teléfono de la empresa** con indicativo (opcional)\n\n"
                "Ejemplo: \"Colombia, Cali, Av 5N #23-45, +57 2 3851234\"\n"
                "o simplemente: \"Cali, Colombia\""
            ),
            "completed": False,
        }

    # ─── LOCATION ────────────────────────────────────
    if step == "location":
        model, _ = selector.get_model("routing")
        try:
            extraction = model.invoke([
                {"role": "system", "content": (
                    "Extrae ubicación de empresa. "
                    "JSON: {\"country\": \"\", \"city\": \"\", \"address\": \"\", \"phone\": \"\", \"timezone\": \"\", \"currency\": \"\"}\n"
                    "Infiere timezone y currency del país:\n"
                    "- Colombia → America/Bogota, COP\n"
                    "- México → America/Mexico_City, MXN\n"
                    "- España → Europe/Madrid, EUR\n"
                    "- USA → America/New_York, USD\n"
                    "- Argentina → America/Argentina/Buenos_Aires, ARS\n"
                    "- Chile → America/Santiago, CLP\n"
                    "- Perú → America/Lima, PEN\n"
                    "- Ecuador → America/Guayaquil, USD\n"
                    "Si no menciona dirección o teléfono, dejar vacío. Sin markdown."
                )},
                {"role": "user", "content": user_response}
            ])
            raw = extraction.content.strip().replace("```json", "").replace("```", "")
            parsed = json.loads(raw)
            company_data["country"] = parsed.get("country", "Colombia")
            company_data["city"] = parsed.get("city", "")
            company_data["address"] = parsed.get("address", "")
            company_data["company_phone"] = parsed.get("phone", "")
            company_data["timezone"] = parsed.get("timezone", "America/Bogota")
            company_data["currency"] = parsed.get("currency", "COP")
        except Exception:
            company_data["city"] = user_response.strip()
            company_data["country"] = "Colombia"
            company_data["timezone"] = "America/Bogota"
            company_data["currency"] = "COP"

        session["step"] = "website"
        session["company_data"] = company_data
        _onboarding_sessions[empresa_id] = session
        return {
            "step": "website",
            "message": (
                "¿Tienes sitio web? Pega la URL y yo extraigo la información automáticamente.\n\n"
                "Si no tienes, escribe 'no tengo' y seguimos."
            ),
            "completed": False,
        }

    # ─── WEBSITE ────────────────────────────────────
    if step == "website":
        resp_lower = user_response.strip().lower()
        if any(k in resp_lower for k in ["http", "www", ".com", ".co", ".org", ".net"]):
            url = user_response.strip()
            if not url.startswith("http"):
                url = "https://" + url
            company_data["website_url"] = url
        else:
            company_data["website_url"] = ""

        session["step"] = "target_icp"
        session["company_data"] = company_data
        _onboarding_sessions[empresa_id] = session
        return {
            "step": "target_icp",
            "message": (
                "¿Quién es tu cliente ideal?\n\n"
                "Descríbeme:\n"
                "• ¿A qué sector pertenece?\n"
                "• ¿Qué cargo tiene quien toma la decisión de compra?\n"
                "• ¿Qué tamaño de empresa?\n"
                "• ¿Cuántos días toma normalmente cerrar una venta?"
            ),
            "completed": False,
        }

    # ─── TARGET ICP ─────────────────────────────────
    if step == "target_icp":
        model, _ = selector.get_model("routing")
        try:
            extraction = model.invoke([
                {"role": "system", "content": (
                    "Extrae el perfil del cliente ideal del texto.\n"
                    "JSON: {\"sector\": \"...\", \"decision_maker_title\": \"...\", "
                    "\"company_size\": \"...\", \"sales_cycle_days\": numero_entero}\n"
                    "Si no menciona dias de venta, usar 30 como default.\n"
                    "Sin markdown, sin explicacion."
                )},
                {"role": "user", "content": user_response}
            ])
            parsed = json.loads(
                extraction.content.strip().replace("```json", "").replace("```", "")
            )
            company_data["target_icp"] = {
                "sector": parsed.get("sector", ""),
                "decision_maker_title": parsed.get("decision_maker_title", ""),
                "company_size": parsed.get("company_size", ""),
            }
            company_data["sales_cycle_days"] = parsed.get("sales_cycle_days", 30)
        except Exception:
            company_data["target_icp"] = {"raw": user_response}
            company_data["sales_cycle_days"] = 30

        session["step"] = "competitors"
        session["company_data"] = company_data
        _onboarding_sessions[empresa_id] = session
        return {
            "step": "competitors",
            "message": (
                "¿Quiénes son tus 3 principales competidores? "
                "Dime sus nombres separados por coma.\n\n"
                "Si no tienes competidores directos o no los conoces, "
                "escribe 'no sé' y seguimos."
            ),
            "completed": False,
        }

    # ─── COMPETITORS ────────────────────────────────
    if step == "competitors":
        resp_lower = user_response.strip().lower()
        if any(k in resp_lower for k in ["no se", "no sé", "ninguno", "no conozco"]):
            company_data["competitors_raw"] = []
        else:
            company_data["competitors_raw"] = [c.strip() for c in user_response.split(",") if c.strip()]

        session["step"] = "brand"
        session["company_data"] = company_data
        _onboarding_sessions[empresa_id] = session
        return {
            "step": "brand",
            "message": (
                "Hablemos de tu marca.\n\n"
                "🎨 ¿Cómo describirías el tono de tu marca? "
                "(formal, cercano, técnico, disruptivo, elegante...)\n\n"
                "📱 ¿Tienes redes sociales? Pega los links de Instagram, "
                "Facebook, LinkedIn o TikTok.\n\n"
                "🖼️ Si tienes el link de tu logo (URL de imagen), "
                "también lo puedo usar para tus reportes."
            ),
            "completed": False,
        }

    # ─── BRAND ──────────────────────────────────────
    if step == "brand":
        model, _ = selector.get_model("routing")
        try:
            extraction = model.invoke([
                {"role": "system", "content": (
                    "Extrae tono de marca, redes sociales y logo del texto.\n"
                    "JSON: {\"brand_voice\": \"...\", \"social_urls\": "
                    "{\"instagram\": \"\", \"facebook\": \"\", \"linkedin\": \"\", \"tiktok\": \"\"}, "
                    "\"logo_url\": \"\"}\n"
                    "Si no menciona alguna red, dejar string vacio.\n"
                    "Sin markdown, sin explicacion."
                )},
                {"role": "user", "content": user_response}
            ])
            parsed = json.loads(
                extraction.content.strip().replace("```json", "").replace("```", "")
            )
            company_data["brand_voice"] = parsed.get("brand_voice", "")
            company_data["social_urls"] = parsed.get("social_urls", {})
            company_data["logo_url"] = parsed.get("logo_url", "")
        except Exception:
            company_data["brand_voice"] = user_response.strip()
            company_data["social_urls"] = {}
            company_data["logo_url"] = ""

        session["step"] = "apps"
        session["company_data"] = company_data
        _onboarding_sessions[empresa_id] = session
        return {
            "step": "apps",
            "message": (
                "¿Qué herramientas de trabajo usa tu empresa?\n\n"
                "📧 Email y Calendario:\n"
                "  1️⃣ Google Workspace (Gmail, Google Calendar)\n"
                "  2️⃣ Microsoft 365 (Outlook, calendario Outlook)\n\n"
                "📋 Gestión de proyectos:\n"
                "  1️⃣ Notion\n"
                "  2️⃣ Plane\n"
                "  3️⃣ Asana\n"
                "  4️⃣ Otro o ninguno\n\n"
                "Puedes responder algo como 'Google y Notion' o '2 y 3'."
            ),
            "completed": False,
        }

    # ─── APPS ───────────────────────────────────────
    if step == "apps":
        model, _ = selector.get_model("routing")
        try:
            extraction = model.invoke([
                {"role": "system", "content": (
                    "Extrae que suite de productividad y PM tool usa la empresa.\n"
                    "JSON: {\"suite\": \"google|microsoft\", \"pm\": \"notion|plane|asana|none\"}\n"
                    "Reglas: '1' o 'gmail' o 'google' = google. '2' o 'outlook' o 'microsoft' = microsoft.\n"
                    "PM: '1' o 'notion' = notion. '2' o 'plane' = plane. '3' o 'asana' = asana. '4' o 'ninguno' o 'otro' = none.\n"
                    "Default suite: google. Default pm: none.\n"
                    "Sin markdown, sin explicacion."
                )},
                {"role": "user", "content": user_response}
            ])
            parsed = json.loads(
                extraction.content.strip().replace("```json", "").replace("```", "")
            )
            company_data["productivity_suite"] = parsed.get("suite", "google")
            company_data["pm_tool"] = parsed.get("pm", "none")
        except Exception:
            company_data["productivity_suite"] = "google"
            company_data["pm_tool"] = "none"

        session["step"] = "interests"
        session["company_data"] = company_data
        _onboarding_sessions[empresa_id] = session
        return {
            "step": "interests",
            "message": (
                "¿Qué información te importa más a TI como administrador?\n\n"
                "📊 Ventas y facturación\n"
                "💰 Cartera y cuentas por cobrar\n"
                "📦 Inventario y stock\n"
                "👥 Clientes y relaciones comerciales\n"
                "📋 Proyectos y tareas\n"
                "💵 Márgenes y rentabilidad\n"
                "📈 Crecimiento y nuevos negocios\n"
                "👤 Gestión de personal\n\n"
                "Dime cuáles o descríbelo con tus palabras."
            ),
            "completed": False,
        }

    # ─── INTERESTS ───────────────────────────────────
    if step == "interests":
        admin_data = company_data.get("admin_data", {})
        model, _ = selector.get_model("routing")
        try:
            classification = model.invoke([
                {"role": "system", "content": (
                    "Extrae temas de interés.\n"
                    "Categorías: ventas, cartera, inventario, clientes, "
                    "proyectos, margenes, crecimiento, personal\n"
                    "JSON array: [\"ventas\", ...]\nSin markdown."
                )},
                {"role": "user", "content": user_response}
            ])
            interests = json.loads(
                classification.content.strip().replace("```json", "").replace("```", "")
            )
        except Exception:
            interests = ["ventas", "cartera"]

        admin_data["primary_interests"] = interests
        company_data["admin_data"] = admin_data
        session["step"] = "style"
        session["company_data"] = company_data
        _onboarding_sessions[empresa_id] = session
        return {
            "step": "style",
            "message": (
                "¿Cómo prefieres que me comunique contigo y tu equipo?\n\n"
                "🎯 Directo — datos y conclusiones, sin rodeos\n"
                "📝 Detallado — explicaciones completas con contexto\n"
                "😊 Casual — como un colega de confianza\n"
                "👔 Formal — profesional y estructurado"
            ),
            "completed": False,
        }

    # ─── STYLE ───────────────────────────────────────
    if step == "style":
        admin_data = company_data.get("admin_data", {})
        style_raw = user_response.strip().lower()
        style_keywords = {
            "directo": ["directo", "grano", "sin rodeo", "conciso"],
            "detallado": ["detallado", "completo", "contexto"],
            "casual": ["casual", "colega", "amigo"],
            "formal": ["formal", "profesional"],
        }
        admin_data["communication_style"] = "directo"
        for style, keywords in style_keywords.items():
            if any(w in style_raw for w in keywords):
                admin_data["communication_style"] = style
                break

        company_data["admin_data"] = admin_data
        session["step"] = "confirmation"
        session["company_data"] = company_data
        _onboarding_sessions[empresa_id] = session

        ada_name = company_data.get("ada_name", "Ada")
        products = company_data.get("main_products") or company_data.get("main_services", [])
        products_str = ", ".join(products) if products else "por definir"
        interests_str = ", ".join(admin_data.get("primary_interests", []))

        icp = company_data.get("target_icp", {})
        icp_str = f"{icp.get('sector', '')} / {icp.get('decision_maker_title', '')}" if icp.get("sector") else "N/D"
        competitors_str = ", ".join(company_data.get("competitors_raw", [])) or "N/D"

        admin_name = f"{admin_data.get('first_name', '')} {admin_data.get('last_name', '')}".strip()

        return {
            "step": "confirmation",
            "message": (
                f"Configuración de {ada_name} para toda tu empresa:\n\n"
                f"👤 Admin: {admin_name}\n"
                f"🤖 Nombre: {ada_name}\n"
                f"🏢 Empresa: {company_data.get('company_name', '')}\n"
                f"🆔 NIT/RUT: {company_data.get('tax_id', 'N/D') or 'N/D'}\n"
                f"💼 Sector: {company_data.get('business_description', '')}\n"
                f"💡 Propuesta de valor: {(company_data.get('value_proposition', '') or 'N/D')[:80]}\n"
                f"📦 Productos/Servicios: {products_str}\n"
                f"📍 Ubicación: {company_data.get('city', '')}, {company_data.get('country', 'Colombia')}\n"
                f"👥 Tamaño: {company_data.get('company_size', '')} "
                f"({company_data.get('num_employees', 'N/D')} empleados)\n"
                f"🌐 Web: {company_data.get('website_url', 'N/D') or 'N/D'}\n"
                f"🎯 Cliente ideal: {icp_str}\n"
                f"🏆 Competidores: {competitors_str}\n"
                f"🎨 Voz de marca: {company_data.get('brand_voice', 'N/D') or 'N/D'}\n"
                f"📧 Suite: {company_data.get('productivity_suite', 'N/D')}\n"
                f"📋 PM: {company_data.get('pm_tool', 'N/D')}\n"
                f"📊 Tus prioridades: {interests_str}\n"
                f"💬 Estilo: {admin_data.get('communication_style', 'directo')}\n\n"
                "¿Está todo bien? (sí/no)"
            ),
            "completed": False,
        }

    # ─── CONFIRMATION → SAVE ─────────────────────────
    if step == "confirmation":
        confirmation = user_response.strip().lower()
        admin_data = company_data.get("admin_data", {})

        if any(w in confirmation for w in ["no", "cambiar", "corregir"]):
            session["step"] = "welcome"
            _onboarding_sessions[empresa_id] = session
            return {
                "step": "welcome",
                "message": "OK, empecemos de nuevo. ¿Cómo quieres que me llame?",
                "completed": False,
            }

        ada_name = company_data.get("ada_name", "Ada")

        # Guardar perfil de empresa con DNA completo
        await db.execute(
            text("""
                INSERT INTO ada_company_profile (
                    empresa_id, company_name, industry_type,
                    business_description, main_products, main_services,
                    company_size, num_employees, city, country, currency,
                    ada_custom_name, ada_personality,
                    admin_interests, configured_by,
                    mission, vision, value_proposition, business_model,
                    sales_cycle_days, brand_voice, website_url,
                    target_icp, social_urls, logo_url,
                    productivity_suite, pm_tool, main_competitors,
                    address, phone, tax_id, timezone, language,
                    onboarding_complete
                ) VALUES (
                    :empresa_id, :company_name, :industry_type,
                    :description, :products, :services,
                    :size, :employees, :city, :country, :currency,
                    :ada_name, :style,
                    :interests, :user_id,
                    :mission, :vision, :value_prop, :biz_model,
                    :sales_days, :brand_voice, :web_url,
                    :icp, :socials, :logo,
                    :suite, :pm, :competitors,
                    :address, :company_phone, :tax_id, :timezone, 'es',
                    TRUE
                )
                ON CONFLICT (empresa_id) DO UPDATE SET
                    company_name = EXCLUDED.company_name,
                    industry_type = EXCLUDED.industry_type,
                    business_description = EXCLUDED.business_description,
                    main_products = EXCLUDED.main_products,
                    main_services = EXCLUDED.main_services,
                    company_size = EXCLUDED.company_size,
                    num_employees = EXCLUDED.num_employees,
                    city = EXCLUDED.city,
                    country = EXCLUDED.country,
                    currency = EXCLUDED.currency,
                    ada_custom_name = EXCLUDED.ada_custom_name,
                    ada_personality = EXCLUDED.ada_personality,
                    admin_interests = EXCLUDED.admin_interests,
                    mission = EXCLUDED.mission,
                    vision = EXCLUDED.vision,
                    value_proposition = EXCLUDED.value_proposition,
                    business_model = EXCLUDED.business_model,
                    sales_cycle_days = EXCLUDED.sales_cycle_days,
                    brand_voice = EXCLUDED.brand_voice,
                    website_url = EXCLUDED.website_url,
                    target_icp = EXCLUDED.target_icp,
                    social_urls = EXCLUDED.social_urls,
                    logo_url = EXCLUDED.logo_url,
                    productivity_suite = EXCLUDED.productivity_suite,
                    pm_tool = EXCLUDED.pm_tool,
                    main_competitors = EXCLUDED.main_competitors,
                    address = EXCLUDED.address,
                    phone = EXCLUDED.phone,
                    tax_id = EXCLUDED.tax_id,
                    timezone = EXCLUDED.timezone,
                    onboarding_complete = TRUE,
                    updated_at = NOW()
            """),
            {
                "empresa_id": empresa_id,
                "company_name": company_data.get("company_name", ""),
                "industry_type": company_data.get("industry_type", "generic"),
                "description": company_data.get("business_description", ""),
                "products": json.dumps(company_data.get("main_products", [])),
                "services": json.dumps(company_data.get("main_services", [])),
                "size": company_data.get("company_size", "small"),
                "employees": company_data.get("num_employees"),
                "city": company_data.get("city", ""),
                "country": company_data.get("country", "Colombia"),
                "currency": company_data.get("currency", "COP"),
                "ada_name": ada_name,
                "style": admin_data.get("communication_style", "directo"),
                "interests": json.dumps(admin_data.get("primary_interests", [])),
                "user_id": user_id,
                "mission": company_data.get("mission", ""),
                "vision": company_data.get("vision", ""),
                "value_prop": company_data.get("value_proposition", ""),
                "biz_model": company_data.get("business_model", ""),
                "sales_days": company_data.get("sales_cycle_days"),
                "brand_voice": company_data.get("brand_voice", ""),
                "web_url": company_data.get("website_url", ""),
                "icp": json.dumps(company_data.get("target_icp", {}), ensure_ascii=False),
                "socials": json.dumps(company_data.get("social_urls", {}), ensure_ascii=False),
                "logo": company_data.get("logo_url", ""),
                "suite": company_data.get("productivity_suite", "google"),
                "pm": company_data.get("pm_tool", "none"),
                "competitors": json.dumps(company_data.get("competitors_raw", []), ensure_ascii=False),
                "address": company_data.get("address", ""),
                "company_phone": company_data.get("company_phone", ""),
                "tax_id": company_data.get("tax_id", ""),
                "timezone": company_data.get("timezone", "America/Bogota"),
            },
        )

        # Guardar datos del admin en tabla usuarios
        admin_full_name = f"{admin_data.get('first_name', '')} {admin_data.get('last_name', '')}".strip()
        if admin_full_name:
            await db.execute(
                text("""
                    UPDATE usuarios SET
                        nombre = :nombre,
                        apellido = :apellido,
                        phone = :phone,
                        country_code = :country_code
                    WHERE id = :uid
                """),
                {
                    "uid": user_id,
                    "nombre": admin_full_name,
                    "apellido": admin_data.get("last_name", ""),
                    "phone": admin_data.get("phone", ""),
                    "country_code": admin_data.get("country_code", "+57"),
                },
            )

        # Guardar preferencias del admin
        await db.execute(
            text("""
                INSERT INTO user_preferences (user_id, preferences, onboarding_completed, onboarding_completed_at)
                VALUES (:user_id, :prefs, TRUE, NOW())
                ON CONFLICT (user_id) DO UPDATE SET
                    preferences = EXCLUDED.preferences,
                    onboarding_completed = TRUE,
                    onboarding_completed_at = NOW()
            """),
            {
                "user_id": user_id,
                "prefs": json.dumps({
                    "communication_style": admin_data.get("communication_style"),
                    "primary_interests": admin_data.get("primary_interests", []),
                    "language": "es",
                    "timezone": company_data.get("timezone", "America/Bogota"),
                }),
            },
        )

        # Registrar admin como team_member con todos los permisos
        all_perms = {
            "can_view_sales": True, "can_view_finance": True,
            "can_view_inventory": True, "can_view_clients": True,
            "can_view_projects": True, "can_view_hr": True,
            "can_send_email": True, "can_manage_calendar": True,
            "can_upload_files": True, "can_use_voice": True,
            "can_prospect": True,
        }

        await db.execute(
            text("""
                INSERT INTO team_members
                    (empresa_id, user_id, display_name, role_title,
                     department, permissions, added_by)
                VALUES (:empresa_id, :user_id, :name, 'Administrador',
                        'Dirección', :perms, :user_id)
                ON CONFLICT (empresa_id, user_id) DO UPDATE SET
                    display_name = EXCLUDED.display_name,
                    permissions = EXCLUDED.permissions
            """),
            {
                "empresa_id": empresa_id,
                "user_id": user_id,
                "name": admin_full_name or user_name,
                "perms": json.dumps(all_perms),
            },
        )

        # Marcar usuario como admin
        await db.execute(
            text("UPDATE usuarios SET rol = 'admin' WHERE id = :user_id"),
            {"user_id": user_id},
        )

        await db.commit()

        # Post-procesamiento en background
        try:
            import threading

            def _post_onboarding():
                import asyncio
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    web_url = company_data.get("website_url", "")
                    if web_url:
                        from api.services.dna_generator import scrape_and_analyze_web
                        loop.run_until_complete(scrape_and_analyze_web(empresa_id, web_url))
                        print(f"ONBOARDING: Web scraping OK para {web_url}")

                    competitors = company_data.get("competitors_raw", [])
                    if competitors:
                        from api.services.dna_generator import analyze_competitors
                        loop.run_until_complete(analyze_competitors(empresa_id, competitors))
                        print(f"ONBOARDING: Análisis de {len(competitors)} competidores OK")

                    from api.services.dna_generator import generate_agent_configs
                    loop.run_until_complete(generate_agent_configs(empresa_id))
                    print(f"ONBOARDING: agent_configs generados OK")

                    from api.database import sync_engine
                    from sqlalchemy import text as sql_text
                    suite = company_data.get("productivity_suite", "google")
                    pm = company_data.get("pm_tool")
                    with sync_engine.connect() as conn:
                        for svc in ["email", "calendar", "drive"]:
                            conn.execute(sql_text("""
                                INSERT INTO tenant_app_config (empresa_id, service, provider)
                                VALUES (:eid, :svc, :provider)
                                ON CONFLICT (empresa_id, service) DO UPDATE SET provider = :provider
                            """), {"eid": empresa_id, "svc": svc, "provider": suite})
                        if pm and pm != "none":
                            conn.execute(sql_text("""
                                INSERT INTO tenant_app_config (empresa_id, service, provider)
                                VALUES (:eid, 'pm', :provider)
                                ON CONFLICT (empresa_id, service) DO UPDATE SET provider = :provider
                            """), {"eid": empresa_id, "provider": pm})
                        conn.commit()
                    print(f"ONBOARDING: tenant_app_config OK")
                except Exception as e:
                    print(f"ONBOARDING: Post-processing error (no bloqueante): {e}")
                finally:
                    loop.close()

            t = threading.Thread(target=_post_onboarding)
            t.start()
            t.join(timeout=45)
        except Exception as e:
            print(f"ONBOARDING: Post-processing thread error: {e}")

        # Transicionar a pasos de conexión
        session["step"] = "connect_telegram"
        _onboarding_sessions[empresa_id] = session

        # Verificar si ya tiene Telegram vinculado
        user_telegram_linked = False
        try:
            result = await db.execute(
                text("SELECT telegram_id FROM usuarios WHERE id = :uid"),
                {"uid": user_id}
            )
            tg_row = result.fetchone()
            user_telegram_linked = bool(tg_row and tg_row.telegram_id)
        except Exception:
            pass

        if user_telegram_linked:
            session["step"] = "connect_oauth"
            _onboarding_sessions[empresa_id] = session
            # Caer al handler de connect_oauth abajo
        else:
            return {
                "step": "connect_telegram",
                "message": (
                    f"✅ ¡{ada_name} está configurada para {company_data.get('company_name', 'tu empresa')}!\n\n"
                    f"Ahora vamos a conectar tus herramientas.\n\n"
                    f"📱 **Paso 1 — Conectar Telegram:**\n"
                    f"1. Abre Telegram y busca el bot **@ADA_Asesora_bot**\n"
                    f"2. Escribe **/start**\n"
                    f"3. El bot te pedirá tu email — escribe el que usaste aquí\n\n"
                    f"Cuando hayas vinculado, escribe **listo**.\n"
                    f"Si prefieres hacerlo después, escribe **saltar**."
                ),
                "completed": False,
            }

    # ─── CONNECT TELEGRAM ────────────────────────────
    if step == "connect_telegram":
        if user_response.lower().strip() in ("listo", "ya", "done", "ok", "siguiente", "saltar", "skip", "después", "despues"):
            session["step"] = "connect_oauth"
            _onboarding_sessions[empresa_id] = session
            # Caer a connect_oauth
        else:
            return {
                "step": "connect_telegram",
                "message": "Escribe **listo** cuando hayas vinculado, o **saltar** para después.",
                "completed": False,
            }

    # ─── CONNECT OAUTH ───────────────────────────────
    if step == "connect_oauth":
        response_lower = user_response.lower().strip()
        suite = company_data.get("productivity_suite", "google")

        # Verificar si ya conectado
        already_connected = False
        provider_check = "gmail" if suite == "google" else "outlook_email"
        try:
            result = await db.execute(
                text("""
                    SELECT provider FROM tenant_credentials
                    WHERE empresa_id = :eid AND provider = :p
                    AND (user_id = :uid OR user_id IS NULL) AND is_active = TRUE
                """),
                {"eid": empresa_id, "uid": user_id, "p": provider_check}
            )
            already_connected = result.fetchone() is not None
        except Exception:
            pass

        if already_connected:
            session["step"] = "connect_pm"
            _onboarding_sessions[empresa_id] = session
            # Caer a connect_pm
        elif response_lower in ("listo", "ya", "done", "ok", "siguiente", "conectado"):
            # Re-verificar
            try:
                result = await db.execute(
                    text("""
                        SELECT provider FROM tenant_credentials
                        WHERE empresa_id = :eid AND provider = :p
                        AND (user_id = :uid OR user_id IS NULL) AND is_active = TRUE
                    """),
                    {"eid": empresa_id, "uid": user_id, "p": provider_check}
                )
                now_connected = result.fetchone() is not None
            except Exception:
                now_connected = False

            if now_connected:
                session["step"] = "connect_pm"
                _onboarding_sessions[empresa_id] = session
                return {
                    "step": "connect_pm",
                    "message": f"✅ {suite.title()} conectado exitosamente.\n\n",
                    "completed": False,
                }
            else:
                return {
                    "step": "connect_oauth",
                    "message": "Parece que aún no se completó la conexión. Intenta hacer click en el enlace de arriba.\n\nCuando termines escribe **listo**, o **saltar** para después.",
                    "completed": False,
                }
        elif response_lower in ("saltar", "skip", "después", "despues"):
            session["step"] = "connect_pm"
            _onboarding_sessions[empresa_id] = session
            # Caer a connect_pm
        else:
            # Primera vez — mostrar link
            if suite == "google":
                client_id = os.getenv("GOOGLE_CLIENT_ID", "")
                redirect_uri = os.getenv("GOOGLE_REDIRECT_URI", "https://backend-ada.duckdns.org/oauth/callback")
                scopes = "https://www.googleapis.com/auth/gmail.modify https://www.googleapis.com/auth/calendar.events https://www.googleapis.com/auth/calendar.readonly https://www.googleapis.com/auth/drive.readonly https://www.googleapis.com/auth/contacts.readonly"
                state = f"{empresa_id}|google|{user_id}"

                if client_id:
                    oauth_url = (
                        f"https://accounts.google.com/o/oauth2/v2/auth?"
                        f"client_id={client_id}&"
                        f"redirect_uri={urllib.parse.quote(redirect_uri)}&"
                        f"response_type=code&"
                        f"scope={urllib.parse.quote(scopes)}&"
                        f"access_type=offline&prompt=consent&"
                        f"state={urllib.parse.quote(state)}"
                    )
                else:
                    oauth_url = f"https://backend-ada.duckdns.org/oauth/connect/google/{empresa_id}?user_id={user_id}"

                return {
                    "step": "connect_oauth",
                    "message": (
                        f"📧 **Paso 2 — Conectar Google Workspace:**\n\n"
                        f"Necesito acceso a tu Gmail, Calendar, Contactos y Drive.\n\n"
                        f"👉 Haz click en este enlace para autorizar:\n{oauth_url}\n\n"
                        f"Cuando termine, escribe **listo**.\n"
                        f"Si prefieres después, escribe **saltar**."
                    ),
                    "completed": False,
                }

            elif suite in ("microsoft", "microsoft365", "outlook"):
                oauth_url = f"https://backend-ada.duckdns.org/oauth/microsoft/connect/microsoft365/{empresa_id}?user_id={user_id}"
                return {
                    "step": "connect_oauth",
                    "message": (
                        f"📧 **Paso 2 — Conectar Microsoft 365:**\n\n"
                        f"Necesito acceso a tu Outlook, Calendar, Contactos y OneDrive.\n\n"
                        f"👉 Haz click en este enlace para autorizar:\n{oauth_url}\n\n"
                        f"Cuando termine, escribe **listo**.\n"
                        f"Si prefieres después, escribe **saltar**."
                    ),
                    "completed": False,
                }
            else:
                session["step"] = "connect_pm"
                _onboarding_sessions[empresa_id] = session

    # ─── CONNECT PM ──────────────────────────────────
    if step == "connect_pm":
        pm_tool = company_data.get("pm_tool", "")
        ada_name = company_data.get("ada_name", "Ada")
        company_name = company_data.get("company_name", "tu empresa")
        response_lower = user_response.lower().strip()

        if not pm_tool or pm_tool in ("none", "ninguno", "otro"):
            _onboarding_sessions.pop(empresa_id, None)
            return {
                "step": "complete",
                "message": (
                    f"🎉 **¡Todo listo!** {ada_name} está completamente configurada para {company_name}.\n\n"
                    f"Ya puedo ayudarte con:\n"
                    f"• 📧 Leer y escribir emails\n"
                    f"• 📅 Gestionar tu agenda\n"
                    f"• 📊 Analizar reportes y datos\n"
                    f"• 👥 Buscar info de contactos\n"
                    f"• 🎯 Perfilar prospectos\n\n"
                    f"¿En qué te ayudo primero?"
                ),
                "completed": True,
            }

        if response_lower in ("saltar", "skip", "después", "despues"):
            _onboarding_sessions.pop(empresa_id, None)
            return {
                "step": "complete",
                "message": (
                    f"🎉 **¡Todo listo!** {ada_name} está configurada para {company_name}.\n\n"
                    f"Puedes conectar {pm_tool.title()} después desde el portal.\n\n"
                    f"¿En qué te ayudo primero?"
                ),
                "completed": True,
            }

        # Si pegó un token largo
        if len(user_response.strip()) > 20 and response_lower not in ("listo", "ya", "ok"):
            token = user_response.strip()
            try:
                from cryptography.fernet import Fernet
                fernet_key = os.getenv("FERNET_KEY", "")
                fernet = Fernet(fernet_key.encode())
                encrypted = fernet.encrypt(json.dumps({"api_key": token}).encode())

                from api.database import sync_engine
                from sqlalchemy import text as sql_text
                with sync_engine.connect() as conn:
                    conn.execute(sql_text("""
                        INSERT INTO tenant_credentials (empresa_id, provider, encrypted_data, is_active)
                        VALUES (:eid, :provider, :creds, TRUE)
                        ON CONFLICT (empresa_id, provider, COALESCE(user_id, '00000000-0000-0000-0000-000000000000'))
                        DO UPDATE SET encrypted_data = :creds, is_active = TRUE
                    """), {"eid": empresa_id, "provider": pm_tool, "creds": encrypted.decode()})
                    conn.commit()

                _onboarding_sessions.pop(empresa_id, None)
                return {
                    "step": "complete",
                    "message": (
                        f"✅ {pm_tool.title()} conectado.\n\n"
                        f"🎉 **¡Todo listo!** {ada_name} está completamente configurada para {company_name}.\n\n"
                        f"¿En qué te ayudo primero?"
                    ),
                    "completed": True,
                }
            except Exception as e:
                print(f"ONBOARDING: Error guardando PM credentials: {e}")
                return {
                    "step": "connect_pm",
                    "message": "Error guardando el token. Intenta de nuevo o escribe **saltar**.",
                    "completed": False,
                }

        # Mostrar instrucciones según PM
        pm_instructions = {
            "notion": (
                f"📋 **Paso 3 — Conectar Notion:**\n\n"
                f"1. Ve a https://www.notion.so/my-integrations\n"
                f"2. Click en **New integration** → Nombre: \"Ada\"\n"
                f"3. Copia el **Internal Integration Token**\n"
                f"4. Pégalo aquí\n\n"
                f"Si prefieres después, escribe **saltar**."
            ),
            "plane": (
                f"📋 **Paso 3 — Conectar Plane:**\n\n"
                f"1. Ve a Plane → Perfil → Settings → API Tokens\n"
                f"2. Genera un nuevo token\n"
                f"3. Pégalo aquí\n\n"
                f"Si prefieres después, escribe **saltar**."
            ),
            "asana": (
                f"📋 **Paso 3 — Conectar Asana:**\n\n"
                f"1. Ve a https://app.asana.com/0/developer-console\n"
                f"2. Personal Access Tokens → New Access Token → \"Ada\"\n"
                f"3. Pégalo aquí\n\n"
                f"Si prefieres después, escribe **saltar**."
            ),
        }

        return {
            "step": "connect_pm",
            "message": pm_instructions.get(pm_tool, f"La conexión con {pm_tool} se configura desde el portal de administración.\n\nEscribe **saltar** para continuar."),
            "completed": False,
        }

    return {"step": "unknown", "message": "No entendí. Escribe /onboarding para reiniciar.", "completed": False}
