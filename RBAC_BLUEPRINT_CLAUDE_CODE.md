# ADA V5 — RBAC COMPLETO: Blueprint para Claude Code

## FECHA: 28 marzo 2026
## PRIORIDAD: CRÍTICA — Completar antes del 8 abril

---

## CONTEXTO

Ada V5 ya tiene RBAC parcial. Este blueprint completa lo que falta para producción multi-tenant con múltiples usuarios por empresa.

### QUÉ YA FUNCIONA (NO TOCAR)
1. `api/services/rbac_service.py` — `check_agent_access()`, `get_report_type_filter()`, `build_sql_rbac_clause()` → COMPLETO
2. `api/services/agent_runner.py` líneas 253-267 — Bloqueo de agentes por permisos → COMPLETO
3. `api/services/memory_service.py` — Filtro RBAC en `search_reports_qdrant()` y `search_vector_store1()` → COMPLETO
4. `api/services/context_builder.py` — Permisos inyectados al prompt del LLM → COMPLETO
5. `api/routers/reports.py` — 13 referencias RBAC → COMPLETO
6. `api/routers/upload.py` — 3 referencias RBAC → COMPLETO

### QUÉ FALTA (ESTE BLUEPRINT)
1. Filtrar `meeting_events` por permisos del usuario
2. Filtrar `prospect_intelligence` por permisos del usuario
3. Crear tabla `audit_log` + servicio de logging
4. Middleware RBAC para endpoints API (portal)
5. Inyectar `user_role` en State de agentes LangGraph

---

## TAREA 1: RBAC en meeting_events

### Archivo: `api/agents/chat_agent.py`
### Línea aprox: 709

**Problema:** La query a `meeting_events` no filtra por permisos. Un usuario con `can_view_finance=false` puede ver reuniones de finanzas.

**Regla de negocio:**
- Admin (usuarios.rol = 'admin') → ve TODAS las reuniones
- Usuario con permisos → ve reuniones donde fue participante O reuniones de áreas a las que tiene acceso
- Usuario sin permisos → solo ve reuniones donde fue participante

**Implementación:**

Buscar en `chat_agent.py` la query que hace `SELECT ... FROM meeting_events` (línea ~709).

Agregar filtro:

```python
# ANTES de la query a meeting_events, obtener permisos
from api.services.rbac_service import get_user_permissions

rbac = get_user_permissions(empresa_id, user_id)

# Construir filtro de reuniones
if rbac.get("is_admin"):
    meeting_rbac_clause = ""
    meeting_rbac_params = {}
else:
    # El usuario solo ve reuniones donde participó
    meeting_rbac_clause = "AND (participants::text ILIKE :user_pattern OR organized_by = :uid)"
    meeting_rbac_params = {"user_pattern": f"%{user_id}%", "uid": user_id}
```

Luego inyectar `meeting_rbac_clause` y `meeting_rbac_params` en la query existente de `meeting_events`, igual que se hace con `rbac_clause` en `search_reports`.

**Test:** Crear 2 reuniones: una con User A como participante, otra sin User A. Verificar que User A solo ve la suya.

---

## TAREA 2: RBAC en prospect_intelligence

### Archivo: `api/agents/commercial_intelligence_agent.py`
### Línea aprox: 484-510

**Problema:** La tabla `prospect_intelligence` recibe INSERT pero no filtra por permisos al leer. Un usuario sin `can_prospect=true` no debería acceder a estos datos.

**Regla de negocio:**
- Admin → ve todo
- Usuario con `can_prospect=true` o `can_view_clients=true` → ve prospectos
- Usuario sin estos permisos → no ve prospectos (pero esto ya se bloquea en agent_runner al negar acceso al agente `prospecting_agent`)

**Implementación:**

En cualquier query SELECT a `prospect_intelligence`, agregar:

```python
from api.services.rbac_service import get_user_permissions

rbac = get_user_permissions(empresa_id, user_id)
if not rbac.get("is_admin"):
    perms = rbac.get("permissions", {})
    if not perms.get("can_prospect") and not perms.get("can_view_clients"):
        return []  # o return "No tienes acceso a prospectos"
```

