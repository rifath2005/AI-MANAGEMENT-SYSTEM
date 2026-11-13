# Approval Management System using AI (Open-Source / Free-Tier Edition)

Implemented end-to-end from `REQUIREMENT OG FILE/AI approval mgmt.docx` using **free, local, open-source components** plus optional BYOK LLM chat and Supabase Storage.

## User Interface Gateways

The login UI has been streamlined into a single unified staff gateway, while keeping administrators isolated on a dedicated security gateway:

- **Unified Staff Sign In & Requester Sign Up:** `http://localhost:5050/login` (or `http://localhost:5050/`)
  - All standard roles (`requester`, `manager`, `approver`, `hr`) log in here directly. Authenticated sessions automatically display their role dashboard and permissions.
  - Legacy role URLs (`/login/requester`, `/login/manager`, `/login/approver`, `/login/hr`) cleanly 302-redirect to `/login`.
- **Isolated Administrator Security Gateway:** `http://localhost:5050/login/admin`
  - Restricted to system administrators (`sysadmin`). Standard login gateways strictly reject admin accounts to prevent credential probing.

## Sample Seeded Accounts (Overridable via Environment Variables)

- `nadia.patel` / `ReqPass#2026` (`requester`) — override with `AMS_SEED_REQ_PASS`
- `rohan.mehta` / `MgrPass#2026` (`manager`) — override with `AMS_SEED_MGR_PASS`
- `claire.chen` / `AprPass#2026` (`approver`) — override with `AMS_SEED_APR_PASS`
- `david.okafor` / `HrPass#2026` (`hr`) — override with `AMS_SEED_HR_PASS`
- `sysadmin` / `AdminGate#2026` (`admin`, `/login/admin` only) — override with `AMS_SEED_ADMIN_PASS`

## Complete System URL Directory

### 1. Web Page & Application URLs
- `http://localhost:5050/` or `http://localhost:5050/login`: Unified Sign In & Main Application Workspace
- `http://localhost:5050/login/admin`: Dedicated Administrator Security Gateway

### 2. Authentication & User Management Endpoints
- `POST http://localhost:5050/api/auth/login`: Standard staff sign-in (rate-limited, blocks admin accounts)
- `POST http://localhost:5050/api/auth/admin/login`: Administrator sign-in (rate-limited, admin role only)
- `POST http://localhost:5050/api/auth/register`: Requester self sign-up
- `GET http://localhost:5050/api/auth/me`: Current user session and role capabilities
- `GET http://localhost:5050/api/users`: List users (Admin & HR)
- `POST http://localhost:5050/api/users`: Create user profile (Admin & HR)
- `PATCH http://localhost:5050/api/users/<id>`: Update user role / status (Admin only)

### 3. Requests, Approvals & Workflows Endpoints
- `GET http://localhost:5050/api/requests`: List requests (filtered by scope & status)
- `POST http://localhost:5050/api/requests`: Submit request with ML risk analysis and auto-routing
- `GET http://localhost:5050/api/requests/<id>`: Request details, approval timeline & attachments
- `POST http://localhost:5050/api/requests/<id>/approve`: Submit approval or rejection decision
- `POST http://localhost:5050/api/requests/<id>/attachments`: Upload attachment (Local disk or Supabase)
- `GET http://localhost:5050/api/requests/<id>/attachments/<att_id>/download`: Download file attachment
- `GET http://localhost:5050/api/workflows`: List active approval workflows
- `POST http://localhost:5050/api/workflows`: Create workflow definition with SLA hours (Admin only)
- `GET http://localhost:5050/api/policies`: List auto-approval thresholds & compliance policies
- `PATCH http://localhost:5050/api/policies/<id>`: Update policy thresholds (Admin only)

### 4. AI Engine, Chat & Predictive Analytics Endpoints
- `POST http://localhost:5050/api/chat`: Conversational AI assistant & voice command processing
- `GET http://localhost:5050/api/chat/config`: View active LLM provider configuration
- `POST http://localhost:5050/api/chat/config`: Save API key / custom fine-tune endpoint (Admin only)
- `GET http://localhost:5050/api/chat/finetune-dataset`: Export JSONL fine-tuning dataset
- `POST http://localhost:5050/api/nlp/preview`: Real-time NLP entity extraction preview
- `GET http://localhost:5050/api/analytics/dashboard`: System KPIs & approval velocity
- `GET http://localhost:5050/api/analytics/role-dashboard`: Role-specific workspace metrics
- `GET http://localhost:5050/api/analytics/predictions`: Bottleneck prediction & volume forecasting
- `GET http://localhost:5050/api/analytics/optimizations`: AI-suggested dynamic workflow rules
- `GET http://localhost:5050/api/analytics/export.csv`: Export analytics report as CSV
- `POST http://localhost:5050/api/ai/retrain`: Trigger cached AI model retraining (Admin only)

### 5. Storage, Audit Trail & Health Endpoints
- `GET http://localhost:5050/api/storage/config`: Supabase storage status
- `POST http://localhost:5050/api/storage/config`: Configure Supabase URL, key, and bucket (Admin only)
- `GET http://localhost:5050/api/audit`: Tamper-evident SHA-256 audit log trail (Admin only)
- `GET http://localhost:5050/api/audit/verify`: Verify audit log cryptographic hash chain (Admin only)
- `GET http://localhost:5050/api/notifications`: Notifications & deadline alerts
- `POST http://localhost:5050/api/notifications/<id>/read`: Mark notification as read
- `POST http://localhost:5050/api/notifications/sweep-reminders`: SLA deadline scanner
- `GET http://localhost:5050/api/health`: System health check

## Quick Start

```bash
.venv/bin/python run.py
```

## Running Tests

```bash
.venv/bin/pytest -v
```
