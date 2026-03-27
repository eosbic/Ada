"""
Admin Router — CRUD para gestion de clientes beta del portal EOS IA.
Requiere JWT admin (get_current_admin dependency).
"""

import json
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from typing import Optional
from sqlalchemy import text as sql_text
from api.database import AsyncSessionLocal
from api.routers.admin_auth import get_current_admin


router = APIRouter()


# ─── Helpers ────────────────────────────────────────────


async def _audit(admin_id: str, action: str, target_type: str, target_id: str, details: dict, ip: str = ""):
    """Registra accion en admin_audit_log."""
    try:
        async with AsyncSessionLocal() as db:
            await db.execute(
                sql_text("""
                    INSERT INTO admin_audit_log
                        (admin_user_id, action, target_type, target_id, details, ip_address)
                    VALUES (:aid, :action, :ttype, :tid, :details, :ip)
                """),
                {
                    "aid": admin_id,
                    "action": action,
                    "ttype": target_type,
                    "tid": target_id,
                    "details": json.dumps(details, ensure_ascii=False, default=str),
                    "ip": ip,
                },
            )
            await db.commit()
    except Exception as e:
        print(f"ADMIN AUDIT error: {e}")


def _get_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


# ─── Plan catalog ──────────────────────────────────────

PLAN_CATALOG = {
    "start": {
        "monthly_limit": 50,
        "base_users": 3,
        "price_per_extra_user": 16.67,
        "monthly_analyses_limit": 30,
        "models": ["gemini-flash", "qwen-72b"],
    },
    "premium": {
        "monthly_limit": 70,
        "base_users": 3,
        "price_per_extra_user": 23.00,
        "monthly_analyses_limit": 50,
        "models": ["gemini-flash", "qwen-72b", "sonnet"],
    },
    "enterprise": {
        "monthly_limit": 90,
        "base_users": 3,
        "price_per_extra_user": 30.00,
        "monthly_analyses_limit": 80,
        "models": ["gemini-flash", "qwen-72b", "sonnet", "opus"],
    },
}

ANALYSIS_PACKS = {
    "basic_pack":  {"analyses": 20,  "price": 8},
    "pro_pack":    {"analyses": 50,  "price": 15},
    "mega_pack":   {"analyses": 150, "price": 35},
}


def _calc_pricing(plan_type: str, extra_users: int = 0) -> dict:
    """Calcula precio total, max_users y limites para un plan + extras."""
    plan = PLAN_CATALOG[plan_type]
    max_users = plan["base_users"] + extra_users
    monthly_limit = plan["monthly_limit"] + (extra_users * plan["price_per_extra_user"])
    return {
        "max_users": max_users,
        "monthly_limit": round(monthly_limit, 2),
        "monthly_analyses_limit": plan["monthly_analyses_limit"],
        "base_users": plan["base_users"],
        "extra_users": extra_users,
        "price_per_extra_user": plan["price_per_extra_user"],
    }


# ─── Request models ────────────────────────────────────


class CreateEmpresaRequest(BaseModel):
    nombre: str
    sector: str = "generic"
    plan_type: str = "start"
    extra_users: int = 0
    admin_nombre: Optional[str] = None
    admin_email: Optional[str] = None
    admin_password: Optional[str] = None


class UpdateEmpresaRequest(BaseModel):
    nombre: Optional[str] = None
    sector: Optional[str] = None
    plan_type: Optional[str] = None
    extra_users: Optional[int] = None


class CreateUsuarioRequest(BaseModel):
    empresa_id: str
    email: str
    nombre: str
    password: str
    rol: str = "member"


class UpdateUsuarioRequest(BaseModel):
    nombre: Optional[str] = None
    rol: Optional[str] = None
    password: Optional[str] = None


class UpdateBudgetRequest(BaseModel):
    monthly_limit: float


# ─── Endpoints ──────────────────────────────────────────


@router.get("/plans")
async def list_plans(admin: dict = Depends(get_current_admin)):
    """Catalogo de planes y packs de analisis."""
    return {"plans": PLAN_CATALOG, "analysis_packs": ANALYSIS_PACKS}


