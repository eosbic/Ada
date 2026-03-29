import re

with open('api/routers/chat.py', 'r') as f:
    c = f.read()

old = '''                print(f"HITL: Draft created from composing, draft_id={result['draft_id']}")

            return result'''

new = '''                print(f"HITL: Draft created from composing, draft_id={result['draft_id']}")

            # Re-check: si el agente pide mas info, guardar nuevo composing
            if not result.get("needs_approval"):
                resp_text = result.get("response", "").lower()
                composing_re = ["qué quieres que le diga", "a quién le envío", "a quién le escribo", "me das el email"]
                if any(p in resp_text for p in composing_re):
                    email_m = re.search(r'[\\w.-]+@[\\w.-]+\\.\\w+', result.get("response", ""))
                    p_email = email_m.group(0) if email_m else partial_to
                    _save_pending(empresa_id, user_id, "email_composing", {
                        "partial_to": p_email,
                        "awaiting": "body" if p_email else "to",
                    })
                    print(f"HITL: Re-saved composing after enrichment, partial_to={p_email}")

            return result'''

if old in c:
    c = c.replace(old, new, 1)
    with open('api/routers/chat.py', 'w') as f:
        f.write(c)
    print('OK: email composing re-save fix applied')
else:
    print('FAIL: patron no encontrado')
