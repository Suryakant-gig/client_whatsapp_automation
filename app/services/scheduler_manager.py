"""APScheduler background execution and lifecycle management."""

import logging
import threading
from typing import Optional
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.services.followup_service import FollowUpService

logger = logging.getLogger("app.services.scheduler")


class SchedulerManager:
    """Singleton manager controlling the APScheduler background lifecycle."""

    _instance: Optional["SchedulerManager"] = None
    _lock = threading.Lock()

    def __new__(cls) -> "SchedulerManager":
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._scheduler = None
                cls._instance._is_running = False
            return cls._instance

    @property
    def is_running(self) -> bool:
        """Return True if background scheduler is active."""
        return self._is_running and self._scheduler is not None and self._scheduler.running

    def start(self) -> None:
        """Start the background scheduler if enabled and not already running."""
        settings = get_settings()

        if not settings.ENABLE_SCHEDULER:
            logger.info("Background scheduler is disabled via configuration (ENABLE_SCHEDULER=False)")
            return

        with self._lock:
            if self.is_running:
                logger.warning("Scheduler start requested but instance is already running")
                return

            try:
                tz = ZoneInfo(settings.SCHEDULER_TIMEZONE)
            except Exception:
                tz = ZoneInfo("Asia/Kolkata")

            self._scheduler = BackgroundScheduler(timezone=tz)

            # Register recurring polling job
            self._scheduler.add_job(
                func=self._scheduled_poll_worker,
                trigger="interval",
                seconds=settings.SCHEDULER_POLL_INTERVAL_SECONDS,
                id="followup_poll_job",
                name="Poll and dispatch due follow-up schedules",
                replace_existing=True,
                max_instances=1,
                coalesce=True,
            )

            self._scheduler.start()
            self._is_running = True
            logger.info(
                "APScheduler started [timezone=%s, poll_interval=%ds]",
                settings.SCHEDULER_TIMEZONE,
                settings.SCHEDULER_POLL_INTERVAL_SECONDS,
            )

    def shutdown(self, wait: bool = False) -> None:
        """Safely terminate the background scheduler."""
        with self._lock:
            if self._scheduler and self._scheduler.running:
                logger.info("Shutting down APScheduler...")
                self._scheduler.shutdown(wait=wait)
                self._is_running = False
                logger.info("APScheduler stopped successfully")

    @staticmethod
    def _scheduled_poll_worker() -> None:
        """Background execution worker using a dedicated, short-lived database session."""
        try:
            with SessionLocal() as db:
                sent, skipped, failed = FollowUpService.process_due_schedules(db)
                if sent > 0 or skipped > 0 or failed > 0:
                    logger.info(
                        "Follow-up poll completed: %d sent, %d skipped, %d failed",
                        sent,
                        skipped,
                        failed,
                    )

                # Process due approved campaign batches (Phase 9.7)
                from app.services.campaign_service import CampaignService
                due_batches = CampaignService.process_due_campaign_batches(db)
                if due_batches:
                    logger.info("Scheduled campaign poll dispatched %d batch(es)", len(due_batches))
        except Exception as e:
            logger.error("Error during scheduled poll execution: %s", str(e))


def get_scheduler_manager() -> SchedulerManager:
    """Return the singleton SchedulerManager instance."""
    return SchedulerManager()