@router.get("/dashboard")
async def dashboard(admin: dict = Depends(get_current_admin)):
    """Metricas globales del sistema."""
    async with AsyncSessionLocal() as db:
        total_empresas = (await db.execute(sql_text("SELECT COUNT(*) FROM empresas"))).scalar()
        total_usuarios = (await db.execute(sql_text("SELECT COUNT(*) FROM usuarios"))).scalar()

        reportes_30d = (await db.execute(sql_text(
            "SELECT COUNT(*) FROM ada_reports WHERE created_at >= NOW() - INTERVAL '30 days'"
        ))).scalar()

        reportes_total = (await db.execute(sql_text("SELECT COUNT(*) FROM ada_reports"))).scalar()

        creds_activas = (await db.execute(sql_text(
            "SELECT COUNT(*) FROM tenant_credentials WHERE is_active = TRUE"
        ))).scalar()

        budget_alerts = (await db.execute(sql_text(
            "SELECT COUNT(*) FROM budget_limits WHERE alert_sent_this_month = TRUE"
        ))).scalar()

        empresas_sector = (await db.execute(sql_text(
            "SELECT sector, COUNT(*) as count FROM empresas GROUP BY sector ORDER BY count DESC LIMIT 10"
        ))).fetchall()

        admin_logins = (await db.execute(sql_text(
            "SELECT a.nombre, a.email, a.last_login FROM admin_users a WHERE a.last_login IS NOT NULL ORDER BY a.last_login DESC LIMIT 5"
        ))).fetchall()

    return {
        "total_empresas": total_empresas,
        "total_usuarios": total_usuarios,
        "reportes_30d": reportes_30d,
        "reportes_total": reportes_total,
        "credenciales_activas": creds_activas,
        "budget_alerts": budget_alerts,
        "empresas_por_sector": [{"sector": r.sector or "sin_sector", "count": r.count} for r in empresas_sector],
        "ultimos_logins_admin": [
            {"nombre": r.nombre, "email": r.email, "last_login": str(r.last_login)}
            for r in admin_logins
        ],
    }


@router.get("/empresas")
async def list_empresas(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    search: str = Query(""),
    admin: dict = Depends(get_current_admin),
):
    """Lista empresas con paginacion y busqueda."""
    offset = (page - 1) * limit

    search_clause = ""
    params = {"lim": limit, "off": offset}
    if search:
        search_clause = "WHERE e.nombre ILIKE :search OR e.sector ILIKE :search"
        params["search"] = f"%{search}%"

    async with AsyncSessionLocal() as db:
        rows = (await db.execute(sql_text(f"""
            SELECT e.id, e.nombre, e.sector, e.created_at,
                   (SELECT COUNT(*) FROM usuarios u WHERE u.empresa_id = e.id) as user_count,
                   (SELECT COUNT(*) FROM ada_reports r WHERE r.empresa_id = e.id) as report_count,
                   (SELECT COUNT(*) FROM tenant_credentials tc WHERE tc.empresa_id = e.id AND tc.is_active = TRUE) as credential_count,
                   bl.plan_type, bl.monthly_limit, bl.used_this_month, bl.topup_balance, bl.max_users,
                   bl.base_users, bl.extra_users, bl.price_per_extra_user,
                   bl.monthly_analyses_limit, bl.analyses_used_this_month
            FROM empresas e
            LEFT JOIN budget_limits bl ON bl.empresa_id = e.id
            {search_clause}
            ORDER BY e.created_at DESC
            LIMIT :lim OFFSET :off
        """), params)).fetchall()

        count_params = {}
        count_clause = ""
        if search:
            count_clause = "WHERE nombre ILIKE :search OR sector ILIKE :search"
            count_params["search"] = f"%{search}%"
        total = (await db.execute(sql_text(f"SELECT COUNT(*) FROM empresas {count_clause}"), count_params)).scalar()

    return {
        "page": page,
        "limit": limit,
        "total": total,
        "data": [
            {
                "id": str(r.id),
                "nombre": r.nombre,
                "sector": r.sector,
                "created_at": str(r.created_at),
                "user_count": r.user_count,
                "report_count": r.report_count,
                "credential_count": r.credential_count,
                "plan_type": r.plan_type,
                "monthly_limit": float(r.monthly_limit or 0),
                "used_this_month": float(r.used_this_month or 0),
                "topup_balance": float(r.topup_balance or 0),
                "max_users": r.max_users or 3,
                "base_users": r.base_users or 3,
                "extra_users": r.extra_users or 0,
                "price_per_extra_user": float(r.price_per_extra_user or 0),
                "monthly_analyses_limit": r.monthly_analyses_limit or 30,
                "analyses_used": r.analyses_used_this_month or 0,
            }
            for r in rows
        ],
    }


