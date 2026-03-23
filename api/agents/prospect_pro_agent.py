"""
Prospecting Pro Agent — Perfila empresas y prospectos con profundidad.

El CEO dice: "Perfila a Empresa XYZ" y Ada:
1. Pide datos clave si faltan
2. Busca info del prospecto en memoria
3. LLM genera perfil comercial completo
4. Incluye estrategia de acercamiento personalizada

Datos que Ada pide/extrae:
- Nombre del gerente o persona de compras
- Empresa
- URL de la empresa
- Redes: Instagram, Facebook, LinkedIn
"""

import json
from typing import TypedDict, Optional, List
from langgraph.graph import StateGraph, END
from models.selector import selector
from api.services.memory_service import search_memory, store_memory


class ProspectState(TypedDict, total=False):
    message: str
    empresa_id: str
    user_id: str
    intent: str

    # Datos del prospecto extraídos
    prospect_data: dict
    needs_more_info: bool
    memory_context: str

    # Output
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
    "linkedin": "URL LinkedIn si lo mencionó",
    "instagram": "URL Instagram si lo mencionó",
    "facebook": "URL Facebook si lo mencionó",
    "telefono": "teléfono si lo mencionó",
    "email_prospecto": "email del prospecto si lo mencionó",
    "contexto": "contexto adicional (cómo lo conoció, qué necesita, etc.)",
    "missing": ["lista de datos que FALTAN y son importantes pedir"]
}

Si falta información clave (nombre, empresa), agrégalo a "missing".
Responde SOLO JSON, sin markdown."""


PROFILE_PROMPT = """Genera un PERFIL COMERCIAL PROFESIONAL de este prospecto.

## DATOS DEL PROSPECTO:
{prospect_data}

## CONTEXTO PREVIO (si hay):
{memory_context}

## INSTRUCCIONES:

### 1. FICHA DEL PROSPECTO
Presenta toda la info disponible en formato de ficha:
- 👤 Contacto: nombre y cargo
- 🏢 Empresa: nombre y sector
- 🌐 Web: URL
- 📱 Redes: LinkedIn, Instagram, Facebook
- 📧 Email / 📞 Teléfono

### 2. ANÁLISIS DE LA EMPRESA
Basado en el sector y contexto:
- Tamaño estimado de la empresa
- Posibles necesidades según su industria
- Dolor probable que nuestros servicios resuelven

### 3. ESTRATEGIA DE ACERCAMIENTO
3 pasos concretos y ejecutables:
- Primer contacto (qué canal usar, qué decir en la primera frase)
- Propuesta de valor (qué ofrecer específicamente)
- Siguiente paso (reunión, demo, cotización)

### 4. PREGUNTAS DE DESCUBRIMIENTO
5 preguntas estratégicas para la primera reunión:
- 2 sobre su negocio actual
- 2 sobre dolores/necesidades
- 1 sobre presupuesto/timeline

### 5. SEÑALES DE OPORTUNIDAD
Clasificar la oportunidad:
- 💰 Alta: si pidió cotización, segunda reunión, referido
- 📊 Media: mostró interés, respondió email
- ❄️ Baja: primer contacto, solo explorando

### 6. DATOS QUE FALTAN
Si hay información faltante, listarla para que el CEO la consiga.

