"""
ModelSelector — Selección dinámica de LLM con fallback chains.
Referencia: ADA_MIGRACION_V5_PART1.md §7
"""

import os
from typing import Optional, Tuple
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_anthropic import ChatAnthropic
from langchain_community.chat_models import ChatOpenAI


class ModelSelector:
    """Selector dinámico con fallback chain.

    Prioridad: preferencia del usuario > default por tarea.
    Cache de instancias para no recrear modelos en cada llamada.
    """

    MODEL_CONFIGS = {
        "gemini-flash": {
            "class": ChatGoogleGenerativeAI,
            "params": {
                "model": "gemini-2.0-flash",
                "google_api_key": os.getenv("GEMINI_API_KEY"),
                "temperature": 0.3,
            },
            "cost_input": 0.00,
            "cost_output": 0.00,
        },
        "sonnet": {
            "class": ChatAnthropic,
            "params": {
                "model": "claude-sonnet-4-5-20250929",
                "api_key": os.getenv("ANTHROPIC_API_KEY"),
                "temperature": 0.3,
                "max_tokens": 4096,
            },
            "cost_input": 3.00,
            "cost_output": 15.00,
        },
        "opus": {
            "class": ChatAnthropic,
            "params": {
                "model": "claude-opus-4-6",
                "api_key": os.getenv("ANTHROPIC_API_KEY"),
                "temperature": 0.2,
                "max_tokens": 8192,
            },
            "cost_input": 15.00,
            "cost_output": 75.00,
        },
        "qwen-72b": {
            "class": ChatOpenAI,
            "params": {
                "model": "Qwen/Qwen2.5-72B-Instruct",
                "openai_api_key": os.getenv("OPENROUTER_API_KEY"),
                "openai_api_base": "https://openrouter.ai/api/v1",
                "temperature": 0.3,
                "max_tokens": 8192,
            },
            "cost_input": 0.23,
            "cost_output": 0.90,
        },
    }

    # Modelo default por tarea
    TASK_DEFAULTS = {
        "routing": "gemini-flash",
        "chat": "gemini-flash",
        "chat_with_tools": "sonnet",
        "excel_analysis": "opus",
        "document_analysis": "opus",
        "voice_response": "gemini-flash",
        "alert_evaluation": "gemini-flash",
        "email_draft": "sonnet",
        "prospecting": "sonnet",
    }

    # Si el modelo principal falla, intentar estos en orden
    FALLBACK_CHAIN = {
        "opus": ["qwen-72b", "sonnet"],
        "sonnet": ["gemini-flash", "qwen-72b"],
        "gemini-flash": ["sonnet"],
        "qwen-72b": ["sonnet", "gemini-flash"],
    }

    def __init__(self):
        self._cache = {}

    # Tier de costo por modelo
    COST_TIERS = {
        "gemini-flash": "free",
        "qwen-72b": "low",
        "sonnet": "medium",
        "opus": "high",
    }

    def get_model(self, task: str, user_preference: str = None, budget_override: str = None) -> Tuple:
        """Devuelve (instancia_modelo, nombre_modelo) para una tarea.
        Prioridad: budget_override > user_preference > task default.
        """
        if budget_override and budget_override in self.MODEL_CONFIGS:
            name = budget_override
        elif user_preference and user_preference in self.MODEL_CONFIGS:
            name = user_preference
        else:
            name = self.TASK_DEFAULTS.get(task, "gemini-flash")
        return self._get_instance(name), name

    def _get_instance(self, name: str):
        """Instancia con cache — no recrea el modelo en cada llamada."""
        if name not in self._cache:
            cfg = self.MODEL_CONFIGS.get(name)
            if not cfg:
                raise ValueError(f"Modelo '{name}' no existe en MODEL_CONFIGS")
            self._cache[name] = cfg["class"](**cfg["params"])
        return self._cache[name]

    def get_model_cost_tier(self, model_name: str) -> str:
        """Retorna el tier de costo del modelo: free/low/medium/high."""
        return self.COST_TIERS.get(model_name, "low")

    async def get_with_fallback(self, task: str, user_pref: str = None, budget_override: str = None):
        """Intenta modelo preferido. Si falla, recorre fallback chain."""
        name = budget_override or user_pref or self.TASK_DEFAULTS.get(task, "gemini-flash")
        chain = [name] + self.FALLBACK_CHAIN.get(name, [])

        last_error = None
        for n in chain:
            try:
                model = self._get_instance(n)
                # Test rápido para verificar que el modelo responde
                await model.ainvoke("ping")
                return model, n
            except Exception as e:
                last_error = e
                print(f"Modelo '{n}' falló: {e}. Intentando siguiente...")
                continue

        raise RuntimeError(
            f"Todos los modelos fallaron para '{task}': {last_error}"
        )

    def estimate_cost(
        self, model_name: str, input_tokens: int, output_tokens: int
    ) -> float:
        """Estima costo en USD para una cantidad de tokens."""
        cfg = self.MODEL_CONFIGS.get(model_name, {})
        return (input_tokens / 1e6) * cfg.get("cost_input", 0) + (
            output_tokens / 1e6
        ) * cfg.get("cost_output", 0)


# Instancia global reutilizable
selector = ModelSelector()