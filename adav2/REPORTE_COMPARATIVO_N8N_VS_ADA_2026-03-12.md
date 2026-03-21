# Reporte Comparativo: Flujo n8n (`guiacompleto.docx`) vs Implementacion Actual

Fecha: 2026-03-12  
Proyecto evaluado: `ada-langgraph-main`

## 1. Resumen ejecutivo

La implementacion actual **ya cubre la mayor parte del flujo central de n8n**: entrada multimodal, seguridad pre-agente, enrutamiento por tipo de archivo, uso de Qdrant, integraciones operativas (Gmail/Calendar/Notion/Plane), ingesta desde Google Drive y salida multimodal.

Estado global:

- **Cumplido:** 8/12
- **Parcial:** 4/12
- **Pendiente total:** 0/12 (no hay bloqueos estructurales, pero si brechas para equivalencia estricta)

La principal diferencia restante no es de "existencia de componentes", sino de **rigidez de politica transversal** (forzado estricto en todas las rutas, no solo en `chat`).

---

## 2. Matriz de cumplimiento (12 elementos)

## Nivel 1 - Critico para igualar n8n

1. Firewall semantico pre-agente  
Estado: **Cumplido**  
Evidencia: `api/services/agent_runner.py`, `api/services/semantic_firewall.py`.

2. Protocolo multi-fuente obligatorio con trazabilidad  
Estado: **Parcial**  
Evidencia: `api/services/tool_orchestrator.py`, `api/services/response_policy.py`, `api/agents/chat_agent.py`.  
Observacion: existe consulta multi-fuente y trazabilidad, pero el uso de herramientas externas (Notion/Gmail/Calendar/Plane) es **contextual por heuristica**, no forzado siempre como contrato duro en todas las consultas de conocimiento.

3. Consulta dual obligatoria a Qdrant antes de responder "no encontre"  
Estado: **Cumplido**  
Evidencia: `tool_orchestrator` (doble consulta) + refuerzo en `agent_runner` para respuestas de ausencia.

4. Reglas secuenciales duras para Calendar  
Estado: **Cumplido**  
Evidencia: `api/agents/calendar_agent.py` (create: availability->create; update/delete: search->action; validacion ISO 8601).

5. Ruta de imagenes con vision + Qdrant  
Estado: **Cumplido**  
Evidencia: `api/routers/upload.py`, `api/agents/image_agent.py`, `api/services/memory_service.py`.

## Nivel 2 - Operacional fuerte

6. Ingesta automatica desde Google Drive  
Estado: **Cumplido**  
Evidencia: `api/workers/drive_worker.py`, `api/services/drive_ingestion.py`.

7. Tagging semantico enriquecido para RAG  
Estado: **Cumplido**  
Evidencia: `api/services/semantic_tagger.py`, `document_agent`, `excel_agent`, `image_agent`.

8. Integracion explicita del flujo Excel especializado  
Estado: **Cumplido**  
Evidencia: `api/agents/excel_agent.py` (pipeline dedicado multi-nodo), `api/routers/upload.py`.

9. Decision centralizada de salida texto/voz  
Estado: **Cumplido**  
Evidencia: `api/services/output_mode_policy.py`, `api/services/agent_runner.py`, `bot/telegram_bot.py`.

## Nivel 3 - Pulido ejecutivo

10. Formato BLUF y confianza condicional como politica global  
Estado: **Parcial**  
Evidencia: `api/services/response_policy.py`.  
Observacion: la confianza condicional si existe. El formato ejecutivo existe, pero el BLUF no esta forzado de forma estricta/visible en todas las respuestas (se suavizo el prefijo por UX).

11. Consolidacion de fuente primaria/secundaria en todas las respuestas de datos  
Estado: **Parcial**  
Evidencia: `response_policy` se aplica en `run_agent` (`/chat/chat`).  
Observacion: rutas que no pasan por `run_agent` (ej. `/files/upload`) pueden devolver salidas sin bloque canonico uniforme de evidencia.

12. Menos routing por agente y mas orquestacion con herramientas para consultas cruzadas  
Estado: **Parcial**  
Evidencia: `agent_runner` + `tool_orchestrator` ya hacen orquestacion previa.  
Observacion: el patron principal sigue siendo `router -> agente especializado`; la orquestacion cross-source existe, pero no domina todas las rutas como "tool-calling central" puro.

---

## 3. Brechas funcionales reales (impacto)

1. **Politica multi-fuente no totalmente dura en todos los casos**  
Actualmente el orquestador usa heuristicas de intencion para llamar herramientas externas. En n8n el contrato es mas estricto para ciertos tipos de consulta.

2. **Contrato de salida de evidencia no uniforme en todas las rutas**  
`/chat/chat` es consistente; `/files/upload` y respuestas de agentes de archivo pueden no salir con el mismo bloque final canonico.

3. **BLUF como politica transversal fuerte esta debilitado por UX**  
Se conserva estilo ejecutivo, pero no hay enforcement estricto de "conclusion primero" en todas las respuestas.

4. **Orquestacion central aun hibrida (router + agentes)**  
No es un blocker, pero para igualdad estricta con el n8n descrito, faltaria reforzar modo "agente central tool-calling" para mas escenarios.

---

## 4. Lista corta de pendientes (de mas importante a menos importante)

1. **Forzar politica multi-fuente estricta por tipo de consulta** (no solo heuristica).  
2. **Aplicar el mismo contrato de trazabilidad a `/files/upload` y salidas de agentes de archivo**.  
3. **Reforzar BLUF estructural sin prefijo visible** (conclusion ejecutiva obligatoria en primer bloque).  
4. **Expandir modo de orquestacion central con tool-calling obligatorio** para consultas que exijan cruce entre Notion/Gmail/Calendar/Qdrant.

---

## 5. Conclusión

La base funcional ya esta muy cerca del flujo n8n descrito.  
No hay faltantes criticos de arquitectura; lo que falta para paridad estricta es **endurecer politicas transversales** (multi-fuente, trazabilidad uniforme, BLUF estructural y mayor centralizacion de tool-calling).

