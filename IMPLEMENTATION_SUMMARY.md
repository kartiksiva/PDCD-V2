# PFCD-V2 Implementation Log

Rolling summary of major deliveries. Append new sections as phases complete.

---

## Section 1: Infrastructure (2026-03-21 to 2026-04-01)

Implemented Azure dev environment provisioning via `infra/dev-bootstrap.sh`.

**Completed:**
- Idempotent bootstrap script for resource group `app-pfcd-v2`
- Storage account with containers: `uploads`, `evidence`, `exports`, `scratch`
- Service Bus namespace + queues (`extracting`, `processing`, `reviewing`)
- Key Vault + required secrets (RBAC mode, `Key Vault Secrets Officer`)
- SQL Server + SQL Database
- App Service Plan + Linux Web App (Python 3.11)
- Azure OpenAI account + Azure Speech account
- Dev metadata tags: `Environment=dev`, `Project=pfcd`, `CostProfile=development`
- App settings wired for storage, service bus, key vault, SQL, OpenAI, Speech
- `infra/README.md` updated with verification commands and caveats

**Known gaps at close:**
- OpenAI deployment requires a region-supported model/version on rerun
- Azure budget creation blocked by CLI preview mismatch; must be done via portal

---

## Section 2: Backend Skeleton (2026-04-01)

Implemented full API surface, state machine, database schema, workers, auth, and cleanup.

**Completed:**
- FastAPI application (`main.py`) with all `/api/*` endpoints and health check
- Job state machine (`job_logic.py`): `QUEUED → PROCESSING → NEEDS_REVIEW → FINALIZING → COMPLETED/FAILED`
- SQLAlchemy ORM (`models.py`) and Alembic migration (`20260401_0001_init.py`) creating all 7 tables
- `JobRepository` persistence layer — all DB reads/writes via `session_scope`
- Service Bus orchestration (`servicebus.py`): `build_message()`, phase dispatch
- Blob/local export storage abstraction (`storage.py`)
- PDF and Markdown export (basic, no evidence links yet)
- Service Bus worker loop (`workers/runner.py`): extracting/processing/reviewing phase handlers
- TTL/cleanup worker (`workers/cleanup.py`): expiry scan + data purge
- Static API key auth (`auth.py`): `X-API-Key` header, 401/403, `secrets.compare_digest`
- GitHub Actions CI/CD (`deploy-backend.yml`): zip deploy to App Service on `backend/**` push
- Unit tests: 45 passing (test_repository, test_worker, test_cleanup, test_auth)

---

## Section 3: Agent Layer (2026-04-05)

Implemented real LLM-backed agents, anchor alignment, evidence strength computation, and parallel worker deployment.

### Semantic Kernel Migration

- Replaced `openai` SDK with `semantic-kernel>=1.41.1`
- `kernel_factory.py`: builds SK `Kernel` using `DefaultAzureCredential` + `AzureChatCompletion` (from `semantic_kernel.connectors.ai.open_ai`)
- `extraction.py`: `_call_extraction` (async SK invocation) + `run_extraction` synchronous wrapper via `asyncio.run`
- `processing.py`: `_call_processing` (async SK invocation) + `run_processing` synchronous wrapper via `asyncio.run`
- `reviewing.py`: pure-Python reviewing agent (no LLM call; deterministic quality-gate logic)
- `openai_client.py`: retained for reference only; unused in production path

### Anchor Alignment Engine (`alignment.py`)

- `run_anchor_alignment(job)` validates VTT cue timestamps against section-label anchors produced by extraction (takes the full job dict)
- VTT cue parsing with 2-second tolerance window for timestamp matching
- Confidence penalty applied per-item when anchor validation fails; mutates `evidence_items[].confidence` in-place
- Computes `similarity_score` and `verdict` from valid-anchor ratio in the first 60-second window (PRD §8.5 "first N seconds" scope); writes both to `transcript_media_consistency` when media is present
- `anchor_alignment_summary` includes: `{validated, invalid, section_label, skipped, verdict, similarity_score, window_sec, window_anchors_checked, consistency_method}`
- Full token/sequence similarity (PRD §8.5) requires Azure Speech — see module docstring for upgrade path

### Evidence Strength Computation (`evidence.py`)

