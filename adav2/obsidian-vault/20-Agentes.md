---
tags: [agentes, langgraph, ia]
---

# Agentes

Volver a [[00-Inicio]].

## Agentes clave

- Router principal: `../api/agents/router_agent.py`
- Agente principal: `../api/agents/main_agent.py`
- Agente de equipo: `../api/agents/team_agent.py`
- Agentes especializados:
  - `../api/agents/document_agent.py`
  - `../api/agents/excel_agent.py`
  - `../api/agents/email_agent.py`
  - `../api/agents/calendar_agent.py`
  - `../api/agents/image_agent.py`
  - `../api/agents/prospecting_agent.py`

## Relaciones

- Entrada desde API: [[30-Routers-API]]
- Servicios que consumen: [[40-Servicios]]
- Skills que habilitan capacidades: [[50-Skills]]

## Preguntas abiertas

- Como estandarizar trazabilidad entre agentes y servicios.
- Como versionar prompts/estrategias por tenant.
