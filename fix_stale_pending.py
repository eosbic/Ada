with open('api/routers/chat.py', 'r') as f:
    c = f.read()

old = '''        # Email en composición — el usuario responde con info faltante
        if pending.get("type") == "email_composing":
            if _is_rejection(message):
                _resolve_pending(pending["id"], "cancelled")
                return {"response": "Email cancelado.", "intent": "email", "model_used": "hitl"}

            _resolve_pending(pending["id"], "completed")'''

new = '''        # Email en composición — el usuario responde con info faltante
        if pending.get("type") == "email_composing":
            if _is_rejection(message):
                _resolve_pending(pending["id"], "cancelled")
                return {"response": "Email cancelado.", "intent": "email", "model_used": "hitl"}

            # Detectar si el usuario inicia una NUEVA solicitud de email (no continuacion)
            _new_email_indicators = ["enviale", "envíale", "escribele", "escríbele", "manda un mail", "envia un mail", "envía un mail", "escribe un mail", "enviale un mail", "envíale un mail"]
            if any(ind in message.lower() for ind in _new_email_indicators):
                _resolve_pending(pending["id"], "cancelled")
                print(f"HITL: New email request detected, cancelling stale composing")
                # Caer al flujo normal (no return, continuar al router)
            else:
                _resolve_pending(pending["id"], "completed")'''

if old in c:
    c = c.replace(old, new, 1)
    with open('api/routers/chat.py', 'w') as f:
        f.write(c)
    print("OK: stale pending detection applied")
else:
    print("FAIL: patron no encontrado")
