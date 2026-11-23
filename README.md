# Travel Agency WhatsApp Follow-up Automation

Production-minded WhatsApp follow-up automation application backend built with Python 3.12, FastAPI, SQLAlchemy 2.0, Alembic, Pandas, and OpenPyXL.

## Overview

- **Phase 1:** Project foundation, FastAPI setup, Pydantic settings, centralized logging, and `/health` endpoint.
- **Phase 2:** Database architecture, declarative SQLAlchemy 2.0 models, SQLite foreign-key enforcement, Alembic migrations, and automated database test suite.
- **Phase 3:** Excel/CSV lead import pipeline (preview + confirmed import), phone number normalization, duplicate detection, safe workbook synchronization with timestamped backups, atomic file updates, and concurrency protection.
- **Phase 4:** Comprehensive Lead Management (CRUD, pagination, search, status filtering, explicit pause/resume follow-ups, business-rule status transitions, safe soft-deletion preserving historical communications and schedules).
- **Phase 5:** Follow-up Scheduler engine using APScheduler, FastAPI lifespan, and SQLAlchemy 2.0. Offline recovery guarantees that missed follow-ups are marked `Skipped` and never burst-sent late on laptop startup; business rules enforce individual follow-up limits, pause independence, and message sender isolation.
- **Phase 6:** Meta WhatsApp Cloud API Integration, asynchronous HTTP client (`httpx.AsyncClient`), template management with dynamic parameter validation, strict opt-in consent compliance, delivery-status distinction (API acceptance vs. delivered), and scheduler integration.
- **Phase 7:** Meta WhatsApp Webhook Integration (`GET /api/whatsapp/webhook` challenge verification and `POST /api/whatsapp/webhook` HMAC-SHA256 event receiver).
- **Phase 8:** Marketing broadcast campaigns, configurable batch partitioning (1–50 recipients), mandatory individual batch approvals, in-flight consent revalidation, and delivery reporting.
- **Phase 9.2:** Authentication & Frontend Routing (PBKDF2-HMAC-SHA256 password hashing with 600,000 iterations, SHA-256 hashed session persistence, HttpOnly session cookies, double-submit CSRF protection, sliding-window login rate limiting, one-time administrator bootstrap CLI/API, dashboard route protection, and Vanilla JS SaaS login portal).
- **Phase 9.3:** CRM Dashboard Shell & Database Overview (Responsive SaaS app shell with collapsible sidebar, authenticated user header, 14 database-backed SQL-aggregated metrics, chronological activity stream, and live system health monitoring).

---

## Project Structure

