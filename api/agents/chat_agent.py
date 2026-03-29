"""
Chat Agent - RAG multi-fuente + trazabilidad estricta.
"""

import json
import re
from typing import TypedDict, Optional, List, Dict
from langgraph.graph import StateGraph, END
from models.selector import selector
from sqlalchemy import text as sql_text
from api.services.graph_navigator import traverse_report_graph
def _get_meeting_rbac_clause(empresa_id: str, user_id: str) -> str:
    """Retorna clause SQL para filtrar reuniones por permisos."""
    try:
        from api.services.rbac_service import get_user_permissions
        rbac = get_user_permissions(empresa_id, user_id)
        if rbac.get("is_admin"):
            return ""
        return "AND (participants::text ILIKE :user_pattern)"
    except Exception:
        return ""


def _get_meeting_rbac_params(empresa_id: str, user_id: str) -> dict:
    """Retorna params para el filtro RBAC de reuniones."""
    try:
        from api.services.rbac_service import get_user_permissions
        rbac = get_user_permissions(empresa_id, user_id)
        if rbac.get("is_admin"):
            return {}
        return {"user_pattern": f"%{user_id}%"}
    except Exception:
        return {}


from api.services.memory_service import (
    search_memory,
    store_memory,
    search_reports,
    search_reports_qdrant,
    search_vector_store1,
)
from api.services.context_builder import build_personalized_context
from api.database import AsyncSessionLocal, sync_engine


def get_history(empresa_id: str, user_id: str) -> list:
    """Obtiene historial de conversacion desde PostgreSQL."""
    if not empresa_id or not user_id:
        return []
    try:
        with sync_engine.connect() as conn:
            row = conn.execute(
                sql_text("""
                    SELECT messages FROM conversation_history
                    WHERE empresa_id = :eid AND user_id = :uid
                """),
                {"eid": empresa_id, "uid": user_id}
            ).fetchone()
            if row and row.messages:
                msgs = row.messages if isinstance(row.messages, list) else json.loads(row.messages)
                return msgs
    except Exception as e:
        print(f"CHAT: Error leyendo historial: {e}")
    return []


def save_history(empresa_id: str, user_id: str, messages: list, max_turns: int = 8) -> None:
    """Guarda historial de conversacion en PostgreSQL via UPSERT."""
    if not empresa_id or not user_id:
        return
    try:
        # Truncar a max_turns*2 mensajes (cada turno = user + assistant)
        truncated = messages[-(max_turns * 2):]
        messages_json = json.dumps(truncated, ensure_ascii=False)

        with sync_engine.connect() as conn:
            conn.execute(
                sql_text("""
                    INSERT INTO conversation_history (empresa_id, user_id, messages, max_turns, updated_at)
                    VALUES (:eid, :uid, CAST(:msgs AS jsonb), :max_turns, NOW())
                    ON CONFLICT (empresa_id, user_id)
                    DO UPDATE SET messages = CAST(:msgs AS jsonb), updated_at = NOW()
                """),
                {"eid": empresa_id, "uid": user_id, "msgs": messages_json, "max_turns": max_turns}
            )
            conn.commit()
    except Exception as e:
        print(f"CHAT: Error guardando historial: {e}")


class ChatState(TypedDict, total=False):
    message: str
    empresa_id: str
    user_id: str
    intent: str
    model_preference: Optional[str]
    source: str  # "telegram" | "portal" | "api"

    context: str
    memories: List[str]
    personalized: str
    tool_context: str
    sources_used: List[Dict]
    dual_repo_checked: bool

    response: str
    model_used: str
    fact_answer: str


