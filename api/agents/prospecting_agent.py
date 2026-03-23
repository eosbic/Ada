"""
Prospecting Agent — Perfila prospectos y clientes.
Referencia: ADA_MIGRACION_V5_PART1.md §8.6

Flujo:
1. Busca info del prospecto en memoria (Qdrant)
2. LLM genera perfil + estrategia comercial
"""

import json
from typing import TypedDict, Optional, List
from langgraph.graph import StateGraph, END
from models.selector import selector
from api.services.memory_service import search_memory, store_memory


class ProspectingState(TypedDict, total=False):
    message: str
    empresa_id: str
    user_id: str
    intent: str

    # Internos
    prospect_context: str

    # Output
    response: str
    model_used: str


PROSPECTING_PROMPT = """Eres Ada, asistente ejecutiva especializada en ventas B2B.

El usuario quiere información sobre un prospecto o cliente para preparar
una reunión comercial, hacer seguimiento, o evaluar una oportunidad.

## TU TAREA
1. Analizar la información disponible del prospecto/cliente
2. Generar un PERFIL COMERCIAL accionable
3. Sugerir estrategia de acercamiento

## FORMATO DE RESPUESTA
1. **BLUF**: Conclusión principal sobre el prospecto (1-2 oraciones)
2. **Perfil**: Datos conocidos del prospecto/empresa
3. **Historial**: Interacciones previas si existen
4. **Estrategia**: 3 recomendaciones concretas para el acercamiento
5. **Preguntas clave**: 2-3 preguntas para hacer en la reunión

## REGLAS
- Si no hay datos en el contexto, dilo honestamente
- NUNCA inventes datos del prospecto
- Si hay datos parciales, trabaja con lo que hay
- Enfócate en lo accionable, no en teoría

## CONTEXTO DISPONIBLE
{context}"""


async def search_prospect_info(state: ProspectingState) -> dict:
    """Busca info del prospecto en Qdrant."""
    message = state.get("message", "")
    empresa_id = state.get("empresa_id", "")
    memories = search_memory(message, empresa_id=empresa_id)

    context = "\n".join(memories) if memories else "Sin información previa de este prospecto."

    print(f"PROSPECTING: {len(memories)} memorias encontradas")

    return {"prospect_context": context}


async def generate_prospect_profile(state: ProspectingState) -> dict:
    """Genera perfil comercial con LLM."""
    model, model_name = selector.get_model("prospecting")

    context = state.get("prospect_context", "Sin contexto.")
    prompt = PROSPECTING_PROMPT.format(context=context)

    response = await model.ainvoke([
        {"role": "system", "content": prompt},
        {"role": "user", "content": state["message"]},
    ])

    # Guardar en memoria para futuras consultas
    empresa_id = state.get("empresa_id", "")
    store_memory(f"Prospecting: {state['message']}", empresa_id=empresa_id)
    store_memory(f"Ada perfil: {response.content[:500]}", empresa_id=empresa_id)

    print(f"PROSPECTING: Perfil generado con {model_name}")

    return {
        "response": response.content,
        "model_used": model_name,
    }


# ─── Compilar grafo ──────────────────────────────────────
graph = StateGraph(ProspectingState)
graph.add_node("search", search_prospect_info)
graph.add_node("profile", generate_prospect_profile)
graph.set_entry_point("search")
graph.add_edge("search", "profile")
graph.add_edge("profile", END)
prospecting_agent = graph.compile()