```text
travel_agency_automation/
│
├── alembic/
│   ├── versions/
│   │   ├── 5fe71a1447a3_initial_schema.py     # Initial migration
│   │   ├── 09362fb7b6f1_add_lead_soft_delete.py # Phase 4 soft delete migration
│   │   ├── 34044a3a7a62_add_phase5_scheduler_fields.py # Phase 5 scheduler migration
│   │   └── d32b850f2386_add_phase6_whatsapp_fields.py # Phase 6 WhatsApp & consent migration
│   ├── env.py                                 # Alembic runtime config
│   └── script.py.mako                         # Migration template
│
├── app/
│   ├── __init__.py                            # Package marker and version
│   ├── main.py                                # FastAPI application factory, lifespan, and scheduler runner
│   ├── core/
│   │   ├── __init__.py                        # Core utilities export
│   │   ├── config.py                          # Pydantic Settings
│   │   └── logging.py                         # Centralized logging configuration
│   ├── db/
│   │   ├── __init__.py                        # Database package exports
│   │   ├── base.py                            # DeclarativeBase definition
│   │   ├── session.py                         # Engine, sessionmaker, SQLite pragma & get_db
│   │   └── models/
│   │       ├── __init__.py                    # Model registry
│   │       ├── lead.py                        # Lead model (with soft deletion)
│   │       ├── follow_up.py                   # FollowUpSchedule model
│   │       ├── campaign.py                    # Campaign, CampaignBatch, CampaignRecipient
│   │       ├── message.py                     # MessageLog and IncomingMessage
│   │       ├── template.py                    # WhatsApp template model
│   │       └── sync_log.py                    # Excel/CSV sync audit log model
│   ├── integrations/
│   │   ├── __init__.py                        # Integrations package marker
│   │   └── whatsapp/
│   │       ├── __init__.py                    # WhatsApp integration exports
│   │       ├── client.py                      # Meta WhatsApp Cloud API async client
│   │       └── exceptions.py                  # Domain error hierarchy
│   ├── schemas/
│   │   ├── __init__.py                        # Schema exports
│   │   ├── followup_schemas.py                # Follow-up scheduling request/response schemas
│   │   ├── import_schemas.py                  # Schemas for preview, eligible records, confirmation
│   │   ├── lead_schemas.py                    # Schemas for lead CRUD, consent, and filtering
│   │   ├── sync_schemas.py                    # Schemas for workbook sync request & response
│   │   └── template_schemas.py                # WhatsApp template CRUD and validation schemas
│   ├── services/
│   │   ├── __init__.py                        # Services exports
│   │   ├── excel_service.py                   # Excel/CSV parsing, validation, and safe sync
│   │   ├── followup_service.py                # Follow-up scheduling, eligibility & offline recovery
│   │   ├── lead_service.py                    # Lead business logic and domain operations
│   │   ├── scheduler_manager.py               # APScheduler background runner & lifecycle manager
│   │   ├── sender_boundary.py                 # Message sender protocol and boundary isolation
│   │   ├── template_service.py                # Template registration, approval & parameter validation
│   │   └── whatsapp_service.py                # Outbound template sending, compliance & message audit
│   ├── api/
│   │   ├── __init__.py                        # API layer exports
│   │   └── routes/
│   │       ├── __init__.py                    # Route aggregation
│   │       ├── excel_routes.py                # POST /api/excel/sync
│   │       ├── followups.py                   # Follow-up scheduler routes
│   │       ├── health.py                      # GET /health endpoint
│   │       ├── import_routes.py               # POST /api/import/preview & POST /api/import/confirm
│   │       ├── leads.py                       # Lead management CRUD, consent, pause/resume
│   │       ├── templates.py                   # WhatsApp template registry routes
│   │       └── whatsapp.py                    # Direct WhatsApp template message dispatch
│
├── tests/
│   ├── __init__.py                            # Test package marker
│   ├── conftest.py                            # Pytest fixtures and isolated temporary DB
│   ├── test_database.py                       # Model validation, constraints, and relationships
│   ├── test_excel.py                          # Excel import preview, validation, confirmation & sync
│   ├── test_followups.py                      # Phase 5 Follow-up scheduler test suite (18 tests)
│   ├── test_health.py                         # Health endpoint and app initialization tests
│   ├── test_leads.py                          # Phase 4 Lead management tests (18 tests)
│   └── test_whatsapp.py                       # Phase 6 Meta WhatsApp integration tests (21 tests)
│
├── alembic.ini                                # Alembic migration configuration
├── .env.example                               # Environment template
├── .env                                       # Local configuration (never committed)
├── .gitignore                                 # Git exclusion rules
├── requirements.txt                           # Production-ready dependencies
└── README.md                                  # Documentation and execution guide
```

---

## Setup Instructions (Windows 11)

### 1. Open Terminal in Project Directory

```powershell
cd "C:\VS_CODE\travel_agency_automation"
```

### 2. Activate Virtual Environment

```powershell
.\.venv\Scripts\Activate.ps1
```

### 3. Install Dependencies

```powershell
python -m pip install -r requirements.txt
```

### 4. Run Database Migrations

```powershell
alembic upgrade head
```

---

## API Endpoints

### 1. System Health
- `GET /health`: Operational status check.

