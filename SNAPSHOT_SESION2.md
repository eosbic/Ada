# SNAPSHOT DE SESIÓN — ADA V5.0 (Actualizado 26 Mar 2026 — Sesión 2 Final)

## INFRA
- **REPO:** https://github.com/eosbic/Ada
- **VPS CONTABO:** ssh -o ServerAliveInterval=60 root@62.171.150.83
- **CÓDIGO EN VPS:** /var/ada/ada-langgraph_v2 (branch github-main)
- **REMOTE GITHUB:** `github` apunta a eosbic/Ada
- **PUSH COMMAND:** `git push github github-main:main` (NO origin, origin es GitLab)
- **PORTAL WEB:** https://backend-ada.duckdns.org/portal
- **DATABASE:** PostgreSQL en 62.171.150.83:5432, user postgres, pass mK9Qw2Jd5ZxT7cLp, db ada
- **QDRANT:** https://1e9adeda-e63f-462b-a6af-64b6d1eafd89.us-east4-0.gcp.cloud.qdrant.io:6333
- **EMPRESA EOS BIC:** empresa_id = e5886d95-71bb-44b4-a0a9-5d9599e2b6fb
- **USUARIO WILLIAM:** user_id = 633e8138-49aa-4540-9aa3-44436bd1b35b

---

## ESTADO ACTUAL DE LA BD
- **1 empresa:** EOS BIC
- **1 usuario:** William (admin)
- **12 reportes** de prueba (excel_analysis, proactive_briefing, email_summary, notion_summary)
- BD limpia, lista para producción

---

## COMPLETADO EN ESTA SESIÓN

### Limpieza del repositorio
1. .gitignore completo (__pycache__, generated_artifacts, boveda, .claude/, env backups)
2. 184 .pyc + 14 generated_artifacts eliminados del tracking
3. Código muerto eliminado (main_agent.py, multi_tenant_patch.py)
4. requirements.txt sin duplicados, README.md con documentación real
5. portal/index.html en Git

### Backend
6. portal_router.py — endpoint /portal en router dedicado (nunca más se pierde en merge)
7. main.py — lifespan context manager + logging estructurado
8. security.py — datetime fix + refresh token 7 días
9. auth.py — POST /auth/refresh + login retorna refresh_token

### Reportes Visuales (FUNCIONAL)
10. visual_report_service.py — genera HTML interactivo con Chart.js, múltiples gráficos, dark/light mode
11. GET /api/v1/reports/{id}/visual — renderiza reporte como dashboard visual
12. excel_agent.py — metrics_summary enriquecido (total, promedio, mediana, min, max, variacion, rankings)
13. excel_agent.py — _retail_metrics() para todas las industrias + report_id en ExcelState
14. bot/telegram_bot.py — link 📊 Visual al final del mensaje
15. portal/index.html — botón 📊 Visual al lado de Copiar y PDF

### Consolidation Agent (FUNCIONAL)
16. Verificado: el agente puede comparar múltiples informes correctamente

---

## TAREA PARA CLAUDE CODE: PORTAL DE ADMINISTRACIÓN DE CLIENTES

### Contexto
Actualmente para crear empresas, usuarios, asignar roles hay que hacerlo por código SQL. Necesitamos un portal de administración web independiente del portal principal de ADA.

### Endpoints existentes que ya sirven
- `POST /auth/login` — login
- `POST /auth/refresh` — refresh token
- `GET /panel/dashboard/` — dashboard datos empresa
- `POST /config/dna/update` — actualizar perfil empresa
- `DELETE /usuarios/team/members/{user_id}` — borrar usuario
- `GET /admin/auth/login` — login admin (ya existe)
- `GET /admin/api/*` — endpoints admin (ya existen en admin_router.py)

### Lo que necesitamos construir

**Un portal admin accesible en `/admin`** (HTML SPA autocontenido como el portal principal) con:

#### 1. Login Admin
- Pantalla de login separada del portal de clientes
- Usa el endpoint existente `/admin/auth/login`
- Solo usuarios con rol "superadmin" pueden acceder

#### 2. Dashboard Principal
- Total empresas, total usuarios, total reportes
- Gráfico de reportes generados por día/semana
- Empresas activas (con actividad reciente)

#### 3. CRUD Empresas
- **Listar** todas las empresas con: nombre, sector, fecha creación, # usuarios, # reportes
- **Crear** empresa nueva: nombre, sector
- **Editar** empresa: nombre, sector
- **Eliminar** empresa (con confirmación, cascade borra usuarios y reportes)
- **Ver detalle**: usuarios de esa empresa, reportes, perfil DNA