@router.get("/empresas/{empresa_id}")
async def get_empresa(empresa_id: str, admin: dict = Depends(get_current_admin)):
    """Detalle completo de una empresa."""
    async with AsyncSessionLocal() as db:
        empresa = (await db.execute(
            sql_text("SELECT id, nombre, sector, created_at FROM empresas WHERE id = :id"),
            {"id": empresa_id},
        )).fetchone()

        if not empresa:
            raise HTTPException(status_code=404, detail="Empresa no encontrada")

        usuarios = (await db.execute(
            sql_text("SELECT id, email, nombre, rol, telegram_id, created_at FROM usuarios WHERE empresa_id = :id ORDER BY created_at"),
            {"id": empresa_id},
        )).fetchall()

        credentials = (await db.execute(
            sql_text("SELECT id, provider, is_active, created_at FROM tenant_credentials WHERE empresa_id = :id"),
            {"id": empresa_id},
        )).fetchall()

        budget = (await db.execute(
            sql_text("SELECT plan_type, monthly_limit, used_this_month, total_tokens_this_month, topup_balance, alert_sent_this_month, max_users, base_users, extra_users, price_per_extra_user, monthly_analyses_limit, analyses_used_this_month FROM budget_limits WHERE empresa_id = :id"),
            {"id": empresa_id},
        )).fetchone()

        profile = (await db.execute(
            sql_text("SELECT company_name, industry_type FROM ada_company_profile WHERE empresa_id = :id"),
            {"id": empresa_id},
        )).fetchone()

        reportes = (await db.execute(
            sql_text("SELECT id, title, report_type, source_file, generated_by, created_at FROM ada_reports WHERE empresa_id = :id AND is_archived = FALSE ORDER BY created_at DESC LIMIT 10"),
            {"id": empresa_id},
        )).fetchall()

    return {
        "empresa": {
            "id": str(empresa.id),
            "nombre": empresa.nombre,
            "sector": empresa.sector,
            "created_at": str(empresa.created_at),
        },
        "usuarios": [
            {
                "id": str(u.id), "email": u.email, "nombre": u.nombre,
                "rol": u.rol, "has_telegram": bool(u.telegram_id),
                "created_at": str(u.created_at),
            }
            for u in usuarios
        ],
        "credentials": [
            {
                "id": str(c.id), "provider": c.provider,
                "is_active": c.is_active, "created_at": str(c.created_at),
            }
            for c in credentials
        ],
        "budget": {
            "plan_type": budget.plan_type if budget else None,
            "monthly_limit": float(budget.monthly_limit or 0) if budget else 0,
            "used_this_month": float(budget.used_this_month or 0) if budget else 0,
            "total_tokens_this_month": int(budget.total_tokens_this_month or 0) if budget else 0,
            "topup_balance": float(budget.topup_balance or 0) if budget else 0,
            "alert_sent": budget.alert_sent_this_month if budget else False,
            "max_users": budget.max_users if budget else 3,
            "base_users": budget.base_users if budget else 3,
            "extra_users": budget.extra_users if budget else 0,
            "price_per_extra_user": float(budget.price_per_extra_user or 0) if budget else 0,
            "monthly_analyses_limit": budget.monthly_analyses_limit if budget else 30,
            "analyses_used": budget.analyses_used_this_month if budget else 0,
        } if budget else None,
        "profile": {
            "company_name": profile.company_name if profile else None,
            "industry_type": profile.industry_type if profile else None,
            
        } if profile else None,
        "reportes": [
            {
                "id": str(r.id), "title": r.title, "report_type": r.report_type,
                "source_file": r.source_file, "generated_by": r.generated_by,
                "created_at": str(r.created_at),
            }
            for r in reportes
        ],
    }


