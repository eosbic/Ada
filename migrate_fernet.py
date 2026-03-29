import os
from cryptography.fernet import Fernet
from sqlalchemy import text as sql_text
from api.database import sync_engine

OLD_KEY = os.getenv('FERNET_KEY').strip()
NEW_KEY = 'alGwoAsDYJjh9ov51Hh-8Rl04LMUiufJJPUYMuZ968w='

old_f = Fernet(OLD_KEY.encode())
new_f = Fernet(NEW_KEY.encode())

with sync_engine.connect() as conn:
    rows = conn.execute(sql_text('SELECT id, provider, encrypted_data, oauth2_refresh_token_encrypted FROM tenant_credentials')).fetchall()
    print(f'Credenciales a migrar: {len(rows)}')
    migrated = 0
    errors = 0
    for row in rows:
        try:
            new_enc = None
            new_refresh = None
            if row.encrypted_data:
                dec = old_f.decrypt(row.encrypted_data.encode())
                new_enc = new_f.encrypt(dec).decode()
            if row.oauth2_refresh_token_encrypted:
                dec_r = old_f.decrypt(row.oauth2_refresh_token_encrypted.encode())
                new_refresh = new_f.encrypt(dec_r).decode()
            conn.execute(
                sql_text('UPDATE tenant_credentials SET encrypted_data = :enc, oauth2_refresh_token_encrypted = :ref WHERE id = :id'),
                {'enc': new_enc, 'ref': new_refresh, 'id': row.id}
            )
            migrated += 1
            print(f'  OK {row.provider} (id={row.id})')
        except Exception as e:
            errors += 1
            print(f'  FAIL {row.provider} (id={row.id}): {e}')
    if errors == 0:
        conn.commit()
        print(f'{migrated} credenciales re-encriptadas')
    else:
        conn.rollback()
        print(f'{errors} errores. ROLLBACK.')
