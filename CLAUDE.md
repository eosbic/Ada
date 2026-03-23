# CLAUDE.md — Contexto para Claude Code

## Proyecto
Ada V5.1 — Asistente ejecutivo de IA para CEOs de PYMEs latinoamericanas.

## Stack
- FastAPI + LangGraph >=0.3 + Python 3.11
- PostgreSQL 15 (asyncpg) + Qdrant Cloud
- Gemini Flash (routing, gratis) / Sonnet 4.5 (chat) / Opus 4.6 (excel) / Qwen-72B (fallback)
- Docker Compose en VPS Contabo (Alemania) | Portal React en Netlify | Bot Telegram

## Comandos
```bash
docker-compose up --build              # levantar todo
python -m bot.telegram_bot             # bot standalone
uvicorn api.main:app --reload --port 8000  # API local
python -m scripts.backfill_tags_links  # backfill Knowledge Graph
```

## Arquitectura principal
```
api/main.py                              → FastAPI app (CORS, rate limit, startup)
api/routers/                             → Endpoints HTTP
api/agents/                              → Agentes LangGraph (16 agentes)
api/services/                            → Lógica de negocio y servicios
api/services/agent_runner.py             → Orquestador: Router → Agente
api/services/provider_router.py          → Decide Google vs Microsoft por tenant
api/workers/                             → Background workers
api/mcp_servers/mcp_host.py              → Orquestador MCP (Notion, Plane, M365)
api/mcp_servers/mcp_microsoft365_server.py → Microsoft Graph API
models/selector.py                       → ModelSelector con fallback chains
bot/telegram_bot.py                      → Bot multimodal
```

## Multi-Provider Architecture (Google + Microsoft 365)
Los agentes (`calendar_agent`, `email_agent`) llaman a los services (`calendar_service`, `gmail_service`) que son provider-aware. Los services consultan `provider_router` que lee `tenant_credentials` y enruta a Google APIs (directo) o Microsoft Graph (via MCP server).

**Regla clave:** Los agentes NUNCA saben qué provider usan.

### Providers por servicio en `tenant_credentials`

| Servicio   | Provider Google    | Provider Microsoft  |
|------------|--------------------|---------------------|
| Calendar   | `google_calendar`  | `outlook_calendar`  |
| Email      | `gmail`            | `outlook_email`     |
| Drive      | `google_drive`     | `onedrive`          |

### OAuth Endpoints
- **Google:** `GET /oauth/connect/{service}/{empresa_id}`
- **Microsoft:** `GET /oauth/microsoft/connect/{service}/{empresa_id}`
- **Status:** `GET /oauth/status/{empresa_id}` — incluye ambos providers

### Variables `.env` requeridas para M365
- `MICROSOFT_CLIENT_ID`
- `MICROSOFT_CLIENT_SECRET`
- `MICROSOFT_TENANT_ID` (default `"common"`)

## Generic PM Architecture
`notion_agent` y `plane_agent` siguen siendo agentes dedicados con tools propias. `generic_pm_agent` cubre Asana, Monday, Trello, ClickUp y Jira vía la interfaz `mcp_pm_base.PMServerBase`.

4 tools estándar: `pm_list_projects`, `pm_list_tasks`, `pm_create_task`, `pm_update_task`. Todos retornan el mismo formato normalizado (estados: pending/in_progress/done, prioridades: urgent/high/medium/low/none).

`agent_runner._resolve_pm_agent()` resuelve automáticamente qué agente PM usar según credenciales de la empresa: si tiene Plane → `project_agent`, si tiene Notion → `notion_agent`, si tiene un PM genérico → `generic_pm_agent`.

**Para agregar un nuevo PM tool:**
1. Crear `api/mcp_servers/mcp_xxx_server.py` que extienda `PMServerBase`
2. Registrar en `mcp_host.MCP_SERVERS` con `category="generic_pm"`
3. Agregar provider name a `/connect-service` en `oauth.py` y a `_resolve_pm_agent` en `agent_runner.py`

