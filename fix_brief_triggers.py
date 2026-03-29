with open('api/routers/chat.py', 'r') as f:
    c = f.read()

old = '''    brief_keywords = [
        "activa el brief", "activar brief", "activa brief", "activar el brief",
        "envíame el brief", "enviame el brief", "quiero el brief",
        "brief diario", "brief a las", "brief todos los dias", "brief todos los días",
        "desactiva el brief", "desactivar brief", "desactiva brief",
        "cancela el brief", "cancelar brief", "no quiero brief",
        "cambia el brief", "cambiar hora del brief",
    ]'''

new = '''    brief_keywords = [
        "activa el brief", "activar brief", "activa brief", "activar el brief",
        "envíame el brief", "enviame el brief", "quiero el brief",
        "brief diario", "brief a las", "brief todos los dias", "brief todos los días",
        "desactiva el brief", "desactivar brief", "desactiva brief",
        "cancela el brief", "cancelar brief", "no quiero brief",
        "cambia el brief", "cambiar hora del brief",
        # Variaciones naturales
        "briefing", "mi briefing", "el briefing", "briefing diario",
        "envíame el briefing", "enviame el briefing", "quiero el briefing",
        "activa el briefing", "desactiva el briefing",
        "resumen matutino", "resumen de la mañana", "resumen mañanero",
        "brief mañanero", "briefing mañanero",
        "enviame mi brief", "envíame mi brief",
        "enviame mi briefing", "envíame mi briefing",
    ]'''

if old in c:
    c = c.replace(old, new, 1)
    with open('api/routers/chat.py', 'w') as f:
        f.write(c)
    print("OK: brief triggers expanded")
else:
    print("FAIL")
