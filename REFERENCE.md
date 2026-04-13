# REFERENCE.md — PFCD-V2 Developer Reference

This file contains stable reference material. Read it when you need to
navigate the codebase, set up the environment, or understand infra naming.
It is not loaded every session — pull it on demand.

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
│   │   ├── agents/
│   │   │   ├── __init__.py
│   │   │   ├── alignment.py       # Anchor validation engine (VTT + section label)
│   │   │   ├── evidence.py        # Evidence strength computation
│   │   │   ├── extraction.py      # SK-based extraction agent (uses AdapterRegistry)
│   │   │   ├── kernel_factory.py  # SK Kernel factory (Azure OpenAI + direct OpenAI)
│   │   │   ├── media_preprocessor.py # ffmpeg audio extraction/chunking + VTT merge helpers
│   │   │   ├── openai_client.py   # (legacy — kept for reference, unused)
│   │   │   ├── processing.py      # SK-based processing agent
│   │   │   ├── reviewing.py       # Pure-Python reviewing agent (uses SIPOCValidator)
│   │   │   ├── sipoc_validator.py # SIPOC schema validation (PRD §8.8 + §10)
│   │   │   ├── transcription.py   # Whisper transcription helper for local media blobs
│   │   │   ├── vision.py          # direct httpx vision-call batching for video frames
│   │   │   └── adapters/
│   │   │       ├── __init__.py
│   │   │       ├── base.py        # IProcessEvidenceAdapter ABC + dataclasses
│   │   │       ├── transcript.py  # TranscriptAdapter (VTT + TXT)
│   │   │       ├── video.py       # VideoAdapter (metadata; Azure Vision pending)
│   │   │       └── registry.py    # AdapterRegistry
│   │   └── workers/
│   │       ├── runner.py  # Service Bus worker (phase handler)
│   │       └── cleanup.py # TTL expiry and data purge worker
│   ├── alembic/           # DB migrations
│   │   └── versions/      # Migration scripts (20260401_0001_init.py)
│   ├── requirements.txt   # Python dependencies (pinned)
│   └── alembic.ini        # Alembic config
├── frontend/              # React/Vite frontend (active — see frontend/src/)
├── infra/
│   ├── dev-bootstrap.sh   # Idempotent Azure resource provisioning script
│   └── README.md          # Infra setup and verification guide
├── tests/
│   ├── conftest.py            # shared fixtures (AppContext, app_client, seeded jobs)
│   ├── unit/
│   │   ├── test_repository.py      # job roundtrip and event logging tests
│   │   ├── test_worker.py          # worker phase dispatch and export tests
│   │   ├── test_cleanup.py         # TTL expiry and purge tests
│   │   ├── test_auth.py            # API key auth HTTP-level tests
│   │   ├── test_agents.py          # extraction, processing, reviewing, alignment, evidence tests
│   │   ├── test_adapters.py        # TranscriptAdapter, VideoAdapter, AdapterRegistry, extraction integration
│   │   ├── test_media_preprocessor.py # ffmpeg availability, VTT merge, chunking, large-file transcription
│   │   ├── test_vision.py          # frame batching and provider-routing tests
│   │   ├── test_sipoc_validator.py # SIPOC schema validation and reviewing agent integration
│   │   └── test_export_builder.py  # evidence bundle, PDF, Markdown, DOCX export tests
│   └── integration/
│       ├── test_lifecycle.py       # full job create→simulate→finalize→delete lifecycle
│       ├── test_auth_enforcement.py # 401/403 on all protected endpoints
│       ├── test_error_cases.py     # 409/410/413/400 error paths
│       └── test_exports.py         # PDF/DOCX/Markdown/JSON export format checks
├── .github/
│   └── workflows/
│       ├── deploy-backend.yml
│       ├── deploy-frontend.yml
│       └── deploy-workers.yml  # parallel worker App Service deployments
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
| Data validation | Pydantic | >=2.11.0 |
| LLM orchestration | Semantic Kernel | >=1.41.1 |
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
| HTTP test client | httpx | 0.28.1 |

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
| `AZURE_STORAGE_CONTAINER_EVIDENCE` | Blob container for frame captures/evidence assets | `evidence` |
| `AZURE_SERVICE_BUS_CONNECTION_STRING` | Service Bus namespace | `""` (skips queue dispatch) |
| `AZURE_SERVICE_BUS_QUEUE_EXTRACTING` | Queue name | `extracting` |
| `AZURE_SERVICE_BUS_QUEUE_PROCESSING` | Queue name | `processing` |
| `AZURE_SERVICE_BUS_QUEUE_REVIEWING` | Queue name | `reviewing` |
| `PFCD_WORKER_ROLE` | Worker phase (`extracting`/`processing`/`reviewing`) | — |
| `PFCD_CLEANUP_INTERVAL_SECONDS` | Cleanup worker poll interval | `300` |
| `PFCD_API_KEY` | Static API key for `X-API-Key` header | `""` (auth disabled if unset) |
| `PFCD_PROVIDER` | Chat/transcription provider (`azure_openai` or `openai`) | `azure_openai` |
| `AZURE_OPENAI_ENDPOINT` | Azure OpenAI REST endpoint | required for agents |
| `AZURE_OPENAI_CHAT_DEPLOYMENT_NAME` | Chat model deployment name (canonical) | required for agents |
| `AZURE_OPENAI_API_VERSION` | Azure OpenAI API version for Semantic Kernel | `2024-10-21` |
| `AZURE_OPENAI_WHISPER_DEPLOYMENT` | Azure OpenAI Whisper deployment name | `whisper` |
| `AZURE_OPENAI_DEPLOYMENT_NAME` | Legacy deployment alias (deprecated) | fallback only |
| `AZURE_OPENAI_DEPLOYMENT` | Legacy deployment alias (deprecated) | fallback only |
| `OPENAI_API_KEY` | Direct OpenAI API key | required when `PFCD_PROVIDER=openai` |
| `OPENAI_CHAT_MODEL_BALANCED` | Direct OpenAI balanced chat model | `gpt-4o-mini` |
| `OPENAI_CHAT_MODEL_QUALITY` | Direct OpenAI quality chat model | `gpt-4o` |
| `OPENAI_TRANSCRIPTION_MODEL` | Direct OpenAI transcription model | `whisper-1` |
| `OPENAI_VISION_MODEL` | Direct OpenAI vision model | `gpt-4o-mini` |
| `AZURE_OPENAI_VISION_DEPLOYMENT` | Azure OpenAI deployment name for vision | `""` |
| `PFCD_VISION_FRAMES_PER_CALL` | Max images sent per vision LLM call | `4` |
| `PFCD_VISION_MAX_FRAMES` | Max frames analyzed per job | `40` |
| `PFCD_CONSISTENCY_MATCH_THRESHOLD` | Transcript/media consistency threshold for `match` | `0.80` |
| `PFCD_CONSISTENCY_INCONCLUSIVE_THRESHOLD` | Anchor-fallback consistency threshold for `inconclusive` | `0.50` |
| `PFCD_CONSISTENCY_MISMATCH_THRESHOLD` | Transcript/media consistency threshold for `suspected_mismatch` | `0.30` |