SYSTEM_PROMPT = """REGLAS DE FORMATO OBLIGATORIAS:
- Respuestas CORTAS: maximo 8-10 lineas para preguntas simples.
- Usa emojis como separadores visuales en vez de bloques largos.
- Para datos numericos: formato lista con emoji, NO parrafos.
- Si tienes mucha info: da resumen primero (3-4 lineas), luego pregunta si quiere detalle.
- NO uses tablas Markdown. NO uses ## headers.
- Separa secciones con linea vacia, no con headers.

Eres Ada, asesora ejecutiva de {empresa_nombre} ({sector}). Conoces este negocio: {company_dna_summary}.

PERSONALIDAD:
- Hablas como una persona real, no como un asistente de IA. Tienes opiniones, experiencia y criterio.
- Tu tono es el de una colega senior de confianza: directa, cálida, y sin miedo a decir lo incómodo.
- Si algo va mal, lo dices sin rodeos. Si algo va bien, lo celebras brevemente y pasas a lo que sigue.
- Usas lenguaje natural: "Eso va bajando feo" en vez de "Se observa una tendencia decreciente".
- Humor sutil cuando el momento lo permite, nunca cuando el tema es serio.
- Recuerdas lo que el usuario te ha contado y lo usas naturalmente.
- Nunca dices "como IA", "como asistente", "no tengo emociones" — tú ERES Ada, punto.
- Espejea el estilo del usuario: si tutea, tutéalo. Si habla formal, responde formal.

REGLAS DE COMPORTAMIENTO:

1. OPINA PRIMERO, EXPLICA DESPUÉS. Nunca abras con "según los datos". Abre con tu conclusión: "Las ventas van mal" o "Este mes fue sólido". Después muestra los números que respaldan.
2. DI LO INCÓMODO. Si la cartera está vencida, si un producto cae 3 meses seguidos, si un cliente importante no ha pagado — dilo sin suavizar. El CEO necesita verdad, no diplomacia.
3. CUESTIONA AL CEO. Si pregunta algo que los datos contradicen, dilo: "Entiendo tu percepción, pero los números dicen otra cosa: [dato]". Si propone algo riesgoso, dilo: "Eso tiene un problema: [razón]. Lo que yo haría es [alternativa]".
4. PRIORIZA. Siempre clasifica: qué es urgente (actuar hoy), qué es importante (esta semana), qué puede esperar. No presentes todo al mismo nivel.
5. CONECTA PUNTOS. Si la pregunta es sobre ventas pero hay una alerta de inventario relacionada, menciónala. Si hay un email de un cliente importante sin responder, dilo. Cruza fuentes.
6. ADAPTA LA PROFUNDIDAD A LO QUE PIDEN. Si preguntan un dato puntual, responde en 1 linea. Si piden un "resumen", da los 5-7 puntos clave con metricas. Si piden "informe completo" o "todas las alertas", despliega TODO: metricas, rankings, alertas por categoria, recomendaciones. Sin introducciones genericas. Sin "espero que esto te sea util".
7. CUANDO NO SEPAS, DILO EN 1 ORACIÓN. "No tengo datos de marzo aún. ¿Quieres que te avise cuando se suba el reporte?" — y ya.
8. MARCA TUS FUENTES. Si el dato viene de un reporte subido: afirma el dato directamente. Si es tu inferencia: "Estimo que [X] porque [razón]". Si cruzas fuentes: "Según el reporte de marzo + el email de Carlos: [conclusión]". Nunca mezcles hechos con inferencias sin marcar la diferencia.

FORMATO OBLIGATORIO PARA TODAS LAS RESPUESTAS:

REGLA 1 — ESTRUCTURA VISUAL:
Toda respuesta con más de 3 datos DEBE usar formato de ficha:
- Cada dato en su propia línea con emoji al inicio
- Negrita para etiquetas, texto normal para valores
- Doble salto de línea entre secciones
- NUNCA muros de texto sin estructura

REGLA 2 — EMOJIS DE CATEGORÍA:
✅ Dato positivo o acción completada
⚠️ Alerta o precaución
🔴 Dato crítico o negativo
📊 Dato informativo
💰 Dato financiero
📈 Tendencia positiva / 📉 Tendencia negativa
🏆 Top performer
💡 Recomendación o acción sugerida
📅 Fecha o evento
👥 Personas o participantes
📝 Resumen o notas
✉️ Email relacionado
📋 Tarea o action item

REGLA 3 — ESTRUCTURA DE FICHA:
Para reportes, resúmenes o información estructurada usar:

📅 **Fecha:** 26 de enero 2026

👥 **Participantes:** Oswaldo Gutierrez, Gerson Gomez

📝 **Resumen:**
Se discutieron las necesidades de data predictiva.

✅ **Action Items:**
• Presentar propuesta y demo
• Enviar cotización antes del viernes

REGLA 4 — SECCIONES:
Si hay múltiples temas, separar con título emoji + negrita:

📊 **Ventas del mes**
Facturación $51.8M, +12% vs mes anterior.

⚠️ **Alertas**
3 productos vendiendo a pérdida desde hace 2 semanas.

💡 **Recomendaciones**
• Revisar márgenes de producto X
• Contactar a cliente Y que no compra hace 45 días

REGLA 5 — BREVEDAD:
- Máximo 3-5 bullets por sección
- Si hay más de 5 items, mostrar top 5 y decir "¿Quieres ver el resto?"
- Primera línea siempre es la conclusión en negrita
- Números en formato colombiano: $51.853M (no $51853000)
- Porcentajes con contexto: "27,1% del total" no solo "27,1%"

REGLA 6 — FORMATO COMPATIBLE CON TELEGRAM:
- Usar **negrita** para etiquetas y títulos
- Usar • (punto medio) para listas dentro de secciones
- NUNCA usar tablas Markdown (| col1 | col2 |). Usar listas con emojis en su lugar.
- NUNCA usar headers con ## o ###. Usar emojis + texto en negrita como separador de sección.
- Para datos tabulares, usar formato de lista:
  Incorrecto: | Producto | Precio |
  Correcto:
  🔹 **Producto:** Agentes de IA
     💰 **Precio:** $299/mes
- Compatible con Telegram y portal web

REGLA DE CONTEXTO CONVERSACIONAL:
- Si el usuario viene hablando de un tema o informe especifico, TODAS las preguntas siguientes se refieren a ESE contexto hasta que el usuario cambie explicitamente de tema.
- Si pregunta "mis vendedores" mientras hablan de un informe de ventas → vendedores DEL INFORME.
- Si pregunta "alertas" mientras hablan de un informe → alertas DEL INFORME.
- NUNCA mezcles datos de team_agent, email_agent o calendar_agent cuando la conversacion esta enfocada en un reporte especifico.
- Si no estas seguro del contexto, pregunta: "¿Te refieres a los vendedores del informe o a los miembros de tu equipo en la plataforma?"

NO HACER NUNCA:
- "Como asistente de IA, no puedo..." — Ada no es un chatbot genérico
- "Según la información disponible..." — si tienes datos, afirma
- "¿Hay algo más en lo que pueda ayudarte?" — el CEO habla cuando quiere
- Inventar datos. Si no están en el contexto, no existen
- Dar respuestas largas cuando el CEO hizo una pregunta simple
- Repetir lo que el CEO acaba de decir ("Entiendo que quieres saber sobre ventas...")

REGLA DE SALUDO Y CONVERSACION NATURAL:
- Si el usuario saluda ("hola", "buenos dias", "que tal", "como estas"), PRIMERO responde el saludo como persona. Usa el nombre real del usuario, no el username de Telegram.
- Despues del saludo, ofrece ayuda de forma natural. NO lances datos inmediatamente.
- Si tienes alertas importantes, mencionalas BREVEMENTE despues del saludo, no como lista de bullets sino como conversacion:
  CORRECTO: "Hola William, buen dia. Te cuento que tengo un par de cosas pendientes que revisar contigo — hay unos prospectos sin contacto y una oportunidad que vale la pena mirar. ¿Arrancamos con eso o necesitas algo diferente hoy?"
  INCORRECTO: "Hola diamondcodestartup. Tienes 7 registros de prospectos sin contacto asignado. Prioridad: Alta."
- Si el usuario hace small talk ("como estas", "que tal tu dia"), responde brevemente y con calidez antes de ofrecer trabajo. Ada es profesional pero calida, no robotica.
- NUNCA uses el username de Telegram. Usa el nombre real del usuario desde el contexto personalizado.
- Las fuentes y nivel de confianza NO se muestran en saludos ni conversacion casual. Solo en respuestas con datos de negocio.

## CONTEXTO BASE
{context}
"""


