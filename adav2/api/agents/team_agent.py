"""
Team Agent — Gestiona equipo desde el chat.
El admin dice "agrega a Carlos carlos@empresa.com como vendedor"
y Ada crea el usuario con los permisos correctos.

Acciones: invite, list, update, remove
"""

import json
import secrets
from typing import TypedDict, Optional
from langgraph.graph import StateGraph, END
from models.selector import selector
from api.database import sync_engine
from sqlalchemy import text as sql_text


class TeamState(TypedDict, total=False):
    message: str
    empresa_id: str
    user_id: str
    intent: str

    action: str
    action_params: dict

    response: str
    model_used: str


TEAM_SYSTEM_PROMPT = """Eres Ada, asistente ejecutiva. El administrador quiere gestionar su equipo.

Analiza el mensaje y determina la acción:

## ACCIONES:
- "agrega a Carlos carlos@empresa.com como vendedor" → action: invite
- "lista mi equipo" / "quiénes están en mi equipo" → action: list
- "cambia a Carlos a gerente" → action: update
- "elimina a Carlos del equipo" → action: remove

## ROLES DISPONIBLES:
- administrador: acceso total
- gerente: acceso total
- vendedor: ventas, clientes, email, calendario, voz, prospectos
- analista: ventas, finanzas, inventario, clientes, proyectos, upload
- operativo: solo inventario y proyectos

## EXTRACCIÓN DE DATOS:
Para invite extrae: nombre, email, rol, departamento
Para update extrae: nombre o email del miembro, nuevo rol
Para remove extrae: nombre o email del miembro

Responde SOLO JSON:
{
    "action": "invite|list|update|remove",
    "params": {
        "nombre": "...",
        "email": "...",
        "role": "...",
        "department": "..."
    }
}
Sin markdown, sin explicación."""


async def classify_team_action(state: TeamState) -> dict:
    """Clasifica qué acción de equipo quiere el admin."""
    model, model_name = selector.get_model("chat_with_tools")

    response = await model.ainvoke([
        {"role": "system", "content": TEAM_SYSTEM_PROMPT},
        {"role": "user", "content": state["message"]},
    ])

    try:
        raw = response.content.strip().replace("```json", "").replace("```", "")
        result = json.loads(raw)
        action = result.get("action", "list")
        params = result.get("params", {})
    except (json.JSONDecodeError, AttributeError):
        action = "list"
        params = {}

    print(f"TEAM AGENT: acción={action}, params={params}")

    return {
        "action": action,
        "action_params": params,
        "model_used": model_name,
    }


async def execute_team_action(state: TeamState) -> dict:
    """Ejecuta la acción de gestión de equipo."""
    action = state.get("action", "")
    params = state.get("action_params", {})
    empresa_id = state.get("empresa_id", "")
    admin_user_id = state.get("user_id", "")

    if not empresa_id or not admin_user_id:
        return {"response": "No se pudo identificar tu empresa. Intenta de nuevo."}

    # Verificar que es admin
    if not _is_admin(empresa_id, admin_user_id):
        return {"response": "⚠️ Solo el administrador puede gestionar el equipo."}

    if action == "list":
        return _list_members(empresa_id)

    elif action == "invite":
        return _invite_member(empresa_id, admin_user_id, params)

    elif action == "update":
        return _update_member(empresa_id, params)

    elif action == "remove":
        return _remove_member(empresa_id, admin_user_id, params)

    else:
        return {"response": "No entendí. Puedo agregar, listar, editar o eliminar miembros del equipo."}


def _is_admin(empresa_id: str, user_id: str) -> bool:
    """Verifica que el usuario es admin."""
    try:
        with sync_engine.connect() as conn:
            result = conn.execute(
                sql_text("SELECT rol FROM usuarios WHERE id = :uid AND empresa_id = :eid"),
                {"uid": user_id, "eid": empresa_id},
            )
            row = result.fetchone()
            return row and row.rol == "admin"
    except Exception:
        return False


