with open('api/routers/chat.py', 'r') as f:
    c = f.read()

fixes = 0

# Fix 1: Guardar el mensaje original cuando se inicia composing
old1 = '''            _save_pending(empresa_id, user_id, "email_composing", {
                "partial_to": partial_email,
                "awaiting": "body" if partial_email else "to",
            })
            print(f"HITL: Email composing saved — partial_to={partial_email}, awaiting={'body' if partial_email else 'to'}")'''

new1 = '''            _save_pending(empresa_id, user_id, "email_composing", {
                "partial_to": partial_email,
                "awaiting": "body" if partial_email else "to",
                "original_message": message,
            })
            print(f"HITL: Email composing saved — partial_to={partial_email}, awaiting={'body' if partial_email else 'to'}, original_msg={message[:50]}")'''

if old1 in c:
    c = c.replace(old1, new1, 1)
    fixes += 1
    print("OK: Fix 1 - guardar original_message en composing")
else:
    print(">> Fix 1 - patron no encontrado")

# Fix 2: Cuando el usuario da el email, re-usar el mensaje original
old2 = '''            if partial_to:
                enriched = f"Escribe un email a {partial_to} con este contenido: {message}"
            else:
                enriched = f"Escribe un email a {message}"'''

new2 = '''            original_msg = pending.get("original_message", "")
            if partial_to:
                enriched = f"Escribe un email a {partial_to} con este contenido: {message}"
            elif original_msg:
                # El usuario dio el email, re-usar contenido original
                enriched = f"Escribe un email a {message} con este contenido: {original_msg}"
            else:
                enriched = f"Escribe un email a {message}"'''

if old2 in c:
    c = c.replace(old2, new2, 1)
    fixes += 1
    print("OK: Fix 2 - re-usar original_message al dar email")
else:
    print(">> Fix 2 - patron no encontrado")

with open('api/routers/chat.py', 'w') as f:
    f.write(c)

print(f"\n{fixes} fixes aplicados")
