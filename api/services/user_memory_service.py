"""
User Memory Service — Ada aprende de cada usuario.
Extrae hechos, guarda memorias, inyecta contexto personal.
"""

import json
from datetime import datetime
from api.database import sync_engine
from sqlalchemy import text as sql_text


CATEGORY_LABELS = {
    "preference": "Preferencias de comunicación",
    "interest": "Temas que le importan",
    "context": "Contexto actual",
    "pattern": "Patrones de comportamiento",
    "relationship": "Personas y relaciones",
    "style": "Forma de hablar",
    "writing": "Preferencias de escritura",
    "contact": "Preferencias por contacto",
    "general": "General",
}


def load_user_memories(empresa_id: str, user_id: str, limit: int = 20) -> str:
    """Carga memorias del usuario agrupadas por categoría para inyectar en system prompt."""
    if not empresa_id or not user_id:
        return ""

    try:
        with sync_engine.connect() as conn:
            result = conn.execute(
                sql_text("""
                    SELECT fact, category, confidence, times_reinforced
                    FROM user_memories
                    WHERE empresa_id = :eid AND user_id = :uid AND is_active = TRUE
                    ORDER BY times_reinforced DESC, confidence DESC
                    LIMIT :lim
                """),
                {"eid": empresa_id, "uid": user_id, "lim": limit},
            )
            rows = result.fetchall()

        if not rows:
            return ""

        by_category = {}
        for row in rows:
            cat = row.category or "general"
            by_category.setdefault(cat, []).append(row.fact)

        blocks = []
        for cat in ["preference", "interest", "context", "pattern", "relationship", "style", "writing", "contact", "general"]:
            if cat in by_category:
                label = CATEGORY_LABELS.get(cat, cat)
                facts = "\n".join(f"- {f}" for f in by_category[cat])
                blocks.append(f"**{label}:**\n{facts}")

        return "\n\n".join(blocks)

    except Exception as e:
        print(f"USER MEMORY: Error cargando memorias: {e}")
        return ""


def save_memory(empresa_id: str, user_id: str, fact: str, category: str = "general", source: str = "conversation") -> bool:
    """Guarda un hecho sobre el usuario. Deduplica con md5(fact)."""
    if not empresa_id or not user_id or not fact or len(fact.strip()) < 5:
        return False

    try:
        with sync_engine.connect() as conn:
            conn.execute(
                sql_text("""
                    INSERT INTO user_memories (empresa_id, user_id, fact, category, source)
                    VALUES (:eid, :uid, :fact, :cat, :src)
                    ON CONFLICT (user_id, md5(fact))
                    DO UPDATE SET
                        times_reinforced = user_memories.times_reinforced + 1,
                        last_seen_at = NOW(),
                        confidence = LEAST(user_memories.confidence + 0.05, 1.0),
                        is_active = TRUE
                """),
                {"eid": empresa_id, "uid": user_id, "fact": fact.strip(), "cat": category, "src": source},
            )
            conn.commit()
        print(f"USER MEMORY: Guardado [{category}] {fact[:60]}")
        return True
    except Exception as e:
        print(f"USER MEMORY: Error guardando: {e}")
        return False


