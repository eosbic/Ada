"""
Commercial Intelligence Agent — Pipeline unificado de prospeccion.
3 modos: proactivo (busca oportunidades), reactivo (perfila un lead), deteccion (email nuevo).

Nodos:
1. classify_mode -> decide si es proactivo o reactivo
2. search_signals -> Tavily (solo modo proactivo)
3. find_leads -> Apollo.io (solo modo proactivo)
4. enrich -> web scraping + memoria
5. synthesize -> perfil empatico + borrador outreach (Sonnet)
6. store -> guardar en prospect_intelligence
"""

import json
from datetime import datetime
from typing import TypedDict, Optional, List, Dict
from langgraph.graph import StateGraph, END
from models.selector import selector


class CommercialState(TypedDict, total=False):
    message: str
    empresa_id: str
    user_id: str
    intent: str
    source: str

    mode: str
    dna: dict
    sectors: list
    regions: list
    signals: list
    leads: list
    prospect: dict
    enrichment: dict
    cross_references: list

    synthesis: str
    email_draft: dict
    prospect_id: str
    response: str
    model_used: str
    needs_approval: bool
    draft_id: str
    original_draft: str
    sources_used: list


async def classify_mode(state: CommercialState) -> dict:
    """Clasifica si es busqueda proactiva o perfilamiento reactivo."""
    message = state.get("message", "").lower()

    proactive_triggers = [
        "busca oportunidades", "busca clientes", "busca prospectos",
        "encuentra leads", "oportunidades en", "busca empresas",
        "quiero nuevos clientes", "prospectar en",
    ]
    reactive_triggers = [
        "perfila", "investiga", "quien es",
        "linkedin.com", "info de", "informacion de",
        "conoces a", "datos de", "profiling",
    ]

    mode = "reactive"
    for trigger in proactive_triggers:
        if trigger in message:
            mode = "proactive"
            break
    for trigger in reactive_triggers:
        if trigger in message:
            mode = "reactive"
            break

    dna = {}
    try:
        from api.services.dna_loader import load_company_dna
        raw = load_company_dna(state.get("empresa_id", ""))
        if raw:
            dna = {
                "company_name": raw.get("company_name", ""),
                "value_prop": raw.get("value_proposition", ""),
                "industry": raw.get("industry_type", ""),
                "target_icp": json.dumps(raw.get("target_icp", ""), ensure_ascii=False) if raw.get("target_icp") else "",
                "city": raw.get("city", ""),
                "country": raw.get("country", "Colombia"),
            }
    except Exception:
        pass

    print(f"COMMERCIAL: Mode={mode}, DNA loaded={bool(dna)}")
    return {"mode": mode, "dna": dna}


async def search_signals(state: CommercialState) -> dict:
    """Busca senales de mercado con Tavily (solo modo proactivo)."""
    if state.get("mode") != "proactive":
        return {"signals": []}

    from api.services.prospect_search_service import search_market_signals

    message = state.get("message", "")
    dna = state.get("dna", {})
    empresa_id = state.get("empresa_id", "")

    model, _ = selector.get_model("routing")
    try:
        resp = await model.ainvoke([
            {"role": "system", "content": (
                "Extrae sectores y regiones del mensaje. Responde SOLO JSON:\n"
                '{"sectors": ["sector1"], "regions": ["ciudad1"], "keywords": ["keyword1"]}\n'
                "Si no menciona region, usar la ciudad de la empresa. Sin markdown."
            )},
            {"role": "user", "content": f"Mensaje: {message}\nCiudad empresa: {dna.get('city', 'Colombia')}"},
        ])
        raw = (resp.content or "").strip().replace("```json", "").replace("```", "")
        parsed = json.loads(raw)
        sectors = parsed.get("sectors", [])
        regions = parsed.get("regions", [dna.get("city", "Colombia")])
        keywords = parsed.get("keywords", [])
    except Exception:
        sectors = []
        regions = [dna.get("city", "Colombia")]
        keywords = []

    signals = await search_market_signals(
        empresa_id=empresa_id,
        sectors=sectors,
        regions=regions,
        keywords=keywords,
    )

    return {"signals": signals, "sectors": sectors, "regions": regions}


