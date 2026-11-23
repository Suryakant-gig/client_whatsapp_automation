"""Excel and CSV data processing, validation, and synchronization service."""

import os
import re
import shutil
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import openpyxl
import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import FollowUpSchedule, IncomingMessage, Lead, MessageLog, SyncLog
from app.schemas.import_schemas import (
    EligibleRecord,
    ImportConfirmResponse,
    ImportPreviewResponse,
    RowValidationError,
)
from app.schemas.sync_schemas import ExcelSyncResponse

# Global lock to prevent concurrent workbook writes
_sync_lock = threading.Lock()

# Column aliases for flexible matching of client's 3 required columns
COLUMN_ALIASES: Dict[str, List[str]] = {
    "serial_number": [
        "serial number",
        "serial no",
        "serial_number",
        "serial_no",
        "sr no",
        "sr. no",
        "sr.no",
        "s.no",
        "sno",
        "serial",
    ],
    "customer_name": [
        "name",
        "customer name",
        "customer_name",
        "client name",
        "client_name",
        "full name",
    ],
    "phone_number": [
        "contact number",
        "contact no",
        "contact_number",
        "contact_no",
        "contact",
        "phone",
        "phone number",
        "phone_number",
        "mobile",
        "mobile number",
        "mobile_number",
        "whatsapp number",
    ],
}

AUTOMATION_COLUMNS = [
    "Status",
    "Follow-up Date",
    "Follow-up Limit",
    "Follow-ups Sent",
    "Follow-up Paused",
    "Last Message Date",
    "Last Reply Date",
]


