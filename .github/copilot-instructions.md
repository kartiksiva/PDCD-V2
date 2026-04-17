# PFCD-V2 Copilot Instructions

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
```

CI runs the suite from the repo root with:

```bash
PYTHONPATH=backend DATABASE_URL=sqlite:///./test-ci.db pytest tests/unit tests/integration -x --tb=short
```

### Frontend

```bash
cd frontend
npm ci
npm run dev
npm run build
```

There is no dedicated lint command checked into the repo today.

## High-level architecture

- `backend/app/main.py` owns the HTTP API. `POST /api/jobs` persists the initial job payload, appends an event, and enqueues the first `extracting` message.
- The async pipeline is split across Service Bus worker phases in `backend/app/workers/runner.py`: `extracting -> processing -> reviewing`. Each phase mutates the job payload and enqueues the next phase.
- Extraction is adapter-driven. `AdapterRegistry` resolves source adapters, `TranscriptAdapter` and `VideoAdapter` normalize raw inputs, and `run_extraction()` sends normalized content through Semantic Kernel chat completion. `run_anchor_alignment()` then scores transcript/media consistency.
- Processing turns extracted evidence into the draft contract: PDD + SIPOC JSON. Reviewing is pure Python: it validates SIPOC rows, computes evidence strength, applies review flags, and sets `agent_review.decision`.
- Persistence is centralized in `backend/app/repository.py`. The API and workers treat the job as one canonical payload, while `JobRepository` fans that payload into SQL tables (`jobs`, `drafts`, `review_notes`, `agent_runs`, `exports`, etc.).
- Export generation is centralized in `backend/app/export_builder.py`; finalized drafts are rendered to JSON, Markdown, PDF, and DOCX, then written through `ExportStorage`, which supports local filesystem and Azure Blob storage.
- `frontend/src/App.jsx` is a thin flow controller for list/create/status/review/export views. The review UI auto-saves draft edits through `PUT /api/jobs/{job_id}/draft` before finalize, and authenticated export downloads go through `frontend/src/api.js`.

## Key conventions

- Route all database access through `JobRepository`; do not open SQLAlchemy sessions directly from endpoints or workers. In FastAPI handlers, wrap blocking repo/storage/export work with `anyio.to_thread.run_sync(...)`.
- Job JSON is treated as a stable contract. Persisted JSON uses deterministic serialization: `json.dumps(..., ensure_ascii=True, separators=(",", ":"))`.
- Service Bus messages should be created with `build_message()`. Workers depend on `payload_hash` plus `last_completed_phase` to skip duplicates and keep phase handling idempotent.
- `job["status"]` is not the same as review readiness. Reviewing always leaves jobs in `needs_review`; the real gate is `job["agent_review"]["decision"]` (`approve_for_draft`, `needs_review`, `blocked`).
- Finalize is intentionally strict: the draft must be saved first (`user_saved_draft` or `draft.user_reconciled_at`) and blocker flags must be cleared. Frontend code should save before calling `finalizeJob()`.
- Azure integrations prefer `DefaultAzureCredential` first, with connection-string fallback only where already implemented (`storage.py`).
- Extraction precedence is transcript-first for LLM input (`AdapterRegistry` returns transcript before video), even though evidence scoring remains video-first later in the pipeline.
- `_transcript_text_inline`, `_video_transcript_inline`, and `_frame_descriptions_inline` are ephemeral phase-local fields. They can be used during extraction/alignment but must not be persisted back into the stored job payload.
- The frontend assumes API auth is header-based. If `PFCD_API_KEY` is enabled, client requests and export downloads must include `X-API-Key` via `VITE_API_KEY`.
