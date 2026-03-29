with open('api/agents/email_agent.py', 'r') as f:
    c = f.read()

old = '''        results = service.people().searchContacts(
            query=name,
            readMask="names,emailAddresses,organizations",
            pageSize=5,
        ).execute()

        contacts = []
        for person in results.get("results", []):'''

new = '''        results = service.people().searchContacts(
            query=name,
            readMask="names,emailAddresses,organizations",
            pageSize=5,
        ).execute()

        print(f"EMAIL CONTACTS: query='{name}', results={len(results.get('results', []))}")

        contacts = []
        for person in results.get("results", []):'''

if old in c:
    c = c.replace(old, new, 1)
    with open('api/agents/email_agent.py', 'w') as f:
        f.write(c)
    print("OK: contacts logging added")
else:
    print("FAIL")