#### 4. CRUD Usuarios
- **Listar** usuarios por empresa: nombre, email, rol, fecha creación, telegram vinculado
- **Crear** usuario: nombre, email, contraseña, rol, empresa_id
- **Editar** usuario: nombre, rol, contraseña
- **Eliminar** usuario (con confirmación)
- **Roles disponibles**: admin, member, vendedor, gerente, logistica, contador, marketing, rrhh, legal

#### 5. Vista de Reportes por Empresa
- Tabla con reportes: título, tipo, fecha, link al visual
- Poder archivar/eliminar reportes
- Contador de reportes por tipo

### Tablas de BD relevantes
```sql
-- Empresas
empresas(id UUID, nombre TEXT, sector TEXT, created_at TIMESTAMP)

-- Usuarios
usuarios(id UUID, empresa_id UUID FK, email TEXT UNIQUE, nombre TEXT, password TEXT, rol TEXT, telegram_id TEXT, is_active BOOLEAN, created_at TIMESTAMP)

-- Perfil empresa
ada_company_profile(empresa_id UUID PK FK, company_name TEXT, industry_type TEXT, business_description TEXT, custom_prompt TEXT, ...)

-- Reportes
ada_reports(id UUID, empresa_id UUID FK, title TEXT, report_type TEXT, markdown_content TEXT, metrics_summary JSONB, alerts JSONB, created_at TIMESTAMP, ...)
```

### Endpoints admin que hay que crear/completar
Revisar `api/routers/admin_router.py` y `api/routers/admin_auth.py` — ya tienen algo implementado. Completar lo que falte:

```
POST   /admin/auth/login              → login superadmin
GET    /admin/api/empresas             → listar empresas con stats
POST   /admin/api/empresas             → crear empresa
PUT    /admin/api/empresas/{id}        → editar empresa
DELETE /admin/api/empresas/{id}        → eliminar empresa (cascade)
GET    /admin/api/empresas/{id}/users  → usuarios de empresa
POST   /admin/api/users               → crear usuario
PUT    /admin/api/users/{id}           → editar usuario
DELETE /admin/api/users/{id}           → eliminar usuario
GET    /admin/api/empresas/{id}/reports → reportes de empresa
DELETE /admin/api/reports/{id}         → eliminar reporte
GET    /admin/api/stats                → stats generales (dashboard)
```

### Diseño visual
- Mismo estilo dark del portal principal
- Responsive
- Modales de confirmación antes de borrar
- Tablas con búsqueda/filtro

### Cómo servir el admin portal
Crear `portal/admin.html` y un `admin_portal_router.py` que sirva `GET /admin` → FileResponse(admin.html), igual que el portal principal.

### Para crear el superadmin
```sql
-- Crear superadmin si no existe
INSERT INTO usuarios (empresa_id, email, nombre, password, rol)
VALUES ('e5886d95-71bb-44b4-a0a9-5d9599e2b6fb', 'admin@eosbic.com', 'Super Admin', '<bcrypt_hash>', 'superadmin')
ON CONFLICT (email) DO NOTHING;
```

### Deploy
```bash
cd /var/ada/ada-langgraph_v2
git add -A
git commit -m "feat: admin portal"
git push github github-main:main
docker compose restart
```

---

## PROBLEMAS RESUELTOS (NO SON RECURRENTES)
- ~~Endpoint /portal se pierde en merge~~ → portal_router.py
- ~~JWT sin refresh~~ → POST /auth/refresh
- ~~184 .pyc en Git~~ → .gitignore
- ~~datetime.utcnow() deprecated~~ → datetime.now(timezone.utc)

## ARQUITECTURA
```
api/main.py                      → FastAPI app (lifespan + logging)
api/routers/                     → Endpoints HTTP
api/routers/portal_router.py     → Sirve /portal (frontend cliente)
api/routers/admin_auth.py        → Auth admin (ya existe)
api/routers/admin_router.py      → Endpoints admin (ya existe, completar)
api/agents/                      → 16 agentes LangGraph
api/services/                    → 30 servicios
api/services/visual_report_service.py → Reportes HTML interactivos
bot/telegram_bot.py              → Bot multimodal
portal/index.html                → Portal cliente SPA
portal/admin.html                → Portal admin SPA (CREAR)
```