### 2. Lead Management
- `GET /api/leads`: List leads with pagination (`page`, `page_size`), search (`search` on name/phone/serial), status filtering (`status`), pause filtering (`follow_up_paused`), and sorting (`sort_by`, `sort_order`).
- `GET /api/leads/{lead_id}`: Retrieve full details for a single lead. Returns 404 if not found.
- `POST /api/leads`: Create a new lead. Rejects duplicate phone numbers with HTTP 409 Conflict.
- `PATCH /api/leads/{lead_id}`: Update lead details. Allowed statuses: `Pending`, `Replied`, `Not Interested`. Setting status to `Not Interested` cancels future scheduled follow-ups. Setting status to `Replied` does **not** pause follow-ups.
- `POST /api/leads/{lead_id}/pause-followups`: Explicitly pause follow-ups (`follow_up_paused = True`).
- `POST /api/leads/{lead_id}/resume-followups`: Explicitly resume follow-ups (`follow_up_paused = False`).
- `POST /api/leads/{lead_id}/consent`: Document recipient's opt-in consent (`opt_in_status: "OPTED_IN"`) or opt-out suppression (`"OPTED_OUT"`).
- `DELETE /api/leads/{lead_id}`: Safely soft-deletes lead (`is_deleted = True`), cancels pending follow-ups, and preserves communication audit history without violating foreign keys.

### 3. Lead Import Pipeline
- `POST /api/import/preview`: Diagnostic workbook preview (total, valid, duplicate, existing, eligible rows). Zero database writes.
- `POST /api/import/confirm`: Transactional database commit of confirmed eligible leads.

### 4. Follow-up Scheduler
- `POST /api/followups`: Create an individual follow-up schedule (`lead_id`, `scheduled_at`, optional `sequence_number`). Rejects past dates, nonexistent leads, and requests exceeding the lead's configured `max_follow_up_limit`.
- `GET /api/followups`: List schedules with pagination (`page`, `page_size`), `lead_id` filtering, and `status` filtering (`Scheduled`, `Approved`, `Sent`, `Skipped`, `Failed`, `Cancelled`).
- `GET /api/followups/{id}`: Retrieve follow-up details.
- `PATCH /api/followups/{id}`: Reschedule a pending follow-up with a new `scheduled_at` timestamp.
- `POST /api/followups/{id}/cancel`: Cancel a pending follow-up. Already sent/skipped items cannot be cancelled.

### 5. Safe Workbook Synchronization
- `POST /api/excel/sync`: Syncs SQLite state into authorized workbook (`data/leads.xlsx`), adds 7 automation columns, creates timestamped backups in `data/backups/`, and protects against concurrent writes.

### 6. WhatsApp Template Management
- `GET /api/templates`: List configured templates with optional `approval_status` and `category` filters.
- `POST /api/templates`: Register or update template metadata (`template_name`, `language`, `category`, `approval_status`, `expected_parameters`, `body_text`, `header_type`).
- `GET /api/templates/{template_id}`: Retrieve full template details and required parameter definitions.
- `PATCH /api/templates/{template_id}`: Update template category, approval status, or parameter requirements.

### 7. WhatsApp Cloud API Messaging
- `POST /api/whatsapp/send-template`: Direct transmission endpoint to dispatch an approved template message to a customer. Enforces lead existence, opt-in consent (`opt_in_status == 'OPTED_IN'`), template approval status (`approval_status == 'APPROVED'`), parameter completeness, and records API acceptance (`delivery_status = 'Accepted'`) in `message_logs`.

---

## Scheduler Engine & Offline Recovery

