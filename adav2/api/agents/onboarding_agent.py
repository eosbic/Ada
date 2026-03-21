"""
Onboarding Agent — Configuración inicial solo para admin.
Flujo conversacional por pasos:
1. welcome → 2. ada_name → 3. company_info →
4. products → 5. business_details → 6. size_city →
7. interests → 8. style → 9. confirmation → Guardar en DB
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
    "products",
    "business_details",
    "size_city",
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
                "Primero: ¿cómo quieres que me llame todo tu equipo?"
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
                f"Perfecto, soy {ada_name} desde ahora. 😊\n\n"
                "Cuéntame sobre tu empresa: ¿cuál es el nombre y a qué se dedican?\n\n"
                "Ejemplo: \"Distribuidora El Paisa, vendemos productos de consumo masivo en el Valle del Cauca\""
            ),
            "completed": False,
        }

    # ─── COMPANY INFO ────────────────────────────────
    if step == "company_info":
        model, _ = selector.get_model("routing")
        try:
            extraction = model.invoke([
                {"role": "system", "content": (
                    "Extrae nombre de empresa, ciudad y clasifica industria.\n"
                    "Industrias: retail, servicios, manufactura, tecnologia, salud, "
                    "educacion, construccion, alimentos, transporte, consultoria, "
                    "restaurante, agricultura, inmobiliario, financiero, generic\n"
                    "JSON: {\"company_name\": \"...\", \"industry_type\": \"...\", "
                    "\"description\": \"...\", \"city\": \"...\"}\nSin markdown."
                )},
                {"role": "user", "content": user_response}
            ])
            parsed = json.loads(
                extraction.content.strip().replace("```json", "").replace("```", "")
            )
            company_data["company_name"] = parsed.get("company_name", user_response)
            company_data["industry_type"] = parsed.get("industry_type", "generic")
            company_data["business_description"] = parsed.get("description", user_response)
            if parsed.get("city"):
                company_data["city"] = parsed.get("city", "")
        except Exception:
            company_data["company_name"] = user_response
            company_data["industry_type"] = "generic"
            company_data["business_description"] = user_response

        session["step"] = "products"
        session["company_data"] = company_data
        _onboarding_sessions[empresa_id] = session
        return {
            "step": "products",
            "message": (
                f"Entendido. ¿Cuáles son los principales productos o servicios "
                f"de {company_data['company_name']}?\n\n"
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

        session["step"] = "business_details"
        session["company_data"] = company_data
        _onboarding_sessions[empresa_id] = session
        return {
            "step": "business_details",
            "message": (
                "Dame información adicional sobre tu presencia digital y métricas clave "
                "(puedes omitir lo que no aplique):\n\n"
                "- Sitio web\n"
                "- LinkedIn, Instagram, Facebook\n"
                "- KPIs que más revisas\n"
                "- Principales clientes\n"
                "- Principales competidores"
            ),
            "completed": False,
        }

    # ─── BUSINESS DETAILS ────────────────────────────
    if step == "business_details":
        model, _ = selector.get_model("routing")
        try:
            extraction = model.invoke([
                {"role": "system", "content": (
                    "Extrae información de presencia digital y negocio.\n"
                    "JSON: {\"website\": \"...\", \"linkedin\": \"...\", "
                    "\"instagram\": \"...\", \"facebook\": \"...\", "
                    "\"kpis\": [\"...\"], \"target_clients\": [\"...\"], "
                    "\"competitors\": [\"...\"]}\n"
                    "Si no hay info para un campo, usa null. Sin markdown."
                )},
                {"role": "user", "content": user_response}
            ])
            parsed = json.loads(
                extraction.content.strip().replace("```json", "").replace("```", "")
            )
            if parsed.get("website"):
                company_data["website"] = parsed["website"]
            if parsed.get("linkedin"):
                company_data["linkedin"] = parsed["linkedin"]
            if parsed.get("instagram"):
                company_data["instagram"] = parsed["instagram"]
            if parsed.get("facebook"):
                company_data["facebook"] = parsed["facebook"]
            if parsed.get("kpis"):
                company_data["key_metrics"] = parsed["kpis"] if isinstance(parsed["kpis"], list) else [parsed["kpis"]]
            if parsed.get("target_clients"):
                company_data["target_market"] = parsed["target_clients"] if isinstance(parsed["target_clients"], list) else [parsed["target_clients"]]
            if parsed.get("competitors"):
                company_data["main_competitors"] = parsed["competitors"] if isinstance(parsed["competitors"], list) else [parsed["competitors"]]
        except Exception as e:
            print(f"ONBOARDING: Error parseando business_details: {e}")
            company_data["business_raw"] = user_response

        # Guardar business_details en DB inmediatamente
        try:
            await db.execute(
                text("""
                    INSERT INTO ada_company_profile (empresa_id, website, linkedin, instagram, facebook, key_metrics, target_market, main_competitors)
                    VALUES (:empresa_id, :website, :linkedin, :instagram, :facebook, :kpis, :target, :competitors)
                    ON CONFLICT (empresa_id) DO UPDATE SET
                        website = COALESCE(EXCLUDED.website, ada_company_profile.website),
                        linkedin = COALESCE(EXCLUDED.linkedin, ada_company_profile.linkedin),
                        instagram = COALESCE(EXCLUDED.instagram, ada_company_profile.instagram),
                        facebook = COALESCE(EXCLUDED.facebook, ada_company_profile.facebook),
                        key_metrics = COALESCE(EXCLUDED.key_metrics, ada_company_profile.key_metrics),
                        target_market = COALESCE(EXCLUDED.target_market, ada_company_profile.target_market),
                        main_competitors = COALESCE(EXCLUDED.main_competitors, ada_company_profile.main_competitors),
                        updated_at = NOW()
                """),
                {
                    "empresa_id": empresa_id,
                    "website": company_data.get("website"),
                    "linkedin": company_data.get("linkedin"),
                    "instagram": company_data.get("instagram"),
                    "facebook": company_data.get("facebook"),
                    "kpis": json.dumps(company_data.get("key_metrics", [])),
                    "target": json.dumps(company_data.get("target_market", [])),
                    "competitors": json.dumps(company_data.get("main_competitors", [])),
                },
            )
            await db.commit()
            print(f"ONBOARDING: business_details guardado para {empresa_id}")
        except Exception as e:
            print(f"ONBOARDING: Error guardando business_details: {e}")

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
            company_data["city"] = parsed.get("city", "") or company_data.get("city", "")
            company_data["company_size"] = parsed.get("size", "small")

            print(f"ONBOARDING: {employees} empleados, {company_data['city']}, {company_data['company_size']}")

        except Exception as e:
            print(f"ONBOARDING: Error parseando size_city: {e}")
            numbers = re.findall(r'\d+', user_response)
            if numbers:
                employees = int(numbers[0])
                company_data["num_employees"] = employees
                company_data["company_size"] = "micro" if employees < 10 else "small" if employees <= 50 else "medium" if employees <= 200 else "large"
            else:
                company_data["num_employees"] = None
                company_data["company_size"] = "small"
            city_text = re.sub(r'\d+', '', user_response).strip().strip(',').strip()
            company_data["city"] = city_text if city_text else company_data.get("city", "")

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

        return {
            "step": "confirmation",
            "message": (
                f"Configuración de {ada_name} para toda tu empresa:\n\n"
                f"🤖 Nombre: {ada_name}\n"
                f"🏢 Empresa: {company_data.get('company_name', '')}\n"
                f"💼 Sector: {company_data.get('business_description', '')}\n"
                f"📦 Productos/Servicios: {products_str}\n"
                f"📍 Ubicación: {company_data.get('city', '')}\n"
                f"👥 Tamaño: {company_data.get('company_size', '')} "
                f"({company_data.get('num_employees', 'N/D')} empleados)\n"
                f"🌐 Web: {company_data.get('website', 'no proporcionada')}\n"
                f"📊 Tus prioridades: {interests_str}\n"
                f"💬 Estilo: {admin_data.get('communication_style', 'directo')}\n\n"
                "¿Está todo bien? (sí/no)"
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

        await db.execute(
            text("""
                INSERT INTO ada_company_profile (
                    empresa_id, company_name, industry_type,
                    business_description, main_products, main_services,
                    company_size, num_employees, city,
                    website, linkedin, instagram, facebook,
                    key_metrics, target_market, main_competitors,
                    ada_custom_name, ada_personality,
                    admin_interests, configured_by
                ) VALUES (
                    :empresa_id, :company_name, :industry_type,
                    :description, :products, :services,
                    :size, :employees, :city,
                    :website, :linkedin, :instagram, :facebook,
                    :kpis, :target, :competitors,
                    :ada_name, :style,
                    :interests, :user_id
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
                    website = COALESCE(EXCLUDED.website, ada_company_profile.website),
                    linkedin = COALESCE(EXCLUDED.linkedin, ada_company_profile.linkedin),
                    instagram = COALESCE(EXCLUDED.instagram, ada_company_profile.instagram),
                    facebook = COALESCE(EXCLUDED.facebook, ada_company_profile.facebook),
                    key_metrics = COALESCE(EXCLUDED.key_metrics, ada_company_profile.key_metrics),
                    target_market = COALESCE(EXCLUDED.target_market, ada_company_profile.target_market),
                    main_competitors = COALESCE(EXCLUDED.main_competitors, ada_company_profile.main_competitors),
                    ada_custom_name = EXCLUDED.ada_custom_name,
                    ada_personality = EXCLUDED.ada_personality,
                    admin_interests = EXCLUDED.admin_interests,
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
                "website": company_data.get("website"),
                "linkedin": company_data.get("linkedin"),
                "instagram": company_data.get("instagram"),
                "facebook": company_data.get("facebook"),
                "kpis": json.dumps(company_data.get("key_metrics", [])),
                "target": json.dumps(company_data.get("target_market", [])),
                "competitors": json.dumps(company_data.get("main_competitors", [])),
                "ada_name": ada_name,
                "style": admin_data.get("communication_style", "directo"),
                "interests": json.dumps(admin_data.get("primary_interests", [])),
                "user_id": user_id,
            },
        )

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

        await db.execute(
            text("UPDATE usuarios SET rol = 'admin' WHERE id = :user_id"),
            {"user_id": user_id},
        )

        await db.commit()
        _onboarding_sessions.pop(empresa_id, None)

        return {
            "step": "complete",
            "message": (
                f"✅ ¡Listo! {ada_name} está configurada para "
                f"{company_data.get('company_name', 'tu empresa')}.\n\n"
                f"Toda la información ha sido guardada correctamente.\n\n"
                f"¿En qué te ayudo primero?"
            ),
            "completed": True,
        }

    return {"step": "unknown", "message": "No entendí. Escribe /onboarding para reiniciar.", "completed": False}