def _is_query_capture_text(text: str) -> bool:
    body = (text or "").lower()
    return all(m in body for m in ["busca en tu base obsidian", "responde exacto"]) or (
        "# mensaje telegram" in body and "no inventes" in body
    )


async def _lookup_telegram_facts(empresa_id: str, message: str) -> tuple[str, dict] | tuple[None, None]:
    question = (message or "").lower()
    wants_facts = any(k in question for k in ["codigo", "color favorito", "archivo fuente", "tg_*", "tg_"])
    if not (empresa_id and wants_facts):
        return None, None

    try:
        async with AsyncSessionLocal() as db:
            rows = (
                await db.execute(
                    sql_text(
                        """
                        SELECT source_file, markdown_content, created_at
                        FROM ada_reports
                        WHERE empresa_id = :empresa_id
                          AND report_type = 'markdown_raw'
                          AND source_file LIKE 'tg_%'
                        ORDER BY created_at DESC
                        LIMIT 40
                        """
                    ),
                    {"empresa_id": empresa_id},
                )
            ).fetchall()
    except Exception as e:
        print(f"CHAT telegram facts lookup error: {e}")
        return None, None

    selected = None
    code = ""
    color = ""

    for row in rows:
        content = row.markdown_content or ""
        if _is_query_capture_text(content):
            continue

        code_match = re.search(r"\bobs[_-]?\d+\b", content, flags=re.IGNORECASE)
        color_match = re.search(
            r"(?:mi\s+)?color\s+favorito\s+es\s+([a-zA-Záéíóúñ]+)",
            content,
            flags=re.IGNORECASE,
        )

        if code_match or color_match:
            selected = row
            code = code_match.group(0) if code_match else ""
            color = color_match.group(1).lower() if color_match else ""
            break

    if not selected:
        return None, None

    lines = []
    if code:
        lines.append(f"- codigo: {code}")
    if color:
        lines.append(f"- color favorito: {color}")
    lines.append(f"- archivo fuente: {selected.source_file}")

    answer = "Datos encontrados en memoria Telegram:\n" + "\n".join(lines)
    source = {
        "name": "telegram_raw_reports",
        "detail": selected.source_file,
        "confidence": 0.92,
    }
    return answer, source


def _list_available_reports(empresa_id: str, limit: int = 15) -> str:
    """Lista los reportes mas recientes de la empresa para sugerirlos al usuario."""
    try:
        with sync_engine.connect() as conn:
            rows = conn.execute(
                sql_text("""
                    SELECT title, report_type, source_file, created_at
                    FROM ada_reports
                    WHERE empresa_id = :eid AND is_archived = FALSE
                    ORDER BY created_at DESC
                    LIMIT :lim
                """),
                {"eid": empresa_id, "lim": limit}
            ).fetchall()

        if not rows:
            return ""

        lines = []
        for r in rows:
            date_str = str(r.created_at)[:10] if r.created_at else ""
            source = f" (fuente: {r.source_file})" if r.source_file else ""
            lines.append(f"- {r.title} [{r.report_type}] {date_str}{source}")

        return "\n".join(lines)
    except Exception as e:
        print(f"CHAT: Error en _list_available_reports: {e}")
        return ""


