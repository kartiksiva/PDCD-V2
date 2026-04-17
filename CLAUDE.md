# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

## Role in This Project

**Claude is architect and code reviewer only.** Codex is the developer who writes and modifies application code.

Claude's permitted actions:
- Review PRs and code changes for correctness, architecture fit, and PRD compliance
- Update `CLAUDE.md`, `HANDOVER.md`, `IMPLEMENTATION_SUMMARY.md`, `prd.md` (progress section only), and `REFERENCE.md`
- Propose design decisions and flag architectural concerns
- Run tests and read files to validate Codex's work

Claude must **not** write or modify application code (`.py`, `.ts`, `.tsx`, `.sh`, config files outside docs).

### Agent File Ownership

| File | Read by | Written by | Purpose |
|------|---------|------------|---------|
| `CLAUDE.md` | Claude | Claude | Claude's bootstrap, architecture reference, review checklist |
| `AGENTS.md` | Codex | Codex | Codex's bootstrap — coding style, commit/PR guidelines, build commands |
| `HANDOVER.md` | **Both** | **Both** | Work assignment board — assignments, in-progress, review queue |
| `IMPLEMENTATION_SUMMARY.md` | Both | Both (append-only) | Rolling history log |
| `prd.md` | Both | Claude (progress table only) | Authoritative requirements |
| `REFERENCE.md` | Both | Claude | File layout, env vars, API/data model, Azure infra |

Work assignments live in `HANDOVER.md`. Claude adds items to "Assigned to Codex"; Codex moves them through the board; Claude closes them after review. Neither agent edits the other's bootstrap file.

---

## Session Bootstrap Protocol (MANDATORY)

At the start of every session, before reviewing or commenting on any code:

1. Read `CLAUDE.md` (this file)
2. Read `HANDOVER.md` — current work assignment board; check what's ready for review
3. Read `IMPLEMENTATION_SUMMARY.md` — rolling log of what has been built and what remains
4. Read `prd.md` — authoritative requirements; never modify requirements, only the progress table
5. Read `REFERENCE.md` on demand — file layout, env vars, API/data model, Azure infra, CI/CD

After any meaningful review or architectural decision, update:
- `CLAUDE.md` → Implementation Status section (Done / Architecture gaps)
- `HANDOVER.md` → close completed items; add new Codex assignments
- `IMPLEMENTATION_SUMMARY.md` → append findings, design decisions, open questions
- `prd.md` → progress milestone table only
- `REFERENCE.md` → only when APIs, infra naming, file layout, or env vars actually change

Shared logs are append-only to avoid overwrite conflicts between agents.

---

## Project Overview

**PFCD Video-First v1** is an Azure-native process documentation system. It ingests video/audio/transcript evidence, runs agentic extraction and review pipelines, and produces structured process documentation (PDD + SIPOC) in multiple export formats.

Reference documents:
- `prd.md` — authoritative product requirements and evidence hierarchy rules
- `REFERENCE.md` — file layout, tech stack, env vars, API endpoints, data model, Azure infra
- `GEMINI.md` — architecture overview and planning context
- `REVIEW_CLOSURE_2026-03-21.md` — skeleton approval status and conditions

---

## Build and Test Commands

All commands run from `backend/` with the venv activated.

```bash
# Setup (first time)
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head

# Run API server (local)
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

# Run all tests
.venv/bin/pytest ../tests/ -v

# Run unit tests only
.venv/bin/pytest ../tests/unit/ -v

# Run a single test file
.venv/bin/pytest ../tests/unit/test_agents.py -v

# Run a single test by name
.venv/bin/pytest ../tests/unit/test_agents.py::test_function_name -v

# Run integration tests only (no Azure creds needed — uses SQLite in-memory)
.venv/bin/pytest ../tests/integration/ -v
```

Use `.venv/bin/pytest` (not system `pytest`) to ensure Python 3.11 venv is active. Tests use `tmp_path` with an isolated SQLite database; no Azure credentials are required.

### Worker processes

```bash
PFCD_WORKER_ROLE=extracting python -m app.workers.runner
PFCD_WORKER_ROLE=processing python -m app.workers.runner
PFCD_WORKER_ROLE=reviewing  python -m app.workers.runner
python -m app.workers.cleanup   # TTL expiry + data purge
```

---

## Architecture

### Request → Pipeline → Export Flow

