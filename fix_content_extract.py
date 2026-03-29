with open('api/routers/chat.py', 'r') as f:
    c = f.read()

old = '''            if has_content and partial_email:
                # Ya tenemos email + contenido, re-disparar automaticamente
                print(f"HITL: Auto-enriching — email={partial_email}, original has content")
                auto_enriched = f"Escribe un email a {partial_email} con este contenido: {message}"'''

new = '''            if has_content and partial_email:
                # Extraer solo el contenido real del mensaje (despues de "dile que", "diciendole", etc.)
                import re as _re_content
                _content_match = _re_content.search(
                    r'(?:dile que|y dile que|diciendole que|diciéndole que|y que le diga que|que le diga que)\s*(.+)',
                    message, _re_content.IGNORECASE | _re_content.DOTALL
                )
                _extracted = _content_match.group(1).strip() if _content_match else message
                print(f"HITL: Auto-enriching — email={partial_email}, extracted content: {_extracted[:60]}")
                auto_enriched = f"Escribe un email a {partial_email}. El destinatario se llama {partial_email}. Contenido del email: {_extracted}"'''

if old in c:
    c = c.replace(old, new, 1)
    with open('api/routers/chat.py', 'w') as f:
        f.write(c)
    print("OK: content extraction applied")
else:
    print("FAIL")
