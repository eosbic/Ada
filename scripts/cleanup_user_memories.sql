-- Limpiar memorias basura extraídas durante onboarding/configuración
DELETE FROM user_memories WHERE fact ILIKE '%Comparte enlaces%';
DELETE FROM user_memories WHERE fact ILIKE '%Conoce Treble%';
DELETE FROM user_memories WHERE fact ILIKE '%Conoce Leadsales%';
DELETE FROM user_memories WHERE fact ILIKE '%Power BI%';
DELETE FROM user_memories WHERE fact ILIKE '%Tableau%';
DELETE FROM user_memories WHERE fact ILIKE '%gerente, CEO, administrador%';
DELETE FROM user_memories WHERE fact ILIKE '%jefe de compras%';
DELETE FROM user_memories WHERE fact ILIKE '%Google Drive%' AND category != 'contact';
DELETE FROM user_memories WHERE fact ILIKE '%Facebook%' AND category != 'contact';
DELETE FROM user_memories WHERE fact ILIKE '%lenguaje formal y técnico%';
DELETE FROM user_memories WHERE fact ILIKE '%automatización de procesos%';
DELETE FROM user_memories WHERE fact ILIKE '%agentes de IA%';
DELETE FROM user_memories WHERE fact ILIKE '%big data%';
DELETE FROM user_memories WHERE fact ILIKE '%sectores de servicios%';
DELETE FROM user_memories WHERE fact ILIKE '%considerando usar google%';
DELETE FROM user_memories WHERE fact ILIKE '%notion y plane%' AND category = 'interest';