```
HTTP POST /api/jobs
    └─ main.py → JobRepository (SQLite/Azure SQL)
                └─ ServiceBusOrchestrator → queue: "extracting"

Worker (PFCD_WORKER_ROLE=extracting)
    └─ runner.py → extraction.py
                    ├─ AdapterRegistry → TranscriptAdapter (VTT/TXT) | VideoAdapter
                    └─ SK Kernel (AzureChatCompletion + DefaultAzureCredential)
                        └─ produces: evidence_items[], document_type_manifests
                            └─ alignment.py: VTT anchor validation, similarity_score
                                └─ queue: "processing"

Worker (PFCD_WORKER_ROLE=processing)
    └─ runner.py → processing.py (SK)
                    └─ evidence.py: source hierarchy → evidence_strength
                        └─ queue: "reviewing"

Worker (PFCD_WORKER_ROLE=reviewing)
    └─ runner.py → reviewing.py (pure-Python, no LLM)
                    └─ sipoc_validator.py: per-row field check, step_anchor cross-ref
                        └─ COMPLETED | NEEDS_REVIEW

GET /api/jobs/{id}/exports/{format}
    └─ export_builder.py → PDF | DOCX | Markdown | JSON (with evidence bundle)
```

### Key Module Responsibilities

| Module | Role |
|--------|------|
| `main.py` | All HTTP endpoints, app startup, upload handling |
| `job_logic.py` | `JobStatus` / `Profile` / `ReviewSeverity` enums; `default_job_payload()` |
| `repository.py` | `JobRepository` — sole owner of all DB reads/writes |
| `db.py` | `session_scope` context manager, DB engine, `DATABASE_URL` config |
| `servicebus.py` | `ServiceBusOrchestrator`, `build_message()`, phase dispatch |
| `storage.py` | `ExportStorage` — blob or local file abstraction |
| `workers/runner.py` | Service Bus receive loop, phase handler dispatch |
| `workers/cleanup.py` | TTL expiry scan and data purge |
| `agents/kernel_factory.py` | Builds SK `Kernel` with `DefaultAzureCredential` |
| `agents/extraction.py` | Adapter-normalized content → SK extraction → evidence_items |
| `agents/processing.py` | SK processing → PDD/SIPOC draft |
| `agents/reviewing.py` | Pure-Python quality gate; calls `sipoc_validator.py` |
| `agents/alignment.py` | VTT cue parsing, 2s tolerance, anchor confidence penalty |
| `agents/evidence.py` | PRD §7 source hierarchy → `evidence_strength` |
| `agents/adapters/` | `IProcessEvidenceAdapter` ABC + Transcript/Video adapters + registry |
| `export_builder.py` | Evidence bundle manifest; PDF/DOCX/Markdown generation |
| `auth.py` | `verify_api_key` FastAPI dependency — `X-API-Key` enforcement |

### Patterns to Know

**Async/sync boundary:** All blocking DB calls use `await anyio.to_thread.run_sync(...)`. SK agent calls use `asyncio.run()` inside synchronous worker handlers.

**Factory pattern:** `from_env()` classmethods on `JobRepository`, `ExportStorage`. This isolates env var reads and enables monkeypatching in tests.

**Repository pattern:** All DB access goes through `JobRepository`. Never call `SessionLocal` directly from endpoints or workers.

**JSON columns:** All JSON stored deterministically: `json.dumps(..., ensure_ascii=True, separators=(',', ':'))`.

---

## Job State Machine

```
QUEUED → PROCESSING → NEEDS_REVIEW → FINALIZING → COMPLETED
                                                 ↘ FAILED
```

`JobStatus` enum is in `job_logic.py`. `phase_attempt` tracks retry count. `error` (JSON TEXT) stores exception details on failure.

---

## Evidence Hierarchy (PRD §7)

When reviewing extraction or review logic:

1. **Video** (highest)
2. **Audio/transcript** derived from video
3. **Standalone transcript**
4. **Document/slide** (lowest)

Video beats transcript on conflict. `evidence.py` implements: `has_video + has_audio` → `"high"`, mean confidence < 0.60 downgrades one tier.

---

## Cost Profiles

| Profile | Model | Cap |
|---------|-------|-----|
| `balanced` | GPT-4o-mini | $4 |
| `quality` | GPT-4o | $8 |