Buscar TODAS las queries SELECT a `prospect_intelligence` en:
- `api/agents/commercial_intelligence_agent.py`
- `api/agents/prospect_pro_agent.py`
- `api/agents/prospecting_agent.py`
- `api/services/agent_runner.py` (si hay)

**Test:** Usuario sin `can_prospect` no puede ver prospectos aunque tenga acceso directo a la BD.

---

## TAREA 3: Tabla audit_log + Servicio

### Migración SQL: `scripts/migration_audit_log.sql`

```sql
CREATE TABLE IF NOT EXISTS audit_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    empresa_id UUID NOT NULL REFERENCES empresas(id),
    user_id UUID NOT NULL,
    action VARCHAR(50) NOT NULL,      -- 'view_report', 'send_email', 'view_meeting', 'access_agent', 'view_prospect', 'login', 'rbac_blocked'
    resource_type VARCHAR(50),         -- 'ada_reports', 'meeting_events', 'prospect_intelligence', 'email', 'calendar'
    resource_id VARCHAR(255),          -- ID del recurso accedido (report_id, meeting_id, etc.)
    agent_name VARCHAR(50),            -- Agente que procesó la petición
    detail JSONB,                      -- Metadata adicional (query, filtros, etc.)
    ip_address VARCHAR(45),            -- IP del usuario (si disponible)
    created_at TIMESTAMP DEFAULT NOW()
);

-- Índices para queries frecuentes
CREATE INDEX IF NOT EXISTS idx_audit_empresa_id ON audit_log(empresa_id);
CREATE INDEX IF NOT EXISTS idx_audit_user_id ON audit_log(user_id);
CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_log(action);
CREATE INDEX IF NOT EXISTS idx_audit_created_at ON audit_log(created_at);
CREATE INDEX IF NOT EXISTS idx_audit_empresa_created ON audit_log(empresa_id, created_at DESC);

-- Partición: eliminar logs > 90 días (cron job, implementar después)
```

### Servicio: `api/services/audit_service.py`

```python
"""
Audit Service — Registra accesos a datos sensibles.
Cada log incluye: quién, qué, cuándo, desde qué agente.
"""

import json
from datetime import datetime
from api.database import sync_engine
from sqlalchemy import text as sql_text


def log_access(
    empresa_id: str,
    user_id: str,
    action: str,
    resource_type: str = "",
    resource_id: str = "",
    agent_name: str = "",
    detail: dict = None,
) -> None:
    """Registra un acceso en audit_log. No-throw: errores se loguean pero no rompen el flujo."""
    try:
        with sync_engine.connect() as conn:
            conn.execute(
                sql_text("""
                    INSERT INTO audit_log (empresa_id, user_id, action, resource_type, resource_id, agent_name, detail)
                    VALUES (:eid, :uid, :action, :rtype, :rid, :agent, CAST(:detail AS jsonb))
                """),
                {
                    "eid": empresa_id,
                    "uid": user_id,
                    "action": action,
                    "rtype": resource_type,
                    "rid": resource_id,
                    "agent": agent_name,
                    "detail": json.dumps(detail or {}),
                },
            )
            conn.commit()
    except Exception as e:
        print(f"AUDIT: Error logging {action}: {e}")


def log_rbac_blocked(empresa_id: str, user_id: str, agent_name: str, reason: str = "") -> None:
    """Atajo para registrar bloqueo RBAC."""
    log_access(
        empresa_id=empresa_id,
        user_id=user_id,
        action="rbac_blocked",
        agent_name=agent_name,
        detail={"reason": reason},
    )


def get_audit_log(empresa_id: str, limit: int = 50, action_filter: str = "") -> list:
    """Consulta audit log para admin dashboard."""
    try:
        with sync_engine.connect() as conn:
            query = """
                SELECT al.*, u.nombre, u.apellido
                FROM audit_log al
                LEFT JOIN usuarios u ON al.user_id = u.id
                WHERE al.empresa_id = :eid
            """
            params = {"eid": empresa_id, "limit": limit}
            
            if action_filter:
                query += " AND al.action = :action"
                params["action"] = action_filter
            
            query += " ORDER BY al.created_at DESC LIMIT :limit"
            
            rows = conn.execute(sql_text(query), params).fetchall()
            return [
                {
                    "id": str(r.id),
                    "user": f"{r.nombre or ''} {r.apellido or ''}".strip(),
                    "user_id": str(r.user_id),
                    "action": r.action,
                    "resource_type": r.resource_type,
                    "resource_id": r.resource_id,
                    "agent_name": r.agent_name,
                    "detail": r.detail,
                    "created_at": r.created_at.isoformat() if r.created_at else "",
                }
                for r in rows
            ]
    except Exception as e:
        print(f"AUDIT: Error querying log: {e}")
        return []
```

