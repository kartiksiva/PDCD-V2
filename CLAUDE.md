# CLAUDE.md — AI Assistant Guide for PDCD-V2

This file provides context, conventions, and workflows for AI assistants working on this repository.

---

## Project Overview

**PFCD Video-First v1** is an Azure-native process documentation system. It ingests video/audio/transcript evidence, runs agentic extraction and review pipelines, and produces structured process documentation (PDD + SIPOC) in multiple export formats.

The system is currently in a **skeleton phase**: the API contract, state machine, SQL schema, and Azure orchestration are implemented; real agent logic (transcription, evidence extraction, review quality gates) is stubbed/simulated.

Reference documents:
- `prd.md` — authoritative product requirements and evidence hierarchy rules
- `AGENTS.md` — repository coding and PR guidelines
- `GEMINI.md` — architecture overview and planning context
- `REVIEW_CLOSURE_2026-03-21.md` — skeleton approval status and conditions

---

## Repository Layout

```
PDCD-V2/
├── backend/               # FastAPI application (Python)
│   ├── app/               # Core application modules
│   │   ├── main.py        # FastAPI app, HTTP endpoints, app lifecycle
│   │   ├── models.py      # SQLAlchemy ORM table definitions
│   │   ├── job_logic.py   # Job state machine, enums, payload helpers
│   │   ├── repository.py  # Persistence layer (JobRepository)
│   │   ├── db.py          # DB engine setup, session_scope context manager
│   │   ├── servicebus.py  # Azure Service Bus orchestration
│   │   ├── storage.py     # Blob/local export storage abstraction
│   │   └── workers/
│   │       └── runner.py  # Service Bus worker (phase handler)
│   ├── alembic/           # DB migrations
│   │   └── versions/      # Migration scripts (20260401_0001_init.py)
│   ├── requirements.txt   # Python dependencies (pinned)
│   └── alembic.ini        # Alembic config
├── frontend/              # Placeholder (not yet implemented)
├── infra/
│   ├── dev-bootstrap.sh   # Idempotent Azure resource provisioning script
│   └── README.md          # Infra setup and verification guide
├── tests/
│   └── unit/
│       └── test_repository.py  # pytest unit tests
├── .github/
│   └── workflows/
│       └── deploy-backend.yml  # GitHub Actions CI/CD (zip deploy to App Service)
├── prd.md
├── AGENTS.md
├── GEMINI.md
└── IMPLEMENTATION_SUMMARY.md
```

---

## Tech Stack

| Layer | Technology | Version |
|-------|------------|---------|
| Language | Python | 3.11 |
| Web framework | FastAPI | 0.116.0 |
| ASGI server | Uvicorn | 0.34.0 |
| Data validation | Pydantic | 2.10.0 |
| ORM | SQLAlchemy | 2.0.38 |
| DB migrations | Alembic | 1.13.3 |
| DB (local) | SQLite | built-in |
| DB (prod) | Azure SQL Server | via pyodbc 5.2.0 |
| Async support | anyio | 4.9.0 |
| Message queue | Azure Service Bus | 7.12.1 |
| Blob storage | Azure Blob Storage | 12.25.0 |
| Azure auth | azure-identity | 1.19.0 |
| PDF export | fpdf2 | 2.8.1 |
| Testing | pytest | 8.3.1 |

---

## Development Setup

```bash
# Install dependencies
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Run DB migrations
alembic upgrade head

# Start API server (local dev)
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

### Required Environment Variables

| Variable | Purpose | Default |
|----------|---------|---------|
| `DATABASE_URL` | SQLAlchemy connection string | `sqlite:///./pfcd.db` |
| `AZURE_STORAGE_CONNECTION_STRING` | Blob storage | local fallback if unset |
| `AZURE_SERVICE_BUS_CONNECTION_STRING` | Service Bus namespace | `""` (skips queue dispatch) |
| `AZURE_SERVICE_BUS_QUEUE_EXTRACTING` | Queue name | `extracting` |
| `AZURE_SERVICE_BUS_QUEUE_PROCESSING` | Queue name | `processing` |
| `AZURE_SERVICE_BUS_QUEUE_REVIEWING` | Queue name | `reviewing` |
| `PFCD_WORKER_ROLE` | Worker phase (`extracting`/`processing`/`reviewing`) | — |

### Starting Workers (Service Bus Phases)

```bash
PFCD_WORKER_ROLE=extracting python -m app.workers.runner
PFCD_WORKER_ROLE=processing python -m app.workers.runner
PFCD_WORKER_ROLE=reviewing python -m app.workers.runner
```

---

## Running Tests

```bash
cd backend
pytest tests/unit/test_repository.py
```