- **APScheduler Background Runner:** Configured in `app/services/scheduler_manager.py` using `BackgroundScheduler`, running a recurring poll worker every `SCHEDULER_POLL_INTERVAL_SECONDS` (default: 60s) in the `Asia/Kolkata` timezone.
- **FastAPI Lifespan Lifecycle:** Controlled via `app/main.py`. On startup, before the scheduler starts, startup reconciliation is executed. On shutdown, APScheduler stops cleanly without orphaned threads.
- **Offline Recovery Invariant:** When the primary laptop is powered off, any scheduled follow-ups that become overdue while offline are automatically reconciled upon next application startup. Overdue records are marked `Skipped` with reason `missed_while_application_offline` and never burst-sent late.
- **Business Rule Invariants:**
  - `lead.status == "Replied"` remains eligible for scheduled follow-ups.
  - `lead.status == "Not Interested"` immediately marks lead ineligible and cancels future schedules.
  - `lead.follow_up_paused` is an independent boolean controlling follow-up pauses.
  - `lead.max_follow_up_limit` counts strictly sent messages (`status == "Sent"`), never failed or skipped attempts.
- **Message Sender Boundary:** Follow-up sending logic is decoupled via `MessageSenderBoundary` interface (`app/services/sender_boundary.py`). Phase 6 implements `WhatsAppMessageSender` which dispatches approved templates to consented leads via `WhatsAppCloudClient`.

---

## WhatsApp Cloud API Integration & Compliance (Phase 6)

- **Official Graph API Architecture:** Uses Meta's official Cloud API endpoint (`POST /{API_VERSION}/{PHONE_NUMBER_ID}/messages`) using an asynchronous `httpx.AsyncClient` managed within FastAPI lifespan.
- **Opt-in Consent & Suppression:** In accordance with Meta WhatsApp messaging policies, marketing and follow-up templates are only dispatched to leads with verified consent (`opt_in_status == "OPTED_IN"`). Leads with status `"NOT_OPTED_IN"` or `"OPTED_OUT"` are strictly suppressed from message dispatch.
- **Template Safety & Dynamic Parameters:** Outbound sends require local templates with `approval_status == "APPROVED"`. Expected body and header parameters are validated before payload generation.
- **API Acceptance Distinction:** Messages accepted by Meta Cloud API are logged with `delivery_status = "Accepted"` and `api_status = "ACCEPTED"`. They are deliberately NOT marked as `Delivered` upon API acceptance; delivery confirmations are reserved for Phase 7 webhook processing.
- **Security & Secret Protection:** Credentials (`WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`) are stored in `.env`, never exposed in API responses or logs, and sanitized across all error-handling boundaries.

---

## Meta WhatsApp Webhook Integration (Phase 7)

- **Verification Endpoint (`GET /api/whatsapp/webhook`):** Responds to Meta subscription verification challenges validating `hub.mode == "subscribe"` and `hub.verify_token == WHATSAPP_WEBHOOK_VERIFY_TOKEN`, returning `hub.challenge` as plain text with HTTP 200.
- **Secure Event Receiver (`POST /api/whatsapp/webhook`):** Validates raw body payload HMAC-SHA256 against `X-Hub-Signature-256` using `META_APP_SECRET` with constant-time comparison (`hmac.compare_digest`). Rejects unsigned or forged requests with HTTP 401.
- **Real-Time Delivery Status Tracking:**
  - `Sent`: Records server dispatch without overwriting historical `sent_at` timestamps.
  - `Delivered`: Updates `delivery_status = "Delivered"` and sets `delivered_at`.
  - `Read`: Advances to `delivery_status = "Read"` and sets `read_at`.
  - `Failed`: Sets `failed_at` and records error code/reason.
  - **Terminal State Preservation:** `Failed` events never overwrite `Delivered` or `Read` terminal states. Lower-ranking delayed events (e.g., late `Sent`) never regress higher delivery states (`Delivered` or `Read`).
- **Inbound Customer Messages:**
  - Safely parses incoming text and non-text messages (`image`, `video`, `audio`, `document`, `button`, `interactive`) without schema errors or assuming `message_text` is present.
  - Automatically associates incoming messages with matching leads via sender phone number. Records unknown senders with `lead_id = None`.
  - Idempotency guard prevents duplicate message and status entries during network retransmissions.
  - Does NOT automatically reply or trigger follow-ups in this phase.