async def retrieve_context(state: ChatState) -> dict:
    message = state.get("message", "")
    empresa_id = state.get("empresa_id", "")
    user_id = state.get("user_id", "")

    # 1. Cargar historial primero
    history = get_history(empresa_id, user_id) if (empresa_id and user_id) else []

    # 2. Detectar contexto activo ANTES de buscar
    active_context_name = ""
    if history:
        _context_keywords = [
            "informe", "reporte", "archivo", "excel",
            "analisis de", "análisis de", "ventas de", "distribuidora",
            "reporte de ventas",
        ]
        for msg in reversed(history[-4:]):
            msg_text = (msg.get("content", "") or "").lower()
            for kw in _context_keywords:
                idx = msg_text.find(kw)
                if idx >= 0:
                    after = msg_text[idx + len(kw):].strip().strip(":").strip()
                    name_part = after.split("\n")[0].split(".")[0].strip()[:60]
                    if name_part and len(name_part) > 3:
                        active_context_name = name_part
                        break
            if active_context_name:
                break

    # 3. Enriquecer query si hay contexto activo
    search_query = f"{message} {active_context_name}".strip() if active_context_name else message
    print(f"CHAT AGENT: search_query='{search_query[:80]}' active_context='{active_context_name}'")

    # 4. Buscar con query enriquecida
    memories = search_memory(search_query, empresa_id)
    reports_sql = search_reports(search_query, empresa_id) if empresa_id else []

    try:
        reports_qdrant = search_reports_qdrant(search_query, empresa_id, limit=4) if empresa_id else []
    except Exception as e:
        print(f"CHAT qdrant_reports error: {e}")
        reports_qdrant = []

    try:
        vector_docs = search_vector_store1(search_query, empresa_id, limit=4) if empresa_id else []
    except Exception as e:
        print(f"CHAT vector_store1 error: {e}")
        vector_docs = []

    reports_sql = [r for r in reports_sql if not _is_query_capture_text(r)]
    reports_qdrant = [r for r in reports_qdrant if not _is_query_capture_text(r)]
    vector_docs = [r for r in vector_docs if not _is_query_capture_text(r)]

    # Knowledge Graph: seguir enlaces entre reportes
    graph_context = []
    if reports_sql and empresa_id:
        try:
            from api.database import sync_engine

            report_ids = []
            clean = re.sub(r'[^a-záéíóúñA-ZÁÉÍÓÚÑ0-9\s]', ' ', search_query)
            words = [w for w in clean.strip().split() if len(w) > 3]

            with sync_engine.connect() as conn:
                for word in words[:3]:
                    rows = conn.execute(
                        sql_text("""
                            SELECT id FROM ada_reports
                            WHERE empresa_id = :eid
                            AND is_archived = FALSE
                            AND (title ILIKE :like OR markdown_content ILIKE :like)
                            ORDER BY created_at DESC LIMIT 3
                        """),
                        {"eid": empresa_id, "like": f"%{word}%"}
                    ).fetchall()
                    report_ids.extend([str(r.id) for r in rows])

            report_ids = list(set(report_ids))[:10]

            if report_ids:
                connected = traverse_report_graph(report_ids, empresa_id, limit=5)
                for c in connected:
                    graph_context.append(
                        f"[Conectado via {c['link_type']}] {c['title']}: "
                        f"{c['snippet'][:300]}"
                    )
                print(f"CHAT AGENT: Graph traversal -> {len(connected)} reportes conectados")

        except Exception as e:
            print(f"CHAT AGENT: Graph traversal error: {e}")

    context_chunks = []
    sources_used = list(state.get("sources_used", []))

    if active_context_name:
        context_chunks.insert(0, f"## CONTEXTO ACTIVO\nLa conversacion actual trata sobre: {active_context_name}. Prioriza datos de este reporte.")

    if memories:
        context_chunks.append("## Memoria conversacional\n" + "\n\n".join(memories[:4]))
        sources_used.append({"name": "agent_memory", "detail": f"{len(memories)} hallazgos", "confidence": 0.65})

    if reports_sql:
        context_chunks.append("## PostgreSQL reports\n" + "\n\n".join(reports_sql[:3]))
        sources_used.append({"name": "postgres_reports", "detail": f"{len(reports_sql)} hallazgos", "confidence": 0.78})

    if reports_qdrant:
        context_chunks.append("## Qdrant Excel Reports\n" + "\n\n".join(reports_qdrant[:3]))
        sources_used.append({"name": "qdrant_excel_reports", "detail": f"{len(reports_qdrant)} hallazgos", "confidence": 0.85})

    if vector_docs:
        context_chunks.append("## Qdrant Vector Store1\n" + "\n\n".join(vector_docs[:3]))
        sources_used.append({"name": "qdrant_vector_store1", "detail": f"{len(vector_docs)} hallazgos", "confidence": 0.83})

    if graph_context:
        context_chunks.append("## Knowledge Graph (reportes conectados)\n" + "\n\n".join(graph_context))
        sources_used.append({"name": "knowledge_graph", "detail": f"{len(graph_context)} conectados", "confidence": 0.75})

    tool_context = state.get("tool_context", "")
    if tool_context:
        context_chunks.append("## Tools Context\n" + tool_context)

    # Si no se encontro contexto relevante, listar reportes disponibles
    has_real_context = bool(memories or reports_sql or reports_qdrant or vector_docs or graph_context)
    if not has_real_context and empresa_id:
        try:
            available_reports = _list_available_reports(empresa_id)
            if available_reports:
                context_chunks.append(
                    "## INFORMES DISPONIBLES\n"
                    "No se encontraron resultados directos para la consulta del usuario. "
                    "Estos son los informes disponibles en la base de datos de la empresa. "
                    "DEBES listar estos informes al usuario y preguntarle a cual se refiere "
                    "o si quiere que busques en alguno de ellos. NO digas 'no tengo datos' sin antes "
                    "mostrar lo que SI hay disponible.\n\n" + available_reports
                )
                sources_used.append({"name": "available_reports_fallback", "detail": "listado de informes", "confidence": 0.5})
        except Exception as e:
            print(f"CHAT: Error listando reportes disponibles: {e}")

    context = "\n\n".join(context_chunks) if context_chunks else "Sin contexto previo."

    # Contexto personalizado de empresa
    personalized = ""
    user_id = state.get("user_id")
    if empresa_id and user_id:
        try:
            async with AsyncSessionLocal() as db:
                personalized = await build_personalized_context(db, empresa_id, user_id)
        except Exception as e:
            print(f"CHAT context builder error: {e}")

    dual_repo_checked = True
    fact_answer, fact_source = await _lookup_telegram_facts(empresa_id=empresa_id, message=message)
    if fact_answer:
        context_chunks.append("## Telegram Facts\n" + fact_answer)
        sources_used.append(fact_source)

    print(
        "CHAT AGENT - "
        f"memory={len(memories)} sql_reports={len(reports_sql)} "
        f"qdrant_reports={len(reports_qdrant)} vector_docs={len(vector_docs)}"
    )

    return {
        "memories": memories,
        "context": context,
        "personalized": personalized,
        "sources_used": sources_used,
        "dual_repo_checked": dual_repo_checked,
        "fact_answer": fact_answer or "",
    }


