import os
from typing import TypedDict

from langgraph.graph import StateGraph, END
from langchain_google_genai import ChatGoogleGenerativeAI

from api.services.memory_service import search_memory, store_memory


model = ChatGoogleGenerativeAI(
    model="gemini-2.0-flash",
    google_api_key=os.getenv("GEMINI_API_KEY")
)


class AgentState(TypedDict, total=False):

    message: str
    empresa_id: str
    response: str
    context: str


def call_model(state: AgentState):

    message = state.get("message")

    if not message:
        return {"response": "No message provided"}

    empresa_id = state.get("empresa_id", "")
    memories = search_memory(message, empresa_id=empresa_id)
    print(f"MEMORIA ENCONTRADA ({len(memories)} resultados):", memories)

    context = "\n".join(memories) if memories else "Sin contexto previo."

    prompt = f"""
Contexto previo:
{context}

Usuario:
{message}
"""
    print("PROMPT ENVIADO:", prompt[:200])

    response = model.invoke(prompt)

    store_memory(f"Usuario: {message}", empresa_id=empresa_id)
    store_memory(f"Ada: {response.content}", empresa_id=empresa_id)

    return {
        "response": response.content
    }

graph = StateGraph(AgentState)

graph.add_node("llm", call_model)

graph.set_entry_point("llm")

graph.add_edge("llm", END)

agent = graph.compile()