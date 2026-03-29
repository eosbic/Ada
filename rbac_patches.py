# -*- coding: utf-8 -*-
"""
RBAC Patches — Modifica archivos existentes para completar RBAC.
Ejecutar:
  docker cp rbac_patches.py ada_api:/app/rbac_patches.py
  docker exec ada_api python3 rbac_patches.py
"""


def apply_fix(filepath, old, new, label):
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
        if old not in content:
            print(f"  >> [{label}] Patron no encontrado (ya aplicado?)")
            return False
        content = content.replace(old, new, 1)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"  OK [{label}]")
        return True
    except Exception as e:
        print(f"  FAIL [{label}] {e}")
        return False


def main():
    print("=" * 60)
    print("  RBAC PATCHES — 4 tareas")
    print("=" * 60)
    fixes = 0

    # ═════════════════════════════════════════════════
    # TAREA 1: Audit logging en agent_runner.py
    # ═════════════════════════════════════════════════
    print("\n[TAREA 1] Audit logging en agent_runner")

    # 1a: Log cuando RBAC bloquea un agente
    r = apply_fix(
        "api/services/agent_runner.py",
        '        if not allowed:\n            return {',
        '        if not allowed:\n            try:\n                from api.services.audit_service import log_rbac_blocked\n                log_rbac_blocked(empresa_id, user_id, routed_to, reason)\n            except Exception:\n                pass\n            return {',
        "Audit log RBAC blocked",
    )
    if r: fixes += 1

    # 1b: Log cuando un agente se ejecuta exitosamente
    r = apply_fix(
        "api/services/agent_runner.py",
        '    # 3) Orquestacion multi-fuente obligatoria',
        '    # 2.9) Audit: registrar acceso al agente\n    try:\n        from api.services.audit_service import log_access\n        log_access(empresa_id or "", user_id or "", "access_agent", agent_name=routed_to)\n    except Exception:\n        pass\n\n    # 3) Orquestacion multi-fuente obligatoria',
        "Audit log agent access",
    )
    if r: fixes += 1

    # 1c: Inyectar user_role y user_permissions en agent_input
    r = apply_fix(
        "api/services/agent_runner.py",
        '        "dual_repo_checked": tool_context.get("dual_repo_checked", True),\n    }\n    if budget_override:',
        '        "dual_repo_checked": tool_context.get("dual_repo_checked", True),\n    }\n\n    # RBAC: Inyectar rol y permisos en el state del agente\n    try:\n        from api.services.rbac_service import get_user_permissions\n        _rbac = get_user_permissions(empresa_id or "", user_id or "")\n        agent_input["user_role"] = _rbac.get("role_title", "")\n        agent_input["user_permissions"] = _rbac.get("permissions", {})\n        agent_input["is_admin"] = _rbac.get("is_admin", False)\n    except Exception as e:\n        print(f"RUNNER: Error injecting RBAC into state: {e}")\n        agent_input["user_role"] = ""\n        agent_input["user_permissions"] = {}\n        agent_input["is_admin"] = False\n\n    if budget_override:',
        "Inject user_role in state",
    )
    if r: fixes += 1

    # ═════════════════════════════════════════════════
    # TAREA 2: RBAC en meeting_events (chat_agent.py)
    # ═════════════════════════════════════════════════
    print("\n[TAREA 2] RBAC en meeting_events")

    r = apply_fix(
        "api/agents/chat_agent.py",
        '                        FROM meeting_events\n                        WHERE empresa_id = :eid\n                        ORDER BY created_at DESC LIMIT 1\n                    """),\n                    {"eid": empresa_id}',
        '                        FROM meeting_events\n                        WHERE empresa_id = :eid\n                        {meeting_rbac}\n                        ORDER BY created_at DESC LIMIT 1\n                    """.format(meeting_rbac=_get_meeting_rbac_clause(empresa_id, user_id))),\n                    {**{"eid": empresa_id}, **_get_meeting_rbac_params(empresa_id, user_id)}',
        "Meeting events RBAC filter",
    )
    if r: fixes += 1

    # Agregar funciones helper para meeting RBAC al inicio del archivo
    r = apply_fix(
        "api/agents/chat_agent.py",
        'from api.services.memory_service import (',
        'def _get_meeting_rbac_clause(empresa_id: str, user_id: str) -> str:\n    """Retorna clause SQL para filtrar reuniones por permisos."""\n    try:\n        from api.services.rbac_service import get_user_permissions\n        rbac = get_user_permissions(empresa_id, user_id)\n        if rbac.get("is_admin"):\n            return ""\n        return "AND (participants::text ILIKE :user_pattern)"\n    except Exception:\n        return ""\n\n\ndef _get_meeting_rbac_params(empresa_id: str, user_id: str) -> dict:\n    """Retorna params para el filtro RBAC de reuniones."""\n    try:\n        from api.services.rbac_service import get_user_permissions\n        rbac = get_user_permissions(empresa_id, user_id)\n        if rbac.get("is_admin"):\n            return {}\n        return {"user_pattern": f"%{user_id}%"}\n    except Exception:\n        return {}\n\n\nfrom api.services.memory_service import (',
        "Meeting RBAC helpers",
    )
    if r: fixes += 1

    # ═════════════════════════════════════════════════
    # TAREA 3: RBAC en prospecting agents
    # ═════════════════════════════════════════════════
    print("\n[TAREA 3] RBAC en prospecting agents")

    # prospecting_agent.py — agregar check al inicio
    r = apply_fix(
        "api/agents/prospecting_agent.py",
        '    # Inyectar sector desde DNA si dice "mi sector"',
        '    # RBAC: verificar permiso de prospeccion\n    if empresa_id and user_id:\n        try:\n            from api.services.rbac_service import get_user_permissions\n            _rbac_p = get_user_permissions(empresa_id, user_id)\n            if not _rbac_p.get("is_admin"):\n                _perms = _rbac_p.get("permissions", {})\n                if not _perms.get("can_prospect") and not _perms.get("can_view_clients"):\n                    return {"response": "No tienes permiso para acceder a prospeccion. Contacta a tu administrador.", "model_used": "rbac"}\n        except Exception as e:\n            print(f"PROSPECTING: RBAC check error: {e}")\n\n    # Inyectar sector desde DNA si dice "mi sector"',
        "Prospecting RBAC check",
    )
    if r: fixes += 1

    # prospect_pro_agent.py — agregar check
    r = apply_fix(
        "api/agents/prospect_pro_agent.py",
        '    memories = search_memory(search_terms, empresa_id=empresa_id) if search_terms else []',
        '    # RBAC: verificar permiso de prospeccion\n    if empresa_id and user_id:\n        try:\n            from api.services.rbac_service import get_user_permissions\n            _rbac_pp = get_user_permissions(empresa_id, user_id)\n            if not _rbac_pp.get("is_admin"):\n                _perms_pp = _rbac_pp.get("permissions", {})\n                if not _perms_pp.get("can_prospect") and not _perms_pp.get("can_view_clients"):\n                    return {"response": "No tienes permiso para acceder a prospeccion. Contacta a tu administrador.", "model_used": "rbac"}\n        except Exception as e:\n            print(f"PROSPECT_PRO: RBAC check error: {e}")\n\n    memories = search_memory(search_terms, empresa_id=empresa_id) if search_terms else []',
        "Prospect Pro RBAC check",
    )
    if r: fixes += 1

    # ═════════════════════════════════════════════════
    # TAREA 4: Audit log en email send y report search
    # ═════════════════════════════════════════════════
    print("\n[TAREA 4] Audit log en email y reportes")

    # Email: log despues de envio exitoso
    r = apply_fix(
        "api/agents/email_agent.py",
        '        return {\n            "response": "\\u2705 Email enviado exitosamente.',
        '        try:\n            from api.services.audit_service import log_access\n            log_access(empresa_id, user_id, "send_email", "email", detail={"draft_id": draft_id})\n        except Exception:\n            pass\n\n        return {\n            "response": "\\u2705 Email enviado exitosamente.',
        "Audit log email send",
    )
    if r: fixes += 1

    # Reportes: log en search_reports de memory_service
    r = apply_fix(
        "api/services/memory_service.py",
        '    _validate_empresa_id(empresa_id, "search_reports")\n    from api.database import sync_engine',
        '    _validate_empresa_id(empresa_id, "search_reports")\n    try:\n        from api.services.audit_service import log_access\n        log_access(empresa_id, user_id or "", "view_report", "ada_reports")\n    except Exception:\n        pass\n    from api.database import sync_engine',
        "Audit log report search",
    )
    if r: fixes += 1

    # ═════════════════════════════════════════════════
    print("\n" + "=" * 60)
    print(f"  {fixes} patches aplicados")
    print("  Ahora: docker compose down && docker compose up -d")
    print("=" * 60)


if __name__ == "__main__":
    main()