- `compute_evidence_strength(has_video, has_audio, has_transcript, evidence_items)` implements PRD §7 source hierarchy:
  - `has_video + has_audio` → `"high"` (Priority 1 — with or without transcript)
  - `has_video + has_transcript` (no audio) → `"medium"` (Priority 2)
  - `has_transcript` only (no video, no audio) → `"medium"` (Priority 3)
  - all other cases (video only, audio only, or no sources) → `"low"` (Priority 4)
- Confidence degradation: mean confidence < 0.60 downgrades strength by one tier (high→medium, medium→low)
- `evidence_strength` initial sentinel in `default_job_payload()` is `None` to distinguish uncomputed from computed-medium

### Worker Deployment Workflow (`deploy-workers.yml`)

- Triggers on push to `main` with changes under `backend/**`
- Builds a single zip artifact once, then deploys in parallel to three App Service instances:
  - `pfcd-dev-worker-extracting`
  - `pfcd-dev-worker-processing`
  - `pfcd-dev-worker-reviewing`
- Required secrets: `AZURE_CREDENTIALS`, `AZURE_RESOURCE_GROUP`, `AZURE_WORKER_EXTRACTING_NAME`, `AZURE_WORKER_PROCESSING_NAME`, `AZURE_WORKER_REVIEWING_NAME`

### Test Coverage

- `tests/unit/test_agents.py` added: 61 tests covering extraction, processing, reviewing, alignment, and evidence modules
- Total passing: 61 (up from 45 at skeleton close)

---

---

## Section 4: Adapter Pattern + SIPOC Validation (2026-04-05)

Implemented `IProcessEvidenceAdapter` contract, `VideoAdapter`, `TranscriptAdapter`, `AdapterRegistry`, and full SIPOC schema validation.

### IProcessEvidenceAdapter (`adapters/`)

- Abstract base class with 4-method contract: `detect()`, `normalize()`, `extract_facts()`, `render_review_notes()`
- `EvidenceObject`, `DetectionResult`, `FactItem`, `DocumentTypeManifest` dataclasses in `base.py`
- `TranscriptAdapter` (VTT + TXT):
  - `detect()`: validates source_type, MIME type, and file extension
  - `normalize()`: strips WEBVTT headers, cue numbers, converts to `[HH:MM:SS-HH:MM:SS] content` inline-anchor format; plain text uses section labels as anchors
  - `extract_facts()`: one `FactItem` per VTT cue with speaker extraction
  - `render_review_notes()`: anchor count, format, confidence notes
- `VideoAdapter`:
  - `detect()`: validates source_type, classifies audio_detected → confidence 0.75 (audio) / 0.45 (no audio)
  - `normalize()`: builds metadata content string from frame_extraction_policy, duration, audio flag — honest stub pending Azure Vision/Speech
  - `extract_facts()`: stub (returns empty; future Azure Vision call)
  - `render_review_notes()`: audio flag, frame policy, pending integration note
- `AdapterRegistry`: maps source_type → adapter; `get_adapters()` returns adapters in transcript-first precedence order; unknown types silently skipped

### Extraction agent integration

- `_normalize_input(job)` uses `AdapterRegistry.get_adapters(source_types)` to normalize input before SK call
- TranscriptAdapter content drives LLM extraction; VideoAdapter contributes `document_type_manifests` only (pending Azure Vision)
- `job["document_type_manifests"]` set on all paths (including graceful degradation)
- VTT text passed to extraction LLM is now cleaned (no WEBVTT headers, inline anchor markers preserved)

### SIPOC Validation (`sipoc_validator.py`)

Full PRD §8.8 + §10 quality gate replacing the prior single-anchor existence check:
- `validate_sipoc(sipoc, pdd_steps) -> SIPOCValidationResult`
- Per-row checks: all 5 required fields (`supplier`, `input`, `process_step`, `output`, `customer`)
- `step_anchor` cross-reference against PDD step IDs — emits `sipoc_invalid_step_ref` warning for unknown IDs
- `source_anchor` classification: `timestamp_range`, `section_label`, `frame_id`, `missing`
- `frame_id` anchors emit `sipoc_frame_id_only` warning (fallback path flag)
- Missing anchors without `anchor_missing_reason` emit `sipoc_missing_reason_absent` warning
- Quality gate (PRD §10): `sipoc_no_anchor` blocker if no row has both step_anchor + source_anchor
- `SIPOCRowResult` dataclass for per-row detail; `SIPOCValidationResult` aggregates counts and flags
- Reviewing agent now calls `validate_sipoc` directly — flags merged into `review_notes.flags`

