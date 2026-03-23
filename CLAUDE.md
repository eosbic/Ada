# CLAUDE.md — Contexto para Claude Code

## Proyecto
Ada V5.0 — Asistente ejecutivo de IA para CEOs de PYMEs latinoamericanas.

## Stack
- FastAPI + LangGraph >=0.3 + Python 3.11
- PostgreSQL 15 (asyncpg) + Qdrant Cloud
- Gemini Flash (routing, gratis) / Sonnet 4.5 (chat) / Opus 4.6 (excel) / Qwen-72B (fallback)
- Docker Compose en VPS Contabo (Alemania) | Portal React en Netlify | Bot Telegram

## Comandos
- `docker-compose up --build` — levantar todo
- `python -m bot.telegram_bot` — bot standalone
- `uvicorn api.main:app --reload --port 8000` — API local
- `python -m scripts.backfill_tags_links` — backfill Knowledge Graph (una vez)

## Arquitectura
```
api/main.py                         → FastAPI app (CORS, rate limit, startup)
api/routers/                        → Endpoints HTTP
api/agents/                         → Agentes LangGraph (13 agentes)
api/services/                       → Lógica de negocio y servicios
api/services/agent_runner.py        → Orquestador: Router → Agente
api/workers/                        → Background workers
models/selector.py                  → ModelSelector con fallback chains
bot/telegram_bot.py                 → Bot multimodal
```

## Convenciones
- Async everywhere (excepto upload.py que usa .invoke() por bug uvloop)
- NUNCA hardcodear API keys — todo va en .env via os.getenv()
- Type hints obligatorios en funciones públicas
- Docstrings en español
- Anti-alucinación: [WEB]/[PROPORCIONADO]/[INFERIDO] en respuestas
- HITL para email y calendario (aprobación del usuario antes de enviar/agendar)

## Base de datos
- `empresas` — tenants principales
- `usuarios` — users por empresa (con telegram_id)
- `ada_reports` — reportes de análisis (markdown + metrics_summary JSONB + tags TEXT[] + search_vector tsvector)
- `report_links` — Knowledge Graph edges (source_report_id → target_report_id + link_type)
- `tenant_credentials` — OAuth2 cifrado con Fernet
- `budget_limits` — presupuesto mensual por empresa
- `token_usage_log` — log granular de consumo de tokens (nuevo)
- `ada_company_profile` — perfil de empresa (onboarding)
- `team_members` — permisos por usuario

## Agentes (AGENT_REGISTRY en agent_runner.py)
- `chat_agent` — RAG multi-fuente + historial
- `excel_analyst` → excel_agent — Pipeline 8 nodos con industry_protocols
- `calendar_agent` — CRUD Google Calendar
- `email_agent` — Gmail search/read/draft/send (HITL)
- `prospecting_agent` → prospect_pro_agent — Web scraping + perfil comercial
- `team_agent` — Gestión de equipo
- `notion_agent` — Notion via MCP
- `project_agent` → plane_agent — Plane via MCP
- `briefing_agent` — Briefing proactivo post-análisis
- `morning_brief_agent` — Resumen matutino
- `consolidation_agent` — Consolidación multi-reporte (NUEVO, pendiente integrar)

## Knowledge Graph (4 servicios en adav2/, pendiente migrar a api/)
- `entity_extractor.py` — Gemini Flash extrae clientes/productos/personas
- `link_weaver.py` — Crea edges bidireccionales, clasifica tipo de enlace
- `auto_tagger.py` — Tags semánticos con taxonomía controlada (17 categorías)
- `graph_navigator.py` — Traversal 1-hop bidireccional por report_links

## PROBLEMAS CONOCIDOS — NO IGNORAR
1. `adav2/` tiene 6 servicios que NO existen en `api/` — migrarlos
2. `upload.py` usa .invoke() (sync) — migrar a .ainvoke()
3. `_CONVERSATION_HISTORY` en RAM — persistir en PostgreSQL
4. `_PENDING_APPROVALS` en RAM — persistir en PostgreSQL
5. Knowledge Graph: entity_extractor y link_weaver no se ejecutan en el flujo normal
6. budget_limits existe en DB pero nadie verifica antes de llamar al LLM
7. pg_trgm: SQL existe pero no se verificó si se ejecutó
8. trigger_briefing usa asyncio.new_event_loop() que puede fallar con uvloop

## SEGURIDAD — REGLAS ABSOLUTAS
- JWT_SECRET_KEY DEBE estar en .env, nunca hardcodeada
- Todos los endpoints /chat, /upload deben usar Depends(get_current_user)
- CORS restringido a ALLOWED_ORIGINS
- empresa_id SIEMPRE del JWT, nunca del body del request
- Fernet AES-128 para credenciales en reposo
- Semantic Firewall antes de cada agente

## Testing
No hay tests automatizados (pendiente). Testear manualmente:
- `curl -X POST http://localhost:8000/auth/login -d '{"email":"...", "password":"..."}'`
- Usar el JWT retornado en headers: `Authorization: Bearer {token}`