class ExcelService:
    """Service handling Excel/CSV parsing, data validation, and two-way synchronization."""

    @staticmethod
    def normalize_phone_number(raw_phone: Any) -> Tuple[Optional[str], Optional[str]]:
        """Clean and validate international or Indian phone numbers.

        Preserves country codes (+91, +1, etc.).
        Does not silently guess missing country codes.
        Returns: (cleaned_phone, error_message)
        """
        if raw_phone is None or pd.isna(raw_phone):
            return None, "Contact number is empty"

        # Convert to string without scientific notation or trailing float decimals
        if isinstance(raw_phone, float):
            if raw_phone.is_integer():
                phone_str = str(int(raw_phone))
            else:
                phone_str = f"{raw_phone:.0f}"
        else:
            phone_str = str(raw_phone).strip()

        if not phone_str or phone_str.lower() in ("nan", "none", "null"):
            return None, "Contact number is empty"

        # Check for disallowed characters (letters or special chars other than +, -, spaces, parens)
        if re.search(r"[a-zA-Z]", phone_str):
            return None, f"Contact number contains letters: '{phone_str}'"

        # Remove spaces, dashes, parentheses
        cleaned = re.sub(r"[\s\-\(\)\.]", "", phone_str)

        # Retain leading + if present
        has_plus = cleaned.startswith("+")
        digits_only = cleaned[1:] if has_plus else cleaned

        if not digits_only.isdigit():
            return None, f"Contact number contains invalid characters: '{phone_str}'"

        total_digits = len(digits_only)

        # Standard Indian number without country code: 10 digits starting with 6, 7, 8, 9
        if not has_plus and total_digits == 10:
            if digits_only[0] in "6789":
                return digits_only, None
            return None, f"10-digit Indian phone number must begin with 6-9: '{phone_str}'"

        # Indian number with leading 0: 11 digits (0 + 10 digits)
        if not has_plus and total_digits == 11 and digits_only.startswith("0"):
            ten_digit = digits_only[1:]
            if ten_digit[0] in "6789":
                return ten_digit, None
            return None, f"Invalid 11-digit number: '{phone_str}'"

        # Indian number with 91 prefix without plus: 12 digits (91 + 10 digits)
        if not has_plus and total_digits == 12 and digits_only.startswith("91"):
            ten_digit = digits_only[2:]
            if ten_digit[0] in "6789":
                return f"+91{ten_digit}", None
            return None, f"Invalid 91-prefixed Indian number: '{phone_str}'"

        # General International number: 7 to 15 digits (ITU-T E.164 recommendation)
        if 7 <= total_digits <= 15:
            return (f"+{digits_only}" if has_plus else digits_only), None

        return None, f"Contact number length ({total_digits} digits) is outside valid range (7-15 digits): '{phone_str}'"

    @staticmethod
    def identify_columns(columns: List[str]) -> Tuple[Dict[str, str], List[str]]:
        """Map user's workbook columns to canonical keys.

        Returns: (mapping_dict, missing_columns_list)
        """
        mapping: Dict[str, str] = {}
        normalized_cols = {col: re.sub(r"[\s_\.\-]+", " ", str(col)).strip().lower() for col in columns}

        for canonical_key, aliases in COLUMN_ALIASES.items():
            matched_col = None
            for original_col, norm in normalized_cols.items():
                if norm in aliases:
                    matched_col = original_col
                    break
            if matched_col:
                mapping[canonical_key] = matched_col

        missing = [key for key in ("serial_number", "customer_name", "phone_number") if key not in mapping]
        return mapping, missing

    @classmethod
    def read_file_to_dataframe(cls, file_bytes: bytes, filename: str) -> pd.DataFrame:
        """Parse uploaded .xlsx or .csv into a pandas DataFrame."""
        settings = get_settings()
        if len(file_bytes) > settings.MAX_UPLOAD_SIZE_BYTES:
            raise ValueError(
                f"File size exceeds maximum permitted limit of {settings.MAX_UPLOAD_SIZE_BYTES / (1024 * 1024):.1f} MB"
            )

        lower_name = filename.lower()
        if lower_name.endswith(".csv"):
            import io

            # Try utf-8 then fallback to latin-1
            try:
                df = pd.read_csv(io.BytesIO(file_bytes), dtype=str, encoding="utf-8")
            except UnicodeDecodeError:
                df = pd.read_csv(io.BytesIO(file_bytes), dtype=str, encoding="latin-1")
        elif lower_name.endswith(".xlsx"):
            import io

            df = pd.read_excel(io.BytesIO(file_bytes), dtype=str, engine="openpyxl")
        else:
            raise ValueError(f"Unsupported file format '{filename}'. Allowed formats: .xlsx, .csv")

        return df

    @classmethod
    def generate_preview(
        cls,
        df: pd.DataFrame,
        db: Session,
    ) -> ImportPreviewResponse:
        """Validate all rows in DataFrame, detect duplicates/existing leads, and return preview."""
        column_mapping, missing_columns = cls.identify_columns(list(df.columns))

        if missing_columns:
            readable_missing = ", ".join(missing_columns)
            readable_found = ", ".join([str(c) for c in df.columns])
            return ImportPreviewResponse(
                total_rows=len(df),
                valid_rows=0,
                invalid_rows=len(df),
                duplicate_rows=0,
                existing_leads=0,
                eligible_for_import=0,
                errors=[
                    RowValidationError(
                        row_number=1,
                        field="columns",
                        value=None,
                        error_code="MISSING_REQUIRED_COLUMNS",
                        message=f"Missing required column(s): [{readable_missing}]. Workbook contains: [{readable_found}]",
                    )
                ],
                eligible_records=[],
            )

        # Retrieve existing phone numbers and serial numbers from SQLite
        existing_phones_query = select(Lead.phone_number).distinct()
        existing_phones = set(db.scalars(existing_phones_query).all())

        col_serial = column_mapping["serial_number"]
        col_name = column_mapping["customer_name"]
        col_phone = column_mapping["phone_number"]

        total_rows = len(df)
        valid_rows = 0
        invalid_rows = 0
        duplicate_rows = 0
        existing_leads_count = 0

        errors: List[RowValidationError] = []
        eligible_records: List[EligibleRecord] = []
        seen_phones_in_file: Set[str] = set()

        for idx, row in df.iterrows():
            row_num = idx + 2  # 1-based index (header is row 1)
            row_has_error = False

            # 1. Validate Serial Number
            raw_serial = row.get(col_serial)
            serial_str = ""
            if raw_serial is not None and not pd.isna(raw_serial):
                serial_str = str(raw_serial).strip()
            if not serial_str or serial_str.lower() in ("nan", "none", "null"):
                errors.append(
                    RowValidationError(
                        row_number=row_num,
                        field="serial_number",
                        value=str(raw_serial) if raw_serial is not None else None,
                        error_code="MISSING_SERIAL_NUMBER",
                        message="Serial number is missing or empty",
                    )
                )
                row_has_error = True

            # 2. Validate Customer Name
            raw_name = row.get(col_name)
            name_str = ""
            if raw_name is not None and not pd.isna(raw_name):
                name_str = str(raw_name).strip()
            if not name_str or name_str.lower() in ("nan", "none", "null"):
                errors.append(
                    RowValidationError(
                        row_number=row_num,
                        field="customer_name",
                        value=str(raw_name) if raw_name is not None else None,
                        error_code="MISSING_CUSTOMER_NAME",
                        message="Customer name is missing or empty",
                    )
                )
                row_has_error = True

            # 3. Validate Contact Number
            raw_phone = row.get(col_phone)
            clean_phone, phone_err = cls.normalize_phone_number(raw_phone)
            if phone_err:
                errors.append(
                    RowValidationError(
                        row_number=row_num,
                        field="phone_number",
                        value=str(raw_phone) if raw_phone is not None else None,
                        error_code="INVALID_PHONE_NUMBER",
                        message=phone_err,
                    )
                )
                row_has_error = True

            if row_has_error:
                invalid_rows += 1
                continue

            valid_rows += 1

            # 4. Detect Duplicate Within Uploaded File
            if clean_phone in seen_phones_in_file:
                duplicate_rows += 1
                errors.append(
                    RowValidationError(
                        row_number=row_num,
                        field="phone_number",
                        value=clean_phone,
                        error_code="DUPLICATE_IN_FILE",
                        message=f"Duplicate contact number '{clean_phone}' found in uploaded file",
                    )
                )
                continue

            seen_phones_in_file.add(clean_phone)

            # 5. Detect Existing Lead in SQLite
            if clean_phone in existing_phones:
                existing_leads_count += 1
                errors.append(
                    RowValidationError(
                        row_number=row_num,
                        field="phone_number",
                        value=clean_phone,
                        error_code="EXISTING_LEAD",
                        message=f"Lead with contact number '{clean_phone}' already exists in database",
                    )
                )
                continue

            # Record is eligible for import
            eligible_records.append(
                EligibleRecord(
                    row_number=row_num,
                    serial_number=serial_str,
                    customer_name=name_str,
                    phone_number=clean_phone,
                )
            )

        return ImportPreviewResponse(
            total_rows=total_rows,
            valid_rows=valid_rows,
            invalid_rows=invalid_rows,
            duplicate_rows=duplicate_rows,
            existing_leads=existing_leads_count,
            eligible_for_import=len(eligible_records),
            errors=errors,
            eligible_records=eligible_records,
        )

    @classmethod
    def confirm_import(
        cls,
        records: List[EligibleRecord],
        file_name: str,
        db: Session,
    ) -> ImportConfirmResponse:
        """Transactionally import confirmed eligible records into SQLite.

        Logs operation in sync_logs table.
        Rolls back completely if an unexpected error occurs.
        """
        if not records:
            return ImportConfirmResponse(
                success=True,
                imported_count=0,
                skipped_count=0,
                message="No records provided for import",
            )

        imported_count = 0
        skipped_count = 0

        try:
            # Query current existing phones to prevent race condition duplicates
            existing_phones_query = select(Lead.phone_number)
            existing_phones = set(db.scalars(existing_phones_query).all())

            for record in records:
                if record.phone_number in existing_phones:
                    skipped_count += 1
                    continue

                lead = Lead(
                    serial_number=record.serial_number,
                    customer_name=record.customer_name,
                    phone_number=record.phone_number,
                    status="Pending",
                    follow_up_paused=False,
                )
                db.add(lead)
                existing_phones.add(record.phone_number)
                imported_count += 1

            # Create audit sync log
            sync_log = SyncLog(
                operation="excel_import" if file_name.lower().endswith(".xlsx") else "csv_import",
                file_name=file_name,
                sync_status="Success",
                records_processed=imported_count,
                error_message=None if skipped_count == 0 else f"{skipped_count} duplicate records skipped",
                created_at=datetime.now(timezone.utc),
            )
            db.add(sync_log)

            db.commit()

            return ImportConfirmResponse(
                success=True,
                imported_count=imported_count,
                skipped_count=skipped_count,
                message=f"Successfully imported {imported_count} leads ({skipped_count} skipped)",
            )

        except Exception as e:
            db.rollback()
            # Log failed sync attempt in a fresh transaction
            try:
                fail_log = SyncLog(
                    operation="excel_import",
                    file_name=file_name,
                    sync_status="Failed",
                    records_processed=0,
                    error_message=str(e),
                    created_at=datetime.now(timezone.utc),
                )
                db.add(fail_log)
                db.commit()
            except Exception:
                db.rollback()

            raise RuntimeError(f"Database import transaction failed: {str(e)}") from e

    @classmethod
    def sync_to_workbook(
        cls,
        target_path: Optional[str],
        db: Session,
    ) -> ExcelSyncResponse:
        """Safely synchronize SQLite lead state into the authorized workbook.

        - Preserves original customer columns.
        - Appends or updates automation columns.
        - Creates a timestamped backup before modifying.
        - Uses atomic file replacement (temp file -> target).
        - Protected by concurrency lock.
        - Logs sync outcome in sync_logs table.
        """
        settings = get_settings()
        resolved_path = Path(target_path or settings.AUTHORIZED_EXCEL_PATH).resolve()

        # Security check: Ensure target_path is within authorized base directory or authorized file
        authorized_file = Path(settings.AUTHORIZED_EXCEL_PATH).resolve()
        authorized_dir = authorized_file.parent

        if not (resolved_path == authorized_file or authorized_dir in resolved_path.parents):
            raise PermissionError(
                f"Unauthorized workbook path: '{resolved_path}'. Synchronization is restricted to '{authorized_dir}'"
            )

        if not resolved_path.exists():
            raise FileNotFoundError(f"Workbook not found at authorized path: '{resolved_path}'")

        # Acquire lock to prevent concurrent sync operations
        acquired = _sync_lock.acquire(blocking=False)
        if not acquired:
            raise BlockingIOError("A workbook synchronization operation is currently in progress. Please retry shortly.")

        try:
            return cls._perform_sync(resolved_path, db)
        finally:
            _sync_lock.release()

    @classmethod
    def _perform_sync(cls, file_path: Path, db: Session) -> ExcelSyncResponse:
        """Execute the backup, update, and atomic write operations."""
        settings = get_settings()
        backup_dir = Path(settings.BACKUP_DIR).resolve()
        backup_dir.mkdir(parents=True, exist_ok=True)

        # 1. Create timestamped backup copy
        timestamp_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        backup_filename = f"{file_path.stem}_{timestamp_str}{file_path.suffix}"
        backup_path = backup_dir / backup_filename
        shutil.copy2(file_path, backup_path)

        # 2. Fetch lead metadata from SQLite
        leads = db.scalars(select(Lead)).all()
        lead_by_phone: Dict[str, Lead] = {lead.phone_number: lead for lead in leads}
        lead_by_serial: Dict[str, Lead] = {lead.serial_number: lead for lead in leads if lead.serial_number}

        # Precompute related data for automation columns
        lead_ids = [lead.id for lead in leads]

        # Scheduled follow-ups: find next scheduled date
        schedules = db.scalars(
            select(FollowUpSchedule).where(FollowUpSchedule.lead_id.in_(lead_ids))
        ).all()
        
        next_follow_up_by_lead: Dict[int, str] = {}
        sent_follow_ups_by_lead: Dict[int, int] = {}

        for sched in sorted(schedules, key=lambda s: s.scheduled_at):
            if sched.status == "Scheduled" and sched.lead_id not in next_follow_up_by_lead:
                next_follow_up_by_lead[sched.lead_id] = sched.scheduled_at.strftime("%Y-%m-%d %H:%M:%S")
            if sched.status == "Sent":
                sent_follow_ups_by_lead[sched.lead_id] = sent_follow_ups_by_lead.get(sched.lead_id, 0) + 1

        # Latest message logs
        msg_logs = db.scalars(
            select(MessageLog).where(MessageLog.lead_id.in_(lead_ids)).order_by(MessageLog.created_at.desc())
        ).all()
        latest_sent_by_lead: Dict[int, str] = {}
        for m in msg_logs:
            if m.lead_id and m.lead_id not in latest_sent_by_lead and m.sent_at:
                latest_sent_by_lead[m.lead_id] = m.sent_at.strftime("%Y-%m-%d %H:%M:%S")

        # Latest incoming messages
        in_msgs = db.scalars(
            select(IncomingMessage).where(IncomingMessage.lead_id.in_(lead_ids)).order_by(IncomingMessage.received_at.desc())
        ).all()
        latest_reply_by_lead: Dict[int, str] = {}
        for im in in_msgs:
            if im.lead_id and im.lead_id not in latest_reply_by_lead:
                latest_reply_by_lead[im.lead_id] = im.received_at.strftime("%Y-%m-%d %H:%M:%S")

        records_matched = 0
        records_updated = 0

        # 3. Synchronize file based on format
        is_excel = file_path.suffix.lower() == ".xlsx"

        try:
            if is_excel:
                records_matched, records_updated = cls._sync_excel(
                    file_path=file_path,
                    lead_by_phone=lead_by_phone,
                    lead_by_serial=lead_by_serial,
                    next_follow_up=next_follow_up_by_lead,
                    sent_counts=sent_follow_ups_by_lead,
                    latest_sent=latest_sent_by_lead,
                    latest_reply=latest_reply_by_lead,
                    default_limit=settings.DEFAULT_FOLLOW_UP_LIMIT,
                )
            else:
                records_matched, records_updated = cls._sync_csv(
                    file_path=file_path,
                    lead_by_phone=lead_by_phone,
                    lead_by_serial=lead_by_serial,
                    next_follow_up=next_follow_up_by_lead,
                    sent_counts=sent_follow_ups_by_lead,
                    latest_sent=latest_sent_by_lead,
                    latest_reply=latest_reply_by_lead,
                    default_limit=settings.DEFAULT_FOLLOW_UP_LIMIT,
                )

            # Record successful sync log
            sync_log = SyncLog(
                operation="excel_sync",
                file_name=str(file_path.name),
                sync_status="Success",
                records_processed=records_updated,
                error_message=None,
                created_at=datetime.now(timezone.utc),
            )
            db.add(sync_log)
            db.commit()

            return ExcelSyncResponse(
                success=True,
                file_path=str(file_path),
                backup_path=str(backup_path),
                records_matched=records_matched,
                records_updated=records_updated,
                message=f"Workbook synchronized successfully. {records_matched} records matched, {records_updated} updated.",
            )

        except Exception as e:
            # Record failed sync log
            try:
                fail_log = SyncLog(
                    operation="excel_sync",
                    file_name=str(file_path.name),
                    sync_status="Failed",
                    records_processed=0,
                    error_message=str(e),
                    created_at=datetime.now(timezone.utc),
                )
                db.add(fail_log)
                db.commit()
            except Exception:
                db.rollback()

            raise RuntimeError(f"Workbook synchronization failed: {str(e)}") from e

    @classmethod
    def _sync_excel(
        cls,
        file_path: Path,
        lead_by_phone: Dict[str, Lead],
        lead_by_serial: Dict[str, Lead],
        next_follow_up: Dict[int, str],
        sent_counts: Dict[int, int],
        latest_sent: Dict[int, str],
        latest_reply: Dict[int, str],
        default_limit: int,
    ) -> Tuple[int, int]:
        """Update .xlsx workbook preserving formatting and using atomic write."""
        wb = openpyxl.load_workbook(file_path)
        ws = wb.active

        # Identify header columns
        header_vals = [cell.value for cell in ws[1]]
        str_headers = [str(v) if v is not None else "" for v in header_vals]
        column_mapping, _ = cls.identify_columns(str_headers)

        col_serial_idx = None
        col_phone_idx = None

        if "serial_number" in column_mapping:
            col_serial_idx = str_headers.index(column_mapping["serial_number"]) + 1
        if "phone_number" in column_mapping:
            col_phone_idx = str_headers.index(column_mapping["phone_number"]) + 1

        # Ensure automation columns exist in header row
        automation_col_indices: Dict[str, int] = {}
        for auto_col in AUTOMATION_COLUMNS:
            if auto_col in str_headers:
                automation_col_indices[auto_col] = str_headers.index(auto_col) + 1
            else:
                new_col_idx = len(str_headers) + 1
                ws.cell(row=1, column=new_col_idx, value=auto_col)
                str_headers.append(auto_col)
                automation_col_indices[auto_col] = new_col_idx

        records_matched = 0
        records_updated = 0

        # Iterate data rows (row 2 onwards)
        for row_idx in range(2, ws.max_row + 1):
            phone_val = ws.cell(row=row_idx, column=col_phone_idx).value if col_phone_idx else None
            serial_val = ws.cell(row=row_idx, column=col_serial_idx).value if col_serial_idx else None

            clean_phone, _ = cls.normalize_phone_number(phone_val)
            clean_serial = str(serial_val).strip() if serial_val is not None else None

            # Match by phone first, then by serial
            matched_lead = None
            if clean_phone and clean_phone in lead_by_phone:
                matched_lead = lead_by_phone[clean_phone]
            elif clean_serial and clean_serial in lead_by_serial:
                matched_lead = lead_by_serial[clean_serial]

            if matched_lead:
                records_matched += 1
                lead_id = matched_lead.id

                ws.cell(row=row_idx, column=automation_col_indices["Status"], value=matched_lead.status)
                ws.cell(
                    row=row_idx,
                    column=automation_col_indices["Follow-up Date"],
                    value=next_follow_up.get(lead_id, ""),
                )
                ws.cell(row=row_idx, column=automation_col_indices["Follow-up Limit"], value=default_limit)
                ws.cell(
                    row=row_idx,
                    column=automation_col_indices["Follow-ups Sent"],
                    value=sent_counts.get(lead_id, 0),
                )
                ws.cell(
                    row=row_idx,
                    column=automation_col_indices["Follow-up Paused"],
                    value="Yes" if matched_lead.follow_up_paused else "No",
                )
                ws.cell(
                    row=row_idx,
                    column=automation_col_indices["Last Message Date"],
                    value=latest_sent.get(lead_id, ""),
                )
                ws.cell(
                    row=row_idx,
                    column=automation_col_indices["Last Reply Date"],
                    value=latest_reply.get(lead_id, ""),
                )
                records_updated += 1

        # Atomic write to temporary file then replace
        temp_dir = file_path.parent
        with tempfile.NamedTemporaryFile(dir=temp_dir, delete=False, suffix=".xlsx") as tmp_file:
            tmp_path = tmp_file.name

        try:
            wb.save(tmp_path)
            wb.close()
            os.replace(tmp_path, file_path)
        except Exception:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            raise

        return records_matched, records_updated

    @classmethod
    def _sync_csv(
        cls,
        file_path: Path,
        lead_by_phone: Dict[str, Lead],
        lead_by_serial: Dict[str, Lead],
        next_follow_up: Dict[int, str],
        sent_counts: Dict[int, int],
        latest_sent: Dict[int, str],
        latest_reply: Dict[int, str],
        default_limit: int,
    ) -> Tuple[int, int]:
        """Update .csv file and replace atomically."""
        df = pd.read_csv(file_path, dtype=str)
        column_mapping, _ = cls.identify_columns(list(df.columns))

        col_phone = column_mapping.get("phone_number")
        col_serial = column_mapping.get("serial_number")

        for col in AUTOMATION_COLUMNS:
            if col not in df.columns:
                df[col] = ""

        records_matched = 0
        records_updated = 0

        for idx, row in df.iterrows():
            phone_val = row.get(col_phone) if col_phone else None
            serial_val = row.get(col_serial) if col_serial else None

            clean_phone, _ = cls.normalize_phone_number(phone_val)
            clean_serial = str(serial_val).strip() if serial_val is not None else None

            matched_lead = None
            if clean_phone and clean_phone in lead_by_phone:
                matched_lead = lead_by_phone[clean_phone]
            elif clean_serial and clean_serial in lead_by_serial:
                matched_lead = lead_by_serial[clean_serial]

            if matched_lead:
                records_matched += 1
                lead_id = matched_lead.id
                df.at[idx, "Status"] = matched_lead.status
                df.at[idx, "Follow-up Date"] = next_follow_up.get(lead_id, "")
                df.at[idx, "Follow-up Limit"] = str(default_limit)
                df.at[idx, "Follow-ups Sent"] = str(sent_counts.get(lead_id, 0))
                df.at[idx, "Follow-up Paused"] = "Yes" if matched_lead.follow_up_paused else "No"
                df.at[idx, "Last Message Date"] = latest_sent.get(lead_id, "")
                df.at[idx, "Last Reply Date"] = latest_reply.get(lead_id, "")
                records_updated += 1

        temp_dir = file_path.parent
        with tempfile.NamedTemporaryFile(dir=temp_dir, delete=False, suffix=".csv") as tmp_file:
            tmp_path = tmp_file.name

        try:
            df.to_csv(tmp_path, index=False, encoding="utf-8")
            os.replace(tmp_path, file_path)
        except Exception:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            raise

        return records_matched, records_updated

    @classmethod
    def list_backups(cls) -> List[Dict[str, Any]]:
        """Retrieve list of timestamped backup files."""
        settings = get_settings()
        backup_dir = Path(settings.BACKUP_DIR).resolve()
        if not backup_dir.exists():
            return []
        files = []
        for p in sorted(backup_dir.glob("*.xlsx"), key=lambda f: f.stat().st_mtime, reverse=True):
            stat = p.stat()
            files.append({
                "filename": p.name,
                "file_path": str(p),
                "size_bytes": stat.st_size,
                "created_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
            })
        return files