### Dónde integrar `log_access()`:

| Archivo | Punto de inserción | Acción a loguear |
|---|---|---|
| `api/services/agent_runner.py` línea ~253 | Después de `check_agent_access` si `not allowed` | `log_rbac_blocked(empresa_id, user_id, routed_to, reason)` |
| `api/services/agent_runner.py` línea ~275 | Después de seleccionar agente exitosamente | `log_access(empresa_id, user_id, "access_agent", agent_name=routed_to)` |
| `api/agents/chat_agent.py` | Después de query exitosa a `meeting_events` | `log_access(empresa_id, user_id, "view_meeting", "meeting_events")` |
| `api/agents/email_agent.py` | Después de `gmail_send` exitoso | `log_access(empresa_id, user_id, "send_email", "email", detail={"to": to})` |
| `api/services/memory_service.py` | En `search_reports` después de retornar resultados | `log_access(empresa_id, user_id, "view_report", "ada_reports")` |

**IMPORTANTE:** `log_access` nunca debe romper el flujo. Try/except interno. Si falla el logging, el flujo principal continúa.

---

## TAREA 4: Middleware RBAC para endpoints API (Portal)

### Archivo nuevo: `api/middleware/rbac_middleware.py`

```python
"""
RBAC Middleware — Verifica permisos antes de ejecutar endpoints del portal.
Se aplica a endpoints que manejan datos sensibles por empresa.
"""

from functools import wraps
from fastapi import HTTPException, Request
from api.services.rbac_service import get_user_permissions


def require_permission(*required_perms: str):
    """
    Decorator para endpoints. Verifica que el usuario tenga al menos uno de los permisos requeridos.
    
    Uso:
        @router.get("/reports/{empresa_id}")
        @require_permission("can_view_sales", "can_view_finance")
        async def get_reports(empresa_id: str, user: dict = Depends(get_current_user)):
            ...
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Extraer empresa_id y user del contexto
            empresa_id = kwargs.get("empresa_id", "")
            user = kwargs.get("user", {})
            user_id = user.get("user_id", "") if isinstance(user, dict) else ""
            
            if not empresa_id or not user_id:
                raise HTTPException(status_code=403, detail="Acceso denegado")
            
            rbac = get_user_permissions(empresa_id, user_id)
            
            if rbac.get("is_admin"):
                return await func(*args, **kwargs)
            
            perms = rbac.get("permissions", {})
            has_any = any(perms.get(p) for p in required_perms)
            
            if not has_any:
                raise HTTPException(
                    status_code=403,
                    detail="No tienes permiso para acceder a este recurso."
                )
            
            return await func(*args, **kwargs)
        return wrapper
    return decorator


def require_admin():
    """Decorator: solo admin puede acceder."""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            empresa_id = kwargs.get("empresa_id", "")
            user = kwargs.get("user", {})
            user_id = user.get("user_id", "") if isinstance(user, dict) else ""
            
            if not empresa_id or not user_id:
                raise HTTPException(status_code=403, detail="Acceso denegado")
            
            rbac = get_user_permissions(empresa_id, user_id)
            
            if not rbac.get("is_admin"):
                raise HTTPException(status_code=403, detail="Solo administradores.")
            
            return await func(*args, **kwargs)
        return wrapper
    return decorator
```

### Dónde aplicar en routers:

