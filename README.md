# Ada V5.0 — Asistente Agéntica para PYMEs

Plataforma de IA multi-agente para CEOs y equipos ejecutivos de PYMEs latinoamericanas. Orquestación con LangGraph, 16 agentes especializados, Knowledge Graph, y soporte multi-tenant con Google + Microsoft 365.

## Stack

- **Backend:** FastAPI + LangGraph + Python 3.11
- **Base de datos:** PostgreSQL 15 (asyncpg) + Qdrant Cloud (vectores)
- **LLMs:** Gemini Flash (routing, gratis) · Sonnet 4.5 (chat) · Opus 4.6 (análisis) · Qwen-72B (fallback)
- **Infraestructura:** Docker Compose en VPS Contabo · Bot Telegram · Portal Web

## Arquitectura
```
api/main.py              → FastAPI app (CORS, rate limit, lifespan)
api/routers/             → Endpoints HTTP (auth, chat, upload, reports, admin, portal...)
api/agents/              → 16 agentes LangGraph especializados
api/services/            → 30 servicios de lógica de negocio
api/workers/             → Background workers (events, drive, morning brief, alerts)
api/mcp_servers/         → Integraciones MCP (Notion, Plane, M365, Asana)
models/selector.py       → ModelSelector con fallback chains y budget control
bot/telegram_bot.py      → Bot multimodal (texto, voz, imagen, archivos)
portal/index.html        → Portal web SPA
```

## Agentes

| Agente | Función |
|--------|---------|
| chat_agent | RAG multi-fuente, conversación general |
| excel_agent | Análisis de Excel/CSV con industry protocols |
| document_agent | Análisis de PDFs y documentos |
| image_agent | Clasificación y análisis de imágenes (7 protocolos) |
| calendar_agent | CRUD Calendar Google/M365 transparente |
| email_agent | Search/read/draft/send Gmail/Outlook con HITL |
| entity_360_agent | Vista 360 cruzando todos los datos de una entidad |
| consolidation_agent | Consolida múltiples reportes por período |
| briefing_agent | Briefing ejecutivo bajo demanda |
| morning_brief_agent | Briefing automático diario vía Telegram |
| prospect_pro_agent | Perfilamiento de prospectos y clientes nuevos |
| team_agent | Gestión de equipo, roles y permisos |
| notion_agent | CRUD en Notion |
| plane_agent | Gestión de tareas en Plane |
| generic_pm_agent | PM agnóstico (Asana, Monday, Trello, ClickUp, Jira) |
| onboarding_agent | Onboarding de 14 pasos con auto-scraping |

## Inicio rápido

    git clone https://github.com/eosbic/Ada.git
    cd Ada
    cp .env.example .env
    docker-compose up --build

## Deploy (VPS)

    cd /var/ada/ada-langgraph_v2
    git stash && git fetch github && git merge github/main
    docker compose restart
    curl https://backend-ada.duckdns.org/health

## Documentación

- CLAUDE.md — Contexto completo para asistentes de código
- ANALISIS_PROYECTO.md — Análisis técnico del proyecto
- obsidian-vault/ — Vault de Obsidian con documentación navegable