async def extract_user_facts(empresa_id: str, user_id: str, user_message: str, ada_response: str) -> list:
    """Extrae hechos sobre el usuario de la conversación usando gemini-flash."""
    if not empresa_id or not user_id:
        return []

    msg = (user_message or "").strip()
    if len(msg) < 15:
        return []

    trivial = {"hola", "gracias", "ok", "chao", "bye", "si", "sí", "no", "dale", "listo", "bueno",
               "buenos dias", "buenos días", "buenas tardes", "buenas noches", "hey"}
    if msg.lower() in trivial:
        return []

    try:
        from models.selector import selector
        model, _ = selector.get_model("routing")

        prompt = f"""Analiza este intercambio entre un usuario y Ada (asistente empresarial).
Extrae SOLO hechos sobre el USUARIO COMO PERSONA.

MENSAJE DEL USUARIO:
{user_message[:500]}

RESPUESTA DE ADA:
{ada_response[:500]}

EXTRAER:
- Cómo prefiere comunicarse (horarios, estilo, canal) → category: "preference"
- Qué temas le preocupan personalmente → category: "interest"
- Contexto personal actual (viaje, presentación, deadline) → category: "context"
- Patrones de comportamiento (siempre pregunta X primero) → category: "pattern"
- Relaciones personales ("Claudio es mi amigo", "Orlando es mi proveedor") → category: "relationship"
- Forma de hablar (tutea, formal, usa humor) → category: "style"

NUNCA EXTRAER:
- Datos de la empresa (sector, productos, competidores, clientes ideales)
- Información de reportes o métricas de negocio
- URLs, links o archivos compartidos
- Configuraciones o herramientas que usa la empresa
- Cargos o roles de terceros (ICP, decisores de compra)
- Hechos genéricos ("trabaja en X", "usa Ada", "habla español")
- Duplicados de lo que ya se sabe

Si el mensaje parece parte de configuración, onboarding o setup → responde [].
Si no hay hechos personales claros → responde [].

Responde SOLO JSON array.
Ejemplo: [{{"fact": "Prefiere que le muestren primero las alertas críticas", "category": "preference"}}]"""

        response = await model.ainvoke([
            {"role": "system", "content": "Extrae hechos sobre el usuario. Responde SOLO JSON array."},
            {"role": "user", "content": prompt},
        ])

        raw = (response.content or "").strip().replace("```json", "").replace("```", "")
        facts = json.loads(raw)
        if not isinstance(facts, list):
            return []

        saved = []
        for item in facts[:3]:
            fact = item.get("fact", "").strip()
            category = item.get("category", "general")
            if fact and len(fact) > 5 and category in CATEGORY_LABELS:
                if save_memory(empresa_id, user_id, fact, category, "conversation"):
                    saved.append(fact)

        if saved:
            print(f"USER MEMORY: Extraídos {len(saved)} hechos")
        return saved

    except Exception as e:
        print(f"USER MEMORY: Error extrayendo hechos: {e}")
        return []


async def extract_correction_learnings(empresa_id: str, user_id: str, original_draft: str, edited_version: str, context_info: str = "") -> list:
    """Aprende de las correcciones del usuario a borradores de email."""
    if not empresa_id or not user_id or not original_draft or not edited_version:
        return []

    try:
        from models.selector import selector
        model, _ = selector.get_model("routing")

        prompt = f"""Compara el borrador original de Ada con la versión editada por el usuario.
Extrae qué aprendió Ada sobre las preferencias del usuario.

BORRADOR ORIGINAL:
{original_draft[:1000]}

VERSIÓN EDITADA POR EL USUARIO:
{edited_version[:1000]}

CONTEXTO: {context_info}

Tipos de aprendizaje:
- Cambios de tono (formal → informal, o viceversa) → category: "writing"
- Cambios de tratamiento (Sr. → Ing., usted → tú) → category: "contact"
- Preferencias de formato (más corto, más largo, con/sin saludo) → category: "writing"
- Información sobre relaciones (es mi amigo, es mi proveedor) → category: "relationship"
- Preferencias generales de redacción → category: "writing"

Si el cambio es sobre un contacto específico, incluir el nombre en el hecho.
Ejemplo: {{"fact": "Con Claudio López usar tono informal y tutear", "category": "contact"}}
Ejemplo: {{"fact": "Orlando Rincón es Ingeniero, usar 'Ing.' no 'Sr.'", "category": "contact"}}
Ejemplo: {{"fact": "Prefiere emails cortos sin párrafo de cierre cortés", "category": "writing"}}

Responde SOLO JSON array. Si no hay aprendizajes, responde []."""

        response = await model.ainvoke([
            {"role": "system", "content": "Analiza correcciones de escritura. Responde SOLO JSON array."},
            {"role": "user", "content": prompt},
        ])

        raw = (response.content or "").strip().replace("```json", "").replace("```", "")
        learnings = json.loads(raw)
        if not isinstance(learnings, list):
            return []

        saved = []
        for item in learnings[:3]:
            fact = item.get("fact", "").strip()
            category = item.get("category", "writing")
            if fact and len(fact) > 5 and category in ("writing", "contact", "relationship"):
                if save_memory(empresa_id, user_id, fact, category, "correction"):
                    saved.append(fact)

        if saved:
            print(f"USER MEMORY: Aprendidos {len(saved)} correcciones")
        return saved

    except Exception as e:
        print(f"USER MEMORY: Error extrayendo correcciones: {e}")
        return []