@router.post("/empresas")
async def create_empresa(
    req: CreateEmpresaRequest,
    request: Request,
    admin: dict = Depends(get_current_admin),
):
    """Crear empresa + budget con plan y usuarios extra."""
    if admin["role"] not in ("superadmin", "admin"):
        raise HTTPException(status_code=403, detail="Permiso insuficiente")

    if req.plan_type not in PLAN_CATALOG:
        raise HTTPException(status_code=400, detail=f"Plan invalido. Opciones: {', '.join(PLAN_CATALOG.keys())}")

    pricing = _calc_pricing(req.plan_type, req.extra_users)

    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                sql_text("INSERT INTO empresas (nombre, sector) VALUES (:nombre, :sector) RETURNING id"),
                {"nombre": req.nombre, "sector": req.sector},
            )
            empresa_id = result.fetchone()[0]

            await db.execute(
                sql_text("""
                    INSERT INTO budget_limits
                        (empresa_id, plan_type, monthly_limit, max_users, base_users,
                         extra_users, price_per_extra_user, monthly_analyses_limit)
                    VALUES (:eid, :plan, :limit, :maxu, :base, :extra, :ppeu, :anlimit)
                    ON CONFLICT (empresa_id) DO UPDATE SET
                        plan_type = :plan, monthly_limit = :limit, max_users = :maxu,
                        base_users = :base, extra_users = :extra,
                        price_per_extra_user = :ppeu, monthly_analyses_limit = :anlimit
                """),
                {
                    "eid": empresa_id, "plan": req.plan_type,
                    "limit": pricing["monthly_limit"], "maxu": pricing["max_users"],
                    "base": pricing["base_users"], "extra": pricing["extra_users"],
                    "ppeu": pricing["price_per_extra_user"],
                    "anlimit": pricing["monthly_analyses_limit"],
                },
            )
            # Crear usuario admin si se proporcionaron los datos
            admin_user_id = None
            if req.admin_email and req.admin_nombre and req.admin_password:
                from api.security import hash_password as hash_pw
                user_result = await db.execute(
                    sql_text("""
                        INSERT INTO usuarios (empresa_id, email, nombre, password, rol)
                        VALUES (:eid, :email, :nombre, :password, 'admin')
                        RETURNING id
                    """),
                    {
                        "eid": empresa_id,
                        "email": req.admin_email.strip().lower(),
                        "nombre": req.admin_nombre,
                        "password": hash_pw(req.admin_password),
                    },
                )
                admin_user_id = str(user_result.fetchone()[0])

            await db.commit()

        audit_details = {
            "nombre": req.nombre, "plan": req.plan_type, "extra_users": req.extra_users,
            "monthly_limit": pricing["monthly_limit"],
        }
        if admin_user_id:
            audit_details["admin_user_created"] = req.admin_email
        await _audit(admin["admin_id"], "create_empresa", "empresa", str(empresa_id),
                     audit_details, _get_ip(request))

        resp = {"id": str(empresa_id), "nombre": req.nombre, "plan_type": req.plan_type, **pricing}
        if admin_user_id:
            resp["admin_user_id"] = admin_user_id
            resp["admin_email"] = req.admin_email
        return resp

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/empresas/{empresa_id}")
async def update_empresa(
    empresa_id: str,
    req: UpdateEmpresaRequest,
    request: Request,
    admin: dict = Depends(get_current_admin),
):
    """Actualizar empresa: nombre, sector, plan, extra_users."""
    empresa_updates = {}
    if req.nombre is not None:
        empresa_updates["nombre"] = req.nombre
    if req.sector is not None:
        empresa_updates["sector"] = req.sector

    has_budget_change = req.plan_type is not None or req.extra_users is not None

    if not empresa_updates and not has_budget_change:
        raise HTTPException(status_code=400, detail="Nada que actualizar")

    async with AsyncSessionLocal() as db:
        if empresa_updates:
            set_clauses = ", ".join([f"{k} = :{k}" for k in empresa_updates])
            await db.execute(
                sql_text(f"UPDATE empresas SET {set_clauses} WHERE id = :id"),
                {**empresa_updates, "id": empresa_id},
            )

        if has_budget_change:
            # Leer valores actuales
            cur = (await db.execute(
                sql_text("SELECT plan_type, extra_users FROM budget_limits WHERE empresa_id = :eid"),
                {"eid": empresa_id},
            )).fetchone()
            current_plan = cur.plan_type if cur else "start"
            current_extra = cur.extra_users if cur else 0

            new_plan = req.plan_type or current_plan
            new_extra = req.extra_users if req.extra_users is not None else current_extra

            if new_plan not in PLAN_CATALOG:
                raise HTTPException(status_code=400, detail=f"Plan invalido. Opciones: {', '.join(PLAN_CATALOG.keys())}")

            pricing = _calc_pricing(new_plan, new_extra)

            await db.execute(
                sql_text("""
                    UPDATE budget_limits SET
                        plan_type = :plan, monthly_limit = :limit, max_users = :maxu,
                        base_users = :base, extra_users = :extra,
                        price_per_extra_user = :ppeu, monthly_analyses_limit = :anlimit
                    WHERE empresa_id = :eid
                """),
                {
                    "eid": empresa_id, "plan": new_plan,
                    "limit": pricing["monthly_limit"], "maxu": pricing["max_users"],
                    "base": pricing["base_users"], "extra": pricing["extra_users"],
                    "ppeu": pricing["price_per_extra_user"],
                    "anlimit": pricing["monthly_analyses_limit"],
                },
            )

        await db.commit()

    audit = {**empresa_updates}
    if req.plan_type:
        audit["plan_type"] = req.plan_type
    if req.extra_users is not None:
        audit["extra_users"] = req.extra_users
    await _audit(admin["admin_id"], "update_empresa", "empresa", empresa_id, audit, _get_ip(request))

    return {"updated": True, **audit}


