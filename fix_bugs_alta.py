# -*- coding: utf-8 -*-
"""
FIX: 5 Bugs de Prioridad ALTA
Ejecutar:
  docker cp fix_bugs_alta.py ada_api:/app/fix_bugs_alta.py
  docker exec ada_api python3 fix_bugs_alta.py
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
    print("  FIXING 5 BUGS PRIORIDAD ALTA")
    print("=" * 60)
    fixes = 0

    # ═════════════════════════════════════════════════
    # BUG 1: Apollo no filtra por industria
    # ═════════════════════════════════════════════════
    print("\n[BUG 1] Apollo: filtro por industria")

    r = apply_fix(
        "api/services/prospect_search_service.py",
        '        if industry_keywords:\n            payload["q_organization_keyword_tags"] = industry_keywords\n\n        async with httpx.AsyncClient(timeout=20) as client:',
        '        if industry_keywords:\n            payload["q_organization_keyword_tags"] = industry_keywords\n            if not company_name and industry_keywords:\n                payload["q_organization_name"] = " ".join(industry_keywords[:2])\n\n        async with httpx.AsyncClient(timeout=20) as client:',
        "Apollo query refuerzo",
    )
    if r: fixes += 1

    r = apply_fix(
        "api/services/prospect_search_service.py",
        '            orgs = resp.json().get("organizations", [])\n            for org in orgs[:max_results]:',
        '            orgs = resp.json().get("organizations", [])\n\n            # Filtro client-side: priorizar matches de industria\n            if industry_keywords and orgs:\n                kw_lower = [k.lower() for k in industry_keywords]\n                def _industry_score(org):\n                    ind = (org.get("industry") or "").lower()\n                    kws = " ".join(org.get("keywords") or []).lower()\n                    return sum(1 for k in kw_lower if k in f"{ind} {kws}")\n                orgs.sort(key=_industry_score, reverse=True)\n\n            for org in orgs[:max_results]:',
        "Apollo client-side filter",
    )
    if r: fixes += 1

    # ═════════════════════════════════════════════════
    # BUG 2: "En mi sector" no usa DNA
    # ═════════════════════════════════════════════════
    print("\n[BUG 2] Router: 'en mi sector'")

    # Match por la ultima linea antes del cierre de la lista
    r = apply_fix(
        "api/agents/router_agent.py",
        '        "perfila la empresa", "informacion de la empresa", "informaci\u00f3n de la empresa",\n    ]',
        '        "perfila la empresa", "informacion de la empresa", "informaci\u00f3n de la empresa",\n        "en mi sector", "en mi industria", "mi sector", "mi industria",\n        "empresas de mi sector", "oportunidades en mi sector",\n        "clientes en mi sector", "competidores en mi sector",\n        "en el sector hotelero", "en el sector de", "en la industria de",\n        "en el sector tecnol\u00f3gico", "en el sector tecnologico",\n        "en el sector salud", "en el sector retail",\n        "en el sector financiero", "en el sector educativo",\n    ]',
        "Router mi sector triggers",
    )
    if r: fixes += 1

    # Inyectar sector desde DNA en prospecting
    r = apply_fix(
        "api/agents/prospecting_agent.py",
        '    memories = search_memory(message, empresa_id=empresa_id)',
        '    # Inyectar sector desde DNA si dice "mi sector"\n    msg_lower_p = message.lower() if message else ""\n    if any(t in msg_lower_p for t in ["mi sector", "mi industria"]):\n        try:\n            from api.database import sync_engine\n            from sqlalchemy import text as _sql_t\n            with sync_engine.connect() as _conn:\n                _row = _conn.execute(\n                    _sql_t("SELECT description FROM ada_company_profile WHERE empresa_id = :eid"),\n                    {"eid": empresa_id}\n                ).fetchone()\n                if _row and _row.description:\n                    message = message + f" (Sector de mi empresa: {_row.description})"\n                    print(f"PROSPECTING: Injected sector from DNA")\n        except Exception as e:\n            print(f"PROSPECTING: Error injecting sector: {e}")\n\n    memories = search_memory(message, empresa_id=empresa_id)',
        "Prospecting inject DNA",
    )
    if r: fixes += 1

    # ═════════════════════════════════════════════════
    # BUG 3: Tech stack JSON crudo
    # ═════════════════════════════════════════════════
    print("\n[BUG 3] Tech stack JSON crudo")
    try:
        with open("api/agents/commercial_intelligence_agent.py", "r") as f:
            ci = f.read()
        if "isinstance(tech_list[0], dict)" in ci:
            print("  OK Ya corregido")
        else:
            print("  >> Necesita revision manual")
    except Exception as e:
        print(f"  FAIL {e}")

    # ═════════════════════════════════════════════════
    # BUG 4: Muros de texto
    # ═════════════════════════════════════════════════
    print("\n[BUG 4] Muros de texto")

    r = apply_fix(
        "api/agents/chat_agent.py",
        'Eres Ada, asistente ejecutiva',
        'REGLAS DE FORMATO OBLIGATORIAS:\n- Respuestas CORTAS: maximo 8-10 lineas para preguntas simples.\n- Usa emojis como separadores visuales en vez de bloques largos.\n- Para datos numericos: formato lista con emoji, NO parrafos.\n- Si tienes mucha info: da resumen primero (3-4 lineas), luego pregunta si quiere detalle.\n- NO uses tablas Markdown. NO uses ## headers.\n- Separa secciones con linea vacia, no con headers.\n\nEres Ada, asistente ejecutiva',
        "Chat formato corto",
    )
    if r: fixes += 1

    # ═════════════════════════════════════════════════
    # BUG 5: Firma emails genero
    # ═════════════════════════════════════════════════
    print("\n[BUG 5] Firma email genero")

    # 5a: Cambiar instruccion de firma
    r = apply_fix(
        "api/agents/email_agent.py",
        '- Firmar con el nombre del remitente si est\u00e1 disponible',
        '- FIRMA: Firmar con el nombre REAL del remitente (NO como Ada). Despedida acorde al genero (Atento/Atenta)',
        "Email firma instruccion",
    )
    if r: fixes += 1

    # 5b: Cargar nombre remitente
    r = apply_fix(
        "api/agents/email_agent.py",
        '        # Si no hay subject o body, generar con LLM',
        '        # Cargar nombre del remitente para firma correcta\n        sender_name = ""\n        sender_hint = ""\n        if empresa_id and user_id:\n            try:\n                from api.database import sync_engine\n                from sqlalchemy import text as _sql_email\n                with sync_engine.connect() as _conn:\n                    _u = _conn.execute(\n                        _sql_email("SELECT nombre, apellido FROM usuarios WHERE id = :uid"),\n                        {"uid": user_id}\n                    ).fetchone()\n                    if _u and _u.nombre:\n                        sender_name = f"{_u.nombre} {_u.apellido or str()}".strip()\n                        sender_hint = f"El remitente se llama {sender_name}. Firma como {sender_name}, NO como Ada."\n            except Exception as e:\n                print(f"EMAIL: Error loading sender info: {e}")\n\n        # Si no hay subject o body, generar con LLM',
        "Email load sender",
    )
    if r: fixes += 1

    # 5c: Inyectar hint
    r = apply_fix(
        "api/agents/email_agent.py",
        '            if writing_prefs:\n                draft_system += writing_prefs\n            gen = await model.ainvoke([',
        '            if writing_prefs:\n                draft_system += writing_prefs\n            if sender_hint:\n                draft_system += "\\n\\n" + sender_hint\n            gen = await model.ainvoke([',
        "Email inject hint",
    )
    if r: fixes += 1

    # ═════════════════════════════════════════════════
    print("\n" + "=" * 60)
    print(f"  {fixes} fixes aplicados")
    print("  Ahora: docker compose down && docker compose up -d")
    print("=" * 60)


if __name__ == "__main__":
    main()
