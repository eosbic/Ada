"""
Agent Runner - orquesta Firewall -> Router -> Tool Orchestrator -> Agente.
"""

import re

from api.agents.excel_agent import excel_agent
from api.agents.router_agent import router_agent
from api.agents.chat_agent import chat_agent
from api.agents.email_agent import email_agent
from api.agents.calendar_agent import calendar_agent
from api.agents.team_agent import team_agent
from api.agents.notion_agent import notion_agent
from api.agents.plane_agent import plane_agent
from api.agents.briefing_agent import briefing_agent
from api.agents.morning_brief_agent import morning_brief_agent
from api.agents.prospect_pro_agent import prospect_pro_agent
from api.agents.image_agent import image_agent
from api.agents.consolidation_agent import consolidation_agent
from api.agents.generic_pm_agent import generic_pm_agent
from api.agents.entity_360_agent import entity_360_agent

from api.services.budget_service import check_budget, get_model_for_plan, log_usage, check_analyses, log_analysis
from api.services.semantic_firewall import evaluate_semantic_firewall
from api.services.tool_orchestrator import collect_multi_source_context
from api.services.response_policy import enforce_response_contract
from api.services.artifact_service import wants_pdf, generate_pdf_from_text
from api.services.chart_service import wants_chart, generate_chart_from_text
from api.services.output_mode_policy import decide_output_mode
from api.services.memory_service import search_reports_qdrant, search_vector_store1
from models.selector import selector


AGENT_TASK_MAP = {
    "chat_agent": "chat",
    "excel_analyst": "excel_analysis",
    "image_analyst": "document_analysis",
    "calendar_agent": "chat_with_tools",
    "email_agent": "email_draft",
    "prospecting_agent": "prospecting",
    "team_agent": "chat",
    "notion_agent": "chat_with_tools",
    "project_agent": "chat_with_tools",
    "briefing_agent": "alert_evaluation",
    "morning_brief_agent": "alert_evaluation",
    "consolidation_agent": "excel_analysis",
    "generic_pm_agent": "chat_with_tools",
    "entity_360_agent": "chat",
}


AGENT_REGISTRY = {
    "chat_agent": chat_agent,
    "excel_analyst": excel_agent,
    "image_analyst": image_agent,
    "calendar_agent": calendar_agent,
    "email_agent": email_agent,
    "prospecting_agent": prospect_pro_agent,
    "team_agent": team_agent,
    "notion_agent": notion_agent,
    "project_agent": plane_agent,
    "briefing_agent": briefing_agent,
    "morning_brief_agent": morning_brief_agent,
    "consolidation_agent": consolidation_agent,
    "generic_pm_agent": generic_pm_agent,
    "entity_360_agent": entity_360_agent,
}

DEFAULT_AGENT = "chat_agent"
_LAST_CHART_BY_USER: dict[str, dict] = {}


def _response_suggests_manual_pdf(text: str) -> bool:
    body = (text or "").lower()
    markers = [
        "copiar este texto",
        "procesador de textos",
        "guardarlo o exportarlo como pdf",
        "exportarlo como pdf",
        "word o google docs",
    ]
    return any(m in body for m in markers)


def _build_pdf_title(intent: str, message: str) -> str:
    safe_intent = (intent or "reporte").strip().lower()
    first_part = re.sub(r"[^a-zA-Z0-9 ]+", " ", (message or "").strip())[:48].strip()
    if not first_part:
        first_part = "reporte"
    return f"Ada {safe_intent} - {first_part}"


def _build_chart_title(intent: str, message: str) -> str:
    safe_intent = (intent or "analisis").strip().lower()
    first_part = re.sub(r"[^a-zA-Z0-9 ]+", " ", (message or "").strip())[:42].strip()
    if not first_part:
        first_part = "estadisticas"
    return f"Grafico {safe_intent} - {first_part}"


def _chart_user_key(empresa_id: str | None, user_id: str | None) -> str:
    return f"{empresa_id or 'no_empresa'}::{user_id or 'no_user'}"


def _align_response_with_artifacts(text: str, has_chart: bool, has_pdf: bool) -> str:
    body = (text or "").strip()
    if not body:
        return body

    if has_chart:
        body = re.sub(r"(?im)^.*no puedo.*gr[aá]fico.*$\n?", "", body)
    if has_pdf:
        body = re.sub(r"(?im)^.*no puedo.*pdf.*$\n?", "", body)

    body = re.sub(r"\n{3,}", "\n\n", body).strip()

    if has_chart and has_pdf:
        headline = "Grafico y PDF generados automaticamente y adjuntados."
    elif has_chart:
        headline = "Grafico generado automaticamente y adjuntado."
    elif has_pdf:
        headline = "PDF generado automaticamente y adjuntado."
    else:
        return body

    if body.lower().startswith("bluf:"):
        body = re.sub(r"(?is)^bluf:\s*", "", body, count=1).strip()
    return f"{headline}\n\n{body}"