@router.post("/usuarios")
async def create_usuario(
    req: CreateUsuarioRequest,
    request: Request,
    admin: dict = Depends(get_current_admin),
):
    """Crear usuario para una empresa."""
    if admin["role"] not in ("superadmin", "admin"):
        raise HTTPException(status_code=403, detail="Permiso insuficiente")

    from api.security import hash_password as hash_pw

    try:
        async with AsyncSessionLocal() as db:
            # Enforce max_users del plan
            budget = (await db.execute(
                sql_text("SELECT max_users, plan_type FROM budget_limits WHERE empresa_id = :eid"),
                {"eid": req.empresa_id},
            )).fetchone()
            if budget and budget.max_users:
                user_count = (await db.execute(
                    sql_text("SELECT COUNT(*) FROM usuarios WHERE empresa_id = :eid"),
                    {"eid": req.empresa_id},
                )).scalar()
                if user_count >= budget.max_users:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Limite alcanzado: el plan {budget.plan_type} permite maximo {budget.max_users} usuarios",
                    )

            result = await db.execute(
                sql_text("""
                    INSERT INTO usuarios (empresa_id, email, nombre, password, rol)
                    VALUES (:eid, :email, :nombre, :password, :rol)
                    RETURNING id
                """),
                {
                    "eid": req.empresa_id,
                    "email": req.email.strip().lower(),
                    "nombre": req.nombre,
                    "password": hash_pw(req.password),
                    "rol": req.rol,
                },
            )
            user_id = result.fetchone()[0]
            await db.commit()

        await _audit(admin["admin_id"], "create_usuario", "usuario", str(user_id),
                     {"email": req.email, "empresa_id": req.empresa_id}, _get_ip(request))

        return {"id": str(user_id), "email": req.email}

    except Exception as e:
        if "unique" in str(e).lower() or "duplicate" in str(e).lower():
            raise HTTPException(status_code=409, detail="Email ya registrado")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/users/{user_id}")
async def update_usuario(
    user_id: str,
    req: UpdateUsuarioRequest,
    request: Request,
    admin: dict = Depends(get_current_admin),
):
    """Editar usuario: nombre, rol, password."""
    if admin["role"] not in ("superadmin", "admin"):
        raise HTTPException(status_code=403, detail="Permiso insuficiente")

    updates = {}
    params = {"id": user_id}
    if req.nombre is not None:
        updates["nombre"] = f"nombre = :nombre"
        params["nombre"] = req.nombre
    if req.rol is not None:
        valid_roles = {"admin", "member", "vendedor", "gerente", "logistica", "contador", "marketing", "rrhh", "legal"}
        if req.rol not in valid_roles:
            raise HTTPException(status_code=400, detail=f"Roles validos: {', '.join(sorted(valid_roles))}")
        updates["rol"] = f"rol = :rol"
        params["rol"] = req.rol
    if req.password is not None:
        from api.security import hash_password as hash_pw
        updates["password"] = f"password = :password"
        params["password"] = hash_pw(req.password)

    if not updates:
        raise HTTPException(status_code=400, detail="Nada que actualizar")

    set_clause = ", ".join(updates.values())
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            sql_text(f"UPDATE usuarios SET {set_clause} WHERE id = :id RETURNING id"),
            params,
        )
        if not result.fetchone():
            raise HTTPException(status_code=404, detail="Usuario no encontrado")
        await db.commit()

    audit_details = {k: v for k, v in {"nombre": req.nombre, "rol": req.rol}.items() if v is not None}
    if req.password:
        audit_details["password"] = "***changed***"
    await _audit(admin["admin_id"], "update_usuario", "usuario", user_id, audit_details, _get_ip(request))

    return {"updated": True, "user_id": user_id}


@router.delete("/usuarios/{user_id}")
async def delete_usuario(
    user_id: str,
    request: Request,
    admin: dict = Depends(get_current_admin),
):
    """Eliminar usuario. Solo superadmin."""
    if admin["role"] != "superadmin":
        raise HTTPException(status_code=403, detail="Solo superadmin puede eliminar usuarios")

    async with AsyncSessionLocal() as db:
        await db.execute(sql_text("DELETE FROM usuarios WHERE id = :id"), {"id": user_id})
        await db.commit()

    await _audit(admin["admin_id"], "delete_usuario", "usuario", user_id, {}, _get_ip(request))

    return {"deleted": True}


@router.post("/empresas/{empresa_id}/add-user")
async def add_extra_user(
    empresa_id: str,
    request: Request,
    admin: dict = Depends(get_current_admin),
):
    """Agrega un usuario extra. Recalcula max_users y monthly_limit."""
    async with AsyncSessionLocal() as db:
        cur = (await db.execute(
            sql_text("SELECT plan_type, extra_users FROM budget_limits WHERE empresa_id = :eid"),
            {"eid": empresa_id},
        )).fetchone()
        if not cur:
            raise HTTPException(status_code=404, detail="Empresa sin budget")

        new_extra = (cur.extra_users or 0) + 1
        pricing = _calc_pricing(cur.plan_type or "start", new_extra)

        await db.execute(
            sql_text("""
                UPDATE budget_limits SET
                    extra_users = :extra, max_users = :maxu,
                    monthly_limit = :limit, price_per_extra_user = :ppeu
                WHERE empresa_id = :eid
            """),
            {"eid": empresa_id, "extra": new_extra, "maxu": pricing["max_users"],
             "limit": pricing["monthly_limit"], "ppeu": pricing["price_per_extra_user"]},
        )
        await db.commit()

    await _audit(admin["admin_id"], "add_extra_user", "empresa", empresa_id,
                 {"extra_users": new_extra, "monthly_limit": pricing["monthly_limit"]}, _get_ip(request))

    return {"extra_users": new_extra, **pricing}


