"""Automated tests for Phase 5 Follow-up Scheduler."""

import pytest
pytestmark = pytest.mark.skip(
    reason="APScheduler and automatic follow-up scheduling decommissioned per final CRM simplification requirements"
)

from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import FollowUpSchedule, Lead, MessageLog
from app.schemas.followup_schemas import FollowUpCreate, FollowUpUpdate
from app.services.followup_service import (
    FollowUpAlreadyProcessedError,
    FollowUpLimitReachedError,
    FollowUpService,
    FollowUpValidationError,
)
from app.services.scheduler_manager import SchedulerManager, get_scheduler_manager
from app.services.sender_boundary import MessageSenderBoundary, SendResult


class FailingMockSender:
    """Mock sender that simulates dispatch failure."""

    def send_follow_up_message(self, lead: Lead, schedule: FollowUpSchedule) -> SendResult:
        return SendResult(
            success=False,
            error_message="Simulated Meta WhatsApp API network timeout",
            timestamp=datetime.now(timezone.utc),
        )


def test_create_valid_schedule(client: TestClient, db_session: Session) -> None:
    """1. Test creating a valid schedule via POST /api/followups."""
    lead = Lead(customer_name="Pooja Sharma", phone_number="+919876543210")
    db_session.add(lead)
    db_session.flush()

    sched_time = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
    response = client.post("/api/followups", json={
        "lead_id": lead.id,
        "scheduled_at": sched_time,
        "attempt_number": 1,
    })
    assert response.status_code == 201
    data = response.json()
    assert data["lead_id"] == lead.id
    assert data["sequence_number"] == 1
    assert data["status"] == "Scheduled"
    assert data["attempt_number"] == 1


def test_reject_invalid_dates(client: TestClient, db_session: Session) -> None:
    """2. Test rejecting invalid dates."""
    lead = Lead(customer_name="Invalid Date Test", phone_number="+919876543211")
    db_session.add(lead)
    db_session.flush()

    response = client.post("/api/followups", json={
        "lead_id": lead.id,
        "scheduled_at": "not-a-valid-timestamp",
    })
    assert response.status_code == 422


def test_reject_schedule_for_nonexistent_lead(client: TestClient) -> None:
    """3. Test rejecting schedules for nonexistent leads."""
    sched_time = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    response = client.post("/api/followups", json={
        "lead_id": 999999,
        "scheduled_at": sched_time,
    })
    assert response.status_code == 422


def test_reject_schedules_beyond_followup_limit(client: TestClient, db_session: Session) -> None:
    """4. Test rejecting schedules beyond customer's configured maximum follow-up limit."""
    lead = Lead(customer_name="Limit Test", phone_number="+919876543212", max_follow_up_limit=2)
    db_session.add(lead)
    db_session.flush()

    # Pre-add 2 sent schedules (reaching the limit of 2)
    now = datetime.now(timezone.utc)
    s1 = FollowUpSchedule(lead_id=lead.id, sequence_number=1, scheduled_at=now, status="Sent")
    s2 = FollowUpSchedule(lead_id=lead.id, sequence_number=2, scheduled_at=now, status="Sent")
    db_session.add_all([s1, s2])
    db_session.flush()

    # Attempt to schedule a 3rd follow-up
    sched_time = (now + timedelta(days=3)).isoformat()
    response = client.post("/api/followups", json={
        "lead_id": lead.id,
        "scheduled_at": sched_time,
    })
    assert response.status_code == 409
    assert "maximum follow-up limit" in response.json()["detail"].lower()


def test_paused_leads_not_eligible(db_session: Session) -> None:
    """5. Test paused leads are not eligible for message dispatch."""
    lead = Lead(customer_name="Paused Lead", phone_number="+919876543213", follow_up_paused=True)
    db_session.add(lead)
    db_session.flush()

    schedule = FollowUpSchedule(
        lead_id=lead.id,
        sequence_number=1,
        scheduled_at=datetime.now(timezone.utc),
        status="Scheduled",
    )
    db_session.add(schedule)
    db_session.flush()

    is_eligible, reason = FollowUpService.check_eligibility(db_session, lead, schedule)
    assert is_eligible is False
    assert reason == "lead_follow_up_paused"


def test_not_interested_leads_not_eligible(db_session: Session) -> None:
    """6. Test 'Not Interested' leads are not eligible for follow-ups."""
    lead = Lead(customer_name="Not Interested Lead", phone_number="+919876543214", status="Not Interested")
    db_session.add(lead)
    db_session.flush()

    schedule = FollowUpSchedule(
        lead_id=lead.id,
        sequence_number=1,
        scheduled_at=datetime.now(timezone.utc),
        status="Scheduled",
    )
    db_session.add(schedule)
    db_session.flush()

    is_eligible, reason = FollowUpService.check_eligibility(db_session, lead, schedule)
    assert is_eligible is False
    assert reason == "lead_not_interested"