| Router | Endpoint | Permiso requerido |
|---|---|---|
| `dashboard.py` | `get_dashboard` | `can_view_sales` o `can_view_finance` |
| `reports.py` | Todos los GET | Ya implementado (verificar) |
| `upload.py` | POST upload | `can_upload_files` |
| `consolidation_router.py` | GET/POST | `can_view_sales` o `can_view_finance` |
| `users.py` | GET/PUT/DELETE | `require_admin()` |
| `companies.py` | PUT (editar empresa) | `require_admin()` |
| `oauth.py` | `disconnect_service` | `require_admin()` |
| `budget_router.py` | GET usage | `can_view_finance` o admin |

**Endpoints que NO necesitan RBAC adicional:**
- `auth.py` — Autenticación (pre-RBAC)
- `oauth.py` — `get_oauth_url`, callbacks (necesario para onboarding)
- `webhooks.py` — Webhooks externos (tienen su propia auth)
- `onboarding_router.py` — Solo se usa durante setup
- `chat.py` — Ya pasa por `agent_runner` que tiene RBAC

---

## TAREA 5: user_role en State de agentes

### Archivos a modificar:
- `api/agents/chat_agent.py`
- `api/agents/email_agent.py`
- `api/agents/calendar_agent.py`
- `api/agents/excel_agent.py`
- `api/agents/document_agent.py`
- `api/agents/prospecting_agent.py`
- `api/agents/prospect_pro_agent.py`
- `api/agents/commercial_intelligence_agent.py`
- `api/agents/cross_agent.py`

### Cambio en cada agente:

1. Agregar `user_role` al TypedDict del State:

```python
class XxxState(TypedDict, total=False):
    # ... campos existentes ...
    user_role: str          # "admin", "gerente", "operador", etc.
    user_permissions: dict  # {"can_view_sales": true, ...}
```

2. En `api/services/agent_runner.py`, antes de invocar el agente, inyectar:

```python
from api.services.rbac_service import get_user_permissions

rbac = get_user_permissions(empresa_id, user_id)
state["user_role"] = rbac.get("role_title", "")
state["user_permissions"] = rbac.get("permissions", {})
state["is_admin"] = rbac.get("is_admin", False)
```

Buscar dónde se construye el `state` dict antes de `agent.ainvoke(state)` (debería estar alrededor de la línea 280-320 en agent_runner.py).

---

## ORDEN DE EJECUCIÓN

1. **Migración SQL** — Crear tabla `audit_log`
2. **audit_service.py** — Crear el servicio
3. **Integrar audit en agent_runner** — Log de accesos y bloqueos
4. **RBAC meeting_events** — Filtrar en chat_agent.py
5. **RBAC prospect_intelligence** — Filtrar en commercial_intelligence_agent.py
6. **user_role en State** — Inyectar en agent_runner, agregar a TypedDicts
7. **Middleware RBAC** — Crear middleware + aplicar en routers
8. **Tests** — Verificar que usuario sin permisos no accede a datos restringidos

## REGLAS PARA CLAUDE CODE

1. **NUNCA** remover código RBAC existente. Solo agregar.
2. **CADA** query SELECT a tablas sensibles (`ada_reports`, `meeting_events`, `prospect_intelligence`) debe incluir filtro por permisos.
3. **audit_service.log_access()** es no-bloqueante. Si falla el logging, el flujo principal continúa.
4. **Todos los archivos nuevos** van con `empresa_id` como parámetro obligatorio (no default vacío).
5. **Hacer commit** después de cada tarea completada con mensaje descriptivo.
6. **Probar** cada tarea antes de pasar a la siguiente.

## DEPLOY

```bash
# 1. Migración SQL
PGPASSWORD=mK9Qw2Jd5ZxT7cLp psql -h localhost -U postgres -d ada -f scripts/migration_audit_log.sql

# 2. Copiar archivos nuevos y modificados

# 3. Restart
docker compose down && docker compose up -d

# 4. Verificar
docker exec ada_api python3 -c "
from api.services.audit_service import log_access, get_audit_log
log_access('e5886d95-71bb-44b4-a0a9-5d9599e2b6fb', '633e8138-49aa-4540-9aa3-44436bd1b35b', 'test', 'test')
logs = get_audit_log('e5886d95-71bb-44b4-a0a9-5d9599e2b6fb', limit=1)
print(f'Audit log OK: {len(logs)} entries')
"
```