@router.post("/empresas/{empresa_id}/purchase-analyses")
async def purchase_analyses(
    empresa_id: str,
    data: dict,
    request: Request,
    admin: dict = Depends(get_current_admin),
):
    """Compra un pack de analisis adicionales."""
    pack_type = data.get("pack_type", "")
    pack = ANALYSIS_PACKS.get(pack_type)
    if not pack:
        raise HTTPException(status_code=400, detail=f"Pack invalido. Opciones: {', '.join(ANALYSIS_PACKS.keys())}")

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            sql_text("""
                UPDATE budget_limits
                SET monthly_analyses_limit = monthly_analyses_limit + :extra
                WHERE empresa_id = :eid
                RETURNING monthly_analyses_limit
            """),
            {"eid": empresa_id, "extra": pack["analyses"]},
        )
        row = result.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Empresa sin budget")
        await db.commit()

    await _audit(admin["admin_id"], "purchase_analyses", "empresa", empresa_id,
                 {"pack": pack_type, "analyses_added": pack["analyses"], "price": pack["price"]},
                 _get_ip(request))

    return {
        "pack": pack_type,
        "analyses_added": pack["analyses"],
        "price": pack["price"],
        "new_monthly_analyses_limit": row.monthly_analyses_limit,
    }


@router.delete("/empresas/{empresa_id}")
async def delete_empresa(
    empresa_id: str,
    request: Request,
    admin: dict = Depends(get_current_admin),
):
    """Eliminar empresa con cascade (reportes, usuarios, credenciales, budget, profile)."""
    if admin["role"] != "superadmin":
        raise HTTPException(status_code=403, detail="Solo superadmin puede eliminar empresas")

    async with AsyncSessionLocal() as db:
        empresa = (await db.execute(
            sql_text("SELECT nombre FROM empresas WHERE id = :id"), {"id": empresa_id}
        )).fetchone()
        if not empresa:
            raise HTTPException(status_code=404, detail="Empresa no encontrada")

        # Cascade delete
        await db.execute(sql_text("DELETE FROM report_links WHERE report_id IN (SELECT id FROM ada_reports WHERE empresa_id = :id)"), {"id": empresa_id})
        await db.execute(sql_text("DELETE FROM ada_reports WHERE empresa_id = :id"), {"id": empresa_id})
        await db.execute(sql_text("DELETE FROM usuarios WHERE empresa_id = :id"), {"id": empresa_id})
        await db.execute(sql_text("DELETE FROM tenant_credentials WHERE empresa_id = :id"), {"id": empresa_id})
        await db.execute(sql_text("DELETE FROM budget_limits WHERE empresa_id = :id"), {"id": empresa_id})
        await db.execute(sql_text("DELETE FROM ada_company_profile WHERE empresa_id = :id"), {"id": empresa_id})
        await db.execute(sql_text("DELETE FROM tenant_app_config WHERE empresa_id = :id"), {"id": empresa_id})
        await db.execute(sql_text("DELETE FROM team_members WHERE empresa_id = :id"), {"id": empresa_id})
        await db.execute(sql_text("DELETE FROM empresas WHERE id = :id"), {"id": empresa_id})
        await db.commit()

    await _audit(admin["admin_id"], "delete_empresa", "empresa", empresa_id,
                 {"nombre": empresa.nombre, "cascade": True}, _get_ip(request))

    return {"deleted": True, "empresa_id": empresa_id}


@router.get("/empresas/{empresa_id}/users")
async def list_empresa_users(empresa_id: str, admin: dict = Depends(get_current_admin)):
    """Lista usuarios de una empresa."""
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            sql_text("""
                SELECT id, email, nombre, rol, telegram_id, is_active, created_at
                FROM usuarios WHERE empresa_id = :id ORDER BY created_at
            """),
            {"id": empresa_id},
        )).fetchall()

    return [
        {
            "id": str(r.id), "email": r.email, "nombre": r.nombre,
            "rol": r.rol, "has_telegram": bool(r.telegram_id),
            "is_active": r.is_active, "created_at": str(r.created_at),
        }
        for r in rows
    ]


