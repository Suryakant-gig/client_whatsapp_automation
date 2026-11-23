"""Main FastAPI application entry point."""

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from fastapi import Depends, FastAPI, Request, status
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
import uvicorn

from app.api import api_router
from app.core.config import get_settings
from app.core.logging import setup_logging
from app.db.session import SessionLocal, get_db
from app.services.auth_service import AuthService
from app.services.followup_service import FollowUpService
from app.services.scheduler_manager import get_scheduler_manager

logger = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan manager handling startup, offline reconciliation, and background scheduler."""
    settings = get_settings()
    setup_logging(settings.LOG_LEVEL)

    logger.info(
        "Starting %s [env=%s, debug=%s]",
        settings.APP_NAME,
        settings.APP_ENV,
        settings.DEBUG,
    )

    # 1. Critical offline recovery: reconcile overdue follow-ups missed while laptop was offline
    try:
        with SessionLocal() as db:
            skipped = FollowUpService.reconcile_offline_missed_schedules(db)
            if skipped > 0:
                logger.info("Startup reconciliation: Marked %d missed schedules as Skipped", skipped)
    except Exception as e:
        logger.error("Error during startup offline schedule reconciliation: %s", str(e))

    # 2. Start background scheduler if enabled
    scheduler_manager = get_scheduler_manager()
    if settings.ENABLE_SCHEDULER:
        try:
            scheduler_manager.start()
        except Exception as e:
            logger.error("Error starting background scheduler: %s", str(e))

    yield

    # 3. Graceful shutdown of scheduler
    scheduler_manager.shutdown(wait=False)

    # 4. Safely close WhatsApp Cloud API HTTP client
    try:
        from app.integrations.whatsapp.client import get_whatsapp_client
        wa_client = get_whatsapp_client()
        await wa_client.close()
    except Exception as e:
        logger.error("Error closing WhatsApp HTTP client: %s", str(e))

    logger.info("Shutting down %s", settings.APP_NAME)


def create_application() -> FastAPI:
    """Application factory for configuring and returning the FastAPI instance."""
    settings = get_settings()

    app = FastAPI(
        title=settings.APP_NAME,
        debug=settings.DEBUG,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    # Register routes
    app.include_router(api_router)

    # Static assets and uploads
    uploads_dir = Path("data/uploads").resolve()
    uploads_dir.mkdir(parents=True, exist_ok=True)
    (uploads_dir / "templates").mkdir(parents=True, exist_ok=True)
    app.mount("/uploads", StaticFiles(directory=str(uploads_dir)), name="uploads")

    # Static assets and frontend page routes
    frontend_dir = Path(__file__).resolve().parent / "frontend"
    if frontend_dir.exists():
        app.mount("/static", StaticFiles(directory=str(frontend_dir)), name="static")

        def check_auth(req: Request, db: Session) -> bool:
            raw_token = req.cookies.get(settings.SESSION_COOKIE_NAME)
            if not raw_token:
                return False
            user = AuthService.validate_session(db, raw_token)
            return user is not None

        @app.get("/login", include_in_schema=False)
        def login_page(request: Request, db: Session = Depends(get_db)):
            if check_auth(request, db):
                return RedirectResponse("/dashboard", status_code=status.HTTP_303_SEE_OTHER)
            login_file = frontend_dir / "login.html"
            if login_file.exists():
                return FileResponse(str(login_file))
            return RedirectResponse("/docs")

        @app.get("/", include_in_schema=False)
        def root_redirect():
            return RedirectResponse("/dashboard", status_code=status.HTTP_303_SEE_OTHER)

        @app.get("/dashboard", include_in_schema=False)
        @app.get("/dashboard/{module}", include_in_schema=False)
        def dashboard_page(request: Request, module: str = None, db: Session = Depends(get_db)):
            if not check_auth(request, db):
                return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
            index_file = frontend_dir / "index.html"
            if index_file.exists():
                return FileResponse(str(index_file))
            return RedirectResponse("/login")

    return app


app = create_application()

if __name__ == "__main__":
    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
    )