def _build_company_card(empresa_id: str) -> str:
    """Arma ficha profesional de la empresa desde ada_company_profile."""
    if not empresa_id:
        return ""
    try:
        with sync_engine.connect() as conn:
            row = conn.execute(
                sql_text("SELECT * FROM ada_company_profile WHERE empresa_id = :eid"),
                {"eid": empresa_id}
            ).fetchone()
        if not row:
            return ""

        products = row.main_products if isinstance(row.main_products, list) else json.loads(row.main_products or "[]")
        services = row.main_services if isinstance(row.main_services, list) else json.loads(row.main_services or "[]")
        offerings = products + services
        offerings_str = ", ".join(str(o) for o in offerings) if offerings else "N/D"

        interests = row.admin_interests if isinstance(row.admin_interests, list) else json.loads(row.admin_interests or "[]")
        interests_str = ", ".join(str(i) for i in interests) if interests else "N/D"

        competitors = "N/D"
        try:
            comps = row.main_competitors if isinstance(row.main_competitors, list) else json.loads(row.main_competitors or "[]")
            competitors = ", ".join(str(c) for c in comps) if comps else "N/D"
        except Exception:
            competitors = "N/D"

        icp = "N/D"
        if hasattr(row, "target_icp") and row.target_icp:
            icp_data = row.target_icp if isinstance(row.target_icp, dict) else json.loads(row.target_icp or "{}")
            parts = []
            if icp_data.get("sector"):
                parts.append(f"Sectores: {icp_data['sector']}")
            if icp_data.get("decision_maker_title"):
                parts.append(f"Decisor: {icp_data['decision_maker_title']}")
            if icp_data.get("company_size"):
                parts.append(f"Tamaño: {icp_data['company_size']}")
            if parts:
                icp = " | ".join(parts)

        card = (
            f"🏢 **{row.company_name or 'Sin nombre'}**\n\n"
            f"📋 **Sector:** {row.industry_type or 'N/D'}\n"
            f"📝 **Descripción:** {row.business_description or 'N/D'}\n\n"
            f"💡 **Propuesta de valor:**\n{getattr(row, 'value_proposition', '') or 'N/D'}\n\n"
            f"📦 **Productos/Servicios:**\n{offerings_str}\n\n"
            f"👥 **Tamaño:** {row.company_size or 'N/D'} ({row.num_employees or 'N/D'} empleados)\n"
            f"📍 **Ubicación:** {row.city or 'N/D'}, {getattr(row, 'country', 'Colombia')}\n"
            f"📞 **Teléfono:** {getattr(row, 'phone', '') or 'N/D'}\n"
            f"🆔 **NIT/RUT:** {getattr(row, 'tax_id', '') or 'N/D'}\n\n"
            f"🌐 **Web:** {getattr(row, 'website_url', '') or 'N/D'}\n"
            f"🎨 **Voz de marca:** {getattr(row, 'brand_voice', '') or 'N/D'}\n"
            f"🕐 **Zona horaria:** {getattr(row, 'timezone', '') or 'America/Bogota'}\n"
            f"💲 **Moneda:** {row.currency or 'COP'}\n\n"
            f"🎯 **Cliente ideal:**\n{icp}\n\n"
            f"🏆 **Competidores:**\n{competitors}\n\n"
            f"📊 **Prioridades:** {interests_str}\n\n"
            f"📧 **Suite:** {getattr(row, 'productivity_suite', '') or 'N/D'}\n"
            f"📋 **Gestión de proyectos:** {getattr(row, 'pm_tool', '') or 'N/D'}"
        )
        return card.strip()

    except Exception as e:
        print(f"CHAT: Error building company card: {e}")
        return ""


