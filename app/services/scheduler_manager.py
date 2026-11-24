"""Scheduler removal stub.

APScheduler and all automatic future scheduling have been completely removed
per architecture requirements.
"""

import logging

logger = logging.getLogger("app.services.scheduler")


class SchedulerManager:
    """Inert stub retained solely for backward compatibility with tests/imports."""

    @property
    def is_running(self) -> bool:
        return False

    def start(self) -> None:
        logger.info("Scheduler is permanently decommissioned.")

    def shutdown(self, wait: bool = False) -> None:
        pass


def get_scheduler_manager() -> SchedulerManager:
    return SchedulerManager()