### Test Coverage

- `tests/unit/test_adapters.py`: 36 tests covering TranscriptAdapter, VideoAdapter, AdapterRegistry, and extraction integration
- `tests/unit/test_sipoc_validator.py`: 21 tests covering quality gate, required fields, step_anchor cross-ref, anchor classification, missing-reason rules, and reviewing agent integration
- Total passing: 118 (up from 61 at agent layer close)

---

## Section 5: Evidence-Linked Exports (2026-04-06)

Implemented PRD §8.10 evidence-linked PDF, DOCX, and Markdown export rendering.

### `export_builder.py`

New module replacing the inline `_build_export_pdf` / `_build_export_markdown` functions in `main.py`.

- **`build_evidence_bundle(finalized_draft, job)`**: builds the evidence bundle manifest
  - Collects anchors from all PDD step `source_anchors[]` entries and SIPOC row `source_anchor` fields
  - Classifies each anchor: `timestamp_range`, `frame_id`, `section_label`, `missing`
  - PRD §8.10 filter: only anchors linked to ≥1 PDD step or SIPOC row are included
  - Deduplicates by anchor value; merged entries accumulate all linked step IDs
  - Attaches OCR snippets from `job.extracted_evidence.evidence_items` when anchor matches
  - Carries `evidence_strength` from `job.agent_signals` and `frame_policy` from `input_manifest`
  - `frame_captures_note`: honest stub note pending Azure Vision integration
- **`build_export_markdown(draft, bundle)`**: enhanced Markdown with evidence bundle section (anchor table with type, confidence, linked steps, OCR snippet)
- **`build_export_pdf(draft, bundle)`**: enhanced PDF with Evidence Bundle section listing all linked anchors, types, confidence, and OCR snippets
- **`build_export_docx(draft, bundle, job_id)`**: real DOCX using `python-docx==1.1.2` — SIPOC table + Evidence Bundle table

### `main.py` changes

- Removed inline `_build_export_pdf` / `_build_export_markdown`; both `fpdf` import and old functions gone
- `finalize_job`: calls `build_evidence_bundle(finalized_draft, job)` and passes bundle to all export builders
- `get_export` fallback path: builds bundle on-the-fly for regenerated exports
- DOCX content-type updated from `text/plain` to correct `application/vnd.openxmlformats-officedocument.wordprocessingml.document`
- JSON export `exports_manifest.evidence_bundle` now populated with the real bundle dict

### Dependencies

- `python-docx==1.1.2` added to `requirements.txt`

### Test Coverage

- `tests/unit/test_export_builder.py`: 44 tests covering `_classify_anchor_type`, `build_evidence_bundle` (PRD §8.10 filter, dedup, OCR attachment, step/SIPOC linking), and all three export format builders
- `tests/unit/test_worker.py`: 5 existing export tests updated to import from `export_builder`
- Total passing: 162 (up from 118 at Section 4 close)

---

## Section 6: Integration Tests + CI Gate (2026-04-06)

Added a complete integration test suite exercising the real job lifecycle through the FastAPI layer with a real SQLite DB and no Azure services.

### Test Infrastructure

- `pytest.ini` (repo root): `testpaths = tests`, `unit`/`integration` markers registered.
- `tests/conftest.py`: shared fixtures — `AppContext` NamedTuple, `app_client`, `app_client_with_auth`, `seeded_needs_review_job`, `seeded_completed_job`.
- Module reload pattern: `importlib.reload(app.db)` → `app.repository` → `app.main` per fixture; each test gets a fresh `tmp_path` SQLite file. `ORCHESTRATOR` is replaced with `MagicMock()` after reload so `enqueue()` is never called against Azure. `ExportStorage` uses local filesystem (`EXPORTS_BASE_PATH=tmp_path/exports`).

### Integration Test Files (`tests/integration/`)

