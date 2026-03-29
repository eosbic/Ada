with open('api/services/agent_runner.py', 'r') as f:
    c = f.read()

old = '    }\n\n    if budget_override:'

new = '    }\n\n    # RBAC: Inyectar rol y permisos en el state del agente\n    try:\n        from api.services.rbac_service import get_user_permissions\n        _rbac = get_user_permissions(empresa_id or "", user_id or "")\n        agent_input["user_role"] = _rbac.get("role_title", "")\n        agent_input["user_permissions"] = _rbac.get("permissions", {})\n        agent_input["is_admin"] = _rbac.get("is_admin", False)\n    except Exception as e:\n        print(f"RUNNER: Error injecting RBAC: {e}")\n\n    if budget_override:'

if old in c:
    c = c.replace(old, new, 1)
    with open('api/services/agent_runner.py', 'w') as f:
        f.write(c)
    print('OK: user_role injected')
else:
    print('FAIL: patron no encontrado')
