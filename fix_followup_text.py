with open('api/routers/chat.py', 'r') as f:
    c = f.read()

fixes = 0

# Buscar todas las variaciones del texto de follow-up
old_texts = [
    'Si quieres que le haga follow-up automático si no responde, dime: "recuérdale en 2 días"',
    "Si quieres que le haga follow-up autom\u00e1tico si no responde, dime: \"recu\u00e9rdale en 2 d\u00edas\"",
]

new_text = '¿Quieres que le reenvíe un recordatorio si no responde en unos días? Solo dime "hazle seguimiento"'

for old in old_texts:
    if old in c:
        c = c.replace(old, new_text)
        fixes += 1
        print(f"OK: texto follow-up actualizado")

with open('api/routers/chat.py', 'w') as f:
    f.write(c)

# Tambien buscar en email_agent.py
with open('api/agents/email_agent.py', 'r') as f:
    e = f.read()

for old in old_texts:
    if old in e:
        e = e.replace(old, new_text)
        fixes += 1
        print(f"OK: texto follow-up en email_agent actualizado")

with open('api/agents/email_agent.py', 'w') as f:
    f.write(e)

# Agregar "hazle seguimiento" a los follow-up triggers del router
with open('api/agents/router_agent.py', 'r') as f:
    r = f.read()

old_triggers = '        "hazle seguimiento", "dale seguimiento",'
if old_triggers not in r:
    r = r.replace(
        '"recuérdale", "recuerdale", "follow up", "follow-up", "followup",',
        '"recuérdale", "recuerdale", "follow up", "follow-up", "followup",\n        "hazle seguimiento", "hazle seguimiento al correo", "hazle seguimiento al mail",'
    )
    with open('api/agents/router_agent.py', 'w') as f:
        f.write(r)
    fixes += 1
    print("OK: trigger 'hazle seguimiento' agregado al router")

print(f"\n{fixes} fixes aplicados")