- **Customer Privacy & Sanitization:**
  - Phone numbers are masked in logs (e.g. `+91****10`).
  - Sensitive tokens or secrets in raw webhook payloads are redacted before database storage.
  - Customer message contents are excluded from standard logging.

### Local Webhook Testing with ngrok

To receive live webhooks from Meta while developing locally:

1. Start the FastAPI server:
   ```powershell
   .\.venv\Scripts\uvicorn.exe app.main:app --host 127.0.0.1 --port 8000 --reload
   ```
2. Start an ngrok tunnel on port 8000:
   ```powershell
   ngrok http 8000
   ```
3. In the Meta Developer Dashboard (WhatsApp > Configuration > Webhook):
   - **Callback URL:** `https://<your-ngrok-domain>.ngrok-free.app/api/whatsapp/webhook`
   - **Verify Token:** The value of `WHATSAPP_WEBHOOK_VERIFY_TOKEN` configured in `.env`.
   - **Webhook Fields:** Subscribe to `messages`.

---

## Campaign Management & Batch Approval (Phase 8)

- **Consent-First Lead Selection:** Broadcast campaigns only accept leads with verified opt-in consent (`opt_in_status == "OPTED_IN"`), valid international phone numbers, unpaused follow-up status, and non-deleted records. Ineligible leads are automatically excluded and categorized with descriptive reasons.
- **Configurable Batch Partitioning:** Eligible recipients are split into sequential batches (1 to 50 recipients, default 50). Duplicate recipients within the same campaign are strictly prohibited.
- **Mandatory Individual Batch Approval:**
  - Newly generated batches default to `PENDING_APPROVAL`.
  - Every batch requires explicit individual approval via `POST /api/campaigns/{id}/batches/{batch_id}/approve`.
  - Approving one batch never approves another.
  - Repeated approval requests are idempotent and duplicate actions are prevented.
  - Approval does **not** automatically trigger dispatch; sending requires explicit user initiation.
- **Safe Batch Sending:**
  - Triggered exclusively via `POST /api/campaigns/{id}/batches/{batch_id}/send`.
  - Revalidates customer consent and lead eligibility immediately before dispatching each message (e.g. catches in-flight opt-outs between approval and send).
  - Outbound messages are linked across `campaign_id`, `batch_id`, and `message_log_id`.
  - Duplicate sends are rejected if a batch is already completed or in progress.
  - Partial failures are handled safely: successful messages proceed while failed messages log error details without crashing the batch.
  - API acceptance logs messages as `Accepted` (not `Delivered`); true delivery status is tracked via Phase 7 webhook events.
- **Reporting & Manual Review:**
  - `GET /api/campaigns/{id}/report`: Full summary of selected leads, eligible leads, excluded leads, batch counts, approval states, and webhook delivery status counters (`Accepted`, `Sent`, `Delivered`, `Read`, `Failed`).
  - `GET /api/campaigns/{id}/failed-recipients`: Allows reviewing failed recipients with full error diagnostics without automatic retries.

---

## Authentication & Frontend Routing (Phase 9.2)

### 1. Overview & Security Architecture
- **PBKDF2-HMAC-SHA256 Password Security:** Uses standard library cryptography (`hashlib.pbkdf2_hmac`) with **600,000 iterations**, a unique 16-byte (32-character hex) random salt per password, and constant-time verification (`hmac.compare_digest`). Passwords are never logged or stored in plaintext.
- **Hashed Session Persistence:** When a user logs in, a cryptographically secure raw token is generated (`secrets.token_urlsafe(32)`). The raw token is **never** persisted in the SQLite database; only its SHA-256 hash (`hashlib.sha256`) is stored. A dump of the database file or backups cannot yield active session tokens.
- **Cookie & Session Management:**
  - `travel_crm_session`: `HttpOnly=True`, `SameSite="Lax"`, `Path="/"`, `Max-Age=86400` (24 hours).
  - Configurable `SESSION_COOKIE_SECURE`: set to `False` for local HTTP LAN setups, or `True` in production behind an HTTPS/TLS reverse proxy.
  - Server-side revocation on logout immediately invalidates the database session record and clears client cookies.
