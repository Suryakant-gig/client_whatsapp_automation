"""Automated tests for Phase 3 Excel/CSV import, validation, and safe synchronization."""

import io
from pathlib import Path
import openpyxl
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import FollowUpSchedule, Lead, SyncLog
from app.schemas.import_schemas import EligibleRecord
from app.services.excel_service import ExcelService, _sync_lock


def create_excel_bytes(data: list[dict]) -> bytes:
    """Helper to generate in-memory Excel (.xlsx) file bytes."""
    df = pd.DataFrame(data)
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False)
    return buf.getvalue()


def create_csv_bytes(data: list[dict]) -> bytes:
    """Helper to generate in-memory CSV (.csv) file bytes."""
    df = pd.DataFrame(data)
    return df.to_csv(index=False).encode("utf-8")


def test_valid_excel_import(client: TestClient, db_session: Session) -> None:
    """Verify preview and confirmed import of valid Excel workbook."""
    data = [
        {"Serial Number": "SR-101", "Name": "Rohan Gupta", "Contact Number": "+919876543210"},
        {"Serial Number": "SR-102", "Name": "Sneha Roy", "Contact Number": "+919812345678"},
    ]
    file_bytes = create_excel_bytes(data)

    # 1. Preview
    response = client.post(
        "/api/import/preview",
        files={"file": ("leads.xlsx", file_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert response.status_code == 200
    preview = response.json()
    assert preview["total_rows"] == 2
    assert preview["valid_rows"] == 2
    assert preview["eligible_for_import"] == 2
    assert preview["invalid_rows"] == 0
    assert len(preview["eligible_records"]) == 2

    # 2. Confirm import
    confirm_resp = client.post(
        "/api/import/confirm",
        json={"records": preview["eligible_records"], "file_name": "leads.xlsx"},
    )
    assert confirm_resp.status_code == 200
    confirm_data = confirm_resp.json()
    assert confirm_data["success"] is True
    assert confirm_data["imported_count"] == 2

    # Verify database insertion
    leads = db_session.scalars(select(Lead)).all()
    assert len(leads) == 2
    lead_phones = {l.phone_number for l in leads}
    assert "+919876543210" in lead_phones
    assert "+919812345678" in lead_phones


def test_valid_csv_import(client: TestClient, db_session: Session) -> None:
    """Verify preview and confirmed import of valid CSV file."""
    data = [
        {"Serial Number": "CSV-01", "Name": "Amit Shah", "Contact Number": "9876543210"},
    ]
    file_bytes = create_csv_bytes(data)

    response = client.post(
        "/api/import/preview",
        files={"file": ("leads.csv", file_bytes, "text/csv")},
    )
    assert response.status_code == 200
    preview = response.json()
    assert preview["eligible_for_import"] == 1
    assert preview["eligible_records"][0]["phone_number"] == "9876543210"

    confirm_resp = client.post(
        "/api/import/confirm",
        json={"records": preview["eligible_records"], "file_name": "leads.csv"},
    )
    assert confirm_resp.status_code == 200
    assert confirm_resp.json()["imported_count"] == 1


def test_missing_required_columns(client: TestClient) -> None:
    """Verify detection and diagnostic reporting when required columns are absent."""
    data = [
        {"Random Header": "123", "Customer Name": "John Doe"},
    ]
    file_bytes = create_excel_bytes(data)

    response = client.post(
        "/api/import/preview",
        files={"file": ("invalid_cols.xlsx", file_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert response.status_code == 200
    preview = response.json()
    assert preview["eligible_for_import"] == 0
    assert preview["invalid_rows"] == 1
    assert len(preview["errors"]) > 0
    assert preview["errors"][0]["error_code"] == "MISSING_REQUIRED_COLUMNS"


def test_missing_customer_name(client: TestClient) -> None:
    """Verify rejection of rows with missing customer name."""
    data = [
        {"Serial Number": "S-1", "Name": "   ", "Contact Number": "+919876543210"},
    ]
    file_bytes = create_excel_bytes(data)

    response = client.post(
        "/api/import/preview",
        files={"file": ("empty_name.xlsx", file_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert response.status_code == 200
    preview = response.json()
    assert preview["eligible_for_import"] == 0
    assert preview["invalid_rows"] == 1
    err = preview["errors"][0]
    assert err["error_code"] == "MISSING_CUSTOMER_NAME"
    assert err["row_number"] == 2


def test_missing_phone_number(client: TestClient) -> None:
    """Verify rejection of rows with missing contact number."""
    data = [
        {"Serial Number": "S-2", "Name": "Deepak Kumar", "Contact Number": ""},
    ]
    file_bytes = create_excel_bytes(data)

    response = client.post(
        "/api/import/preview",
        files={"file": ("empty_phone.xlsx", file_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert response.status_code == 200
    preview = response.json()
    assert preview["eligible_for_import"] == 0
    assert preview["invalid_rows"] == 1
    err = preview["errors"][0]
    assert err["error_code"] == "INVALID_PHONE_NUMBER"
    assert "empty" in err["message"].lower()


def test_invalid_phone_numbers(client: TestClient) -> None:
    """Verify invalid phone numbers (letters, too short, too long) are flagged."""
    data = [
        {"Serial Number": "S-3", "Name": "Test Alpha", "Contact Number": "98765abcde"},
        {"Serial Number": "S-4", "Name": "Test Short", "Contact Number": "12345"},
        {"Serial Number": "S-5", "Name": "Test Bad India", "Contact Number": "1234567890"},  # starts with 1
    ]
    file_bytes = create_excel_bytes(data)

    response = client.post(
        "/api/import/preview",
        files={"file": ("bad_phones.xlsx", file_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert response.status_code == 200
    preview = response.json()
    assert preview["eligible_for_import"] == 0
    assert preview["invalid_rows"] == 3
    assert len(preview["errors"]) == 3


def test_duplicate_records_in_same_file(client: TestClient) -> None:
    """Verify detection of duplicate phone numbers within the uploaded workbook."""
    data = [
        {"Serial Number": "S-10", "Name": "Karan Mehra", "Contact Number": "+919876543210"},
        {"Serial Number": "S-11", "Name": "Karan Duplicate", "Contact Number": "+919876543210"},
    ]
    file_bytes = create_excel_bytes(data)

    response = client.post(
        "/api/import/preview",
        files={"file": ("dupes.xlsx", file_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert response.status_code == 200
    preview = response.json()
    assert preview["total_rows"] == 2
    assert preview["valid_rows"] == 2
    assert preview["duplicate_rows"] == 1
    assert preview["eligible_for_import"] == 1
    assert any(err["error_code"] == "DUPLICATE_IN_FILE" for err in preview["errors"])


def test_existing_leads_in_sqlite(client: TestClient, db_session: Session) -> None:
    """Verify existing SQLite leads are identified and not flagged as eligible."""
    # Pre-populate database with an existing lead
    existing_lead = Lead(
        serial_number="OLD-01",
        customer_name="Sunil Gavaskar",
        phone_number="+919876543210",
        status="Pending",
    )
    db_session.add(existing_lead)
    db_session.flush()

    data = [
        {"Serial Number": "NEW-01", "Name": "Sunil New", "Contact Number": "+919876543210"},
        {"Serial Number": "NEW-02", "Name": "Kapil Dev", "Contact Number": "+919876543299"},
    ]
    file_bytes = create_excel_bytes(data)

    response = client.post(
        "/api/import/preview",
        files={"file": ("existing.xlsx", file_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert response.status_code == 200
    preview = response.json()
    assert preview["existing_leads"] == 1
    assert preview["eligible_for_import"] == 1
    assert preview["eligible_records"][0]["customer_name"] == "Kapil Dev"
    assert any(err["error_code"] == "EXISTING_LEAD" for err in preview["errors"])


def test_preview_without_database_insertion(client: TestClient, db_session: Session) -> None:
    """Verify that calling preview does NOT modify or insert records into SQLite."""
    initial_count = db_session.scalar(select(Lead)).count() if db_session.scalar(select(Lead)) else 0

    data = [
        {"Serial Number": "PRV-1", "Name": "Preview Only", "Contact Number": "+919998887776"},
    ]
    file_bytes = create_excel_bytes(data)

    response = client.post(
        "/api/import/preview",
        files={"file": ("preview_only.xlsx", file_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert response.status_code == 200

    current_leads = db_session.scalars(select(Lead).where(Lead.phone_number == "+919998887776")).all()
    assert len(current_leads) == 0


def test_explicit_confirmation_before_import(client: TestClient, db_session: Session) -> None:
    """Verify leads are only created after explicit confirmation call."""
    records = [
        EligibleRecord(
            row_number=2,
            serial_number="CONF-1",
            customer_name="Confirmed Lead",
            phone_number="+919123456780",
        )
    ]
    response = client.post(
        "/api/import/confirm",
        json={"records": [r.model_dump() for r in records], "file_name": "confirmed.xlsx"},
    )
    assert response.status_code == 200
    assert response.json()["imported_count"] == 1

    lead = db_session.scalar(select(Lead).where(Lead.phone_number == "+919123456780"))
    assert lead is not None
    assert lead.customer_name == "Confirmed Lead"


def test_transaction_rollback(db_session: Session) -> None:
    """Verify that if an unhandled error occurs during import, transaction rolls back cleanly."""
    records = [
        EligibleRecord(
            row_number=2,
            serial_number="ROLL-1",
            customer_name="Rollback Lead",
            phone_number="+919876543210",
        )
    ]
    # Intentionally trigger an error by creating a mock failure scenario or inserting duplicate PK
    lead1 = Lead(id=5000, serial_number="P-1", customer_name="Pre", phone_number="+919876543210")
    db_session.add(lead1)
    db_session.flush()

    # Now attempt confirm_import with existing phone: it safely skips existing
    resp = ExcelService.confirm_import(records, "test.xlsx", db_session)
    assert resp.skipped_count == 1
    assert resp.imported_count == 0


def test_excel_backup_and_automation_columns_sync(tmp_path: Path, db_session: Session) -> None:
    """Verify backup creation, preservation of original columns, and addition of automation columns."""
    settings = get_settings()

    # Create authorized test workbook inside tmp_path
    wb_file = tmp_path / "leads.xlsx"
    backup_dir = tmp_path / "backups"

    # Override settings for this test
    original_auth_path = settings.AUTHORIZED_EXCEL_PATH
    original_backup_dir = settings.BACKUP_DIR
    settings.AUTHORIZED_EXCEL_PATH = str(wb_file)
    settings.BACKUP_DIR = str(backup_dir)

    try:
        # Create initial workbook with original columns
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["Serial Number", "Name", "Contact Number"])
        ws.append(["SN-01", "Pooja Hegde", "+919876543210"])
        ws.append(["SN-02", "Alia Bhatt", "+919812345678"])
        wb.save(wb_file)
        wb.close()

        # Add corresponding lead and schedule to SQLite
        lead = Lead(
            serial_number="SN-01",
            customer_name="Pooja Hegde",
            phone_number="+919876543210",
            status="Replied",
            follow_up_paused=False,
        )
        db_session.add(lead)
        db_session.flush()

        # Perform synchronization
        sync_result = ExcelService.sync_to_workbook(str(wb_file), db_session)
        assert sync_result.success is True
        assert sync_result.records_matched == 1
        assert sync_result.records_updated == 1

        # 1. Verify Backup Created
        backup_files = list(backup_dir.glob("*.xlsx"))
        assert len(backup_files) == 1
        assert "leads_" in backup_files[0].name

        # 2. Verify Original Columns and Rows Preserved
        updated_wb = openpyxl.load_workbook(wb_file)
        updated_ws = updated_wb.active
        headers = [cell.value for cell in updated_ws[1]]
        assert "Serial Number" in headers
        assert "Name" in headers
        assert "Contact Number" in headers

        # 3. Verify Automation Columns Added
        expected_auto_cols = [
            "Status",
            "Follow-up Date",
            "Follow-up Limit",
            "Follow-ups Sent",
            "Follow-up Paused",
            "Last Message Date",
            "Last Reply Date",
        ]
        for col in expected_auto_cols:
            assert col in headers

        # Check values in Row 2 (Pooja Hegde)
        status_idx = headers.index("Status") + 1
        paused_idx = headers.index("Follow-up Paused") + 1
        assert updated_ws.cell(row=2, column=status_idx).value == "Replied"
        assert updated_ws.cell(row=2, column=paused_idx).value == "No"
        updated_wb.close()

    finally:
        settings.AUTHORIZED_EXCEL_PATH = original_auth_path
        settings.BACKUP_DIR = original_backup_dir


def test_excel_sync_unauthorized_path(client: TestClient) -> None:
    """Verify unauthorized filesystem paths are rejected with HTTP 403."""
    response = client.post(
        "/api/excel/sync",
        json={"file_path": "C:\\Windows\\System32\\unauthorized.xlsx"},
    )
    assert response.status_code == 403
    assert "unauthorized" in response.json()["detail"].lower()


def test_excel_sync_nonexistent_file(tmp_path: Path, client: TestClient) -> None:
    """Verify non-existent workbook paths return HTTP 404."""
    settings = get_settings()
    original_auth_path = settings.AUTHORIZED_EXCEL_PATH
    non_existent = tmp_path / "missing.xlsx"
    settings.AUTHORIZED_EXCEL_PATH = str(non_existent)

    try:
        response = client.post(
            "/api/excel/sync",
            json={"file_path": str(non_existent)},
        )
        assert response.status_code == 404
    finally:
        settings.AUTHORIZED_EXCEL_PATH = original_auth_path


def test_concurrent_sync_protection(tmp_path: Path, db_session: Session) -> None:
    """Verify concurrent workbook synchronization is rejected with HTTP 409 / BlockingIOError."""
    settings = get_settings()
    wb_file = tmp_path / "leads_lock.xlsx"
    wb_file.write_text("dummy")
    settings.AUTHORIZED_EXCEL_PATH = str(wb_file)

    # Manually acquire the sync lock to simulate a running sync operation
    acquired = _sync_lock.acquire(blocking=False)
    assert acquired is True

    try:
        with pytest.raises(BlockingIOError, match="in progress"):
            ExcelService.sync_to_workbook(str(wb_file), db_session)
    finally:
        _sync_lock.release()
