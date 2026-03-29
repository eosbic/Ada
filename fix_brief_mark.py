with open('api/workers/morning_brief_worker.py', 'r') as f:
    c = f.read()

old = "SET preferences = preferences || :patch::jsonb,"
new = "SET preferences = preferences || CAST(:patch AS jsonb),"

if old in c:
    c = c.replace(old, new, 1)
    with open('api/workers/morning_brief_worker.py', 'w') as f:
        f.write(c)
    print('OK: brief mark_sent fix')
else:
    print('FAIL: patron no encontrado')
