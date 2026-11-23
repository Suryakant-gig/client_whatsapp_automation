"""API routes aggregator."""

from fastapi import APIRouter, Depends

from app.api.deps import get_current_user, verify_csrf
from app.api.routes.auth import router as auth_router
from app.api.routes.campaigns import router as campaign_router
from app.api.routes.dashboard import router as dashboard_router
from app.api.routes.excel_routes import router as excel_router
from app.api.routes.followups import router as followup_router
from app.api.routes.health import router as health_router
from app.api.routes.import_routes import router as import_router
from app.api.routes.leads import router as lead_router
from app.api.routes.templates import router as template_router
from app.api.routes.webhook import router as webhook_router
from app.api.routes.whatsapp import router as whatsapp_router

api_router = APIRouter()

# Health check router registered at root level (/health) - Public
api_router.include_router(health_router)

# Authentication & Session Management routes (/api/auth) - Public endpoints handle own checks
api_router.include_router(auth_router)

# Phase 7: WhatsApp Webhook routes (/api/whatsapp/webhook) - Public, verified via Meta HMAC/token
api_router.include_router(webhook_router)

# Authenticated & CSRF-protected CRM dashboard routes
protected_dependencies = [Depends(get_current_user), Depends(verify_csrf)]

# Phase 3: Excel import and synchronization routes
api_router.include_router(import_router, dependencies=protected_dependencies)
api_router.include_router(excel_router, dependencies=protected_dependencies)

# Phase 4: Lead Management routes
api_router.include_router(lead_router, dependencies=protected_dependencies)

# Phase 5: Follow-up Scheduler routes
api_router.include_router(followup_router, dependencies=protected_dependencies)

# Phase 6: WhatsApp Cloud API & Template routes
api_router.include_router(template_router, dependencies=protected_dependencies)
api_router.include_router(whatsapp_router, dependencies=protected_dependencies)

# Phase 8: Campaign Management and Batch Approval routes
api_router.include_router(campaign_router, dependencies=protected_dependencies)

# Phase 9.3: CRM Dashboard Overview & Metrics routes
api_router.include_router(dashboard_router, dependencies=protected_dependencies)