- **`test_lifecycle.py`** (14 tests): create, get, simulate, get draft, update draft, finalize (idempotency), delete, finalize-after-delete.
- **`test_auth_enforcement.py`** (13 tests): 401/403 on missing/wrong key, correct key passes, auth-disabled path, /health and /dev/simulate exempt, parametrized coverage of all 6 protected endpoints.
- **`test_error_cases.py`** (8 tests): draft endpoints on wrong state → 409, finalize without user_saved_draft → 409, finalize with injected BLOCKER flag → 409 (PRD §10 gate), export before finalize → 409, invalid export format → 400, simulate missing job → 404, upload oversize file → 413.
- **`test_exports.py`** (8 tests): JSON fields present, Markdown has `#` heading, PDF `%PDF` magic + Content-Disposition, DOCX `PK` ZIP + openxmlformats content-type, all 4 formats 200, evidence bundle linked_anchors non-empty, scenario-a happy path, transcript-only fallback.

### CI Gate

`deploy-backend.yml` updated: new `test` job runs before `deploy` (via `needs: test`). Installs `unixodbc-dev` system dep for pyodbc build on Ubuntu, then `pytest tests/unit tests/integration -x --tb=short` with `PYTHONPATH=backend` and `DATABASE_URL=sqlite:///./test-ci.db`.

### Test Coverage

- 43 integration tests passing.
- Total: 162 unit + 43 integration = 205 tests in the suite.

---

## Section 7: Bug-Fix Pass (2026-04-07)

Resolved issues from Codex + Gemini review. No new features — all changes are corrections to existing behaviour.

### OCR Anchor Field Mismatch (`export_builder.py`)

- `build_evidence_bundle` was looking up OCR snippets via `item.get("source_anchor")` but the extraction schema stores the field as `anchor`.
- Fixed to `item.get("anchor") or item.get("source_anchor")` — prefers the real extraction field, falls back for compatibility.
- Updated `test_export_builder.py` fixture to use `anchor`, so the test now exercises the actual extraction code path.

### Alignment Verdict + Consistency Scoring (`alignment.py`, `job_logic.py`)

- Default seed in `default_job_payload()` changed from conditional `"match"` (for video+transcript) to unconditional `"inconclusive"`. Verdict is now computed by `run_anchor_alignment`.
- **First-N-seconds scope (PRD §8.5):** `_consistency_score_from_anchors` filters evidence items to those whose timestamp anchors start within `CONSISTENCY_WINDOW_SEC` (60 s), falling back to full-corpus if no items fall in the window. This implements the "first N seconds" scoping specified by the PRD.
- **`similarity_score`** (float 0.0–1.0 or `None`) is now computed and written to `transcript_media_consistency.similarity_score`. Thresholds: `≥0.8 → match`, `0.5–0.8 → inconclusive`, `<0.5 → suspected_mismatch`. `None` when no timestamp anchors exist (section-label-only transcripts).
- `anchor_alignment_summary` now includes: `verdict`, `similarity_score`, `window_sec`, `window_anchors_checked`, `consistency_method`.
- **Known limitation:** `consistency_method` is `"anchor_validity_proxy"`. Full PRD §8.5 token/sequence similarity against audio-derived text requires Azure Speech transcription of the video — blocked until VideoAdapter Azure Vision/Speech integration is complete. The module docstring documents the upgrade path.
- Verdict and `similarity_score` are written to `transcript_media_consistency` **only when `has_video or has_audio`** — transcript-only jobs leave the field as `"inconclusive"` (PRD §8.5 scope guard).

### Reviewing Agent Transcript-Mismatch Guard (`reviewing.py`)

- The `transcript_mismatch` flag now requires `(has_video or has_audio) and has_transcript` before checking `verdict == "suspected_mismatch"`.
- Prevents spurious "inconsistent with video/audio source" warnings on transcript-only jobs regardless of what the alignment engine writes.

### Runner `approve_for_draft` Dead Code (`workers/runner.py`)

- Both branches of the reviewing-phase if/else were setting `JobStatus.NEEDS_REVIEW` — the condition was dead code.
- Collapsed to a single unconditional `NEEDS_REVIEW` assignment with a comment explaining the design: `agent_review.decision` (`approve_for_draft` / `needs_review` / `blocked`) is the differentiator the UI should use, not job status.