## Convenciones
- Async everywhere (excepto `upload.py` por bug uvloop)
- NUNCA hardcodear API keys — todo en `.env`
- Type hints obligatorios en funciones públicas
- Docstrings en español
- Anti-alucinación con tags `[WEB]`/`[PROPORCIONADO]`/`[INFERIDO]`
- HITL para email y calendario

## Base de datos
- `empresas` — tenants principales
- `usuarios` — users por empresa (con `telegram_id`)
- `ada_reports` — reportes (markdown + `metrics_summary` JSONB + `search_vector` tsvector)
- `report_links` — Knowledge Graph edges
- `tenant_credentials` — OAuth2 cifrado Fernet (Google + Microsoft + Notion + Plane)
- `budget_limits` — presupuesto mensual por empresa
- `token_usage_log` — log granular de consumo de tokens
- `ada_company_profile` — perfil de empresa (onboarding)
- `team_members` — permisos por usuario

## Agentes (AGENT_REGISTRY en agent_runner.py)
- `chat_agent` — RAG multi-fuente
- `excel_analyst` / `excel_agent` — Pipeline 8 nodos con `industry_protocols`
- `calendar_agent` — CRUD Calendar Google/M365 transparente
- `email_agent` — search/read/draft/send Gmail/Outlook transparente con HITL
- `prospecting_agent` / `prospect_pro_agent`
- `team_agent`
- `notion_agent`
- `project_agent` / `plane_agent`
- `generic_pm_agent` — PM agnóstico (Asana, Monday, Trello, ClickUp, Jira) via `mcp_pm_base`
- `briefing_agent`
- `morning_brief_agent`
- `consolidation_agent`
- `image_analyst` / `image_agent`
- `document_agent`
- `onboarding_agent`
- `alert_agent`

## MCP Servers en `mcp_host.py`
- `notion` — CRUD Notion (category: project_management, agente dedicado)
- `plane` — CRUD Plane (category: project_management, agente dedicado)
- `microsoft365` — Calendar + Email + Drive via Microsoft Graph (category: productivity)
- `asana` — PM genérico via Asana REST API (category: generic_pm, usa `mcp_pm_base`)

## Knowledge Graph (en `api/services/`)
- `entity_extractor.py` — Gemini Flash extrae clientes/productos/personas
- `link_weaver.py` — Crea edges bidireccionales, clasifica tipo de enlace
- `auto_tagger.py` — Tags semánticos con taxonomía controlada (17 categorías)
- `graph_navigator.py` — Traversal 1-hop bidireccional por `report_links`

## Services clave
- `provider_router.py` — Google vs M365 por tenant
- `budget_service.py` — control presupuesto
- `context_builder.py`
- `tool_orchestrator.py` — dual-repo Qdrant
- `memory_service.py` — RAG
- `artifact_service.py` — PDFs
- `chart_service.py`
- `industry_protocols.py`

## PROBLEMAS CONOCIDOS — NO IGNORAR
1. `adav2/` es copia legacy, **NO modificar**
2. Knowledge Graph: `entity_extractor` y `link_weaver` no corren en flujo normal
3. `budget_limits` verificación parcial
4. M365 sync wrappers usan `asyncio.run()` — funciona pero no ideal en async context
5. `provider_router` cache in-memory, se limpia en redeploy
6. `notion_agent.py` y `plane_agent.py` son agentes dedicados legacy; `generic_pm_agent` los complementa para nuevos PM tools

## SEGURIDAD — REGLAS ABSOLUTAS
- `JWT_SECRET_KEY` en `.env` nunca hardcodeada
- Endpoints protegidos con `Depends(get_current_user)`
- CORS restringido a `ALLOWED_ORIGINS`
- `empresa_id` SIEMPRE del JWT, nunca del body
- Fernet AES-128 para credenciales en reposo
- Semantic Firewall antes de cada agente

## Testing
No hay tests automatizados. Testear manualmente:
- `curl` a `/auth/login`
- M365: `GET /oauth/microsoft/connect/microsoft365/{empresa_id}`
- Status: `GET /oauth/status/{empresa_id}`