def _looks_like_no_data_response(text: str) -> bool:
    body = (text or "").lower()
    markers = [
        "no encontre",
        "no encontr",
        "no hay informacion",
        "sin informacion",
        "no tengo datos",
        "no se encontro",
    ]
    return any(m in body for m in markers)


def _resolve_pm_agent(empresa_id: str, routed_to: str) -> str:
    """Resuelve qué agente PM usar según credenciales de la empresa."""
    if routed_to not in ("project_agent", "notion_agent") or not empresa_id:
        return routed_to

    try:
        from api.database import sync_engine
        from sqlalchemy import text as sql_text

        with sync_engine.connect() as conn:
            result = conn.execute(
                sql_text("""
                    SELECT provider FROM tenant_credentials
                    WHERE empresa_id = :eid
                      AND provider IN ('plane', 'notion', 'asana', 'monday', 'trello', 'clickup', 'jira')
                      AND is_active = TRUE
                """),
                {"eid": empresa_id},
            )
            rows = result.fetchall()

        providers = {row.provider for row in rows}

        if routed_to == "project_agent":
            if "plane" in providers:
                return "project_agent"
            if "notion" in providers:
                return "notion_agent"
            generic_providers = providers & {"asana", "monday", "trello", "clickup", "jira"}
            if generic_providers:
                return "generic_pm_agent"
            return routed_to

        if routed_to == "notion_agent":
            if "notion" in providers:
                return "notion_agent"
            if "plane" in providers:
                return "project_agent"
            generic_providers = providers & {"asana", "monday", "trello", "clickup", "jira"}
            if generic_providers:
                return "generic_pm_agent"
            return routed_to

    except Exception as e:
        print(f"RUNNER _resolve_pm_agent error: {e}")

    return routed_to