### AgentRun Incremental Insert (`repository.py`)

- `upsert_job` was deleting all `agent_runs` rows then re-inserting the full in-memory list on every call, risking audit trail loss on a crash between delete and insert.
- Changed to insert-only-if-new: loads existing `agent_run_id`s from DB once, skips any already-persisted runs. The in-memory set is updated after each insert to guard against duplicate IDs within the same payload.

### Documentation Corrections (`IMPLEMENTATION_SUMMARY.md`, `REFERENCE.md`)

- Corrected alignment function signature (`run_anchor_alignment(job)`, not `(manifest, extraction_result)`).
- Corrected alignment output description (emits count summary, not verdict values — verdict now correctly described after the above fix).
- Corrected evidence-strength tier table: `transcript_only → medium`, `audio_only / video_only / no_sources → low`.
- Corrected `AzureOpenAIChatCompletion` → `AzureChatCompletion` (actual import in `kernel_factory.py`).
- Updated `REFERENCE.md`: frontend is active (not placeholder), `/health` can return 503 with env diagnostics, test directory layout reflects integration tests and `test_export_builder.py`.

### Test Coverage

- 205 tests (162 unit + 43 integration) — all passing after fixes.

---

## Section 8: Azure End-to-End Deployment (2026-04-07)

Validated full Azure deployment. All four App Services are running and the job pipeline is live. A series of infrastructure bugs were found and fixed during the first real end-to-end run.

### Worker Deploy 504 GatewayTimeout (`deploy-workers.yml`)

- `az webapp deploy` without `--async true` blocks until Kudu finishes zip extraction — times out at 504 on lower-tier plans.
- Fixed: added `--async true` to all three worker deploy steps.
- Added a post-deploy verify step per worker: waits 60 s then checks `az webapp show --query state=Running`; fails the job if the background extraction left the app in a bad state.

### Backend Deploy Failure — `semantic-kernel` Pre-Release Dep (`requirements.txt`)

- `semantic-kernel>=1.41.1` requires `azure-ai-agents>=1.2.0b3` (a pre-release). Kudu uses `uv` which rejects transitive pre-release deps by default → deploy failed with "requirements are unsatisfiable".
- Fixed: explicitly added `azure-ai-agents>=1.2.0b3` to `requirements.txt`. `uv` allows pre-releases for packages listed as explicit requirements.

### Worker ContainerTimeout — No HTTP Server (`workers/runner.py`)

- Azure App Service probes containers with an HTTP warmup request and kills them after 230 s if no 200 is returned. Workers run `python -m app.workers.runner` (a Service Bus consumer loop) with no HTTP server → crash loop (`ContainerTimeout`).
- Fixed: added `_start_health_server()` to `runner.py`. Starts a minimal `http.server.HTTPServer` on port 8000 in a daemon thread before the Service Bus loop. Responds 200 to all GET requests. Warmup probe succeeds; container stays alive.

### Wrong Azure OpenAI Endpoint (`AZURE_OPENAI_ENDPOINT`)

- `pfcd-dev-oai` has no custom subdomain (`customSubDomainName: null`), so the correct endpoint is `https://southindia.api.cognitive.microsoft.com/` — not the assumed `https://pfcd-dev-oai.openai.azure.com/` format.
- Fixed: updated the setting on all four App Services via `az webapp config appsettings set`.
- Added `AZURE_OPENAI_ENDPOINT` and `AZURE_OPENAI_DEPLOYMENT_NAME` to `deploy-workers.yml` (sourced from GitHub secrets `AZURE_OPENAI_ENDPOINT` and `AZURE_OPENAI_DEPLOYMENT_NAME`) so they are set automatically on every deploy.

### Missing OpenAI RBAC (`Cognitive Services OpenAI User`)

- All four App Services have system-assigned managed identities and `Key Vault Secrets User` on `pfcd-dev-kv` (pre-existing).
- `Cognitive Services OpenAI User` role was missing on `pfcd-dev-oai` → `DefaultAzureCredential` token acquisition would fail when agents call the LLM.
- Fixed: assigned `Cognitive Services OpenAI User` to all four managed identity principal IDs on the `pfcd-dev-oai` resource via `az role assignment create`.

### Required GitHub Secrets for Workers