async def find_leads(state: CommercialState) -> dict:
    """Busca leads en Apollo.io (proactivo) o extrae datos del mensaje (reactivo)."""
    if state.get("mode") != "proactive":
        message = state.get("message", "")
        model, _ = selector.get_model("routing")

        try:
            resp = await model.ainvoke([
                {"role": "system", "content": (
                    "Extrae nombre de persona y/o empresa del mensaje. Responde SOLO JSON:\n"
                    '{"person_name": "", "company_name": "", "email": "", "linkedin_url": ""}\n'
                    "Dejar vacio lo que no se menciona. Sin markdown."
                )},
                {"role": "user", "content": message},
            ])
            raw = (resp.content or "").strip().replace("```json", "").replace("```", "")
            prospect_data = json.loads(raw)
        except Exception:
            prospect_data = {"person_name": message.strip(), "company_name": ""}

        lead = {
            "full_name": prospect_data.get("person_name", ""),
            "company_name": prospect_data.get("company_name", ""),
            "email": prospect_data.get("email", ""),
            "linkedin_url": prospect_data.get("linkedin_url", ""),
            "source": "manual",
        }

        return {"leads": [lead] if lead["full_name"] or lead["company_name"] else []}

    # Modo proactivo: buscar empresas en Apollo
    from api.services.prospect_search_service import search_and_enrich_companies

    empresa_id = state.get("empresa_id", "")
    dna = state.get("dna", {})
    signals = state.get("signals", [])
    sectors = state.get("sectors", [])
    regions = state.get("regions", [])

    all_leads = []

    if signals:
        model, _ = selector.get_model("routing")
        signals_text = "\n".join(f"- {s['title']}: {s['content'][:200]}" for s in signals[:5])

        try:
            resp = await model.ainvoke([
                {"role": "system", "content": (
                    "De estas noticias, extrae nombres de empresas que podrian ser clientes potenciales.\n"
                    'Responde SOLO JSON: {"companies": [{"name": "", "domain": ""}]}\n'
                    "Maximo 3 empresas. Sin markdown."
                )},
                {"role": "user", "content": signals_text},
            ])
            raw = (resp.content or "").strip().replace("```json", "").replace("```", "")
            companies = json.loads(raw).get("companies", [])
        except Exception:
            companies = []

        for company in companies[:3]:
            results = await search_and_enrich_companies(
                empresa_id=empresa_id,
                company_name=company.get("name", ""),
                company_domain=company.get("domain", ""),
                location=dna.get("city", ""),
                industry_keywords=sectors,
                max_results=2,
            )
            all_leads.extend(results)

    if not all_leads:
        results = await search_and_enrich_companies(
            empresa_id=empresa_id,
            company_name="",
            location=regions[0] if regions else dna.get("city", "Colombia"),
            industry_keywords=sectors,
            max_results=5,
        )
        all_leads.extend(results)

    print(f"COMMERCIAL: Found {len(all_leads)} leads/companies total")
    return {"leads": all_leads[:5]}


async def enrich_and_cross_reference(state: CommercialState) -> dict:
    """Enriquece leads con web scraping + busca conexiones en memoria."""
    leads = state.get("leads", [])
    empresa_id = state.get("empresa_id", "")
    user_id = state.get("user_id", "")

    if not leads:
        return {"prospect": {}, "enrichment": {}, "cross_references": []}

    prospect = leads[0]

    enrichment = {}
    company_domain = prospect.get("company_domain", "")
    if company_domain:
        from api.services.prospect_search_service import enrich_company_web
        enrichment = await enrich_company_web(company_domain)

    cross_refs = []
    person_name = prospect.get("full_name", "")
    company_name = prospect.get("company_name", "")

    if person_name or company_name:
        try:
            from api.services.memory_service import search_reports
            results = search_reports(person_name or company_name, empresa_id)
            for r in (results or [])[:2]:
                cross_refs.append({"type": "ada_report", "content": r[:200]})
        except Exception:
            pass

    print(f"COMMERCIAL: Enriched prospect, {len(cross_refs)} cross-references")
    return {"prospect": prospect, "enrichment": enrichment, "cross_references": cross_refs}


