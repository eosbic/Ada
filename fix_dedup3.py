with open('api/workers/email_monitor_worker.py', 'r') as f:
    c = f.read()

old = '                    mark_responded(followup_id, response.get("snippet", ""))\n\n                    if telegram_id:'
new = '                    mark_responded(followup_id, response.get("snippet", ""))\n\n                    if telegram_id and to_email not in _notified_emails:\n                        _notified_emails.add(to_email)'

if old in c:
    c = c.replace(old, new, 1)
    with open('api/workers/email_monitor_worker.py', 'w') as f:
        f.write(c)
    print("OK: dedup check applied")
else:
    print("FAIL")