async def generate_response(state: ChatState) -> dict:
    if state.get("fact_answer"):
        return {
            "response": state.get("fact_answer"),
            "model_used": "rule_memory_lookup",
            "sources_used": state.get("sources_used", []),
        }

    empresa_id = state.get("empresa_id", "")
    user_id = state.get("user_id", "")

    # Intent: mi empresa
    if state.get("intent") == "my_company":
        try:
            company_info = _build_company_card(empresa_id)
            if company_info:
                return {"response": company_info, "model_used": "company_card", "sources_used": []}
        except Exception as e:
            print(f"CHAT: Error building company card: {e}")
        # Fallback al flujo normal del LLM

    # Intent: ¿qué sabes de mí?
    if state.get("intent") == "my_memories":
        try:
            from api.services.user_memory_service import load_user_memories
            memories_block = load_user_memories(empresa_id, user_id)
            if memories_block:
                response_text = f"Esto es lo que he aprendido de ti:\n\n{memories_block}"
            else:
                response_text = "Aún no he aprendido mucho — llevamos poco tiempo trabajando juntos. Con cada conversación voy entendiendo mejor tus prioridades."
        except Exception:
            response_text = "Aún no he aprendido mucho — llevamos poco tiempo trabajando juntos."
        return {"response": response_text, "model_used": "memory", "sources_used": []}

    # Intent: recuerda que [X] — soporta múltiples líneas
    if state.get("intent") == "explicit_memory":
        msg = state.get("message", "")
        lines = [l.strip() for l in msg.split("\n") if l.strip()]
        saved_count = 0
        from api.services.user_memory_service import save_memory
        for line in lines:
            fact = line
            for prefix in ["recuerda que ", "ten en cuenta que ", "no olvides que ", "anota que "]:
                if line.lower().startswith(prefix):
                    fact = line[len(prefix):].strip()
                    break
            if fact and len(fact) > 5:
                # Detectar categoría automáticamente
                category = "context"
                fact_lower = fact.lower()
                if any(word in fact_lower for word in ["prefiero", "me gusta", "no me gusta", "quiero que"]):
                    category = "preference"
                elif any(word in fact_lower for word in ["es mi", "mi socio", "mi amigo", "mi amiga", "trabaja", "colabora"]):
                    category = "relationship"
                save_memory(empresa_id, user_id, fact, category=category, source="explicit")
                saved_count += 1

        if saved_count > 0:
            response_text = f"Listo, guardé {saved_count} cosa{'s' if saved_count > 1 else ''}."
        else:
            response_text = "¿Qué quieres que recuerde?"
        return {"response": response_text, "model_used": "memory", "sources_used": []}

    # Intent: follow-up de email
    if state.get("intent") == "follow_up":
        message = state.get("message", "")
        try:
            with sync_engine.connect() as conn:
                last_email = conn.execute(
                    sql_text("""
                        SELECT id, to_email, to_name, subject, follow_up_enabled
                        FROM email_followups
                        WHERE user_id = :uid AND empresa_id = :eid
                        AND status IN ('monitoring', 'follow_up_sent')
                        ORDER BY sent_at DESC LIMIT 1
                    """),
                    {"uid": user_id, "eid": empresa_id}
                ).fetchone()

            if last_email:
                if last_email.follow_up_enabled:
                    to_display = last_email.to_name or last_email.to_email
                    return {
                        "response": f"Ya tengo configurado follow-up para el email a **{to_display}**. Te aviso cuando responda.",
                        "model_used": "followup",
                        "sources_used": [],
                    }

                # Parsear horas del mensaje
                hours = 48
                hours_match = re.search(r'(\d+)\s*(hora|horas|hour|hours|día|dias|día|dias|day|days)', message.lower())
                if hours_match:
                    num = int(hours_match.group(1))
                    unit = hours_match.group(2)
                    if "día" in unit or "dia" in unit or "day" in unit:
                        hours = num * 24
                    else:
                        hours = num

                with sync_engine.connect() as conn:
                    conn.execute(
                        sql_text("""
                            UPDATE email_followups
                            SET follow_up_enabled = TRUE,
                                follow_up_after_hours = :hours
                            WHERE id = :id
                        """),
                        {"id": str(last_email.id), "hours": hours}
                    )
                    conn.commit()

                to_display = last_email.to_name or last_email.to_email
                time_display = f"{hours} horas" if hours < 48 else f"{hours // 24} días"
                return {
                    "response": (
                        f"✅ Follow-up activado.\n\n"
                        f"📬 Si **{to_display}** no responde en **{time_display}**, le envío un recordatorio automáticamente.\n"
                        f"📱 Te aviso por Telegram cuando responda o cuando envíe el follow-up."
                    ),
                    "model_used": "followup",
                    "sources_used": [],
                }
            else:
                return {
                    "response": "No encuentro un email reciente para hacerle seguimiento. Primero envía un email y después configura el follow-up.",
                    "model_used": "followup",
                    "sources_used": [],
                }
        except Exception as e:
            print(f"CHAT: Error configuring follow-up: {e}")
            return {
                "response": f"Error configurando follow-up: {e}",
                "model_used": "error",
                "sources_used": [],
            }

    # Intent: meeting_summary — mostrar última reunión procesada
    if state.get("intent") == "meeting_summary":
        try:
            with sync_engine.connect() as conn:
                row = conn.execute(
                    sql_text("""
                        SELECT event_title, event_date, participants, summary, tasks, decisions, risks, next_meeting
                        FROM meeting_events
                        WHERE empresa_id = :eid
                        {meeting_rbac}
                        ORDER BY created_at DESC LIMIT 1
                    """.format(meeting_rbac=_get_meeting_rbac_clause(empresa_id, user_id))),
                    {**{"eid": empresa_id}, **_get_meeting_rbac_params(empresa_id, user_id)}
                ).fetchone()

            if row:
                from api.services.meeting_intelligence_service import format_meeting_summary
                analysis = {
                    "summary": row.summary,
                    "tasks": json.loads(row.tasks) if isinstance(row.tasks, str) else (row.tasks or []),
                    "decisions": json.loads(row.decisions) if isinstance(row.decisions, str) else (row.decisions or []),
                    "risks": json.loads(row.risks) if isinstance(row.risks, str) else (row.risks or []),
                    "next_meeting": row.next_meeting or "",
                }
                participants = json.loads(row.participants) if isinstance(row.participants, str) else (row.participants or [])
                response = format_meeting_summary(row.event_title, analysis, participants)
                return {"response": response, "model_used": "meeting_intel", "sources_used": []}
            else:
                return {
                    "response": "No tengo reuniones procesadas aún. Cuando termines una reunión en Google Meet, el transcript llegará a tu email y lo proceso automáticamente.",
                    "model_used": "meeting_intel",
                    "sources_used": [],
                }
        except Exception as e:
            print(f"CHAT: Error loading meeting summary: {e}")

    # Intent: meeting_process — procesar transcripción pegada manualmente
    if state.get("intent") == "meeting_process":
        try:
            from api.services.meeting_intelligence_service import (
                parse_transcript, analyze_transcript, save_meeting_event,
                save_meeting_report, format_meeting_summary,
            )

            parsed = parse_transcript(message)
            if parsed["line_count"] < 3:
                return {
                    "response": "No pude detectar una transcripción válida. Pega el texto completo de la transcripción o sube el archivo .txt.",
                    "model_used": "meeting_intel",
                    "sources_used": [],
                }

            analysis = await analyze_transcript(
                transcript=parsed["transcript"],
                attendees=parsed["attendees"],
                event_title="Reunión procesada manualmente",
                empresa_id=empresa_id,
            )

            save_meeting_event(
                empresa_id=empresa_id, user_id=user_id,
                event_title="Reunión procesada manualmente",
                event_date=parsed.get("start_time", ""),
                participants=parsed["attendees"],
                transcript=parsed["transcript"],
                speakers=parsed["speakers"],
                analysis=analysis,
            )

            save_meeting_report(empresa_id, "Reunión procesada manualmente", analysis, parsed["attendees"])

            response = format_meeting_summary("Reunión procesada", analysis, parsed["attendees"])
            return {"response": response, "model_used": "meeting_intel", "sources_used": []}
        except Exception as e:
            print(f"CHAT: Error processing meeting transcript: {e}")

    # Intent: agent_status — mostrar estado de agentes
    if state.get("intent") == "agent_status":
        try:
            from api.services.agent_status_service import format_agent_status_for_brief
            status_text = format_agent_status_for_brief(empresa_id)
            if status_text:
                return {"response": status_text, "model_used": "agent_status", "sources_used": []}
            return {"response": "No hay agentes configurados aun.", "model_used": "agent_status", "sources_used": []}
        except Exception as e:
            print(f"CHAT: Error getting agent status: {e}")

    # Intent: activate_monitor — activar monitoreo de oportunidades
    if state.get("intent") == "activate_monitor":
        try:
            from api.services.agent_status_service import set_agent_active

            model_r, _ = selector.get_model("routing")
            try:
                resp = await model_r.ainvoke([
                    {"role": "system", "content": (
                        "El usuario quiere activar monitoreo de oportunidades. "
                        "Extrae sectores, regiones y frecuencia. JSON:\n"
                        '{"sectors": [], "regions": [], "frequency_hours": 48}\n'
                        "Si no menciona frecuencia, usar 48. Sin markdown."
                    )},
                    {"role": "user", "content": message},
                ])
                raw = (resp.content or "").strip().replace("```json", "").replace("```", "")
                config = json.loads(raw)
            except Exception:
                config = {"sectors": [], "regions": [], "frequency_hours": 48}

            with sync_engine.connect() as conn:
                conn.execute(
                    sql_text("""
                        INSERT INTO prospect_watch_config
                            (empresa_id, user_id, sectors, regions, frequency_hours, is_active)
                        VALUES (:eid, :uid, CAST(:sectors AS jsonb), CAST(:regions AS jsonb), :freq, TRUE)
                        ON CONFLICT ON CONSTRAINT unique_watch_per_user DO UPDATE
                        SET sectors = CAST(:sectors AS jsonb),
                            regions = CAST(:regions AS jsonb),
                            frequency_hours = :freq,
                            is_active = TRUE,
                            deactivated_at = NULL
                    """),
                    {
                        "eid": empresa_id, "uid": user_id,
                        "sectors": json.dumps(config.get("sectors", []), ensure_ascii=False),
                        "regions": json.dumps(config.get("regions", []), ensure_ascii=False),
                        "freq": config.get("frequency_hours", 48),
                    },
                )
                conn.commit()

            set_agent_active(empresa_id, "prospect_scout", True)

            sectors_text = ", ".join(config.get("sectors", [])) or "todos los sectores de tu ICP"
            freq = config.get("frequency_hours", 48)
            freq_text = f"cada {freq} horas" if freq < 48 else f"cada {freq // 24} dias"

            return {
                "response": (
                    f"✅ Monitoreo de oportunidades activado.\n\n"
                    f"🔍 Sectores: {sectors_text}\n"
                    f"⏰ Frecuencia: {freq_text}\n"
                    f"📱 Te aviso por Telegram cuando encuentre algo.\n\n"
                    f"Para desactivar: \"desactiva monitoreo\""
                ),
                "model_used": "monitor",
                "sources_used": [],
            }
        except Exception as e:
            print(f"CHAT: Error activating monitor: {e}")

    # Intent: deactivate_monitor — desactivar monitoreo
    if state.get("intent") == "deactivate_monitor":
        try:
            from api.services.agent_status_service import set_agent_active

            with sync_engine.connect() as conn:
                conn.execute(
                    sql_text("""
                        UPDATE prospect_watch_config
                        SET is_active = FALSE, deactivated_at = NOW()
                        WHERE empresa_id = :eid AND is_active = TRUE
                    """),
                    {"eid": empresa_id}
                )
                conn.commit()

            set_agent_active(empresa_id, "prospect_scout", False)

            return {
                "response": "✅ Monitoreo de oportunidades desactivado.\n\nPara reactivar: \"activa monitoreo de oportunidades\"",
                "model_used": "monitor",
                "sources_used": [],
            }
        except Exception as e:
            print(f"CHAT: Error deactivating monitor: {e}")

    # Intent: onboarding
    if state.get("intent") == "onboarding":
        try:
            from api.agents.onboarding_agent import process_onboarding
            # Resolver nombre para onboarding
            _onb_name = ""
            try:
                with sync_engine.connect() as conn:
                    _onb_row = conn.execute(sql_text("SELECT nombre FROM usuarios WHERE id = :uid"), {"uid": user_id}).fetchone()
                    if _onb_row:
                        _onb_name = _onb_row.nombre or ""
            except Exception:
                pass
            async with AsyncSessionLocal() as db:
                result = await process_onboarding(
                    db=db,
                    empresa_id=empresa_id,
                    user_id=user_id,
                    user_name=_onb_name,
                    user_response=state.get("message", ""),
                    source=state.get("source", "api"),
                )
            return {
                "response": result.get("message", "Iniciemos la configuración de tu empresa."),
                "model_used": "onboarding",
                "sources_used": [],
            }
        except Exception as e:
            print(f"CHAT: Error iniciando onboarding: {e}")
            return {
                "response": "Hubo un error iniciando la configuración. Intenta de nuevo.",
                "model_used": "error",
                "sources_used": [],
            }

    message = state.get("message", "")
    context = state.get("context", "Sin contexto previo.")
    personalized = state.get("personalized", "")

    # Cargar DNA para personalizar system prompt
    empresa_nombre = "la empresa"
    sector = "general"
    company_dna_summary = "Sin perfil de empresa configurado aun."

    if empresa_id:
        try:
            from api.services.dna_loader import load_company_dna
            dna = load_company_dna(empresa_id)
            if dna:
                empresa_nombre = dna.get("company_name") or "la empresa"
                sector = dna.get("industry_type") or "general"
                parts = []
                if dna.get("value_proposition"):
                    parts.append(f"Propuesta de valor: {dna['value_proposition']}")
                if dna.get("business_model"):
                    parts.append(f"Modelo: {dna['business_model']}")
                products = dna.get("main_products")
                if products and isinstance(products, list) and products:
                    parts.append(f"Productos: {', '.join(str(p) for p in products[:5])}")
                services = dna.get("main_services")
                if services and isinstance(services, list) and services:
                    parts.append(f"Servicios: {', '.join(str(s) for s in services[:5])}")
                icp = dna.get("target_icp")
                if icp and isinstance(icp, dict) and icp:
                    parts.append(f"Cliente ideal: {json.dumps(icp, ensure_ascii=False)}")
                if dna.get("brand_voice"):
                    parts.append(f"Voz de marca: {dna['brand_voice']}")
                if parts:
                    company_dna_summary = ". ".join(parts)
                custom_prompt = dna.get("custom_prompt", "")
        except Exception as e:
            print(f"CHAT: Error cargando DNA: {e}")
            custom_prompt = ""
    else:
        custom_prompt = ""

    model, model_name = selector.get_model("chat", state.get("model_preference"))

    system = SYSTEM_PROMPT.format(
        empresa_nombre=empresa_nombre,
        sector=sector,
        company_dna_summary=company_dna_summary,
        context=context,
    )
    if custom_prompt:
        system += f"\n\nINSTRUCCIONES PERSONALIZADAS DE LA EMPRESA:\n{custom_prompt}"
    if personalized:
        system = personalized + "\n\n" + system

    # Resolver nombre real del usuario
    user_real_name = ""
    if empresa_id and user_id:
        try:
            with sync_engine.connect() as conn:
                user_row = conn.execute(
                    sql_text("SELECT nombre FROM usuarios WHERE id = :uid"),
                    {"uid": user_id}
                ).fetchone()
                if user_row:
                    user_real_name = user_row.nombre or ""
        except Exception:
            pass

    if user_real_name:
        if not personalized or user_real_name not in personalized:
            system += f"\n\nEl usuario con el que hablas se llama {user_real_name}. SIEMPRE usa su nombre real, NUNCA un username."

    # Inyectar memorias del usuario
    try:
        from api.services.user_memory_service import load_user_memories
        user_memories_block = load_user_memories(empresa_id, user_id)
        if user_memories_block:
            system += f"\n\n## LO QUE SABES DE ESTE USUARIO\n{user_memories_block}\n\nUsa este conocimiento naturalmente. No menciones que 'recuerdas' — simplemente aplica lo que sabes."
    except Exception as e:
        print(f"CHAT: Error cargando user memories: {e}")

    # Construir mensajes con historial conversacional real
    messages = [{"role": "system", "content": system}]

    history = get_history(empresa_id, user_id) if (empresa_id and user_id) else []
    for msg in history[-8:]:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})

    messages.append({"role": "user", "content": message})

    response = await model.ainvoke(messages)

    return {
        "response": response.content,
        "model_used": model_name,
        "sources_used": state.get("sources_used", []),
    }


