with open('api/routers/chat.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

fixed = False
for i, line in enumerate(lines):
    if 'follow-up' in line and 'recuérdale en 2' in line:
        old_line = lines[i]
        lines[i] = line.replace(
            'Si quieres que le haga follow-up automático si no responde, dime: \\"recuérdale en 2 días\\".',
            '¿Quieres que le reenvíe un recordatorio si no responde en unos días? Solo dime \\"hazle seguimiento\\".'
        )
        if lines[i] == old_line:
            # Intentar sin los backslash escapes
            lines[i] = line.replace(
                'follow-up automático si no responde, dime: \\"recuérdale en 2 días\\".',
                'reenvíe un recordatorio si no responde en unos días? Solo dime \\"hazle seguimiento\\".'
            )
        if lines[i] != old_line:
            fixed = True
            print(f"OK: linea {i+1} actualizada")
        else:
            print(f"FAIL: linea {i+1} no matcheo, contenido:")
            print(repr(line))

with open('api/routers/chat.py', 'w', encoding='utf-8') as f:
    f.writelines(lines)

if not fixed:
    print("No se pudo aplicar")