def test_replied_leads_remain_eligible(db_session: Session) -> None:
    """7. Business Rule: Replied leads remain eligible for follow-ups unless manually paused."""
    lead = Lead(customer_name="Replied Lead", phone_number="+919876543215", status="Replied", follow_up_paused=False)
    db_session.add(lead)
    db_session.flush()

    schedule = FollowUpSchedule(
        lead_id=lead.id,
        sequence_number=1,
        scheduled_at=datetime.now(timezone.utc),
        status="Scheduled",
    )
    db_session.add(schedule)
    db_session.flush()

    is_eligible, reason = FollowUpService.check_eligibility(db_session, lead, schedule)
    assert is_eligible is True
    assert reason is None


def test_due_schedules_identified_and_processed(db_session: Session) -> None:
    """8. Test due schedules are identified and processed with Sent status and MessageLog."""
    lead = Lead(customer_name="Due Lead", phone_number="+919876543216")
    db_session.add(lead)
    db_session.flush()

    past_time = datetime.now(timezone.utc) - timedelta(minutes=5)
    schedule = FollowUpSchedule(
        lead_id=lead.id,
        sequence_number=1,
        scheduled_at=past_time,
        status="Scheduled",
    )
    db_session.add(schedule)
    db_session.flush()

    sent, skipped, failed = FollowUpService.process_due_schedules(db_session)
    assert sent == 1
    assert skipped == 0
    assert failed == 0

    updated_sched = db_session.get(FollowUpSchedule, schedule.id)
    assert updated_sched.status == "Sent"
    assert updated_sched.processed_at is not None

    # Check MessageLog creation
    log = db_session.scalar(select(MessageLog).where(MessageLog.lead_id == lead.id))
    assert log is not None
    assert log.delivery_status == "Sent"


def test_future_schedules_remain_pending(db_session: Session) -> None:
    """9. Test future schedules are not processed prematurely."""
    lead = Lead(customer_name="Future Lead", phone_number="+919876543217")
    db_session.add(lead)
    db_session.flush()

    future_time = datetime.now(timezone.utc) + timedelta(days=2)
    schedule = FollowUpSchedule(
        lead_id=lead.id,
        sequence_number=1,
        scheduled_at=future_time,
        status="Scheduled",
    )
    db_session.add(schedule)
    db_session.flush()

    sent, skipped, failed = FollowUpService.process_due_schedules(db_session)
    assert sent == 0
    assert schedule.status == "Scheduled"


def test_offline_overdue_schedules_become_skipped(db_session: Session) -> None:
    """10. Critical: Missed follow-ups during laptop downtime must be marked Skipped."""
    lead = Lead(customer_name="Offline Test", phone_number="+919876543218")
    db_session.add(lead)
    db_session.flush()

    # Schedule that became due 2 hours ago while app was offline
    offline_time = datetime.now(timezone.utc) - timedelta(hours=2)
    schedule = FollowUpSchedule(
        lead_id=lead.id,
        sequence_number=1,
        scheduled_at=offline_time,
        status="Scheduled",
    )
    db_session.add(schedule)
    db_session.flush()

    # Startup reconciliation executes
    skipped_count = FollowUpService.reconcile_offline_missed_schedules(db_session)
    assert skipped_count == 1

    updated_sched = db_session.get(FollowUpSchedule, schedule.id)
    assert updated_sched.status == "Skipped"
    assert updated_sched.skip_reason == "missed_while_application_offline"
    assert updated_sched.processed_at is not None


def test_missed_schedules_never_sent_after_restart(db_session: Session) -> None:
    """11. Critical: Missed schedules must NEVER be sent automatically after app restart."""
    lead = Lead(customer_name="Never Late Test", phone_number="+919876543219")
    db_session.add(lead)
    db_session.flush()

    offline_time = datetime.now(timezone.utc) - timedelta(hours=1)
    schedule = FollowUpSchedule(
        lead_id=lead.id,
        sequence_number=1,
        scheduled_at=offline_time,
        status="Scheduled",
    )
    db_session.add(schedule)
    db_session.flush()

    # 1. Startup reconciliation marks skipped
    FollowUpService.reconcile_offline_missed_schedules(db_session)

    # 2. Poller runs after restart
    sent, skipped, failed = FollowUpService.process_due_schedules(db_session)
    assert sent == 0  # Zero sent!
    assert schedule.status == "Skipped"


def test_followup_count_increment_only_after_send(db_session: Session) -> None:
    """12. Test follow-up count increments only after successful send confirmation."""
    lead = Lead(customer_name="Count Test", phone_number="+919876543220")
    db_session.add(lead)
    db_session.flush()

    assert FollowUpService.get_sent_count(db_session, lead.id) == 0

    schedule = FollowUpSchedule(
        lead_id=lead.id,
        sequence_number=1,
        scheduled_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        status="Scheduled",
    )
    db_session.add(schedule)
    db_session.flush()

    FollowUpService.process_due_schedules(db_session)
    assert FollowUpService.get_sent_count(db_session, lead.id) == 1


