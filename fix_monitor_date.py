with open('api/workers/email_monitor_worker.py', 'r') as f:
    c = f.read()

old = '''        if isinstance(results, list):
            for email in results:
                email_from = email.get("from", "").lower()
                if to_email.lower() in email_from:
                    snippet = email.get("snippet", email.get("subject", ""))
                    return {
                        "found": True,
                        "subject": email.get("subject", ""),
                        "snippet": snippet[:300],
                        "from": email.get("from", ""),
                        "message_id": email.get("id", ""),
                    }'''

new = '''        if isinstance(results, list):
            from datetime import datetime, timezone
            from email.utils import parsedate_to_datetime
            # Solo considerar respuestas POSTERIORES al envio del followup
            sent_dt = None
            if sent_at:
                if isinstance(sent_at, datetime):
                    sent_dt = sent_at.replace(tzinfo=timezone.utc) if not sent_at.tzinfo else sent_at
                elif isinstance(sent_at, str):
                    try:
                        sent_dt = datetime.fromisoformat(sent_at).replace(tzinfo=timezone.utc)
                    except Exception:
                        pass

            for email in results:
                email_from = email.get("from", "").lower()
                if to_email.lower() in email_from:
                    # Verificar que la respuesta es posterior al envio
                    if sent_dt:
                        email_date_str = email.get("date", "")
                        try:
                            email_dt = parsedate_to_datetime(email_date_str)
                            if email_dt <= sent_dt:
                                continue  # Respuesta anterior al envio, ignorar
                        except Exception:
                            pass

                    snippet = email.get("snippet", email.get("subject", ""))
                    return {
                        "found": True,
                        "subject": email.get("subject", ""),
                        "snippet": snippet[:300],
                        "from": email.get("from", ""),
                        "message_id": email.get("id", ""),
                    }'''

if old in c:
    c = c.replace(old, new, 1)
    with open('api/workers/email_monitor_worker.py', 'w') as f:
        f.write(c)
    print("OK: monitor date filter applied")
else:
    print("FAIL")