@router.get("/empresas/{empresa_id}/reports")
async def list_empresa_reports(
    empresa_id: str,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    admin: dict = Depends(get_current_admin),
):
    """Lista reportes de una empresa con paginacion."""
    offset = (page - 1) * limit
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(sql_text("""
            SELECT id, title, report_type, source_file, generated_by,
                   is_archived, created_at
            FROM ada_reports WHERE empresa_id = :eid
            ORDER BY created_at DESC LIMIT :lim OFFSET :off
        """), {"eid": empresa_id, "lim": limit, "off": offset})).fetchall()

        total = (await db.execute(
            sql_text("SELECT COUNT(*) FROM ada_reports WHERE empresa_id = :eid"),
            {"eid": empresa_id},
        )).scalar()

        # Stats por tipo
        type_stats = (await db.execute(sql_text("""
            SELECT report_type, COUNT(*) as count
            FROM ada_reports WHERE empresa_id = :eid
            GROUP BY report_type ORDER BY count DESC
        """), {"eid": empresa_id})).fetchall()

    return {
        "page": page, "limit": limit, "total": total,
        "type_stats": [{"type": r.report_type, "count": r.count} for r in type_stats],
        "data": [
            {
                "id": str(r.id), "title": r.title, "report_type": r.report_type,
                "source_file": r.source_file, "generated_by": r.generated_by,
                "is_archived": r.is_archived, "created_at": str(r.created_at),
            }
            for r in rows
        ],
    }


@router.delete("/reports/{report_id}")
async def delete_report(
    report_id: str,
    request: Request,
    admin: dict = Depends(get_current_admin),
):
    """Eliminar un reporte."""
    if admin["role"] not in ("superadmin", "admin"):
        raise HTTPException(status_code=403, detail="Permiso insuficiente")

    async with AsyncSessionLocal() as db:
        row = (await db.execute(
            sql_text("SELECT title FROM ada_reports WHERE id = :id"), {"id": report_id}
        )).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Reporte no encontrado")

        await db.execute(sql_text("DELETE FROM report_links WHERE report_id = :id"), {"id": report_id})
        await db.execute(sql_text("DELETE FROM ada_reports WHERE id = :id"), {"id": report_id})
        await db.commit()

    await _audit(admin["admin_id"], "delete_report", "report", report_id,
                 {"title": row.title}, _get_ip(request))

    return {"deleted": True}


@router.get("/stats")
async def global_stats(admin: dict = Depends(get_current_admin)):
    """Stats generales para dashboard: totales + reportes por dia."""
    async with AsyncSessionLocal() as db:
        total_empresas = (await db.execute(sql_text("SELECT COUNT(*) FROM empresas"))).scalar()
        total_usuarios = (await db.execute(sql_text("SELECT COUNT(*) FROM usuarios"))).scalar()
        total_reportes = (await db.execute(sql_text("SELECT COUNT(*) FROM ada_reports"))).scalar()

        # Reportes por dia (ultimos 30 dias)
        reportes_por_dia = (await db.execute(sql_text("""
            SELECT DATE(created_at) as dia, COUNT(*) as count
            FROM ada_reports
            WHERE created_at >= NOW() - INTERVAL '30 days'
            GROUP BY DATE(created_at)
            ORDER BY dia
        """))).fetchall()

        # Empresas activas (con reportes en ultimos 7 dias)
        empresas_activas = (await db.execute(sql_text("""
            SELECT DISTINCT e.id, e.nombre, MAX(r.created_at) as last_activity
            FROM empresas e
            JOIN ada_reports r ON r.empresa_id = e.id
            WHERE r.created_at >= NOW() - INTERVAL '7 days'
            GROUP BY e.id, e.nombre
            ORDER BY last_activity DESC
        """))).fetchall()

    return {
        "total_empresas": total_empresas,
        "total_usuarios": total_usuarios,
        "total_reportes": total_reportes,
        "reportes_por_dia": [{"dia": str(r.dia), "count": r.count} for r in reportes_por_dia],
        "empresas_activas": [
            {"id": str(r.id), "nombre": r.nombre, "last_activity": str(r.last_activity)}
            for r in empresas_activas
        ],
    }


@router.put("/empresas/{empresa_id}/budget")
async def update_budget(
    empresa_id: str,
    req: UpdateBudgetRequest,
    request: Request,
    admin: dict = Depends(get_current_admin),
):
    """Actualizar monthly_limit de una empresa."""
    async with AsyncSessionLocal() as db:
        await db.execute(
            sql_text("""
                INSERT INTO budget_limits (empresa_id, monthly_limit)
                VALUES (:eid, :limit)
                ON CONFLICT (empresa_id) DO UPDATE SET monthly_limit = :limit
            """),
            {"eid": empresa_id, "limit": req.monthly_limit},
        )
        await db.commit()

    await _audit(admin["admin_id"], "update_budget", "empresa", empresa_id,
                 {"monthly_limit": req.monthly_limit}, _get_ip(request))

    return {"updated": True, "monthly_limit": req.monthly_limit}