def _list_members(empresa_id: str) -> dict:
    """Lista miembros del equipo."""
    try:
        with sync_engine.connect() as conn:
            result = conn.execute(
                sql_text("""
                    SELECT tm.display_name, tm.role_title, tm.department,
                           tm.is_active, u.email, u.telegram_id
                    FROM team_members tm
                    JOIN usuarios u ON u.id = tm.user_id
                    WHERE tm.empresa_id = :eid
                    ORDER BY tm.added_at
                """),
                {"eid": empresa_id},
            )
            rows = result.fetchall()

        if not rows:
            return {"response": "No hay miembros en el equipo aún. Puedes agregar uno diciéndome su nombre, email y rol."}

        members_text = f"👥 Tu equipo ({len(rows)} miembros):\n\n"
        for row in rows:
            status = "✅" if row.is_active else "❌"
            telegram = "📱" if row.telegram_id else "⏳"
            members_text += (
                f"{status} **{row.display_name}** — {row.role_title}\n"
                f"   📧 {row.email} | {telegram} {'Telegram vinculado' if row.telegram_id else 'Sin vincular'}\n"
                f"   🏢 {row.department or 'Sin departamento'}\n\n"
            )

        return {"response": members_text}

    except Exception as e:
        print(f"ERROR list members: {e}")
        return {"response": "Error listando el equipo."}


