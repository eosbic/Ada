with open('api/workers/email_monitor_worker.py', 'r') as f:
    c = f.read()

fixes = 0

# Fix 1: agregar set de dedup
old1 = '            followups = get_active_followups()\n\n            if followups:'
new1 = '            followups = get_active_followups()\n\n            if followups:\n                _notified_emails = set()'

if old1 in c:
    c = c.replace(old1, new1, 1)
    fixes += 1
    print("OK: dedup set added")
else:
    print("FAIL: patron 1")

# Fix 2: check antes de notificar
old2 = '                if response and response.get("found"):\n                    mark_responded(followup_id, response.get("snippet", ""))\n                    if telegram_id:'
new2 = '                if response and response.get("found"):\n                    mark_responded(followup_id, response.get("snippet", ""))\n                    if telegram_id and to_email not in _notified_emails:\n                        _notified_emails.add(to_email)'

if old2 in c:
    c = c.replace(old2, new2, 1)
    fixes += 1
    print("OK: dedup check added")
else:
    print("FAIL: patron 2")

with open('api/workers/email_monitor_worker.py', 'w') as f:
    f.write(c)

print(f"\n{fixes} fixes")