Tracked in `agent_runs.cost_estimate_usd`. Respect caps when reviewing agent call scheduling.

---

## Authentication

All `/api/*` endpoints require `X-API-Key` header when `PFCD_API_KEY` env var is set. `/health` is always public. Uses `secrets.compare_digest` (timing-safe). Implemented in `auth.py`.

---

## Coding Guidelines (Karpathy Principles)

These apply to all agents working in this repo:

1. **Think before coding** — state assumptions explicitly; if multiple interpretations exist, surface them rather than picking silently; ask when unclear.
2. **Simplicity first** — minimum code that solves the problem; no speculative features, abstractions for single use, or error handling for impossible scenarios.
3. **Surgical changes** — touch only what the task requires; don't improve adjacent code; match existing style; remove only imports/variables made unused by *your* changes.
4. **Goal-driven execution** — define verifiable success criteria before acting; for multi-step tasks, state a brief plan with a per-step verification check.

---

## Code Conventions

- **Python indent:** 4 spaces
- **Classes:** `PascalCase` | **functions/vars:** `snake_case` | **constants:** `UPPER_SNAKE_CASE` | **private helpers:** `_leading_underscore`
- **Enums:** `PascalCase` class, `UPPER_CASE` members (e.g., `JobStatus.QUEUED`)
- **Timestamps:** `datetime.now(timezone.utc).isoformat()`
- **IDs:** `str(uuid4())`
- **HTTP errors:** `HTTPException` with 400/409/410/413/503 — no error handling for impossible scenarios

---

## Commit Style

```
feat: add transcript alignment engine
fix: correct phase retry counter reset
docs: update API endpoint table in REFERENCE.md
refactor: extract evidence scoring to separate module
chore: bump SQLAlchemy to 2.0.38
```

## PR Review Checklist (for Claude's review role)

- Does the change comply with the PRD section it claims to address?
- Does it route all DB access through `JobRepository`?
- Does it respect the evidence hierarchy for extraction/review changes?
- Are new env vars documented in `REFERENCE.md`?
- Do tests cover the failure path, not just the happy path?
- Are Azure SDK clients using `DefaultAzureCredential` (no hardcoded keys)?

---

## Current Implementation Status (as of 2026-04-17)

**Done:**
- FastAPI endpoints and job lifecycle API
- SQL schema and Alembic migration (8 migrations: init + enum + review + datetime)
- Job state machine (QUEUED → COMPLETED/FAILED)
- Service Bus message queuing and three-worker framework
- Blob/local export storage abstraction
- Azure infrastructure bootstrap script (`infra/dev-bootstrap.sh`)
- TTL/cleanup worker
- Static API key authentication (timing-safe)
- Real agent logic: extraction + processing (SK + `DefaultAzureCredential`)
- Transcript/video anchor alignment engine (`alignment.py`)
- Evidence strength computation (`evidence.py`)
- Worker App Service deployment workflow (`deploy-workers.yml` — parallel)
- `IProcessEvidenceAdapter` + `TranscriptAdapter` (VTT/TXT) + `VideoAdapter` (metadata stub) + `AdapterRegistry`
- SIPOC schema validation (`sipoc_validator.py`)
- Evidence-linked PDF/DOCX/Markdown exports (`export_builder.py`)
- CI test gate in `deploy-backend.yml` (`test` job gates `deploy`)
- Azure end-to-end deployment validated: all four App Services live (pfcd-dev-api + 3 workers)
- Deployment pipeline hardening (Section 13)
- Section 14 C/H pass: `/dev/simulate` auth, async finalize, AgentRun lifecycle, DefaultAzureCredential storage, SK kernel caching, SB sender reuse, cost tracking + cap warn, deployment-aware pricing, profile-specific deployment vars
- SK runtime hardening: canonical `AZURE_OPENAI_CHAT_DEPLOYMENT_NAME`, api_version pinned, safe usage parsing, fail-fast on missing deployment
- **Phase 6 — Frontend Integration (reviewed 2026-04-13, 264 tests passing):**
  - `api.js` `_fetch` + `uploadFile` send `X-API-Key` header from `VITE_API_KEY`
  - `saveDraft` called before `finalizeJob` — fixes the `user_saved_draft` 409 gate
  - `GET /api/jobs` endpoint + `JobRepository.list_jobs()` — lightweight, deleted-excluded, most recent first
  - `JobList.jsx` — history table with status badges, source chips, click-to-navigate by status
  - `App.jsx` defaults to list view; `onSelectJob` routes to review/exports/status by job state
  - `ExportLinks.jsx` switched to `downloadExport` (programmatic via `_fetch`) — auth header on downloads
  - `vite.config.js` `/dev` proxy added — dev simulate button now works locally
  - `VITE_API_KEY` documented in `REFERENCE.md`