def _invite_member(empresa_id: str, admin_user_id: str, params: dict) -> dict:
    """Agrega un nuevo miembro al equipo."""
    from api.security import hash_password

    nombre = params.get("nombre", "")
    email = params.get("email", "").strip().lower()
    role = params.get("role", "operativo").lower()
    department = params.get("department", "")

    if not nombre or not email:
        return {"response": "Necesito el nombre y email del nuevo miembro. Ejemplo: 'Agrega a Carlos carlos@empresa.com como vendedor'"}

    if "@" not in email:
        return {"response": f"'{email}' no parece un email válido. Intenta de nuevo."}

    # Roles válidos
    ROLE_TEMPLATES = {
        "administrador": {k: True for k in [
            "can_view_sales", "can_view_finance", "can_view_inventory",
            "can_view_clients", "can_view_projects", "can_view_hr",
            "can_send_email", "can_manage_calendar", "can_upload_files",
            "can_use_voice", "can_prospect",
        ]},
        "gerente": {
            "can_view_sales": True, "can_view_finance": True,
            "can_view_inventory": True, "can_view_clients": True,
            "can_view_projects": True, "can_view_hr": True,
            "can_send_email": True, "can_manage_calendar": True,
            "can_upload_files": True, "can_use_voice": True,
            "can_prospect": True,
        },
        "vendedor": {
            "can_view_sales": True, "can_view_finance": False,
            "can_view_inventory": False, "can_view_clients": True,
            "can_view_projects": False, "can_view_hr": False,
            "can_send_email": True, "can_manage_calendar": True,
            "can_upload_files": False, "can_use_voice": True,
            "can_prospect": True,
        },
        "analista": {
            "can_view_sales": True, "can_view_finance": True,
            "can_view_inventory": True, "can_view_clients": True,
            "can_view_projects": True, "can_view_hr": False,
            "can_send_email": False, "can_manage_calendar": False,
            "can_upload_files": True, "can_use_voice": False,
            "can_prospect": False,
        },
        "operativo": {
            "can_view_sales": False, "can_view_finance": False,
            "can_view_inventory": True, "can_view_clients": False,
            "can_view_projects": True, "can_view_hr": False,
            "can_send_email": False, "can_manage_calendar": False,
            "can_upload_files": False, "can_use_voice": False,
            "can_prospect": False,
        },
    }

    if role not in ROLE_TEMPLATES:
        role = "operativo"

    permissions = ROLE_TEMPLATES[role]

    try:
        with sync_engine.connect() as conn:
            # Verificar si email ya existe
            existing = conn.execute(
                sql_text("SELECT id FROM usuarios WHERE email = :email"),
                {"email": email},
            ).fetchone()

            if existing:
                # Verificar si ya es miembro
                member = conn.execute(
                    sql_text("SELECT id FROM team_members WHERE empresa_id = :eid AND user_id = :uid"),
                    {"eid": empresa_id, "uid": existing.id},
                ).fetchone()

                if member:
                    return {"response": f"⚠️ {nombre} ({email}) ya es miembro de tu equipo."}

                user_id = existing.id
            else:
                # Crear usuario
                temp_password = secrets.token_urlsafe(12)
                result = conn.execute(
                    sql_text("""
                        INSERT INTO usuarios (empresa_id, email, nombre, password, rol)
                        VALUES (:eid, :email, :nombre, :password, 'member')
                        RETURNING id
                    """),
                    {
                        "eid": empresa_id,
                        "email": email,
                        "nombre": nombre,
                        "password": hash_password(temp_password),
                    },
                )
                user_id = result.fetchone()[0]

            # Crear team_member
            conn.execute(
                sql_text("""
                    INSERT INTO team_members
                        (empresa_id, user_id, display_name, role_title,
                         department, permissions, added_by)
                    VALUES (:eid, :uid, :name, :role, :dept, :perms, :admin)
                    ON CONFLICT (empresa_id, user_id) DO UPDATE SET
                        display_name = EXCLUDED.display_name,
                        role_title = EXCLUDED.role_title,
                        permissions = EXCLUDED.permissions,
                        is_active = TRUE
                """),
                {
                    "eid": empresa_id,
                    "uid": user_id,
                    "name": nombre,
                    "role": role.capitalize(),
                    "dept": department,
                    "perms": json.dumps(permissions),
                    "admin": admin_user_id,
                },
            )
            conn.commit()

        # Permisos activos
        active_perms = [k.replace("can_view_", "").replace("can_", "") for k, v in permissions.items() if v]

        return {
            "response": (
                f"✅ **{nombre}** agregado al equipo como **{role.capitalize()}**\n\n"
                f"📧 Email: {email}\n"
                f"🏢 Departamento: {department or 'Sin asignar'}\n"
                f"🔑 Accesos: {', '.join(active_perms)}\n\n"
                f"Para conectarse a Ada, {nombre} debe abrir Telegram → @nuevoadabot → /start → escribir su email: {email}"
            ),
        }

    except Exception as e:
        print(f"ERROR invite member: {e}")
        import traceback
        traceback.print_exc()
        return {"response": f"Error agregando miembro: {str(e)}"}


