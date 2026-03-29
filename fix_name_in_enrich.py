with open('api/routers/chat.py', 'r') as f:
    c = f.read()

old = 'auto_enriched = f"Escribe un email a {partial_email}. El destinatario se llama {partial_email}. Contenido del email: {_extracted}"'

new = '''# Extraer nombre del destinatario del mensaje original
                _name_match = _re_content.search(
                    r'(?:mail|correo|email|mensaje)\s+a\s+([A-ZÁÉÍÓÚÑ][a-záéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+)*)',
                    message, _re_content.IGNORECASE
                )
                _recipient = _name_match.group(1) if _name_match else partial_email
                auto_enriched = f"Escribe un email a {partial_email}. El destinatario se llama {_recipient}. Contenido del email: {_extracted}"'''

if old in c:
    c = c.replace(old, new, 1)
    with open('api/routers/chat.py', 'w') as f:
        f.write(c)
    print("OK: recipient name in auto-enrich")
else:
    print("FAIL")