### Frontend Dev Environment Variables

| Variable | Purpose | Default |
|----------|---------|---------|
| `VITE_API_BASE` | Frontend API origin override | `""` |
| `VITE_API_KEY` | Client-side API key sent as `X-API-Key` | `""` |

**ffmpeg dependency:** `media_preprocessor.py` calls `ffmpeg` via subprocess. Azure App Service (Linux) does not include `ffmpeg` by default. For local dev, install with `brew install ffmpeg` on macOS or `apt install ffmpeg` on Linux. For Azure production, Docker workers with a custom image are required (Phase 5b). When `ffmpeg` is absent, files larger than 24 MB fall back to `[transcription_skipped:file_too_large]`, matching the pre-Phase 5 behavior.

### Starting Workers (Service Bus Phases)

```bash
PFCD_WORKER_ROLE=extracting python -m app.workers.runner
PFCD_WORKER_ROLE=processing python -m app.workers.runner
PFCD_WORKER_ROLE=reviewing python -m app.workers.runner

# Run cleanup worker (TTL expiry + data purge)
python -m app.workers.cleanup
```

---

## Running Tests

```bash
cd backend
.venv/bin/pytest ../tests/unit/ -v
```

Use `.venv/bin/pytest` (not system `pytest`) to ensure the correct Python 3.11 venv is used.

Tests use `tmp_path` fixture with an isolated SQLite database; no Azure credentials required. They monkeypatch `DATABASE_URL` and reload modules to pick up the change.

**Test naming convention:** `tests/<layer>/<feature>_test.<ext>` with behavior-focused names (e.g., `test_video_without_audio_forces_review`).

---

## API Endpoints