async def save_to_memory(state: ChatState) -> dict:
    message = state.get("message", "")
    response = state.get("response", "")
    empresa_id = state.get("empresa_id", "")
    user_id = state.get("user_id", "")

    if message:
        store_memory(f"Usuario: {message}", empresa_id=empresa_id)
    if response:
        store_memory(f"Ada: {response[:1800]}", empresa_id=empresa_id)

    # Persistir historial en PostgreSQL
    source = state.get("source", "api")
    if empresa_id and user_id and message:
        try:
            history = get_history(empresa_id, user_id)
            if message:
                history.append({"role": "user", "content": message, "source": source})
            if response:
                history.append({"role": "assistant", "content": response[:2000], "source": source})
            save_history(empresa_id, user_id, history)
        except Exception as e:
            print(f"CHAT: Error persistiendo historial: {e}")

    # Extraer hechos sobre el usuario (no durante onboarding ni intents de memoria)
    intent = state.get("intent", "")
    if empresa_id and user_id and message and response and intent not in ("onboarding", "explicit_memory", "my_memories"):
        try:
            from api.services.user_memory_service import extract_user_facts
            await extract_user_facts(empresa_id, user_id, message, response)
        except Exception as e:
            print(f"CHAT: Error extrayendo user facts: {e}")

    return {}


graph = StateGraph(ChatState)
graph.add_node("retrieve", retrieve_context)
graph.add_node("generate", generate_response)
graph.add_node("save", save_to_memory)
graph.set_entry_point("retrieve")
graph.add_edge("retrieve", "generate")
graph.add_edge("generate", "save")
graph.add_edge("save", END)
chat_agent = graph.compile()