def _update_member(empresa_id: str, params: dict) -> dict:
    """Actualiza rol de un miembro."""
    nombre = params.get("nombre", "")
    email = params.get("email", "")
    new_role = params.get("role", "")

    if not new_role:
        return {"response": "¿A qué rol quieres cambiarlo? Roles: administrador, gerente, vendedor, analista, operativo"}

    search = email or nombre

    try:
        with sync_engine.connect() as conn:
            result = conn.execute(
                sql_text("""
                    SELECT tm.user_id, tm.display_name, u.email
                    FROM team_members tm
                    JOIN usuarios u ON u.id = tm.user_id
                    WHERE tm.empresa_id = :eid
                    AND (u.email ILIKE :search OR tm.display_name ILIKE :search)
                """),
                {"eid": empresa_id, "search": f"%{search}%"},
            )
            row = result.fetchone()

        if not row:
            return {"response": f"No encontré a '{search}' en tu equipo."}

        # Actualizar rol usando el endpoint lógica
        ROLE_TEMPLATES = {
            "administrador": {k: True for k in [
                "can_view_sales", "can_view_finance", "can_view_inventory",
                "can_view_clients", "can_view_projects", "can_view_hr",
                "can_send_email", "can_manage_calendar", "can_upload_files",
                "can_use_voice", "can_prospect",
            ]},
            "gerente": {"can_view_sales": True, "can_view_finance": True, "can_view_inventory": True, "can_view_clients": True, "can_view_projects": True, "can_view_hr": True, "can_send_email": True, "can_manage_calendar": True, "can_upload_files": True, "can_use_voice": True, "can_prospect": True},
            "vendedor": {"can_view_sales": True, "can_view_finance": False, "can_view_inventory": False, "can_view_clients": True, "can_view_projects": False, "can_view_hr": False, "can_send_email": True, "can_manage_calendar": True, "can_upload_files": False, "can_use_voice": True, "can_prospect": True},
            "analista": {"can_view_sales": True, "can_view_finance": True, "can_view_inventory": True, "can_view_clients": True, "can_view_projects": True, "can_view_hr": False, "can_send_email": False, "can_manage_calendar": False, "can_upload_files": True, "can_use_voice": False, "can_prospect": False},
            "operativo": {"can_view_sales": False, "can_view_finance": False, "can_view_inventory": True, "can_view_clients": False, "can_view_projects": True, "can_view_hr": False, "can_send_email": False, "can_manage_calendar": False, "can_upload_files": False, "can_use_voice": False, "can_prospect": False},
        }

        perms = ROLE_TEMPLATES.get(new_role.lower(), ROLE_TEMPLATES["operativo"])

        with sync_engine.connect() as conn:
            conn.execute(
                sql_text("""
                    UPDATE team_members
                    SET role_title = :role, permissions = :perms
                    WHERE empresa_id = :eid AND user_id = :uid
                """),
                {"role": new_role.capitalize(), "perms": json.dumps(perms), "eid": empresa_id, "uid": row.user_id},
            )
            conn.commit()

        return {"response": f"✅ {row.display_name} ahora es **{new_role.capitalize()}**"}

    except Exception as e:
        print(f"ERROR update member: {e}")
        return {"response": f"Error actualizando: {str(e)}"}


def _remove_member(empresa_id: str, admin_user_id: str, params: dict) -> dict:
    """Desactiva un miembro del equipo."""
    nombre = params.get("nombre", "")
    email = params.get("email", "")
    search = email or nombre

    if not search:
        return {"response": "¿A quién quieres eliminar? Dime el nombre o email."}

    try:
        with sync_engine.connect() as conn:
            result = conn.execute(
                sql_text("""
                    SELECT tm.user_id, tm.display_name
                    FROM team_members tm
                    JOIN usuarios u ON u.id = tm.user_id
                    WHERE tm.empresa_id = :eid
                    AND (u.email ILIKE :search OR tm.display_name ILIKE :search)
                """),
                {"eid": empresa_id, "search": f"%{search}%"},
            )
            row = result.fetchone()

        if not row:
            return {"response": f"No encontré a '{search}' en tu equipo."}

        if str(row.user_id) == admin_user_id:
            return {"response": "⚠️ No puedes eliminarte a ti mismo del equipo."}

        with sync_engine.connect() as conn:
            conn.execute(
                sql_text("UPDATE team_members SET is_active = FALSE WHERE empresa_id = :eid AND user_id = :uid"),
                {"eid": empresa_id, "uid": row.user_id},
            )
            conn.commit()

        return {"response": f"✅ {row.display_name} eliminado del equipo."}

    except Exception as e:
        print(f"ERROR remove member: {e}")
        return {"response": f"Error eliminando: {str(e)}"}


# ─── Compilar grafo ──────────────────────────────────────
graph = StateGraph(TeamState)
graph.add_node("classify", classify_team_action)
graph.add_node("execute", execute_team_action)
graph.set_entry_point("classify")
graph.add_edge("classify", "execute")
graph.add_edge("execute", END)
team_agent = graph.compile()