FORMATO: Profesional, accionable, español colombiano B2B.
NO inventar datos del prospecto. Si no tienes info, pide que la consigan."""


async def extract_prospect_info(state: ProspectState) -> dict:
    """Extrae datos del prospecto del mensaje del usuario."""
    model, model_name = selector.get_model("chat_with_tools")

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
            "missing": ["nombre_contacto", "cargo", "url_empresa"],
        }

    # Buscar en memoria si ya tenemos info de este prospecto
    search_terms = prospect_data.get("empresa", "") or prospect_data.get("nombre_contacto", "")
    empresa_id = state.get("empresa_id", "")
    memories = search_memory(search_terms, empresa_id=empresa_id) if search_terms else []
    memory_context = "\n".join(memories) if memories else "Sin historial previo."

    missing = prospect_data.get("missing", [])
    needs_more = len(missing) >= 3 and not prospect_data.get("empresa")

    print(f"PROSPECT PRO: Extraído → empresa={prospect_data.get('empresa')}, contacto={prospect_data.get('nombre_contacto')}, missing={missing}")

    return {
        "prospect_data": prospect_data,
        "memory_context": memory_context,
        "needs_more_info": needs_more,
        "model_used": model_name,
    }


async def generate_profile_or_ask(state: ProspectState) -> dict:
    """Genera perfil completo o pide más info si falta mucho."""
    prospect_data = state.get("prospect_data", {})
    memory_context = state.get("memory_context", "")
    needs_more = state.get("needs_more_info", False)

    # Si falta demasiada info, pedir antes de perfilar
    if needs_more:
        missing = prospect_data.get("missing", [])
        missing_labels = {
            "nombre_contacto": "Nombre del gerente o persona de compras",
            "cargo": "Cargo de la persona",
            "empresa": "Nombre de la empresa",
            "url_empresa": "URL del sitio web",
            "linkedin": "LinkedIn de la persona o empresa",
            "instagram": "Instagram de la empresa",
            "facebook": "Facebook de la empresa",
            "sector": "Sector o industria",
        }
        missing_text = "\n".join([
            f"- {missing_labels.get(m, m)}" for m in missing[:5]
        ])

        return {
            "response": (
                f"Para hacer un perfilamiento completo, necesito que me proporciones:\n\n"
                f"{missing_text}\n\n"
                f"Puedes darme la información que tengas y yo complemento el resto. "
                f"Mientras más datos me des, mejor será la estrategia de acercamiento."
            ),
        }

    # Generar perfil completo
    model, model_name = selector.get_model("chat_with_tools")

    prompt = PROFILE_PROMPT.format(
        prospect_data=json.dumps(prospect_data, ensure_ascii=False, indent=2),
        memory_context=memory_context,
    )

    response = await model.ainvoke([
        {"role": "system", "content": (
            "Eres Ada, la mejor asesora comercial B2B de Latinoamérica. "
            "Tu trabajo es darle al CEO toda la inteligencia necesaria para "
            "cerrar un negocio. Sé estratégica, concreta y accionable."
        )},
        {"role": "user", "content": prompt},
    ])

    # Guardar perfil en memoria para futuras consultas
    empresa_name = prospect_data.get("empresa", "prospecto")
    empresa_id = state.get("empresa_id", "")
    store_memory(f"Perfil prospecto {empresa_name}: {response.content[:1000]}", empresa_id=empresa_id)
    store_memory(f"Datos prospecto {empresa_name}: {json.dumps(prospect_data, ensure_ascii=False)}", empresa_id=empresa_id)

    # Guardar en ada_reports
    try:
        from api.database import sync_engine
        from sqlalchemy import text as sql_text

        empresa_id = state.get("empresa_id", "")
        report_id = None
        if empresa_id:
            with sync_engine.connect() as conn:
                result = conn.execute(
                    sql_text("""
                        INSERT INTO ada_reports
                            (empresa_id, title, report_type, markdown_content,
                             metrics_summary, alerts, generated_by, allowed_roles)
                        VALUES (:eid, :title, 'prospect_profile', :content,
                                :metrics, '[]', :model, :roles)
                        RETURNING id
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
                row = result.fetchone()
                if row:
                    report_id = str(row[0])
                conn.commit()

            if report_id and empresa_id:
                from api.services.kg_pipeline import run_kg_pipeline
                run_kg_pipeline(report_id, empresa_id, response.content, "")
    except Exception as e:
        print(f"PROSPECT PRO: Error guardando en DB: {e}")

    print(f"PROSPECT PRO: Perfil generado con {model_name}")

    return {
        "response": response.content,
        "model_used": model_name,
    }


# ─── Compilar grafo ──────────────────────────────────────

graph = StateGraph(ProspectState)
graph.add_node("extract", extract_prospect_info)
graph.add_node("profile", generate_profile_or_ask)
graph.set_entry_point("extract")
graph.add_edge("extract", "profile")
graph.add_edge("profile", END)
prospect_pro_agent = graph.compile()