- **Double-Submit CSRF Defense:**
  - Accompanied by a non-HttpOnly cookie `travel_crm_csrf`.
  - Frontend JavaScript reads `travel_crm_csrf` and attaches `X-CSRF-Token: <token>` to all mutating HTTP methods (`POST`, `PUT`, `PATCH`, `DELETE`).
  - Server validates constant-time match between cookie and header before executing any mutating dashboard operations.
- **Brute-Force Rate Limiting:**
  - Thread-safe sliding-window rate limiter blocks IP/username pairs after **5 consecutive failed attempts** within 5 minutes, returning `HTTP 429 Too Many Requests` with a `Retry-After` header.
- **Webhook Immunity:**
  - Meta WhatsApp Webhook endpoints (`GET` and `POST` at `/api/whatsapp/webhook`) are strictly exempt from session authentication and CSRF checks, maintaining Meta verify token and HMAC-SHA256 signature verification.

---

### 2. Initial Administrator Setup Instructions

To guarantee security, **no hardcoded default administrator credentials exist**. You must initialize the primary administrator account once before logging in.

#### Option A: CLI Bootstrap (Recommended)
On the host machine, run:
```powershell
.\.venv\Scripts\python.exe -m app.cli create-admin --username admin --password "YourStrongPassword2026!" --setup-secret travel_agency_setup_secret_key_2026_secure
```
*(You can also omit flags to be prompted securely for username and password with hidden terminal input).*

#### Option B: HTTP API Setup
If `SETUP_SECRET` is defined in `.env`:
```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/auth/setup" -Method POST -ContentType "application/json" -Body '{"username": "admin", "password": "YourStrongPassword2026!", "setup_secret": "travel_agency_setup_secret_key_2026_secure"}'
```
*Note: Once an administrator exists, all subsequent setup attempts are strictly blocked with `HTTP 403 Forbidden`.*

---

### 3. Required Environment Variables

Add the following to your `.env` file (see `.env.example`):
```ini
# Authentication & Session Security (Phase 9.2)
SESSION_COOKIE_NAME=travel_crm_session
SESSION_MAX_AGE_SECONDS=86400
SESSION_COOKIE_SECURE=false
SESSION_COOKIE_SAMESITE=lax
CSRF_COOKIE_NAME=travel_crm_csrf
SETUP_SECRET=travel_agency_setup_secret_key_2026_secure
```

---

### 4. Frontend Access & Routing
- **Login Portal:** Navigate to `http://localhost:8000/login` in your browser.
- **Dashboard Guard:** Unauthenticated access to `http://localhost:8000/` automatically redirects to `/login`.
- **Session Expiration:** If a session expires or is revoked, API requests automatically redirect the browser to `/login?expired=1`.
- **Sign Out:** Clicking "Sign Out" calls `POST /api/auth/logout`, invalidating the session server-side and returning to `/login`.

---

### 5. Authentication Troubleshooting
- **`401 Unauthorized` on CRM Endpoints:** The session cookie is missing, expired, or revoked. Log in again at `/login`.
- **`403 Forbidden - CSRF verification failed`:** A state-modifying request (`POST`, `PATCH`, `DELETE`) was issued with a session cookie but lacked the matching `X-CSRF-Token` header. Ensure `api.js` is included.
- **`429 Too Many Requests`:** More than 5 failed login attempts were detected from your IP or username. Wait 5 minutes for the sliding window to reset.
- **Local LAN Cookie Drop:** If accessing over LAN (e.g. `http://192.168.1.50:8000`), ensure `SESSION_COOKIE_SECURE=false` in `.env` so cookies can be set over plain HTTP.

---

## Running Automated Tests

Run the complete test suite (all 160 tests across Phases 1–9.3):

```powershell
.\.venv\Scripts\pytest.exe -v
```