- Section 14 M/L pass (reviewed 2026-04-12, 231 tests passing):
  - Timestamp columns → `DateTime(timezone=True)` (M1)
  - Canonical `anchor_utils.classify_anchor()` shared by all three callers (M2)
  - `_transcript_text_inline` ephemeral field documented + popped before persistence (M3)
  - Draft upsert-by-composite-PK preserving audit timestamps (M4)
  - Stub draft detection: `draft_source:"stub"` + BLOCKER flag in reviewing agent (M5)
  - `_utc_now()` consolidated; `servicebus._utc_now_dt()` renamed (L1)
  - Workers use canonical `AZURE_OPENAI_CHAT_DEPLOYMENT_NAME` (L2)
  - Speaker heuristic tightened: VTT tag preference, 25-char cap, numeric-start rejection, prefix filter (L3)
  - `/dev/simulate` no longer sets `user_saved_draft=True`; 409 path exercisable (L4)
  - Dead code removed: `_cost_usd()`, `_DEPLOYMENT` vars (DC1)

**Assigned to Codex:** See `HANDOVER.md` for current assignments, in-progress work, and review queue.

**Deployment note (fully resolved as of 2026-04-17):**
- `WEBSITE_RUN_FROM_PACKAGE` pattern now active for both backend (`deploy-backend.yml`) and all three workers (`deploy-workers.yml`)
- Both workflows upload a zip to the `scratch` blob container, generate a SAS URL, and apply `WEBSITE_RUN_FROM_PACKAGE` via `az webapp config appsettings set`
- No Kudu OneDeploy dependency remains; `azure/webapps-deploy@v3` removed from both workflows
- RBAC: `pfcd-dev-api-gha` has `Storage Blob Data Contributor`; all App Service identities have `Storage Blob Data Reader` on `pfcddevstorage`

**Deployment review follow-up (2026-04-17):**
- Backend deploy is not fully resolved: `deploy-backend.yml` currently validates `DATABASE_URL` and `AZURE_SERVICE_BUS_CONNECTION_STRING` as GitHub secrets even though `infra/dev-bootstrap.sh` provisions them as Key Vault-backed App Service settings; latest backend run `24559639332` failed before rollout on this mismatch.
- Worker deploy is not yet fully hardened: `deploy-workers.yml` ships a source-only zip under `WEBSITE_RUN_FROM_PACKAGE`, unlike backend which vendors dependencies into `antenv`; this leaves worker startup sensitive to host/runtime drift on Azure App Service.

**Active Codex task queue:** Queue is empty. Phase 7 (PRD gap closure) complete at 273 tests (reviewed 2026-04-13):
- `DRAFT-EDIT`: editable PDD/SIPOC + re-review on save ✓
- `SPEAKER-RESOLVE`: speaker resolution UI + extraction speaker hint ✓
- `FRAME-PERSIST`: frame upload to evidence container + export bundle ✓
Remaining PRD gaps: OCR execution (§8.1/§8.6), `confidence_delta` population (§8.11), Application Insights (§8.4).

**Architecture decision (2026-04-13):**
- Provider scope: Azure OpenAI + direct OpenAI only. Google/Gemini dropped.
- Rationale: individual Azure account cannot provision latest models (gpt-4o, gpt-4.1); direct OpenAI provides identical models without quota constraints. Same SK connector family — no prompt or schema changes.
- Azure remains the deployment/storage/orchestration platform; provider flexibility is LLM call path only.

**Architecture gaps (non-blocking):**
- `VideoAdapter` Whisper transcription limited to 25 MB until MediaPreprocessor (Phase 5) is built
- Full frame extraction (ffmpeg keyframes → multimodal LLM) pending MediaPreprocessor
- Frontend (`frontend/`) is present but not yet integrated with the backend pipeline
- Service Bus sender auto-reconnect on stale AMQP link (optional enhancement)
