with open('api/agents/email_agent.py', 'r') as f:
    c = f.read()

# Fix: extraer nombre del destinatario del mensaje y pasarlo al prompt
old = '            gen = await model.ainvoke([\n                {"role": "system", "content": draft_system},\n                {"role": "user", "content": f"Para: {to}. Contexto: {state[\'message\']}"},'

new = '''            # Extraer nombre del destinatario del contexto
            import re as _re_email
            _recipient_name = ""
            _msg = state.get("message", "")
            # Patron: "email a NombreApellido" o "a NombreApellido con"
            _name_match = _re_email.search(r'(?:email|mail|mensaje|correo|escr[ií]b[ea]le|env[ií]ale)\s+a\s+([A-ZÁÉÍÓÚÑ][a-záéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+)*)', _msg)
            if _name_match:
                _recipient_name = _name_match.group(1)
            recipient_hint = f"\\nEl DESTINATARIO se llama {_recipient_name}. El saludo DEBE ser para {_recipient_name}, NO para el remitente." if _recipient_name else "\\nEl saludo debe dirigirse al DESTINATARIO (persona en Para:), NO al remitente."
            draft_system += recipient_hint

            gen = await model.ainvoke([
                {"role": "system", "content": draft_system},
                {"role": "user", "content": f"Para: {to}. Contexto: {state['message']}"},'''

if old in c:
    c = c.replace(old, new, 1)
    with open('api/agents/email_agent.py', 'w') as f:
        f.write(c)
    print("OK: recipient name extraction applied")
else:
    print("FAIL: patron no encontrado")