def get_all_memories(empresa_id: str, user_id: str) -> list:
    """Retorna todas las memorias activas de un usuario."""
    try:
        with sync_engine.connect() as conn:
            result = conn.execute(
                sql_text("""
                    SELECT id, fact, category, confidence, source,
                           times_reinforced, last_seen_at, created_at
                    FROM user_memories
                    WHERE empresa_id = :eid AND user_id = :uid AND is_active = TRUE
                    ORDER BY times_reinforced DESC, created_at DESC
                """),
                {"eid": empresa_id, "uid": user_id},
            )
            rows = result.fetchall()

        return [
            {
                "id": str(r.id),
                "fact": r.fact,
                "category": r.category,
                "confidence": float(r.confidence) if r.confidence else 0.8,
                "source": r.source,
                "times_reinforced": r.times_reinforced,
                "last_seen_at": str(r.last_seen_at)[:16] if r.last_seen_at else None,
                "created_at": str(r.created_at)[:16] if r.created_at else None,
            }
            for r in rows
        ]
    except Exception as e:
        print(f"USER MEMORY: Error listando memorias: {e}")
        return []


def deactivate_memory(memory_id: str) -> bool:
    """Desactiva una memoria."""
    try:
        with sync_engine.connect() as conn:
            conn.execute(
                sql_text("UPDATE user_memories SET is_active = FALSE WHERE id = :id"),
                {"id": memory_id},
            )
            conn.commit()
        return True
    except Exception as e:
        print(f"USER MEMORY: Error desactivando: {e}")
        return False


def get_contact_preferences(empresa_id: str, user_id: str, contact_name: str) -> str:
    """Busca preferencias guardadas para un contacto específico."""
    if not empresa_id or not user_id or not contact_name:
        return ""

    try:
        # Extraer nombre significativo del email o nombre
        name_parts = contact_name.replace("@", " ").replace(".", " ").split()
        search_names = [p for p in name_parts if len(p) > 2 and not p.isdigit()]

        if not search_names:
            return ""

        with sync_engine.connect() as conn:
            all_prefs = []
            for name in search_names[:3]:
                result = conn.execute(
                    sql_text("""
                        SELECT fact FROM user_memories
                        WHERE user_id = :uid AND category = 'contact'
                        AND is_active = TRUE AND fact ILIKE :pattern
                        ORDER BY times_reinforced DESC
                        LIMIT 5
                    """),
                    {"uid": user_id, "pattern": f"%{name}%"},
                )
                rows = result.fetchall()
                all_prefs.extend([r.fact for r in rows])

            # También cargar preferencias generales de escritura
            result = conn.execute(
                sql_text("""
                    SELECT fact FROM user_memories
                    WHERE user_id = :uid AND category = 'writing'
                    AND is_active = TRUE
                    ORDER BY times_reinforced DESC
                    LIMIT 5
                """),
                {"uid": user_id},
            )
            writing_prefs = [r.fact for r in result.fetchall()]

        parts = []
        if all_prefs:
            parts.append("Preferencias para este contacto:\n" + "\n".join(f"- {p}" for p in all_prefs))
        if writing_prefs:
            parts.append("Preferencias generales de escritura:\n" + "\n".join(f"- {p}" for p in writing_prefs))

        return "\n\n".join(parts)

    except Exception as e:
        print(f"USER MEMORY: Error buscando preferencias de contacto: {e}")
        return ""