async def synthesize_and_draft(state: CommercialState) -> dict:
    """Genera perfil empatico + borrador de email (Sonnet)."""
    prospect = state.get("prospect", {})
    enrichment = state.get("enrichment", {})
    cross_refs = state.get("cross_references", [])
    signals = state.get("signals", [])
    dna = state.get("dna", {})
    leads = state.get("leads", [])
    empresa_id = state.get("empresa_id", "")
    user_id = state.get("user_id", "")

    if not prospect and not leads:
        # Si hay senales pero no leads, mostrar las senales al usuario
        if signals:
            signals_text = "\n".join(
                f"  🔹 {s['title'][:100]}\n     {s['url']}"
                for s in signals[:5]
            )
            return {
                "response": (
                    f"📰 **Senales de mercado encontradas ({len(signals)}):**\n\n"
                    f"{signals_text}\n\n"
                    f"⚠️ No pude obtener contactos directos de estas empresas.\n"
                    f"¿Tienes el nombre de alguien en alguna de estas empresas? "
                    f"Escribe \"perfila [nombre] de [empresa]\" y te armo el perfil."
                ),
                "model_used": "none",
                "sources_used": [],
            }
        return {
            "response": "No encontre prospectos relevantes. Intenta con otro sector o empresa.",
            "model_used": "none",
            "sources_used": [],
        }

    model, model_name = selector.get_model("chat_with_tools")

    prospect_info = json.dumps(prospect, ensure_ascii=False, default=str)[:800]
    enrichment_info = json.dumps(enrichment, ensure_ascii=False)[:300]
    cross_ref_info = json.dumps(cross_refs, ensure_ascii=False)[:300] if cross_refs else "Ninguna conexion previa"
    signals_info = json.dumps(signals[:3], ensure_ascii=False, default=str)[:500] if signals else "Sin senales"

    remitent_name = ""
    try:
        from api.database import sync_engine
        from sqlalchemy import text as sql_text
        with sync_engine.connect() as conn:
            row = conn.execute(
                sql_text("SELECT nombre FROM usuarios WHERE id = :uid"),
                {"uid": user_id}
            ).fetchone()
            if row:
                remitent_name = row.nombre or ""
    except Exception:
        pass

    synthesis_prompt = f"""Eres Ada, asesora comercial de {dna.get('company_name', 'la empresa')}.

SOBRE MI EMPRESA:
{dna.get('company_name', '')}: {dna.get('value_prop', '')}
Sector: {dna.get('industry', '')}
ICP: {dna.get('target_icp', '')}

PROSPECTO A PERFILAR:
{prospect_info}

ENRIQUECIMIENTO WEB:
{enrichment_info}

CONEXIONES PREVIAS:
{cross_ref_info}

SENALES DE MERCADO:
{signals_info}

GENERA DOS COSAS:

1. PERFIL EMPATICO (maximo 8 lineas):
- Si es una PERSONA: quien es, su empresa, por que podria necesitar nuestro servicio
- Si es una EMPRESA (sin persona especifica): que hace, tamano, industria, por que podria necesitar nuestro servicio
- Angulo de acercamiento recomendado
- Punto de dolor probable
- Nivel de oportunidad (alta/media/baja)

2. BORRADOR DE EMAIL DE ACERCAMIENTO (solo si hay email del prospecto):
- Personalizado con la senal o contexto detectado
- Maximo 5 lineas
- Directo, no generico
- Firmar como {remitent_name or 'el remitente'}
- NO usar "Estimado/a"
- Si no hay email, dejar email_subject y email_body vacios

Responde JSON:
{{
    "synthesis": "perfil empatico aqui",
    "email_subject": "asunto del email o vacio",
    "email_body": "cuerpo del email o vacio",
    "opportunity_level": "alta|media|baja"
}}"""

    try:
        resp = await model.ainvoke([
            {"role": "system", "content": "Generas perfiles comerciales y borradores de acercamiento. Responde SOLO JSON."},
            {"role": "user", "content": synthesis_prompt},
        ])

        raw = (resp.content or "").strip().replace("```json", "").replace("```", "")
        result = json.loads(raw)

        synthesis = result.get("synthesis", "")
        email_subject = result.get("email_subject", "")
        email_body = result.get("email_body", "")

    except Exception as e:
        print(f"COMMERCIAL: Synthesis error: {e}")
        synthesis = f"Prospecto: {prospect.get('full_name', 'N/D')} en {prospect.get('company_name', 'N/D')}"
        email_subject = ""
        email_body = ""

    # Formatear respuesta — distinguir persona vs empresa
    has_person = bool(prospect.get("full_name"))
    prospect_email = prospect.get("email", "")

    other_leads = ""
    if len(leads) > 1:
        other_items = []
        for l in leads[1:4]:
            if l.get("full_name"):
                other_items.append(f"  🔹 {l['full_name']} — {l.get('job_title', '')} en {l.get('company_name', '')}")
            else:
                size = l.get("company_size", "")
                size_str = f" ({size} emp.)" if size else ""
                other_items.append(f"  🔹 {l.get('company_name', 'N/D')} — {l.get('industry', '')}{size_str}")
        other_leads = f"\n\n🏢 **Otras empresas encontradas:**\n" + "\n".join(other_items)

    if has_person:
        response = f"""🎯 **Perfil Comercial**

👤 **{prospect.get('full_name', 'N/D')}**
💼 {prospect.get('job_title', 'N/D')} en {prospect.get('company_name', 'N/D')}
📍 {prospect.get('city', '')} {prospect.get('country', '')}
📧 {prospect_email or 'Email no disponible'}

📋 **Analisis:**
{synthesis}"""
    else:
        # Perfil de empresa
        company = prospect.get("company_name", "N/D")
        size = prospect.get("company_size", "")
        size_str = f" ({size} empleados)" if size else ""
        desc = prospect.get("description") or prospect.get("seo_description") or ""
        tech_list = prospect.get("technologies", [])
        if tech_list and isinstance(tech_list[0], dict):
            techs_str = ", ".join(t.get("name", "") for t in tech_list[:5] if t.get("name"))
        elif tech_list:
            techs_str = ", ".join(str(t) for t in tech_list[:5])
        else:
            techs_str = ""
        revenue = prospect.get("annual_revenue", "")

        response = f"""🎯 **Perfil de Empresa**

🏢 **{company}**
🌐 {prospect.get('company_domain', 'N/D')}
📍 {prospect.get('city', '')} {prospect.get('country', '')}
🏭 {prospect.get('industry', 'N/D')}{size_str}"""

        if revenue:
            response += f"\n💰 Facturacion: {revenue}"
        if desc:
            response += f"\n📝 {desc[:200]}"
        if techs_str:
            response += f"\n🔧 Tech: {techs_str}"

        response += f"\n\n📋 **Analisis:**\n{synthesis}"

    if cross_refs:
        refs_text = "\n".join(f"  🔗 {r.get('type', '')}: {r.get('content', '')[:80]}" for r in cross_refs[:2])
        response += f"\n\n🔗 **Conexiones previas:**\n{refs_text}"

    response += other_leads

    if prospect_email and email_body:
        try:
            from api.services.gmail_service import gmail_draft
            draft_result = gmail_draft(
                to=prospect_email,
                subject=email_subject,
                body=email_body,
                empresa_id=empresa_id,
                user_id=user_id,
            )

            if draft_result.get("draft_id"):
                response += (
                    f"\n\n✉️ **Borrador de acercamiento:**\n\n"
                    f"📬 Para: {prospect_email}\n"
                    f"📝 Asunto: {email_subject}\n\n"
                    f"💬 {email_body}\n\n"
                    f"---\n"
                    f"¿Lo envio? Responde **si** para confirmar o **no** para cancelar."
                )

                return {
                    "synthesis": synthesis,
                    "email_draft": {"subject": email_subject, "body": email_body},
                    "response": response,
                    "model_used": model_name,
                    "needs_approval": True,
                    "draft_id": draft_result.get("draft_id", ""),
                    "original_draft": f"Para: {prospect_email}\nAsunto: {email_subject}\n\n{email_body}",
                    "sources_used": [],
                }
        except Exception as e:
            print(f"COMMERCIAL: Draft error: {e}")

    if not prospect_email and has_person:
        response += "\n\n⚠️ No encontre email verificado. ¿Tienes el email de esta persona?"
    elif not has_person:
        company = prospect.get("company_name", "esta empresa")
        response += f"\n\n💡 Escribe \"perfila a [nombre] de {company}\" para obtener el contacto directo."

    return {
        "synthesis": synthesis,
        "response": response,
        "model_used": model_name,
        "sources_used": [],
    }