@router.post("/empresas/{empresa_id}/budget/reset")
async def reset_budget(
    empresa_id: str,
    request: Request,
    admin: dict = Depends(get_current_admin),
):
    """Reset uso mensual. Solo superadmin."""
    if admin["role"] != "superadmin":
        raise HTTPException(status_code=403, detail="Solo superadmin puede resetear budget")

    async with AsyncSessionLocal() as db:
        await db.execute(
            sql_text("""
                UPDATE budget_limits
                SET used_this_month = 0, total_tokens_this_month = 0,
                    topup_balance = 0, alert_sent_this_month = FALSE
                WHERE empresa_id = :eid
            """),
            {"eid": empresa_id},
        )
        await db.commit()

    await _audit(admin["admin_id"], "reset_budget", "empresa", empresa_id, {}, _get_ip(request))

    return {"reset": True}


@router.get("/empresas/{empresa_id}/credentials")
async def list_credentials(empresa_id: str, admin: dict = Depends(get_current_admin)):
    """Lista credenciales sin datos sensibles."""
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            sql_text("""
                SELECT id, provider, is_active, created_at
                FROM tenant_credentials
                WHERE empresa_id = :eid
                ORDER BY created_at
            """),
            {"eid": empresa_id},
        )).fetchall()

    return [
        {
            "id": str(r.id), "provider": r.provider,
            "is_active": r.is_active, "created_at": str(r.created_at),
        }
        for r in rows
    ]


@router.put("/credentials/{cred_id}/toggle")
async def toggle_credential(
    cred_id: str,
    request: Request,
    admin: dict = Depends(get_current_admin),
):
    """Activar/desactivar credencial."""
    async with AsyncSessionLocal() as db:
        row = (await db.execute(
            sql_text("SELECT id, is_active FROM tenant_credentials WHERE id = :id"),
            {"id": cred_id},
        )).fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="Credencial no encontrada")

        new_status = not row.is_active
        await db.execute(
            sql_text("UPDATE tenant_credentials SET is_active = :status WHERE id = :id"),
            {"status": new_status, "id": cred_id},
        )
        await db.commit()

    await _audit(admin["admin_id"], "toggle_credential", "credential", cred_id,
                 {"is_active": new_status}, _get_ip(request))

    return {"id": cred_id, "is_active": new_status}


@router.get("/audit-log")
async def audit_log(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    admin: dict = Depends(get_current_admin),
):
    """Consulta log de auditoria con paginacion."""
    offset = (page - 1) * limit

    async with AsyncSessionLocal() as db:
        rows = (await db.execute(sql_text("""
            SELECT al.id, al.action, al.target_type, al.target_id,
                   al.details, al.ip_address, al.created_at,
                   au.email as admin_email, au.nombre as admin_nombre
            FROM admin_audit_log al
            JOIN admin_users au ON au.id = al.admin_user_id
            ORDER BY al.created_at DESC
            LIMIT :lim OFFSET :off
        """), {"lim": limit, "off": offset})).fetchall()

        total = (await db.execute(sql_text("SELECT COUNT(*) FROM admin_audit_log"))).scalar()

    return {
        "page": page,
        "limit": limit,
        "total": total,
        "data": [
            {
                "id": str(r.id),
                "action": r.action,
                "target_type": r.target_type,
                "target_id": str(r.target_id) if r.target_id else None,
                "details": r.details if isinstance(r.details, dict) else {},
                "ip_address": r.ip_address,
                "created_at": str(r.created_at),
                "admin_email": r.admin_email,
                "admin_nombre": r.admin_nombre,
            }
            for r in rows
        ],
    }


@router.get("/users/{user_id}/memories")
async def list_user_memories(user_id: str, admin: dict = Depends(get_current_admin)):
    """Lista memorias de un usuario."""
    from api.services.user_memory_service import get_all_memories

    async with AsyncSessionLocal() as db:
        user = (await db.execute(
            sql_text("SELECT empresa_id FROM usuarios WHERE id = :uid"), {"uid": user_id}
        )).fetchone()

    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    memories = get_all_memories(str(user.empresa_id), user_id)
    return {"user_id": user_id, "count": len(memories), "memories": memories}


@router.delete("/memories/{memory_id}")
async def delete_memory(memory_id: str, request: Request, admin: dict = Depends(get_current_admin)):
    """Elimina (desactiva) una memoria."""
    from api.services.user_memory_service import deactivate_memory

    deactivate_memory(memory_id)
    await _audit(admin["admin_id"], "delete_memory", "memory", memory_id, {}, _get_ip(request))
    return {"deleted": True}
