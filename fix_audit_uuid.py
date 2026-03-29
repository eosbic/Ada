with open('api/services/audit_service.py', 'r') as f:
    c = f.read()

old = '    try:\n        with sync_engine.connect() as conn:\n            conn.execute('
new = '    if not empresa_id or not user_id:\n        return\n    try:\n        with sync_engine.connect() as conn:\n            conn.execute('

if old in c:
    c = c.replace(old, new, 1)
    with open('api/services/audit_service.py', 'w') as f:
        f.write(c)
    print('OK: audit_service UUID guard')
else:
    print('FAIL: patron no encontrado')
