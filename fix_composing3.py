with open('api/routers/chat.py', 'r') as f:
    c = f.read()

# Buscar el bloque donde se guarda composing al final del chat
old = '''            _save_pending(empresa_id, user_id, "email_composing", {
                "partial_to": partial_email,
                "awaiting": "body" if partial_email else "to",
                "original_message": message,
            })
            print(f"HITL: Email composing saved — partial_to={partial_email}, awaiting={'body' if partial_email else 'to'}, original_msg={message[:50]}")'''

new = '''            # Detectar si el mensaje original ya tiene contenido ("dile que...", "y que...")
            content_indicators = ["dile que", "y dile", "diciendole", "diciéndole", "y que ", "con este mensaje", "que le diga"]
            msg_lower_comp = message.lower()
            has_content = any(ind in msg_lower_comp for ind in content_indicators)

            if has_content and partial_email:
                # Ya tenemos email + contenido, re-disparar automaticamente
                print(f"HITL: Auto-enriching — email={partial_email}, original has content")
                auto_enriched = f"Escribe un email a {partial_email} con este contenido: {message}"
                auto_result = await run_agent(
                    message=auto_enriched,
                    empresa_id=empresa_id,
                    user_id=user_id,
                    source=source,
                )
                if auto_result.get("needs_approval") and auto_result.get("draft_id"):
                    to_m = re.search(r'[\\w.-]+@[\\w.-]+\\.\\w+', auto_result.get("response", ""))
                    to_a = to_m.group(0) if to_m else partial_email
                    _save_pending(empresa_id, user_id, "email_send", {
                        "draft_id": auto_result["draft_id"],
                        "to": to_a,
                        "original_draft": auto_result.get("original_draft", ""),
                    })
                    print(f"HITL: Auto-draft created, draft_id={auto_result['draft_id']}")
                return auto_result

            _save_pending(empresa_id, user_id, "email_composing", {
                "partial_to": partial_email,
                "awaiting": "body" if partial_email else "to",
                "original_message": message,
            })
            print(f"HITL: Email composing saved — partial_to={partial_email}, awaiting={'body' if partial_email else 'to'}, original_msg={message[:50]}")'''

if old in c:
    c = c.replace(old, new, 1)
    with open('api/routers/chat.py', 'w') as f:
        f.write(c)
    print("OK: auto-enrich cuando mensaje ya tiene contenido")
else:
    print("FAIL: patron no encontrado")