async def run_agent(
    message: str,
    empresa_id: str = None,
    user_id: str = None,
    has_file: bool = False,
    file_type: str = None,
    source: str = "api",
) -> dict:
    output_mode = decide_output_mode(message=message or "", source=source)

    # 1) Semantic firewall previo al agente
    firewall = evaluate_semantic_firewall(message=message or "", source=source)
    if firewall.get("blocked"):
        return {
            "response": firewall.get("response", "Solicitud bloqueada por Firewall Semantico."),
            "intent": "blocked",
            "confidence": 1.0,
            "routed_to": "semantic_firewall",
            "model_used": "firewall",
            "blocked": True,
            "firewall_reason": firewall.get("reason", "blocked"),
            "output_mode": output_mode,
            "traceability": {
                "primary_source": "semantic_firewall",
                "secondary_source": "semantic_firewall",
                "sources_used": [{"name": "semantic_firewall", "detail": firewall.get("reason", "blocked"), "confidence": 1.0}],
                "confidence": 1.0,
            },
        }

    # 1.5) Budget check
    budget_status = check_budget(empresa_id) if empresa_id else None
    budget_override = None
    analyses_exhausted = False
    if budget_status and budget_status.is_downgraded:
        budget_override = budget_status.forced_model

    # 2) Router por intent
    router_result = await router_agent.ainvoke({
        "message": message,
        "empresa_id": empresa_id or "",
        "user_id": user_id or "",
        "has_file": has_file,
        "file_type": file_type,
        "source": source,
    })

    intent = router_result.get("intent", "conversational")
    routed_to = router_result.get("routed_to", DEFAULT_AGENT)
    confidence = router_result.get("confidence", 0.0)

    print(f"RUNNER: intent={intent}, routed_to={routed_to}, confidence={confidence}")

    routed_to = _resolve_pm_agent(empresa_id, routed_to)

    # 2.5) RBAC: verificar acceso al agente
    if empresa_id and user_id:
        from api.services.rbac_service import check_agent_access
        allowed, reason = check_agent_access(empresa_id, user_id, routed_to)
        if not allowed:
            return {
                "response": reason,
                "intent": intent,
                "confidence": confidence,
                "routed_to": "rbac_blocked",
                "model_used": "rbac",
                "blocked": True,
                "output_mode": output_mode,
                "traceability": {
                    "primary_source": "rbac",
                    "secondary_source": "rbac",
                    "sources_used": [{"name": "rbac", "detail": f"agent {routed_to} blocked for user", "confidence": 1.0}],
                    "confidence": 1.0,
                },
            }

    agent = AGENT_REGISTRY.get(routed_to)
    if not agent:
        print(f"WARNING: Agent '{routed_to}' not implemented. Using {DEFAULT_AGENT}")
        agent = AGENT_REGISTRY[DEFAULT_AGENT]
        routed_to = DEFAULT_AGENT

    # 3) Orquestacion multi-fuente obligatoria (dual repo + tools contextuales)
    tool_context = await collect_multi_source_context(
        message=message,
        empresa_id=empresa_id or "",
        intent=intent,
        user_id=user_id or "",
    )

    # 3.5) Plan-based model restriction
    plan_downgraded = False
    if budget_status and not budget_override:
        task_type = AGENT_TASK_MAP.get(routed_to, "chat")
        plan_model, plan_downgraded = get_model_for_plan(
            budget_status.plan_type, task_type
        )
        if plan_downgraded:
            budget_override = plan_model

    # 3.6) Analysis limit check (solo para tareas de analisis)
    analysis_tasks = ("excel_analysis", "document_analysis")
    current_task_type = AGENT_TASK_MAP.get(routed_to, "chat")
    if current_task_type in analysis_tasks and empresa_id:
        analysis_status = check_analyses(empresa_id)
        if not analysis_status.allowed:
            analyses_exhausted = True
            budget_override = "gemini-flash"
            print(f"RUNNER: Empresa {empresa_id[:8]} agoto analisis ({analysis_status.used}/{analysis_status.limit}), degradando a gemini-flash")

    # Enriquecer mensaje con contexto conversacional para agentes que no manejan historial
    enriched_message = message
    if empresa_id and user_id and routed_to in ("project_agent", "notion_agent", "calendar_agent", "generic_pm_agent"):
        try:
            from api.agents.chat_agent import get_history
            history = get_history(empresa_id, user_id)
            if history:
                recent = history[-6:]
                context_summary = "\n".join(
                    f"{m.get('role','user')}: {m.get('content','')[:200]}"
                    for m in recent
                )
                enriched_message = f"[CONTEXTO CONVERSACIONAL RECIENTE:\n{context_summary}\n]\n\nMENSAJE ACTUAL: {message}"
        except Exception as e:
            print(f"RUNNER: history enrichment error: {e}")

    agent_input = {
        "message": enriched_message,
        "empresa_id": empresa_id or "",
        "user_id": user_id or "",
        "intent": intent,
        "source": source,
        "tool_context": tool_context.get("context_text", ""),
        "sources_used": tool_context.get("sources_used", []),
        "dual_repo_checked": tool_context.get("dual_repo_checked", True),
    }

    if budget_override:
        agent_input["model_preference"] = budget_override

    # 4) Ejecutar agente especializado
    try:
        agent_result = await agent.ainvoke(agent_input)
    except Exception as e:
        print(f"RUNNER agent execution error: {e}")
        agent_result = {
            "response": f"No pude procesar la solicitud por un error interno: {e}",
            "model_used": "error",
            "sources_used": [],
        }

    response = agent_result.get("response", "No pude procesar tu mensaje.")
    model_used = agent_result.get("model_used", "unknown")

    # 4.4) Log analysis count
    if current_task_type in analysis_tasks and empresa_id:
        try:
            log_analysis(empresa_id)
        except Exception as e:
            print(f"RUNNER: Error logging analysis: {e}")

    # 4.5) Log token usage
    if empresa_id and budget_status:
        try:
            task_type = AGENT_TASK_MAP.get(routed_to, "chat")
            input_tokens = len(message or "") // 4
            output_tokens = len(response or "") // 4
            cost_usd = selector.estimate_cost(model_used, input_tokens, output_tokens)
            was_downgraded = budget_status.is_downgraded or plan_downgraded
            log_usage(
                empresa_id=empresa_id,
                user_id=user_id,
                agent=routed_to,
                model_name=model_used,
                task_type=task_type,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=cost_usd,
                was_downgraded=was_downgraded,
                original_model=None if not was_downgraded else AGENT_TASK_MAP.get(routed_to, "chat"),
            )
        except Exception as e:
            print(f"RUNNER budget log error: {e}")

    # 4.1) Garantiza consulta dual antes de aceptar respuestas tipo "no encontre".
    if _looks_like_no_data_response(response) and not tool_context.get("dual_repo_checked", False) and empresa_id and message:
        try:
            forced_a = search_reports_qdrant(message, empresa_id, limit=2)
            forced_b = search_vector_store1(message, empresa_id, limit=2)
            if forced_a:
                tool_context.setdefault("sources_used", []).append(
                    {"name": "qdrant_excel_reports", "detail": f"{len(forced_a)} hallazgos (forced)", "confidence": 0.8}
                )
            if forced_b:
                tool_context.setdefault("sources_used", []).append(
                    {"name": "qdrant_vector_store1", "detail": f"{len(forced_b)} hallazgos (forced)", "confidence": 0.78}
                )
            tool_context["dual_repo_checked"] = True
        except Exception as e:
            print(f"RUNNER forced dual-check error: {e}")

    # 5) Trazabilidad unificada y BLUF transversal
    merged_sources = list(tool_context.get("sources_used", [])) + list(agent_result.get("sources_used", []))
    policy = enforce_response_contract(response=response, sources_used=merged_sources, confidence=confidence)
    final_response = policy["response"]

    attachment = None
    attachments = []

    chart_attachment = None
    should_generate_chart = wants_chart(message)
    if should_generate_chart:
        chart = generate_chart_from_text(
            content=response,
            title=_build_chart_title(intent=intent, message=message),
        )
        if chart.get("ok"):
            chart_attachment = {
                "type": "chart",
                "file_path": chart.get("file_path"),
                "file_name": chart.get("file_name"),
                "mime_type": chart.get("mime_type", "image/png"),
            }
            _LAST_CHART_BY_USER[_chart_user_key(empresa_id, user_id)] = chart_attachment
            attachments.append(chart_attachment)
            print(f"ARTIFACT CHART ok: {chart_attachment.get('file_name')}")
        else:
            print(f"ARTIFACT CHART error: {chart.get('error', 'unknown')}")
            cached_chart = _LAST_CHART_BY_USER.get(_chart_user_key(empresa_id, user_id))
            if cached_chart and cached_chart.get("file_path"):
                chart_attachment = cached_chart
                attachments.append(chart_attachment)
                print(f"ARTIFACT CHART fallback: {cached_chart.get('file_name')}")

    should_generate_pdf = wants_pdf(message) or _response_suggests_manual_pdf(final_response)
    if should_generate_pdf:
        image_paths = [chart_attachment.get("file_path")] if chart_attachment else []
        pdf = generate_pdf_from_text(
            content=final_response,
            title=_build_pdf_title(intent=intent, message=message),
            image_paths=image_paths,
        )
        if pdf.get("ok"):
            pdf_attachment = {
                "type": "pdf",
                "file_path": pdf.get("file_path"),
                "file_name": pdf.get("file_name"),
                "mime_type": pdf.get("mime_type", "application/pdf"),
            }
            attachments.append(pdf_attachment)
            attachment = pdf_attachment
            print(f"ARTIFACT PDF ok: {pdf_attachment.get('file_name')}")
        else:
            print(f"ARTIFACT PDF error: {pdf.get('error', 'unknown')}")

    if not attachment and attachments:
        attachment = attachments[0]

    has_chart = any(a.get("type") == "chart" for a in attachments if isinstance(a, dict))
    has_pdf = any(a.get("type") == "pdf" for a in attachments if isinstance(a, dict))
    final_response = _align_response_with_artifacts(final_response, has_chart=has_chart, has_pdf=has_pdf)

    result = {
        "response": final_response,
        "intent": intent,
        "confidence": confidence,
        "routed_to": routed_to,
        "model_used": model_used,
        "blocked": False,
        "dual_repo_checked": tool_context.get("dual_repo_checked", True),
        "output_mode": output_mode,
        "traceability": policy["traceability"],
        "attachment": attachment,
        "attachments": attachments,
    }

    # Budget metadata
    if budget_status:
        result["budget"] = {
            "plan_type": budget_status.plan_type,
            "usage_percent": budget_status.usage_percent,
            "remaining": budget_status.remaining,
            "is_downgraded": budget_status.is_downgraded,
            "topup_balance": budget_status.topup_balance,
        }
        if budget_status.is_downgraded:
            result["budget_warning"] = (
                "Has alcanzado tu limite mensual de presupuesto. "
                "Tu servicio ha sido degradado a modelos gratuitos temporalmente. "
                "Puedes adquirir tokens adicionales desde el panel: "
                "paquetes de $20, $50 o $100 USD."
            )

    return result