Base path: `/api`

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/jobs` | Create a new job (accepts `JobCreateRequest`) |
| GET | `/api/jobs` | List recent non-deleted jobs (most recent first) |
| GET | `/api/jobs/{job_id}` | Get job state and payload |
| PUT | `/api/jobs/{job_id}/draft` | Update draft (reconcile review notes) |
| POST | `/api/jobs/{job_id}/finalize` | Finalize draft (move to FINALIZING) |
| GET | `/api/jobs/{job_id}/exports/{format}` | Export draft (`json`, `markdown`, `pdf`, `docx`) |
| DELETE | `/api/jobs/{job_id}` | Soft-delete / mark job expired |
| GET | `/health` | Health check — returns `{"status": "ok"}` (200) or `{"status": "degraded", ...}` (503) with env diagnostics when Azure connections are unavailable |

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

**File:** `.github/workflows/deploy-workers.yml`

- Triggers on push to `main` with changes under `backend/**`
- Builds one worker zip, uploads it to the storage account `scratch` container, writes a SAS-backed package URL artifact, then deploys in parallel to `pfcd-dev-worker-extracting`, `pfcd-dev-worker-processing`, `pfcd-dev-worker-reviewing` via `WEBSITE_RUN_FROM_PACKAGE`
- Required secrets: `AZURE_CREDENTIALS`, `AZURE_RESOURCE_GROUP`, `AZURE_WORKER_EXTRACTING_NAME`, `AZURE_WORKER_PROCESSING_NAME`, `AZURE_WORKER_REVIEWING_NAME`
- Required GitHub Actions variable: `AZURE_STORAGE_ACCOUNT`

### GitHub Variables

| Variable | Used by | Purpose |
|----------|---------|---------|
| `AZURE_STORAGE_ACCOUNT` | `deploy-workers.yml` | Storage account resource name used to upload `worker.zip` to `scratch` and generate the `WEBSITE_RUN_FROM_PACKAGE` SAS URL |

---

## Key Files Quick Reference

| File | What it does |
|------|-------------|
| `backend/app/auth.py` | `verify_api_key` FastAPI dependency — X-API-Key enforcement |
| `backend/app/main.py` | All HTTP endpoints, app startup |
| `backend/app/job_logic.py` | `JobStatus`, `Profile`, `ReviewSeverity` enums; `default_job_payload()` |
| `backend/app/repository.py` | `JobRepository` — all DB reads/writes |
| `backend/app/db.py` | `session_scope`, DB engine, `DATABASE_URL` config |
| `backend/app/servicebus.py` | `ServiceBusOrchestrator`, `build_message()` |
| `backend/app/storage.py` | `ExportStorage`, save/load blob or local file |
| `backend/app/workers/runner.py` | Service Bus worker loop, phase dispatch |
| `backend/app/workers/cleanup.py` | TTL expiry scan and job data purge worker |
| `backend/app/models.py` | SQLAlchemy ORM table classes |
| `backend/alembic/versions/20260401_0001_init.py` | Single DB migration creating all tables |
| `tests/unit/test_repository.py` | Job roundtrip and event logging tests |
| `tests/unit/test_worker.py` | Worker phase dispatch and export tests |
| `tests/unit/test_cleanup.py` | TTL expiry and purge tests |
| `tests/unit/test_auth.py` | API key auth HTTP-level tests |
| `tests/unit/test_agents.py` | 61-test suite covering all agent modules |
| `tests/unit/test_adapters.py` | 36-test suite for adapters and extraction integration |
| `tests/unit/test_sipoc_validator.py` | 21-test suite for SIPOC validation and reviewing integration |
| `backend/app/agents/kernel_factory.py` | SK Kernel factory — change provider auth or chat model routing here |
| `backend/app/agents/transcription.py` | Whisper transcription helper for local video/audio blobs |
| `backend/app/agents/extraction.py` | `_call_extraction` async + `run_extraction` + `_normalize_input` (adapter-backed) |
| `backend/app/agents/processing.py` | `_call_processing` async + `run_processing` SK wrapper |
| `backend/app/agents/alignment.py` | `run_anchor_alignment` — validates VTT/section-label anchors post-extraction |
| `backend/app/agents/evidence.py` | `compute_evidence_strength` — derives high/medium/low from sources + confidence |
| `backend/app/agents/sipoc_validator.py` | `validate_sipoc` — per-row schema check, step_anchor cross-ref, quality gate |
| `backend/app/agents/adapters/base.py` | `IProcessEvidenceAdapter` ABC, `EvidenceObject`, `DetectionResult`, `FactItem` |
| `backend/app/agents/adapters/transcript.py` | `TranscriptAdapter` — VTT/TXT normalize, facts, review notes |
| `backend/app/agents/adapters/video.py` | `VideoAdapter` — metadata normalize, audio confidence, review notes |
| `backend/app/agents/adapters/registry.py` | `AdapterRegistry` — source_type → adapter mapping, transcript-first precedence |
| `infra/dev-bootstrap.sh` | Idempotent Azure provisioning |
| `prd.md` | Authoritative product requirements |
