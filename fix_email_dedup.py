with open('api/workers/email_monitor_worker.py', 'r') as f:
    c = f.read()

old = '''            followups = get_active_followups()
            if followups:
                print(f"EMAIL MONITOR: Revisando {len(followups)} emails en seguimiento")'''

new = '''            followups = get_active_followups()
            if followups:
                print(f"EMAIL MONITOR: Revisando {len(followups)} emails en seguimiento")
                _notified_emails = set()  # Dedup: solo notificar 1 vez por destinatario por ciclo'''

if old in c:
    c = c.replace(old, new, 1)
else:
    print("FAIL: patron 1 no encontrado")
    exit()

# Agregar check antes de notificar
old2 = '''                if response and response.get("found"):
                    mark_responded(followup_id, response.get("snippet", ""))
                    if telegram_id:'''

new2 = '''                if response and response.get("found"):
                    mark_responded(followup_id, response.get("snippet", ""))
                    if telegram_id and to_email not in _notified_emails:
                        _notified_emails.add(to_email)'''

if old2 in c:
    c = c.replace(old2, new2, 1)
    with open('api/workers/email_monitor_worker.py', 'w') as f:
        f.write(c)
    print("OK: email monitor dedup applied")
else:
    print("FAIL: patron 2 no encontrado")
