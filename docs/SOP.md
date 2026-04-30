# PFCD-V2 — Standard Operating Procedure

> **Audience:** Developers and ops/admin users onboarding to the PFCD-V2 project.  
> **Last updated:** 2026-04-30

---

## Table of Contents

1. [Overview](#1-overview)
2. [Prerequisites](#2-prerequisites)
3. [Setup — Option A: Docker Compose (Recommended)](#3-setup--option-a-docker-compose-recommended)
4. [Setup — Option B: Bare-metal Python](#4-setup--option-b-bare-metal-python)
5. [LLM Provider Configuration](#5-llm-provider-configuration)
6. [Running the Project](#6-running-the-project)
7. [Running Tests](#7-running-tests)
8. [Database Schema Reference](#8-database-schema-reference)
9. [Job Lifecycle / State Machine](#9-job-lifecycle--state-machine)
10. [Common Operations](#10-common-operations)

---

## 1. Overview

PFCD-V2 is an **Azure-native AI pipeline** that ingests video recordings, transcripts, and documents and produces structured process documentation: a **Process Definition Document (PDD)** and a **SIPOC map** (Suppliers, Inputs, Process, Outputs, Customers).

### Architecture

```
HTTP Client (Browser / Streamlit / API)
         │
         ▼
   FastAPI (backend/app/main.py)  ←→  PostgreSQL / SQLite
         │
         ▼
   Azure Service Bus
    ┌────┼────┐
    ▼    ▼    ▼
Extract  Process  Review
Worker   Worker   Worker
    │
    LLM (Azure OpenAI or direct OpenAI)
```

| Component | Description |
|---|---|
| **API** | FastAPI on port 8000. Handles job creation, file uploads (SAS or local), draft editing, finalize, export download, health checks. |
| **Worker: extracting** | Reads uploaded media/transcripts, calls LLM to extract evidence items. |
| **Worker: processing** | Converts evidence into PDD + SIPOC draft. |
| **Worker: reviewing** | Pure-Python quality gate — validates SIPOC schema, computes evidence strength, sets review flags. |
| **Streamlit UI** | Python-based review UI on port 8501 (opt-in profile). |
| **React UI** | Vite/React frontend on port 3000 (included in Docker stack by default). |

---

## 2. Prerequisites

### Required

| Tool | Minimum version | Notes |
|---|---|---|
| Docker Desktop | 4.x | For Option A (Docker Compose) |
| Python | 3.11 | For Option B (bare-metal) or running tests |
| PostgreSQL | 15+ | Local install **or** Azure PostgreSQL Flexible Server |

### Choose one LLM provider

| Provider | What you need |
|---|---|
| **OpenAI (direct)** | `OPENAI_API_KEY` — obtain from [platform.openai.com](https://platform.openai.com) |
| **Azure OpenAI** | `AZURE_OPENAI_ENDPOINT` + a chat deployment name (`AZURE_OPENAI_CHAT_DEPLOYMENT_NAME`) + `DefaultAzureCredential` (login with `az login`) |

### For full pipeline (workers active)

- **Azure Service Bus** connection string — or provision with `infra/dev-bootstrap.sh`

### Optional

- **ffmpeg** — required only for video files >24 MB. Install with `brew install ffmpeg` (macOS) or `apt install ffmpeg` (Linux/WSL).

---

## 3. Setup — Option A: Docker Compose (Recommended)

This option runs the API, all three workers, and the React frontend as Docker containers.

### Step 1 — Copy the env file

```bash
cp docker-compose.local.env.example .env.docker.local
```

### Step 2 — Edit `.env.docker.local`

Open the file and fill in these values (at minimum):

```ini
# --- Database ---
# Local PostgreSQL (must be running on your machine):
DATABASE_URL=postgresql+psycopg://pfcd_user:changeme@host.docker.internal:5432/pfcd?sslmode=disable

# OR: Azure PostgreSQL Flexible Server:
# DATABASE_URL=postgresql+psycopg://pfcd_admin:YOUR_PASSWORD@your-server.postgres.database.azure.com:5432/pfcd?sslmode=require

# --- LLM Provider: choose ONE block ---

# OpenAI (direct) — recommended for quick local dev:
PFCD_PROVIDER=openai
OPENAI_API_KEY=sk-...

# Azure OpenAI — requires az login + deployed model:
# PFCD_PROVIDER=azure_openai
# AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
# AZURE_OPENAI_CHAT_DEPLOYMENT_NAME=gpt-4o-mini

# --- Azure Service Bus (for workers to pick up jobs) ---
AZURE_SERVICE_BUS_CONNECTION_STRING=Endpoint=sb://...
```

> **Shell env var warning:** If `OPENAI_API_KEY` (or related provider/model vars) is already exported in your shell, Docker Compose can use that value instead of `.env.docker.local`.
> Prefer the safe restart command in Step 5A so `.env.docker.local` is guaranteed to win.

### Step 3 — Create the local PostgreSQL database

If using a local PostgreSQL install (not Azure):

```bash
psql -U postgres -c "CREATE USER pfcd_user WITH PASSWORD 'changeme';"
psql -U postgres -c "CREATE DATABASE pfcd OWNER pfcd_user;"
```

### Step 4 — Run database migrations

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
DATABASE_URL="postgresql+psycopg://pfcd_user:changeme@127.0.0.1:5432/pfcd?sslmode=disable" \
  .venv/bin/alembic upgrade head
```

### Step 5 — Start the stack

```bash
docker compose --env-file .env.docker.local -f docker-compose.local.yml up --build -d
```

Wait ~30 seconds for the API health check to pass, then verify:

```bash
curl http://127.0.0.1:8000/health
# Expected: {"status":"ok"} or {"status":"degraded",...}
```

### Step 5A — Force Docker to use `.env.docker.local` for OpenAI keys/models

Use this when jobs fail with `429 insufficient_quota` and you suspect a stale shell-exported key:

```bash
env -u OPENAI_API_KEY \
    -u PFCD_PROVIDER \
    -u OPENAI_CHAT_MODEL_BALANCED \
    -u OPENAI_CHAT_MODEL_QUALITY \
    -u OPENAI_TRANSCRIPTION_MODEL \
    -u OPENAI_VISION_MODEL \
  docker compose --env-file .env.docker.local -f docker-compose.local.yml \
  up -d --force-recreate api worker-extracting worker-processing worker-reviewing
```

Verify runtime provider/model values inside containers:

```bash
for s in api worker-extracting worker-processing worker-reviewing; do
  docker compose --env-file .env.docker.local -f docker-compose.local.yml exec -T "$s" \
    /bin/sh -lc 'echo "$PFCD_PROVIDER | $OPENAI_CHAT_MODEL_BALANCED | $OPENAI_CHAT_MODEL_QUALITY"'
done
```

### Step 6 — (Optional) Start the Streamlit UI

```bash
docker compose --env-file .env.docker.local -f docker-compose.local.yml \
  --profile streamlit up -d streamlit
```

Access Streamlit at `http://127.0.0.1:8501`.

### Stopping the stack

```bash
docker compose --env-file .env.docker.local -f docker-compose.local.yml down
```

---

## 4. Setup — Option B: Bare-metal Python

Use this when you want to develop without Docker or run individual components.

### Step 1 — Create venv and install dependencies

```bash
cd backend
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Step 2 — Set environment variables

Create a local file (e.g., `.env.local`) and `source` it, or export each variable:

```bash
export DATABASE_URL="postgresql+psycopg://pfcd_user:changeme@127.0.0.1:5432/pfcd?sslmode=disable"
export PFCD_PROVIDER=openai
export OPENAI_API_KEY=sk-...
export AZURE_SERVICE_BUS_CONNECTION_STRING="Endpoint=sb://..."
```

### Step 3 — Run database migrations

```bash
cd backend
.venv/bin/alembic upgrade head
```

### Step 4 — Start the API

```bash
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

### Step 5 — Start the workers (three separate terminals)

```bash
# Terminal 1
PFCD_WORKER_ROLE=extracting python -m app.workers.runner

# Terminal 2
PFCD_WORKER_ROLE=processing python -m app.workers.runner

# Terminal 3
PFCD_WORKER_ROLE=reviewing python -m app.workers.runner
```

### Step 6 — (Optional) Start the Streamlit UI

```bash
cd streamlit_app
pip install -r requirements.txt   # if not installed
API_BASE=http://127.0.0.1:8000 streamlit run app.py
```

### Step 7 — (Optional) Start the cleanup worker

```bash
python -m app.workers.cleanup
```

---

## 5. LLM Provider Configuration

Set `PFCD_PROVIDER` to choose the LLM backend. All other config flows from that single toggle.

### `PFCD_PROVIDER=openai` (Direct OpenAI API)

| Variable | Required | Default | Description |
|---|---|---|---|
| `OPENAI_API_KEY` | ✅ | — | API key from platform.openai.com |
| `OPENAI_CHAT_MODEL_BALANCED` | No | `gpt-4o-mini` | Model used for the `balanced` cost profile |
| `OPENAI_CHAT_MODEL_QUALITY` | No | `gpt-4o` | Model used for the `quality` cost profile |
| `OPENAI_TRANSCRIPTION_MODEL` | No | `whisper-1` | Whisper model for transcription |
| `OPENAI_VISION_MODEL` | No | `gpt-4o-mini` | Model for vision/frame analysis |

### `PFCD_PROVIDER=azure_openai` (Azure OpenAI — default)

| Variable | Required | Default | Description |
|---|---|---|---|
| `AZURE_OPENAI_ENDPOINT` | ✅ | — | REST endpoint, e.g. `https://my-resource.openai.azure.com/` |
| `AZURE_OPENAI_CHAT_DEPLOYMENT_NAME` | ✅ | — | Chat deployment name in your Azure resource |
| `AZURE_OPENAI_API_VERSION` | No | `2024-10-21` | API version string for Semantic Kernel |
| `AZURE_OPENAI_WHISPER_DEPLOYMENT` | No | `whisper` | Whisper deployment name |
| `AZURE_OPENAI_VISION_DEPLOYMENT` | No | `""` | Vision deployment name (optional) |
| `AZURE_OPENAI_DEPLOYMENT_BALANCED` | No | — | Override deployment for balanced profile |
| `AZURE_OPENAI_DEPLOYMENT_QUALITY` | No | — | Override deployment for quality profile |

Azure OpenAI uses `DefaultAzureCredential` (no API key needed). You must be logged in:

```bash
az login
```

### Cost profiles

| Profile | Purpose | Default model (OpenAI) |
|---|---|---|
| `balanced` | Most jobs — lower cost | `gpt-4o-mini` |
| `quality` | Complex jobs — higher accuracy | `gpt-4o` |

---

## 6. Running the Project

### Service URLs

| Service | URL | Notes |
|---|---|---|
| API | `http://127.0.0.1:8000` | FastAPI backend |
| API docs (Swagger) | `http://127.0.0.1:8000/docs` | Auto-generated OpenAPI UI |
| Health check | `http://127.0.0.1:8000/health` | Returns `ok` or `degraded` |
| Readiness probe | `http://127.0.0.1:8000/health/readiness` | Returns `ready` or `not_ready` |
| React frontend | `http://127.0.0.1:3000` | Default Docker port |
| Streamlit UI | `http://127.0.0.1:8501` | Opt-in `--profile streamlit` |

### Verify workers are connected

Workers log their Service Bus connection status on startup:

```bash
docker compose --env-file .env.docker.local -f docker-compose.local.yml logs worker-extracting
docker compose --env-file .env.docker.local -f docker-compose.local.yml logs worker-processing
docker compose --env-file .env.docker.local -f docker-compose.local.yml logs worker-reviewing
```

Look for: `Worker connected, listening on queue: extracting`

### Creating a job via API

```bash
# 1. Upload a file
curl -X POST http://127.0.0.1:8000/api/upload \
  -F "file=@/path/to/recording.mp4"

# 2. Create a job with the returned upload_id
curl -X POST http://127.0.0.1:8000/api/jobs \
  -H "Content-Type: application/json" \
  -d '{
    "title": "My Process Recording",
    "profile": "balanced",
    "input_files": [{"upload_id": "<upload_id_from_step_1>", "source_type": "video"}]
  }'
```

---

## 7. Running Tests

All test commands run from the **`backend/`** directory using the repo venv (not system Python).

```bash
cd backend

# All tests (unit + integration)
.venv/bin/pytest ../tests/ -v

# Unit tests only
.venv/bin/pytest ../tests/unit/ -v

# Integration tests only (uses in-memory SQLite — no Azure credentials needed)
.venv/bin/pytest ../tests/integration/ -v

# Single test file
.venv/bin/pytest ../tests/unit/test_agents.py -v

# Single test by name
.venv/bin/pytest ../tests/unit/test_agents.py::test_function_name -v

# PostgreSQL smoke test (requires a running PostgreSQL instance)
PFCD_POSTGRES_SMOKE_DATABASE_URL="postgresql+psycopg://postgres:postgres@127.0.0.1:5432/pfcd_test" \
  .venv/bin/pytest ../tests/integration/test_postgres_smoke.py -v
```

> Tests use an isolated SQLite database via `tmp_path` — no Azure credentials are needed for the standard suite.

---

## 8. Database Schema Reference

All JSON columns use deterministic serialization: `json.dumps(..., ensure_ascii=True, separators=(',', ':'))`.

---

### Table: `jobs`

The core state table. One row per job submission.

| Column | Type | Nullable | Description |
|---|---|---|---|
| `job_id` | VARCHAR(64) | No | Primary key. UUID string generated at job creation. |
| `version` | INTEGER | No | SQLAlchemy optimistic-locking version counter. Increments on every UPDATE. Prevents concurrent write conflicts. |
| `status` | VARCHAR(32) | No | Current job lifecycle status. See [Job Lifecycle](#9-job-lifecycle--state-machine). Values: `queued`, `processing`, `needs_review`, `finalizing`, `completed`, `failed`. |
| `created_at` | TIMESTAMPTZ | No | UTC timestamp of job creation. |
| `updated_at` | TIMESTAMPTZ | No | UTC timestamp of last state change. |
| `profile_requested` | VARCHAR(32) | No | Cost/quality profile requested by the caller. Values: `balanced`, `quality`. |
| `provider_effective` | TEXT (JSON) | No | JSON object recording which LLM provider and model were used per pipeline phase. Structure: `{"profile": "balanced", "cost_cap_usd": 4, "phase_resolved": {"extracting": {...}, "processing": {...}}}`. |
| `has_video` | BOOLEAN | No | True if the job includes at least one video file. Used by evidence scoring. |
| `has_audio` | BOOLEAN | No | True if the job includes audio (either standalone or extracted from video). |
| `has_transcript` | BOOLEAN | No | True if the job includes a transcript (VTT or TXT file). |
| `teams_metadata` | TEXT (JSON) | No | Optional Microsoft Teams meeting metadata supplied at job creation (title, attendees, recording markers, etc.). |
| `transcript_media_consistency` | TEXT (JSON) | No | Output of the anchor alignment engine. Records per-anchor similarity scores and overall consistency verdict (`match`, `inconclusive`, `suspected_mismatch`). |
| `extracted_evidence` | TEXT (JSON) | No | Evidence items produced by the extraction agent. Array of objects with fields: `step_id`, `step_name`, `description`, `source_anchor`, `evidence_type`, `confidence`, `speaker`. |
| `agent_signals` | TEXT (JSON) | No | Intermediate agent signals used between processing and reviewing (e.g., evidence strength tier, extracted speaker list). |
| `agent_review` | TEXT (JSON) | No | Final reviewing agent output. Key field: `decision` — `approve_for_draft`, `needs_review`, or `blocked`. Also contains `flags` array (BLOCKER/WARNING/INFO items). |
| `speaker_resolutions` | TEXT (JSON) | No | Map of raw speaker labels (e.g., `"Speaker 1"`, `"unknown_0"`) to resolved human names, set by the user during review. |
| `user_saved_draft` | BOOLEAN | No | True once the user has saved the draft via `PUT /api/jobs/{id}/draft`. Required gate before finalize. |
| `user_saved_at` | TIMESTAMPTZ | Yes | UTC timestamp of the last user draft save. Null until first save. |
| `current_phase` | VARCHAR(32) | Yes | The pipeline phase currently in progress (`extracting`, `processing`, `reviewing`). Null when idle or completed. |
| `last_completed_phase` | VARCHAR(32) | Yes | The last phase that completed successfully. Used for idempotency checks in Service Bus message dispatch. |
| `phase_attempt` | INTEGER | No | How many times the current phase has been attempted. Resets on phase transition. Used for retry backoff. |
| `payload_hash` | VARCHAR(128) | Yes | SHA-256 hash of the job payload at last phase dispatch. Used alongside `last_completed_phase` to detect duplicate Service Bus messages. |
| `active_agent_run_id` | VARCHAR(64) | Yes | FK reference to the `agent_runs` row currently executing. Cleared on phase completion or failure. |
| `deleted_at` | TIMESTAMPTZ | Yes | UTC timestamp of soft-delete. Non-null means the job is logically deleted and excluded from list results. |
| `cleanup_pending` | BOOLEAN | No | Set to True by the TTL expiry scan. The cleanup worker uses this flag to purge associated blobs and then hard-delete the row. |
| `ttl_expires_at` | TIMESTAMPTZ | Yes | UTC timestamp after which the cleanup worker will expire this job. Set at job creation based on `PFCD_JOB_TTL_DAYS`. |
| `error` | TEXT (JSON) | Yes | JSON object with exception details when `status=failed`. Includes `phase`, `exception_type`, `message`, `traceback`. Null on success. |

---

### Table: `input_manifests`

Stores the original input file metadata supplied at job creation.

| Column | Type | Nullable | Description |
|---|---|---|---|
| `job_id` | VARCHAR(64) | No | PK + FK → `jobs.job_id`. One manifest per job. |
| `payload` | TEXT (JSON) | No | JSON array of input file descriptors. Each entry includes `upload_id`, `storage_key`, `source_type` (`video`, `transcript`, `document`), `filename`, `size_bytes`, `mime_type`. |

---

### Table: `review_notes`

Stores the structured review flags generated by the reviewing agent (and any user overrides).

| Column | Type | Nullable | Description |
|---|---|---|---|
| `job_id` | VARCHAR(64) | No | PK + FK → `jobs.job_id`. One review_notes row per job. |
| `payload` | TEXT (JSON) | No | JSON object: `{"flags": [...]}`. Each flag has `severity` (`BLOCKER`, `WARNING`, `INFO`), `code`, `message`, and optionally `step_id` and `field`. BLOCKER flags must all be cleared before finalize is allowed. |

---

### Table: `drafts`

Stores PDD and SIPOC drafts. Each job can have multiple draft_kind rows (`pdd`, `sipoc`).

| Column | Type | Nullable | Description |
|---|---|---|---|
| `job_id` | VARCHAR(64) | No | Composite PK (part 1). FK → `jobs.job_id`. |
| `draft_kind` | VARCHAR(32) | No | Composite PK (part 2). Values: `pdd` (Process Definition Document), `sipoc` (SIPOC map rows). |
| `payload` | TEXT (JSON) | No | The draft content as a JSON object. For `pdd`: structured fields (process name, scope, steps, etc.). For `sipoc`: array of rows with Supplier/Input/Process/Output/Customer fields. |
| `version` | INTEGER | No | API-level edit versioning. The client must supply this version on `PUT /api/jobs/{id}/draft`; a stale version returns HTTP 409. |
| `generated_at` | TIMESTAMPTZ | Yes | UTC timestamp when the processing agent first created this draft. |
| `user_reconciled_at` | TIMESTAMPTZ | Yes | UTC timestamp of the most recent user save via `PUT /api/jobs/{id}/draft`. Null until first user edit. |
| `finalized_at` | TIMESTAMPTZ | Yes | UTC timestamp when the job was finalized (exports generated). Null until finalize. |
| `updated_at` | TIMESTAMPTZ | Yes | UTC timestamp of the most recent update (agent write or user save). |

---

### Table: `agent_runs`

Audit log of every LLM agent invocation. One row per phase per job.

| Column | Type | Nullable | Description |
|---|---|---|---|
| `agent_run_id` | VARCHAR(64) | No | PK. UUID string. |
| `job_id` | VARCHAR(64) | No | FK → `jobs.job_id`. |
| `agent` | VARCHAR(64) | No | Which agent executed. Values: `extraction`, `processing`, `reviewing`. |
| `model` | VARCHAR(64) | No | The model/deployment name that was used (e.g., `gpt-4o-mini`, `gpt-4o`). |
| `profile` | VARCHAR(32) | No | Cost profile active during this run (`balanced` or `quality`). |
| `status` | VARCHAR(32) | No | Outcome. Values: `running`, `completed`, `failed`. |
| `duration_ms` | INTEGER | No | Wall-clock time the agent took in milliseconds. |
| `cost_estimate_usd` | FLOAT | No | Estimated cost in USD for this agent invocation (token-count based). |
| `confidence_delta` | FLOAT | No | Change in overall evidence confidence score from this phase (positive = improved). |
| `message` | TEXT | Yes | Human-readable status message or error description. Null on success. |
| `created_at` | TIMESTAMPTZ | No | UTC timestamp when the run started. |
| `updated_at` | TIMESTAMPTZ | Yes | UTC timestamp of the last status update. |

---

### Table: `exports`

Stores export generation metadata after finalize.

| Column | Type | Nullable | Description |
|---|---|---|---|
| `job_id` | VARCHAR(64) | No | PK + FK → `jobs.job_id`. |
| `payload` | TEXT (JSON) | No | JSON object listing generated export files and their storage keys. Keys: `json`, `markdown`, `pdf`, `docx`, each pointing to a `storage_key` path in blob storage or the local filesystem. |

---

### Table: `job_events`

Append-only audit event log. One row per significant lifecycle transition.

| Column | Type | Nullable | Description |
|---|---|---|---|
| `event_id` | VARCHAR(64) | No | PK. UUID string. |
| `job_id` | VARCHAR(64) | No | FK → `jobs.job_id`. |
| `event_type` | VARCHAR(64) | No | Event name. Examples: `job_created`, `phase_started`, `phase_completed`, `phase_failed`, `draft_saved`, `job_finalized`, `job_deleted`. |
| `payload` | TEXT (JSON) | No | JSON object with event-specific data (e.g., phase name, error type, file counts). |
| `created_at` | TIMESTAMPTZ | No | UTC timestamp of the event. |

---

## 9. Job Lifecycle / State Machine

```
POST /api/jobs
      │
      ▼
   QUEUED ──── Service Bus: extracting queue
      │
      ▼
 PROCESSING ──── Worker: extracting → processing → reviewing
      │
      ▼
 NEEDS_REVIEW ──── User reviews in Streamlit / React UI
      │
      ▼             ◄── PUT /api/jobs/{id}/draft (user saves edits)
 FINALIZING ──── POST /api/jobs/{id}/finalize
      │
    ┌─┴──────────┐
    ▼            ▼
COMPLETED      FAILED
```

### Status descriptions

| Status | Meaning |
|---|---|
| `queued` | Job created; waiting for the extracting worker to pick it up. |
| `processing` | One of the three pipeline workers is actively running. |
| `needs_review` | All three pipeline phases completed. Awaiting human review and approval. |
| `finalizing` | User clicked Finalize; exports are being generated. |
| `completed` | Exports generated successfully. Download links are available. |
| `failed` | An unrecoverable error occurred. See `jobs.error` for details. |

### `agent_review.decision` values

| Value | Meaning |
|---|---|
| `approve_for_draft` | Reviewing agent found no blockers — job can be finalized without changes. |
| `needs_review` | Reviewing agent found warnings — human review recommended before finalize. |
| `blocked` | Reviewing agent found BLOCKER flags — finalize is disabled until flags are resolved. |

### Finalize pre-conditions

The API enforces both before allowing finalize:
1. `user_saved_draft=true` OR `draft.user_reconciled_at` is set (user has saved at least once)
2. No BLOCKER flags remain in `review_notes.flags`

---

## 10. Common Operations

### Re-run a stuck job (dev environments only)

If a job is stuck in `queued` or `processing` (e.g., worker crashed before completing):

```bash
# Use the dev simulate endpoint to advance the job to needs_review
curl -X POST http://127.0.0.1:8000/dev/simulate/{job_id}
```

> `/dev/simulate` is available in all environments (no feature flag). It bypasses LLM calls and injects a synthetic extraction/review result. Useful for UI testing without consuming LLM quota.

### Soft-delete a job

```bash
curl -X DELETE http://127.0.0.1:8000/api/jobs/{job_id}
```

Sets `deleted_at` and `cleanup_pending=true`. The cleanup worker will purge blobs and hard-delete the row once the TTL passes.

### Export formats

After finalize, download exports via:

```bash
curl http://127.0.0.1:8000/api/jobs/{job_id}/exports/json      > output.json
curl http://127.0.0.1:8000/api/jobs/{job_id}/exports/markdown  > output.md
curl http://127.0.0.1:8000/api/jobs/{job_id}/exports/pdf       > output.pdf
curl http://127.0.0.1:8000/api/jobs/{job_id}/exports/docx      > output.docx
```

If `PFCD_API_KEY` is set, add `-H "X-API-Key: <your-key>"` to all requests.

### Check migrations status

```bash
cd backend
.venv/bin/alembic current      # which migration is applied
.venv/bin/alembic history      # full migration chain
.venv/bin/alembic upgrade head # apply pending migrations
```

### View job state directly in PostgreSQL

```sql
-- Most recent 10 jobs
SELECT job_id, status, current_phase, created_at, error
FROM jobs
ORDER BY created_at DESC
LIMIT 10;

-- Jobs stuck in processing
SELECT job_id, status, current_phase, phase_attempt, updated_at
FROM jobs
WHERE status = 'processing'
ORDER BY updated_at;

-- Review flags for a specific job
SELECT payload FROM review_notes WHERE job_id = '<job_id>';

-- Agent run history for a job
SELECT agent, model, status, duration_ms, cost_estimate_usd, created_at
FROM agent_runs
WHERE job_id = '<job_id>'
ORDER BY created_at;
```
