from fastapi import APIRouter
from . import companies
from . import users
from . import auth
from . import events
from . import workflows
from . import chat
from . import upload
from . import onboarding_router
from . import oauth
from . import reports
from . import dashboard
from . import budget_router
from . import consolidation_router
from . import admin_auth
from . import admin_router
from . import portal_router


api_router = APIRouter()


api_router.include_router(
    dashboard.router,
    prefix="/panel",
    tags=["Dashboard"]
)


api_router.include_router(
    companies.router,
    prefix="/empresas",
    tags=["Empresas"]
)


api_router.include_router(
    users.router,
    prefix="/usuarios",
    tags=["Usuarios"]
)


api_router.include_router(
    auth.router,
    prefix="/auth",
    tags=["Auth"]
)


api_router.include_router(
    events.router,
    prefix="/events",
    tags=["Events"]
)


api_router.include_router(
    workflows.router,
    prefix="/workflows",
    tags=["Workflows"]
)


api_router.include_router(
    chat.router,
    prefix="/chat",
    tags=["Chat"]
)

api_router.include_router(
    upload.router,
    prefix="/files",
    tags=["Files"]
)

api_router.include_router(
    onboarding_router.router,
    prefix="/config",
    tags=["Onboarding"]
)


api_router.include_router(
    oauth.router,
    prefix="/oauth",
    tags=["OAuth"]
)

api_router.include_router(
    reports.router,
    prefix="/api/v1",
    tags=["Reports"]
)

api_router.include_router(
    budget_router.router,
    prefix="/admin/api/budget",
    tags=["Budget"]
)

api_router.include_router(
    consolidation_router.router,
    prefix="/api/v1",
    tags=["Consolidation"]
)

api_router.include_router(
    admin_auth.router,
    prefix="/admin/auth",
    tags=["Admin Auth"]
)

api_router.include_router(
    admin_router.router,
    prefix="/admin/api",
    tags=["Admin"]
)

api_router.include_router(
    portal_router.router,
    tags=["Portal"]
)