async def store_prospect(state: CommercialState) -> dict:
    """Guarda en prospect_intelligence."""
    prospect = state.get("prospect", {})
    empresa_id = state.get("empresa_id", "")
    user_id = state.get("user_id", "")
    synthesis = state.get("synthesis", "")
    signals = state.get("signals", [])
    mode = state.get("mode", "reactive")

    if not prospect.get("full_name") and not prospect.get("company_name"):
        return {}

    try:
        from api.database import sync_engine
        from sqlalchemy import text as sql_text

        signal_text = signals[0].get("title", "") if signals else ""
        source = "proactive_scout" if mode == "proactive" else "manual"

        with sync_engine.connect() as conn:
            result = conn.execute(
                sql_text("""
                    INSERT INTO prospect_intelligence
                        (empresa_id, user_id, full_name, job_title, company_name,
                         email, linkedin_url, phone, photo_url,
                         source, intent_signal, intent_source,
                         empathy_synthesis, profile_data, status)
                    VALUES
                        (:eid, :uid, :name, :title, :company,
                         :email, :linkedin, :phone, :photo,
                         :source, :signal, :signal_source,
                         :synthesis, CAST(:profile_data AS jsonb), 'profiled')
                    ON CONFLICT DO NOTHING
                    RETURNING id
                """),
                {
                    "eid": empresa_id, "uid": user_id,
                    "name": prospect.get("full_name", ""),
                    "title": prospect.get("job_title", ""),
                    "company": prospect.get("company_name", ""),
                    "email": prospect.get("email", ""),
                    "linkedin": prospect.get("linkedin_url", ""),
                    "phone": prospect.get("phone", ""),
                    "photo": prospect.get("photo_url", ""),
                    "source": source,
                    "signal": signal_text[:500],
                    "signal_source": "tavily" if signals else "manual",
                    "synthesis": synthesis[:2000],
                    "profile_data": json.dumps(prospect, ensure_ascii=False, default=str),
                },
            )
            row = result.fetchone()
            conn.commit()

            prospect_id = str(row.id) if row else ""
            if prospect_id:
                print(f"COMMERCIAL: Saved prospect {prospect_id}")
    except Exception as e:
        print(f"COMMERCIAL: Error saving prospect: {e}")
        prospect_id = ""

    return {"prospect_id": prospect_id}


# --- Compilar grafo ---

graph = StateGraph(CommercialState)
graph.add_node("classify", classify_mode)
graph.add_node("signals", search_signals)
graph.add_node("leads", find_leads)
graph.add_node("enrich", enrich_and_cross_reference)
graph.add_node("synthesize", synthesize_and_draft)
graph.add_node("store", store_prospect)

graph.set_entry_point("classify")
graph.add_edge("classify", "signals")
graph.add_edge("signals", "leads")
graph.add_edge("leads", "enrich")
graph.add_edge("enrich", "synthesize")
graph.add_edge("synthesize", "store")
graph.add_edge("store", END)

commercial_intelligence_agent = graph.compile()