The following secrets must be set in the repo (Settings → Secrets → Actions) for `deploy-workers.yml` to configure workers correctly:

| Secret | Value |
|--------|-------|
| `AZURE_OPENAI_ENDPOINT` | `https://pfcd-dev-oai.openai.azure.com/` ← updated 2026-04-08 (see Section 9) |
| `AZURE_OPENAI_DEPLOYMENT_NAME` | `gpt-4o-mini` |
| `AZURE_WORKER_EXTRACTING_NAME` | `pfcd-dev-worker-extracting` |
| `AZURE_WORKER_PROCESSING_NAME` | `pfcd-dev-worker-processing` |
| `AZURE_WORKER_REVIEWING_NAME` | `pfcd-dev-worker-reviewing` |
| `AZURE_RESOURCE_GROUP` | `app-pfcd-v2` |
| `AZURE_CREDENTIALS` | service principal JSON |

---

## Section 9: Live Pipeline Debugging (2026-04-08)

End-to-end test with a real uploaded file exposed three bugs blocking job progression. All three are now fixed; the processing worker resilience fix (`ff40258`) is deployed. The pipeline is partially working — extracting phase completes, but the processing worker has an open issue (see Current Problem below).

### Key files to read for context

| File | Purpose |
|------|---------|
| `CLAUDE.md` | Conventions, state machine, current implementation status |
| `IMPLEMENTATION_SUMMARY.md` | This file — rolling log of what has been built |
| `prd.md` | Authoritative product requirements |
| `REFERENCE.md` | File layout, env vars, Azure resource names, API endpoints |
| `backend/app/workers/runner.py` | Worker entry point — health server + Service Bus receive loop |
| `.github/workflows/deploy-workers.yml` | Worker deployment workflow |
| `backend/app/agents/kernel_factory.py` | How SK + AzureChatCompletion is initialised |

---

### Bug 1: Worker boot loop — ContainerTimeout (FIXED, commit `9469000`)

**Symptom:** All three workers restart every ~230 s; no messages consumed.

**Root cause:** Azure App Service default warmup probe timeout is 230 s. The full startup path takes ~224 s:
- Cert updates: ~72 s
- Oryx decompresses `output.tar.zst`: ~98 s
- Python module imports (semantic-kernel, azure.servicebus, SQLAlchemy): ~26 s
- Health server starts responding: ~224 s elapsed

`_start_health_server()` is called as the first statement in `run()`, but `run()` is only invoked after all module-level imports complete (lines 15–22 of `runner.py` pull the full agent/SK import graph). The health server is correct; the probe window is just too tight.

**Fix:** `WEBSITES_CONTAINER_START_TIME_LIMIT=600` set on all three workers via `az webapp config appsettings set` (live). Added to `deploy-workers.yml` so it survives future deployments.

---

### Bug 2: Azure OpenAI 404 — wrong endpoint (FIXED)

**Symptom:** Processing agent calls fail with `404 Resource not found` from `AzureChatCompletion`.

**Root cause:** `AZURE_OPENAI_ENDPOINT` was set to `https://southindia.api.cognitive.microsoft.com/` (the generic regional cognitive services URL). The `pfcd-dev-oai` resource had no custom subdomain, so calls to that URL return 404. The regional endpoint does not route to a specific OpenAI resource.

**Fix:**
1. Added custom subdomain to `pfcd-dev-oai` via `az cognitiveservices account update --custom-domain pfcd-dev-oai` → resource endpoint is now `https://pfcd-dev-oai.openai.azure.com/`.
2. Updated `AZURE_OPENAI_ENDPOINT` app setting on all four App Services (3 workers + API) to `https://pfcd-dev-oai.openai.azure.com/`.
3. GitHub secret `AZURE_OPENAI_ENDPOINT` updated by user to match.

---

### Bug 3: Worker crash on transient Service Bus DNS failure (FIXED, commit `ff40258`)

**Symptom:** Processing worker starts, logs "Worker listening on phase processing", then crashes ~90 s later:
```
ServiceBusConnectionError: Failed to initiate the connection due to exception:
failed to resolve broker hostname  Error condition: amqp:socket-error
```
Crash restarts the process; the same DNS blip can hit again, creating a crash loop.

