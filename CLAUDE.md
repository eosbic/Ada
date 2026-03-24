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
api/workers/                             → Background workers (event, drive, morning_brief, alert)
api/services/kg_pipeline.py              → Knowledge Graph pipeline reutilizable
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

## Entity 360° — Vista en tiempo real
Cuando un agente consulta datos externos (emails, calendario, tareas, Notion), guarda un mini-reporte en `ada_reports` con `report_type` especifico: `email_summary`, `calendar_event_summary`, `pm_task_summary`, `notion_summary`. El KG pipeline existente (`auto_tag` → `extract_entities` → `weave_links`) conecta estos rastros con los reportes de analisis automaticamente. Zero tablas nuevas.

`trail_service.py` centraliza la logica de "dejar rastro". Funciones: `leave_email_trail`, `leave_calendar_trail`, `leave_pm_trail`, `leave_notion_trail`.

**Vista 360°:** `graph_navigator.get_entity_360()` busca una entidad en TODOS los `report_types` de `ada_reports`. `tool_orchestrator` la inyecta automaticamente cuando detecta nombres propios en el query del usuario.

**API:** `GET /api/v1/entities/{name}/360?empresa_id=yyy`

**Agentes que dejan rastro:** `briefing_agent` (calendar+email+notion), `morning_brief_agent` (calendar+email+tasks), `plane_agent` (tasks), `notion_agent` (searches+queries), `generic_pm_agent` (tasks).

## Company DNA
`ada_company_profile` extendida con campos DNA: `mission`, `vision`, `value_proposition`, `business_model`, `brand_voice`, `target_icp`, `product_catalog`, `agent_configs`, `website_url`, `website_summary`, `social_urls`, `sales_cycle_days`, `success_cases`, `logo_url`, `brand_colors`, `productivity_suite`, `pm_tool`, `extra_apps`, `onboarding_complete`.

`dna_loader.py` es el servicio central — TODO agente usa `load_company_dna(empresa_id)` para cargar contexto. `dna_generator.py` genera `agent_configs` automaticamente con Gemini Flash basandose en el DNA.

`context_builder.py` enriquecido: inyecta mision, vision, propuesta de valor, modelo de negocio, ICP y voz de marca en cada system prompt.

`tenant_app_config` — Tracking de que provider usa cada empresa por servicio (email, calendar, drive, pm).

### Endpoints DNA
- `GET /config/dna/{empresa_id}` — DNA completo
- `POST /config/dna/update` — Actualizar campos
- `POST /config/dna/generate-configs` — Generar agent_configs
- `POST /config/dna/analyze-web` — Scrapear y analizar sitio web
- `POST /config/dna/analyze-competitors` — Analizar competidores
- `POST /config/apps/setup` — Configurar providers por servicio

### Industry Protocols
`industry_protocols.py` — 15 protocolos de industria: construccion, retail, salud, agricultura, servicios, tecnologia, educacion, alimentos, transporte, inmobiliario, financiero, consultoria, restaurante, manufactura, generic.

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
- `ada_company_profile` — perfil de empresa + Company DNA (mission, vision, agent_configs, etc.)
- `tenant_app_config` — provider por servicio por empresa (email→google, pm→asana, etc.)
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
- `graph_navigator.py` — Traversal 1-hop bidireccional por `report_links` + vista 360° por entidad

## Services clave
- `provider_router.py` — Google vs M365 por tenant
- `budget_service.py` — control presupuesto
- `context_builder.py`
- `tool_orchestrator.py` — dual-repo Qdrant
- `memory_service.py` — RAG
- `artifact_service.py` — PDFs
- `chart_service.py`
- `industry_protocols.py`
- `kg_pipeline.py` — Helper reutilizable: `run_kg_pipeline(report_id, empresa_id, content, alerts)`. Threading aislado.
- `trail_service.py` — Guarda rastros de datos externos en `ada_reports` + ejecuta KG pipeline.
- `dna_loader.py` — Servicio central para cargar Company DNA de `ada_company_profile`.
- `dna_generator.py` — Genera `agent_configs` con Gemini Flash + analiza web/competidores.
- `rbac_service.py` — RBAC enforcement: mapeo permissions → report_types + agentes. Filtro SQL + bloqueo de agentes.

## Workers (en `api/workers/`)
- `event_worker` — Procesa eventos async
- `drive_worker` — Ingesta automática Google Drive / OneDrive
- `morning_brief_worker` — Cron diario (`MORNING_BRIEF_HOUR`, default 7am Colombia). Envía briefing por Telegram a admins.
- `alert_worker` — Cron cada 5min (`ALERT_CHECK_INTERVAL_SECONDS`). Evalúa `ada_reports` con `requires_action=TRUE`.

### Variables `.env` para workers
- `ENABLE_MORNING_BRIEF` (default `"false"`)
- `MORNING_BRIEF_HOUR` (default `"7"`)
- `ENABLE_ALERT_WORKER` (default `"false"`)
- `ALERT_CHECK_INTERVAL_SECONDS` (default `"300"`)

## PROBLEMAS CONOCIDOS — NO IGNORAR
1. Knowledge Graph: pipeline conectado en excel, document, prospect, briefing y consolidation agents. Falta: `chat_agent` (no produce reportes), `morning_brief_agent` (consume pero no produce datos persistentes).
2. `budget_limits` verificación parcial
3. M365 sync wrappers usan `asyncio.run()` — funciona pero no ideal en async context
4. `provider_router` cache in-memory, se limpia en redeploy
5. `notion_agent.py` y `plane_agent.py` son agentes dedicados legacy; `generic_pm_agent` los complementa para nuevos PM tools

## SEGURIDAD — REGLAS ABSOLUTAS
- `JWT_SECRET_KEY` en `.env` nunca hardcodeada
- Endpoints protegidos con `Depends(get_current_user)`
- CORS restringido a `ALLOWED_ORIGINS`
- `empresa_id` SIEMPRE del JWT, nunca del body
- Fernet AES-128 para credenciales en reposo
- Semantic Firewall antes de cada agente
- **RBAC enforcement real:** `rbac_service.py` mapea `permissions` de `team_members` a `report_types` y agentes permitidos. `search_reports` filtra por `report_type` segun permisos del usuario. `agent_runner` bloquea agentes no autorizados antes de ejecutar. `upload` verifica `can_upload_files`. Admin tiene acceso total siempre. `context_builder.py` inyecta permisos al prompt como segunda capa.

## Testing
No hay tests automatizados. Testear manualmente:
- `curl` a `/auth/login`
- M365: `GET /oauth/microsoft/connect/microsoft365/{empresa_id}`
- Status: `GET /oauth/status/{empresa_id}`
