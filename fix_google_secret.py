import os, json
from cryptography.fernet import Fernet
from sqlalchemy import text as sql_text
from api.database import sync_engine

FERNET_KEY = os.getenv("FERNET_KEY").strip()
f = Fernet(FERNET_KEY.encode())

NEW_CLIENT_SECRET = "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"

with sync_engine.connect() as conn:
    rows = conn.execute(sql_text(
        "SELECT id, provider, encrypted_data FROM tenant_credentials WHERE provider LIKE 'g%'"
    )).fetchall()

    print(f"Credenciales Google: {len(rows)}")
    updated = 0

    for row in rows:
        try:
            decrypted = f.decrypt(row.encrypted_data.encode())
            data = json.loads(decrypted)

            old_secret = data.get("client_secret", "")
            if old_secret != NEW_CLIENT_SECRET:
                data["client_secret"] = NEW_CLIENT_SECRET
                re_encrypted = f.encrypt(json.dumps(data).encode()).decode()
                conn.execute(
                    sql_text("UPDATE tenant_credentials SET encrypted_data = :enc WHERE id = :id"),
                    {"enc": re_encrypted, "id": row.id}
                )
                updated += 1
                print(f"  OK {row.provider} (id={row.id}) secret actualizado")
            else:
                print(f"  -- {row.provider} (id={row.id}) ya tiene el secret correcto")
        except Exception as e:
            print(f"  FAIL {row.provider} (id={row.id}): {e}")

    conn.commit()
    print(f"\n{updated} credenciales actualizadas")