**Root cause:** `receive_messages()` in the `while True` loop was not wrapped in try/except. A `ServiceBusConnectionError` propagates up through `run()` and kills the Python process. The SDK's internal retry (up to its own timeout) gives up after ~90 s; after that the exception escapes.

**Fix (`runner.py`):** Wrap `receive_messages()` in:
```python
try:
    messages = receiver.receive_messages(max_message_count=1, max_wait_time=5)
except SBConnectionError as exc:
    logger.warning("Service Bus connection error; will retry in 10s: %s", exc)
    time.sleep(10)
    continue
```
The process now survives transient DNS blips and retries after 10 s.

**Status:** Committed and pushed (`ff40258`). `deploy-workers.yml` triggered. Deployment in progress as of 2026-04-08.

---

### Current Problem (OPEN as of 2026-04-08)

**Job `83ff7e57-457d-4954-9a90-f3fc61b2ad01` is stuck at status `processing`, `current_phase: extracting`, `last_completed_phase: extracting`.**

- Extracting phase: **completed** (agent_runs shows one `success` entry).
- Processing queue: **2 active messages** (1 original + 1 retry enqueued by a failed attempt).
- Processing worker: currently booting after a crash caused by Bug 3 (DNS error). Running the old code (pre-`ff40258`).
- Once the `ff40258` deploy completes and the processing worker picks up the message, the job should progress to `current_phase: processing`.

**What to verify next:**
1. Processing worker runtime log shows `"Health server listening on port 8000"` followed by `"Worker listening on phase processing"` — confirms new code is deployed and worker is stable.
2. Processing queue active count drops from 2 → 0.
3. Job status advances to `processing` → `needs_review`.
4. If the processing agent call still fails, check for errors in the processing worker runtime log. The most likely remaining cause would be an RBAC issue (`Cognitive Services OpenAI User` on `pfcd-dev-oai`) or a Semantic Kernel API version mismatch.

**If the processing worker still crashes after the `ff40258` deploy:** the DNS resolution failure may be persistent rather than transient — investigate the App Service VNet/DNS configuration or consider moving workers to Azure Container Apps (which has better networking for long-running consumers).

---

## Section 10: Worker Reconnect Hardening + Deploy Runtime Guards (2026-04-08)

Implemented follow-up hardening to prevent workers from stalling on repeated Service Bus link failures, plus deploy-time runtime verification to ensure workers really enter their receive loops.

### Worker receive-loop resilience (`backend/app/workers/runner.py`)

- Added `_connection_backoff_seconds(consecutive_errors)`:
  - bounded exponential backoff (caps at 60 s)
  - + small random jitter
- Refactored `run()` into an outer reconnect loop:
  - `with worker.orchestrator.receive(phase)` now reopens after connection failures
  - `SBConnectionError` during `receive_messages()` no longer just sleeps on the same receiver; it breaks inner loop and recreates receiver
  - `SBConnectionError` during receiver setup is also caught with the same backoff path
- Added reconnection log markers:
  - `"Service Bus receiver reconnected for phase ..."`
  - warnings include phase + consecutive error count + next delay

### Unit tests (`tests/unit/test_worker.py`)

- Added `test_run_recreates_receiver_after_servicebus_error`:
  - simulates one `ServiceBusConnectionError`
  - verifies `run()` reopens receiver context (2 receive calls) rather than crashing
- Added `test_connection_backoff_seconds_is_bounded`:
  - validates backoff progression and 60 s cap behavior

### Worker deployment guardrails (`.github/workflows/deploy-workers.yml`)

- Added post-deploy runtime log checks for all three workers:
  - downloads App Service logs (`az webapp log download`)
  - fails deploy if logs do not contain:
    - `"Health server listening on port 8000"`
    - `"Worker listening on phase <role>"`
- Existing app state check (`state == Running`) remains; runtime log checks are an additional guard.

### Operational impact for current incident

- This hardening does not mutate job state directly, but reduces probability of processing worker stalls during DNS/network blips.
- For job `83ff7e57-457d-4954-9a90-f3fc61b2ad01`, expected recovery signal remains:
  - processing queue active count drops to 0
  - job transitions from `extracting` completion toward `needs_review` once processing/reviewing phases consume pending messages.