Tests use `tmp_path` fixture with an isolated SQLite database; no Azure credentials required. They monkeypatch `DATABASE_URL` and reload modules to pick up the change.

**Test naming convention:** `tests/<layer>/<feature>_test.<ext>` with behavior-focused names (e.g., `test_video_without_audio_forces_review`).

---

## API Endpoints

Base path: `/api`

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/jobs` | Create a new job (accepts `JobCreateRequest`) |
| GET | `/api/jobs/{job_id}` | Get job state and payload |
| PUT | `/api/jobs/{job_id}/draft` | Update draft (reconcile review notes) |
| POST | `/api/jobs/{job_id}/finalize` | Finalize draft (move to FINALIZING) |
| GET | `/api/jobs/{job_id}/exports/{format}` | Export draft (`json`, `markdown`, `pdf`, `docx`) |
| DELETE | `/api/jobs/{job_id}` | Soft-delete / mark job expired |
| GET | `/health` | Health check (`{"status": "ok"}`) |

---

## Job State Machine

```
QUEUED → PROCESSING → NEEDS_REVIEW → FINALIZING → COMPLETED
                                                 ↘ FAILED
```

- `JobStatus` enum defined in `backend/app/job_logic.py`
- Transitions driven by Service Bus worker phases (extracting → processing → reviewing)
- `phase_attempt` tracks retry count per phase
- `error` field (JSON TEXT) stores exception details on failure

---

## Data Model (Database Tables)

| Table | Key Columns | Notes |
|-------|-------------|-------|
| `jobs` | `job_id` (PK), `status`, `current_phase`, `phase_attempt`, `ttl_expires_at`, `error` | Core state |
| `input_manifests` | `job_id` (PK), `payload` (JSON TEXT) | Input file metadata |
| `review_notes` | `job_id` (PK), `payload` (JSON TEXT) | Review flags (BLOCKER/WARNING/INFO) |
| `drafts` | `job_id` + `draft_kind` (PK), `payload` (JSON TEXT), `version` | PDD and SIPOC drafts |
| `agent_runs` | `agent_run_id` (PK), `job_id`, `agent`, `model`, `status`, `duration_ms`, `cost_estimate_usd` | Execution history |
| `exports` | `job_id` (PK), `payload` (JSON TEXT) | Export metadata |
| `job_events` | `event_id` (PK), `job_id`, `event_type`, `created_at` | Audit log |

All JSON columns use deterministic serialization: `json.dumps(..., ensure_ascii=True, separators=(',', ':'))`.

---

## Code Conventions

### Python Style

- **Indent:** 4 spaces
- **Classes:** `PascalCase` (e.g., `JobRepository`, `ExportStorage`)
- **Functions/methods/variables:** `snake_case`
- **Constants:** `UPPER_SNAKE_CASE` (e.g., `MAX_UPLOAD_BYTES`)
- **Private helpers:** `_leading_underscore` (e.g., `_utc_now`, `_serialize`)
- **Enums:** `PascalCase` class, `UPPER_CASE` members (e.g., `JobStatus.QUEUED`, `ReviewSeverity.BLOCKER`)

### Async Pattern

All blocking DB operations are wrapped:
```python
result = await anyio.to_thread.run_sync(JOB_REPO.get_job, job_id)
```

FastAPI endpoints use `async def` throughout.

### Factory Pattern

Services use `from_env()` classmethods for construction:
```python
JOB_REPO = JobRepository.from_env()
EXPORT_STORAGE = ExportStorage.from_env()
ORCHESTRATOR = ServiceBusOrchestrator()
```

This keeps environment variable reading isolated and makes testing via monkeypatch easy.

### Repository Pattern

All persistence goes through `JobRepository` in `repository.py`. Do not access `SessionLocal` or ORM models directly from endpoints — call repository methods.

### Context Managers

- `session_scope()` in `db.py` wraps DB sessions with commit/rollback
- `_lifespan()` in `main.py` handles app startup (calls `JOB_REPO.init_db()`)

### Error Handling

- Use `HTTPException` with appropriate status codes (400, 409, 410, 413, 503)
- Store exception details in the `error` JSON field on the job record
- Do not add error handling for scenarios that cannot happen; trust internal guarantees

### Timestamps

Always use `datetime.now(timezone.utc).isoformat()` for UTC timestamps stored as ISO 8601 strings.

### IDs

Use `str(uuid4())` for all new identifiers.

---

## Evidence Hierarchy (from PRD)

When working on extraction or review logic, respect this priority order:

1. **Video** (highest evidence value)
2. **Audio/transcript** derived from video
3. **Standalone transcript**
4. **Document/slide** (lowest)

If video and transcript conflict, video evidence takes precedence. This rule must be implemented in the evidence scoring and review phase.

---

## Cost Profiles

| Profile | Model | Cost Cap |
|---------|-------|----------|
| `balanced` | GPT-4o-mini | $4 |
| `quality` | GPT-4o | $8 |

Track per-run estimates in the `agent_runs.cost_estimate_usd` column. Respect profile caps when scheduling agent calls.

---

## Azure Infrastructure

All Azure resources are in resource group `app-pfcd-v2`.

| Resource | Name Pattern |
|----------|--------------|
| Storage Account | `pfcd[env]storage` (containers: uploads, evidence, exports, scratch) |
| Service Bus | `pfcd-[env]-bus` (queues: extracting, processing, reviewing) |
| SQL Server | `pfcd-[env]-sql` |
| SQL Database | `pfcd-[env]-jobs` |
| Key Vault | `pfcd-[env]-kv` |
| App Service Plan | `pfcd-[env]-asp` (Linux) |
| Web App | `pfcd-[env]-api` (Python 3.11) |
| Azure OpenAI | `pfcd-[env]-oai` (model: gpt-4o-mini) |
| Azure Speech | `pfcd-[env]-speech` |

**Provision dev environment:**
```bash
az login
SPEECH_ACCOUNT_LOCATION=eastus bash infra/dev-bootstrap.sh
```

The script is idempotent — safe to re-run.

**Authentication:** All Azure SDK clients use `DefaultAzureCredential` (supports Managed Identity, CLI login, and environment variables). Secrets are stored in Key Vault and injected at runtime.

---

## CI/CD

**File:** `.github/workflows/deploy-backend.yml`

- Triggers on push to `main` with changes under `backend/**`
- Deploys via `az webapp deploy` (zip upload)
- Required secrets: `AZURE_CREDENTIALS`, `AZURE_RESOURCE_GROUP`, `AZURE_WEBAPP_NAME`
- No automated tests run in CI yet — add pytest step when integration tests exist

---

## Commit Style

Follow conventional commits:

```
feat: add transcript alignment engine
fix: correct phase retry counter reset
docs: update API endpoint table in README
refactor: extract evidence scoring to separate module
chore: bump SQLAlchemy to 2.0.38
```

---

## PR Guidelines

- Brief summary of user-facing change
- Link to relevant PRD section or decision
- List validation steps actually run
- Note any Azure resource or config impact
- Include log snippets for workflow changes

---

## Security Rules

- **Never** hardcode secrets, connection strings, or credentials
- All secrets go in environment variables or Azure Key Vault
- Redact transcript/video identifiers in logs by default
- Use `DefaultAzureCredential` — do not use storage shared keys or SAS tokens in application code
- Validate file size at the API boundary (`MAX_UPLOAD_BYTES = 500 * 1024 * 1024`)

---

## Current Implementation Status (as of 2026-04-02)

**Done:**
- FastAPI endpoints and job lifecycle API
- SQL schema and Alembic migration
- Job state machine (QUEUED → COMPLETED/FAILED)
- Service Bus message queuing and worker framework
- Blob/local export storage abstraction
- PDF and Markdown export (basic)
- Azure infrastructure bootstrap script
- Unit tests (job roundtrip, event logging)

**Not yet implemented (next phase):**
- Real agent logic (extraction, processing, review quality gates)
- Transcript/video alignment engine
- Evidence strength computation
- Adapter pattern for source types
- SIPOC schema validation
- Evidence-linked PDF/DOCX rendering
- TTL/cleanup worker
- Authentication/authorization layer
- Integration and E2E tests
- CI test step in GitHub Actions workflow

---

## Key Files Quick Reference

| File | What it does |
|------|-------------|
| `backend/app/main.py` | All HTTP endpoints, app startup |
| `backend/app/job_logic.py` | `JobStatus`, `Profile`, `ReviewSeverity` enums; `default_job_payload()` |
| `backend/app/repository.py` | `JobRepository` — all DB reads/writes |
| `backend/app/db.py` | `session_scope`, DB engine, `DATABASE_URL` config |
| `backend/app/servicebus.py` | `ServiceBusOrchestrator`, `build_message()` |
| `backend/app/storage.py` | `ExportStorage`, save/load blob or local file |
| `backend/app/workers/runner.py` | Service Bus worker loop, phase dispatch |
| `backend/app/models.py` | SQLAlchemy ORM table classes |
| `backend/alembic/versions/20260401_0001_init.py` | Single DB migration creating all tables |
| `tests/unit/test_repository.py` | pytest unit tests |
| `infra/dev-bootstrap.sh` | Idempotent Azure provisioning |
| `prd.md` | Authoritative product requirements |
