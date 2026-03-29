with open('api/agents/email_agent.py', 'r') as f:
    c = f.read()

old = '''        results = service.people().searchContacts(
            query=name,
            readMask="names,emailAddresses,organizations",
            pageSize=5,
        ).execute()

        print(f"EMAIL CONTACTS: query=\'{name}\', results={len(results.get(\'results\', []))}")'''

new = '''        results = service.people().searchContacts(
            query=name,
            readMask="names,emailAddresses,organizations",
            pageSize=5,
        ).execute()

        # Google People API a veces retorna 0 en la primera llamada — retry una vez
        if not results.get("results"):
            import time
            time.sleep(1)
            results = service.people().searchContacts(
                query=name,
                readMask="names,emailAddresses,organizations",
                pageSize=5,
            ).execute()

        print(f"EMAIL CONTACTS: query=\'{name}\', results={len(results.get(\'results\', []))}")'''

if old in c:
    c = c.replace(old, new, 1)
    with open('api/agents/email_agent.py', 'w') as f:
        f.write(c)
    print("OK: contacts retry applied")
else:
    print("FAIL")
