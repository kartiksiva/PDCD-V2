# PFCD-V2 Copilot Instructions

## Repository workflow

- Read `AGENTS.md`, the relevant GitHub issue / PR context, `IMPLEMENTATION_SUMMARY.md`, and `prd.md` before making code changes. Use `REFERENCE.md` when you need file layout, env var, API, or infra details.
- GitHub issues and pull requests are the source of truth for task tracking and review state.

## Build, test, and dev commands

### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

### Backend workers

```bash
cd backend
PFCD_WORKER_ROLE=extracting python -m app.workers.runner
PFCD_WORKER_ROLE=processing python -m app.workers.runner
PFCD_WORKER_ROLE=reviewing python -m app.workers.runner
python -m app.workers.cleanup
```

### Tests

Run tests from `backend/` using the repo venv, not system `pytest`:

```bash
cd backend
.venv/bin/pytest ../tests/ -v
.venv/bin/pytest ../tests/unit/ -v
.venv/bin/pytest ../tests/integration/ -v
.venv/bin/pytest ../tests/unit/test_agents.py -v
.venv/bin/pytest ../tests/unit/test_agents.py::test_function_name -v
.venv/bin/pytest ../tests/integration/test_postgres_smoke.py -v
```

PostgreSQL smoke coverage needs `PFCD_POSTGRES_SMOKE_DATABASE_URL` set.

CI runs the suite from the repo root with:

```bash
PYTHONPATH=backend DATABASE_URL=sqlite:///./test-ci.db pytest tests/unit tests/integration -x --tb=short
PYTHONPATH=backend PFCD_POSTGRES_SMOKE_DATABASE_URL=postgresql+psycopg://postgres:postgres@127.0.0.1:5432/pfcd_test pytest tests/integration/test_postgres_smoke.py -x --tb=short
```

### Frontend

```bash
cd frontend
npm ci
npm run dev
npm run build
npm run preview
```

There is no dedicated lint command checked into the repo today.

### Docker smoke paths

```bash
# Backend container smoke
cd backend
docker compose -f docker-compose.smoke.yml build
PFCD_SMOKE_API_PORT=8010 docker compose -f docker-compose.smoke.yml up -d api
curl http://127.0.0.1:8010/health
docker compose -f docker-compose.smoke.yml down --remove-orphans

# Repo-level integrated frontend + backend stack
cd /path/to/repo
cp docker-compose.local.env.example .env.docker.local
docker compose --env-file .env.docker.local -f docker-compose.local.yml up --build -d
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:3000/health
docker compose -f docker-compose.local.yml down --remove-orphans
```

## High-level architecture

- `backend/app/main.py` owns the HTTP API. `POST /api/upload` stores raw uploads locally for the current ingestion path, and `POST /api/jobs` persists the initial job payload, appends an event, and enqueues the first `extracting` message.
- The async pipeline is split across Service Bus worker phases in `backend/app/workers/runner.py`: `extracting -> processing -> reviewing`. Each phase mutates the canonical job payload, persists it, and enqueues the next phase. Retries and duplicate suppression rely on `attempt`, `payload_hash`, and `last_completed_phase`.
- Extraction is adapter-driven. `AdapterRegistry` resolves source adapters, `TranscriptAdapter` and `VideoAdapter` normalize raw inputs, media preprocessing/transcription/vision helpers enrich video evidence, and `run_extraction()` sends normalized content through Semantic Kernel chat completion. `run_anchor_alignment()` then scores transcript/media consistency.
- Processing turns extracted evidence into the draft contract: PDD + SIPOC JSON. Reviewing is pure Python: it validates SIPOC rows, computes evidence strength, applies review flags, and sets `agent_review.decision`. `PUT /api/jobs/{job_id}/draft` re-runs the reviewing gate after user edits so flags stay aligned with the saved draft.
- Persistence is centralized in `backend/app/repository.py`. The API and workers treat the job as one canonical payload, while `JobRepository` fans that payload into SQL tables (`jobs`, `drafts`, `review_notes`, `agent_runs`, `exports`, etc.).
- Export generation is centralized in `backend/app/export_builder.py`; finalized drafts are rendered to JSON, Markdown, PDF, and DOCX, then written through `ExportStorage`, which supports local filesystem and Azure Blob storage.
- `frontend/src/App.jsx` is a thin flow controller for list/create/status/review/export views. `frontend/src/api.js` centralizes API access, automatically adds `X-API-Key` when `VITE_API_KEY` is set, and handles authenticated export downloads programmatically rather than by raw anchor links.

## Key conventions

- Route all database access through `JobRepository`; do not open SQLAlchemy sessions directly from endpoints or workers. In FastAPI handlers, wrap blocking repo/storage/export work with `anyio.to_thread.run_sync(...)`.
- Job JSON is treated as a stable contract. Persisted JSON uses deterministic serialization: `json.dumps(..., ensure_ascii=True, separators=(",", ":"))`.
- Service Bus messages should be created with `build_message()`. Workers depend on `payload_hash` plus `last_completed_phase` to skip duplicates and keep phase handling idempotent.
- `job["status"]` is not the same as review readiness. Reviewing always leaves jobs in `needs_review`; the real gate is `job["agent_review"]["decision"]` (`approve_for_draft`, `needs_review`, `blocked`).
- Finalize is intentionally strict: the draft must be saved first (`user_saved_draft` or `draft.user_reconciled_at`) and blocker flags must be cleared. Frontend code should save before calling `finalizeJob()`.
- Saving a draft is not passive persistence: `PUT /api/jobs/{job_id}/draft` removes rerunnable review flags and re-runs the reviewing agent so the returned flags/decision reflect the edited draft.
- Azure integrations prefer `DefaultAzureCredential` first, with connection-string fallback only where already implemented (`storage.py`).
- Extraction precedence is transcript-first for LLM input (`AdapterRegistry` returns transcript before video), even though evidence scoring remains video-first later in the pipeline.
- `_transcript_text_inline`, `_video_transcript_inline`, and `_frame_descriptions_inline` are ephemeral phase-local fields. They can be used during extraction/alignment but must not be persisted back into the stored job payload.
- `PFCD_API_KEY` is an optional deployment guard rather than a product auth workflow; leave it unset for open local/demo flows.
- The frontend assumes API auth is header-based. If `PFCD_API_KEY` is enabled, client requests and export downloads must include `X-API-Key` via `VITE_API_KEY`.
- Local Docker and local API smoke checks can legitimately return `status: "degraded"` from `/health` when Azure-backed env vars are absent; local startup validation cares that the service responds, not that every Azure dependency is configured.
