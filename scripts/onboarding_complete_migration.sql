-- Onboarding completo: campos faltantes en empresa y usuarios

-- Empresa
ALTER TABLE ada_company_profile
    ADD COLUMN IF NOT EXISTS address TEXT DEFAULT '',
    ADD COLUMN IF NOT EXISTS phone TEXT DEFAULT '',
    ADD COLUMN IF NOT EXISTS tax_id TEXT DEFAULT '',
    ADD COLUMN IF NOT EXISTS timezone TEXT DEFAULT 'America/Bogota',
    ADD COLUMN IF NOT EXISTS language TEXT DEFAULT 'es';

-- Usuarios: separar nombre + agregar teléfono
ALTER TABLE usuarios
    ADD COLUMN IF NOT EXISTS apellido TEXT DEFAULT '',
    ADD COLUMN IF NOT EXISTS phone TEXT DEFAULT '',
    ADD COLUMN IF NOT EXISTS country_code TEXT DEFAULT '+57';
