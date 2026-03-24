"""
Onboarding Agent — Configuración inicial solo para admin.
Referencia: ADA_V5_ANEXO_ONBOARDING.md §6

Flujo conversacional por pasos:
1. Bienvenida → 2. Nombre Ada → 3. Empresa + actividad →
4. Productos → 5. Tamaño + ciudad → 6. Intereses →
7. Estilo comunicación → 8. Confirmación → Guardar en DB

Cada llamada al endpoint avanza un paso.
El estado se mantiene en memoria (dict por empresa_id).
"""

import json
import re
from typing import Optional
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from models.selector import selector


_onboarding_sessions = {}

STEPS = [
    "welcome",
    "ada_name",
    "company_info",
    "value_prop",
    "products",
    "size_city",
    "website",
    "target_icp",
    "competitors",
    "brand",
    "apps",
    "interests",
    "style",
    "confirmation",
]


async def process_onboarding(
    db: AsyncSession,
    empresa_id: str,
    user_id: str,
    user_name: str,
    user_response: str = "",
) -> dict:
    """Procesa un paso del onboarding. Retorna pregunta actual."""

    session = _onboarding_sessions.get(empresa_id, {
        "step": "welcome",
        "company_data": {},
        "admin_data": {},
    })

    step = session["step"]
    company_data = session["company_data"]
    admin_data = session["admin_data"]

    # ─── WELCOME ─────────────────────────────────────
    if step == "welcome":
        session["step"] = "ada_name"
        _onboarding_sessions[empresa_id] = session
        return {
            "step": "ada_name",
            "message": (
                "👋 ¡Hola! Soy Ada, tu asistente ejecutiva de inteligencia artificial.\n\n"
                "Mi trabajo es ayudarte a gestionar tu negocio: analizo datos, "
                "manejo agenda, redacto correos, y te alerto cuando algo necesita "
                "tu atención.\n\n"
                "Como eres el administrador, necesito que me configures. "
                "Son unas pocas preguntas y toma menos de 3 minutos.\n\n"
                "Primero: mi nombre es Ada, pero tú decides cómo me llama "
                "todo tu equipo. ¿Cómo quieres que me llame?"
            ),
            "completed": False,
        }

    # ─── ADA NAME ────────────────────────────────────
    if step == "ada_name":
        ada_name = user_response.strip() if user_response.strip() else "Ada"
        if len(ada_name) > 50:
            ada_name = "Ada"
        admin_data["ada_name"] = ada_name
        session["step"] = "company_info"
        session["admin_data"] = admin_data
        _onboarding_sessions[empresa_id] = session
        return {
            "step": "company_info",
            "message": (
                f"Perfecto, soy {ada_name} desde ahora para todo el equipo. 😊\n\n"
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

        session["step"] = "value_prop"
        session["company_data"] = company_data
        _onboarding_sessions[empresa_id] = session
        return {
            "step": "value_prop",
            "message": (
                f"Entendido, {company_data['company_name']}.\n\n"
                f"¿Cual es la propuesta de valor de {company_data['company_name']}? "
                f"¿Por que te eligen tus clientes en vez de a la competencia?"
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
                f"¿Cuales son los principales productos o servicios "
                f"de {company_data.get('company_name', 'tu empresa')}?\n\n"
                "Dime los mas importantes separados por comas."
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

        session["step"] = "size_city"
        session["company_data"] = company_data
        _onboarding_sessions[empresa_id] = session
        return {
            "step": "size_city",
            "message": "¿Cuántos empleados tienen aproximadamente y en qué ciudad están?",
            "completed": False,
        }

    # ─── SIZE + CITY ─────────────────────────────────
    if step == "size_city":
        model, _ = selector.get_model("routing")
        try:
            extraction = model.invoke([
                {"role": "system", "content": (
                    "Del siguiente texto extrae el número de empleados y la ciudad.\n"
                    "SIEMPRE responde JSON válido con estos 3 campos:\n"
                    "{\"employees\": número_entero, \"city\": \"nombre_ciudad\", "
                    "\"size\": \"micro|small|medium|large\"}\n\n"
                    "Reglas de tamaño:\n"
                    "- micro: menos de 10 empleados\n"
                    "- small: 10 a 50\n"
                    "- medium: 51 a 200\n"
                    "- large: más de 200\n\n"
                    "Si dice '4 personas' o '4 trabajadores', employees = 4.\n"
                    "SOLO JSON, sin markdown, sin explicación."
                )},
                {"role": "user", "content": user_response}
            ])
            raw = extraction.content.strip().replace("```json", "").replace("```", "")
            parsed = json.loads(raw)

            employees = parsed.get("employees")
            if employees is not None:
                employees = int(employees)

            company_data["num_employees"] = employees
            company_data["city"] = parsed.get("city", "")
            company_data["company_size"] = parsed.get("size", "small")

            print(f"ONBOARDING: Parseado OK → {employees} empleados, {company_data['city']}, {company_data['company_size']}")

        except Exception as e:
            print(f"ONBOARDING: Error parseando size_city: {e}")
            # Fallback: extraer números manualmente
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

            city_text = re.sub(r'\d+', '', user_response).strip().strip(',').strip()
            company_data["city"] = city_text if city_text else user_response

        session["step"] = "website"
        session["company_data"] = company_data
        _onboarding_sessions[empresa_id] = session
        return {
            "step": "website",
            "message": (
                "¿Tienes sitio web? Pega la URL y yo extraigo la informacion automaticamente.\n\n"
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
                "¿Quien es tu cliente ideal?\n\n"
                "Describeme:\n"
                "- ¿A que sector pertenece?\n"
                "- ¿Que cargo tiene quien toma la decision de compra?\n"
                "- ¿Que tamano de empresa?\n"
                "- ¿Cuantos dias toma normalmente cerrar una venta?"
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
                "¿Quienes son tus 3 principales competidores? "
                "Dime sus nombres separados por coma.\n\n"
                "Si no tienes competidores directos o no los conoces, "
                "escribe 'no se' y seguimos."
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
                "🎨 ¿Como describirias el tono de tu marca? "
                "(formal, cercano, tecnico, disruptivo, elegante...)\n\n"
                "📱 ¿Tienes redes sociales? Pega los links de Instagram, "
                "Facebook, LinkedIn o TikTok.\n\n"
                "🖼️ Si tienes el link de tu logo (URL de imagen), "
                "tambien lo puedo usar para tus reportes."
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
                "¿Que herramientas de trabajo usa tu empresa?\n\n"
                "📧 Email y Calendario:\n"
                "  1️⃣ Google Workspace (Gmail, Google Calendar)\n"
                "  2️⃣ Microsoft 365 (Outlook, calendario Outlook)\n\n"
                "📋 Gestion de proyectos:\n"
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
                "¿Que informacion te importa mas a TI como administrador?\n\n"
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
        session["step"] = "style"
        session["admin_data"] = admin_data
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

        session["step"] = "confirmation"
        session["admin_data"] = admin_data
        _onboarding_sessions[empresa_id] = session

        ada_name = admin_data.get("ada_name", "Ada")
        products = company_data.get("main_products") or company_data.get("main_services", [])
        products_str = ", ".join(products) if products else "por definir"
        interests_str = ", ".join(admin_data.get("primary_interests", []))

        icp = company_data.get("target_icp", {})
        icp_str = f"{icp.get('sector', '')} / {icp.get('decision_maker_title', '')}" if icp.get("sector") else "N/D"
        competitors_str = ", ".join(company_data.get("competitors_raw", [])) or "N/D"

        return {
            "step": "confirmation",
            "message": (
                f"Configuracion de {ada_name} para toda tu empresa:\n\n"
                f"🤖 Nombre: {ada_name}\n"
                f"🏢 Empresa: {company_data.get('company_name', '')}\n"
                f"💼 Sector: {company_data.get('business_description', '')}\n"
                f"💡 Propuesta de valor: {(company_data.get('value_proposition', '') or 'N/D')[:80]}\n"
                f"📦 Productos/Servicios: {products_str}\n"
                f"📍 Ubicacion: {company_data.get('city', '')}\n"
                f"👥 Tamano: {company_data.get('company_size', '')} "
                f"({company_data.get('num_employees', 'N/D')} empleados)\n"
                f"🌐 Web: {company_data.get('website_url', 'N/D') or 'N/D'}\n"
                f"🎯 Cliente ideal: {icp_str}\n"
                f"🏢 Competidores: {competitors_str}\n"
                f"🎨 Voz de marca: {company_data.get('brand_voice', 'N/D') or 'N/D'}\n"
                f"📧 Suite: {company_data.get('productivity_suite', 'N/D')}\n"
                f"📋 PM: {company_data.get('pm_tool', 'N/D')}\n"
                f"📊 Tus prioridades: {interests_str}\n"
                f"💬 Estilo: {admin_data.get('communication_style', 'directo')}\n\n"
                "¿Esta todo bien? (si/no)"
            ),
            "completed": False,
        }

    # ─── CONFIRMATION → SAVE ─────────────────────────
    if step == "confirmation":
        confirmation = user_response.strip().lower()

        if any(w in confirmation for w in ["no", "cambiar", "corregir"]):
            session["step"] = "welcome"
            _onboarding_sessions[empresa_id] = session
            return {
                "step": "welcome",
                "message": "OK, empecemos de nuevo. ¿Cómo quieres que me llame?",
                "completed": False,
            }

        ada_name = admin_data.get("ada_name", "Ada")

        # Guardar perfil de empresa con DNA completo
        await db.execute(
            text("""
                INSERT INTO ada_company_profile (
                    empresa_id, company_name, industry_type,
                    business_description, main_products, main_services,
                    company_size, num_employees, city,
                    ada_custom_name, ada_personality,
                    admin_interests, configured_by,
                    mission, vision, value_proposition, business_model,
                    sales_cycle_days, brand_voice, website_url,
                    target_icp, social_urls, logo_url,
                    productivity_suite, pm_tool, onboarding_complete
                ) VALUES (
                    :empresa_id, :company_name, :industry_type,
                    :description, :products, :services,
                    :size, :employees, :city,
                    :ada_name, :style,
                    :interests, :user_id,
                    :mission, :vision, :value_prop, :biz_model,
                    :sales_days, :brand_voice, :web_url,
                    :icp, :socials, :logo,
                    :suite, :pm, TRUE
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
                    "timezone": "America/Bogota",
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
                    permissions = EXCLUDED.permissions
            """),
            {
                "empresa_id": empresa_id,
                "user_id": user_id,
                "name": user_name,
                "perms": json.dumps(all_perms),
            },
        )

        # Marcar usuario como admin en tabla usuarios
        await db.execute(
            text("UPDATE usuarios SET rol = 'admin' WHERE id = :user_id"),
            {"user_id": user_id},
        )

        await db.commit()

        # Post-procesamiento en background: scrape web, competidores, agent_configs
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
                        print(f"ONBOARDING: Analisis de {len(competitors)} competidores OK")

                    from api.services.dna_generator import generate_agent_configs
                    loop.run_until_complete(generate_agent_configs(empresa_id))
                    print(f"ONBOARDING: agent_configs generados OK")

                    # Setup app connections en tenant_app_config
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

        _onboarding_sessions.pop(empresa_id, None)

        return {
            "step": "complete",
            "message": (
                f"✅ ¡Listo! {ada_name} esta configurada para "
                f"{company_data.get('company_name', 'tu empresa')}.\n\n"
                f"🔄 Estoy analizando tu sitio web y competidores en segundo plano. "
                f"En unos minutos tendre todo listo para personalizar cada respuesta "
                f"a tu negocio.\n\n"
                f"¿En que te ayudo primero?"
            ),
            "completed": True,
        }

    return {"step": "unknown", "message": "No entendí. Escribe /onboarding para reiniciar.", "completed": False}