def test_failed_schedules_do_not_increment_count(db_session: Session) -> None:
    """13. Test failed schedules do NOT increment the customer's sent follow-up count."""
    lead = Lead(customer_name="Fail Test", phone_number="+919876543221")
    db_session.add(lead)
    db_session.flush()

    schedule = FollowUpSchedule(
        lead_id=lead.id,
        sequence_number=1,
        scheduled_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        status="Scheduled",
    )
    db_session.add(schedule)
    db_session.flush()

    # Process with failing mock sender
    sent, skipped, failed = FollowUpService.process_due_schedules(db_session, sender=FailingMockSender())
    assert failed == 1
    assert sent == 0

    updated_sched = db_session.get(FollowUpSchedule, schedule.id)
    assert updated_sched.status == "Failed"
    assert "timeout" in updated_sched.skip_reason.lower()

    # Sent count must remain 0!
    assert FollowUpService.get_sent_count(db_session, lead.id) == 0


def test_duplicate_execution_prevention(db_session: Session) -> None:
    """14. Test schedules are never processed twice."""
    lead = Lead(customer_name="Dupe Execution Test", phone_number="+919876543222")
    db_session.add(lead)
    db_session.flush()

    schedule = FollowUpSchedule(
        lead_id=lead.id,
        sequence_number=1,
        scheduled_at=datetime.now(timezone.utc) - timedelta(minutes=2),
        status="Sent",  # Already sent
        processed_at=datetime.now(timezone.utc) - timedelta(minutes=2),
    )
    db_session.add(schedule)
    db_session.flush()

    sent, skipped, failed = FollowUpService.process_due_schedules(db_session)
    assert sent == 0
    assert skipped == 0
    assert failed == 0


def test_cancellation_behavior(client: TestClient, db_session: Session) -> None:
    """15. Test cancellation of scheduled items and rejection for already sent items."""
    lead = Lead(customer_name="Cancel Test", phone_number="+919876543223")
    db_session.add(lead)
    db_session.flush()

    now = datetime.now(timezone.utc)
    s1 = FollowUpSchedule(lead_id=lead.id, sequence_number=1, scheduled_at=now + timedelta(days=1), status="Scheduled")
    s2 = FollowUpSchedule(lead_id=lead.id, sequence_number=2, scheduled_at=now - timedelta(days=1), status="Sent")
    db_session.add_all([s1, s2])
    db_session.flush()

    # Cancel scheduled: succeeds
    resp1 = client.post(f"/api/followups/{s1.id}/cancel")
    assert resp1.status_code == 200
    assert resp1.json()["status"] == "Cancelled"

    # Cancel sent: rejected with 400
    resp2 = client.post(f"/api/followups/{s2.id}/cancel")
    assert resp2.status_code == 400
    assert "cannot cancel a follow-up that has already been sent" in resp2.json()["detail"].lower()


def test_scheduler_lifecycle(db_session: Session) -> None:
    """16. Test SchedulerManager initialization, start, shutdown, and double-start safety."""
    manager = get_scheduler_manager()

    # Start scheduler
    manager.start()
    assert manager.is_running is True

    # Attempting to start again should safely do nothing
    manager.start()
    assert manager.is_running is True

    # Shutdown
    manager.shutdown()
    assert manager.is_running is False


def test_asia_kolkata_timezone_handling(db_session: Session) -> None:
    """17. Test timezone conversion: Asia/Kolkata business time stored in UTC."""
    kolkata_tz = ZoneInfo("Asia/Kolkata")
    local_time = datetime(2026, 12, 1, 10, 0, 0, tzinfo=kolkata_tz)

    lead = Lead(customer_name="TZ Test", phone_number="+919876543224")
    db_session.add(lead)
    db_session.flush()

    schedule = FollowUpService.create_followup(
        db=db_session,
        payload=FollowUpCreate(lead_id=lead.id, scheduled_at=local_time),
    )

    # 10:00 AM IST (UTC+5:30) is 04:30 AM UTC
    assert schedule.scheduled_at.hour == 4
    assert schedule.scheduled_at.minute == 30
    assert schedule.scheduled_at.tzinfo in (timezone.utc, None)


def test_database_rollback_on_failure(db_session: Session) -> None:
    """18. Test transaction rollback when invalid lead ID is provided."""
    with pytest.raises(FollowUpValidationError):
        FollowUpService.create_followup(
            db=db_session,
            payload=FollowUpCreate(
                lead_id=-999,
                scheduled_at=datetime.now(timezone.utc) + timedelta(days=1),
            ),
        )
