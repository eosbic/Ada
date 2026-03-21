---
tags: [servicios, negocio, integraciones]
---

# Servicios

Volver a [[00-Inicio]].

## Servicios core

- Runner de agentes: `../api/services/agent_runner.py`
- Gateway IA: `../api/services/ai_gateway.py`
- Orquestador de herramientas: `../api/services/tool_orchestrator.py`
- Memoria: `../api/services/memory_service.py`
- Parser de documentos: `../api/services/document_parser.py`
- Ingestion Drive: `../api/services/drive_ingestion.py`
- Servicio de voz: `../api/services/voice_service.py`
- Servicio de calendario: `../api/services/calendar_service.py`

## Politicas y seguridad

- `../api/services/response_policy.py`
- `../api/services/output_mode_policy.py`
- `../api/services/semantic_firewall.py`
- `../api/services/semantic_tagger.py`

## Relaciones

- Son invocados desde: [[30-Routers-API]]
- Dan soporte a: [[20-Agentes]]
- Se extienden por capacidades de: [[50-Skills]]
