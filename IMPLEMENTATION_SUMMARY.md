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

## Section 8: Provider Flex + Video Transcription + Real Similarity (2026-04-13)

Implemented the full Codex handoff chain: prompt anchoring fix, provider routing flexibility, Whisper-backed video transcription, and transcript/media text similarity.

### Processing Prompt Anchors

- `processing.py` SIPOC schema now uses concrete anchor examples instead of abstract placeholders.
- Prompt rules now explicitly require non-empty `step_anchor`, verbatim non-empty `source_anchor`, and correct `anchor_missing_reason` behavior.
- Added unit coverage asserting all mocked SIPOC rows contain anchors so prompt regressions hit tests before review-time quality gates.

### Provider Routing

- `kernel_factory.py` now supports both `azure_openai` (default) and direct `openai` via `PFCD_PROVIDER`.
- Added `get_chat_service(deployment)` so extraction/processing no longer hard-code Azure service lookup.
- `job_logic.py` now resolves provider-specific chat models and writes the active provider into `provider_effective`.
- `REFERENCE.md` env var table now documents `PFCD_PROVIDER`, direct OpenAI chat model vars, Whisper deployment/model vars, and the new transcription helper module.

### Video Transcription + Extraction Input

- Added `agents/transcription.py` with synchronous Whisper helpers for Azure OpenAI and direct OpenAI.
- `VideoAdapter.normalize()` now upgrades to real VTT content when `storage_key` is available and transcription succeeds; it also writes `_video_transcript_inline` as an ephemeral worker-only field and derives timestamp anchors from VTT cues.
- Extraction input normalization now supports:
  - uploaded transcript only
  - video transcript only
  - combined video transcript + uploaded transcript with explicit labels for cross-reference
- Worker extracting-phase cleanup now removes `_video_transcript_inline` anywhere `_transcript_text_inline` was already being dropped.

### Alignment Similarity

- `alignment.py` keeps the existing anchor-validity proxy as fallback.
- Added normalized text similarity helpers using token overlap + `SequenceMatcher`.
- When both uploaded transcript text and video transcript text are present, `run_anchor_alignment(job)` now overwrites the fallback score with real text similarity and records `consistency_method="text_similarity"`.

### Validation

- Added/updated unit coverage in:
  - `test_agents.py`
  - `test_adapters.py`
  - `test_job_logic.py`
  - `test_kernel_factory.py`
  - `test_worker.py`
- Validation run:
  - `cd backend && .venv/bin/pytest ../tests/unit/test_kernel_factory.py ../tests/unit/test_job_logic.py -v`
  - `cd backend && .venv/bin/pytest ../tests/unit/test_agents.py ../tests/unit/test_adapters.py -v`
  - `cd backend && .venv/bin/pytest ../tests/ -q`
- Result: 243 tests passed.

### Decisions / Notes

- Provider selection is resolved from environment at call time instead of module import time so tests and runtime overrides behave predictably.
- The extracting worker test now stubs `run_extraction` directly; it no longer relies on missing Azure env vars to avoid entering the chat path.
- No migration or review-gate logic changes were made beyond the prompt/schema tightening requested in the handoff.

---

## Section 9: Review Cleanup L1/L2/L3 (2026-04-13)

Completed the low-severity follow-up bundle raised during Claude review of Section 8.

### Completed

- Deduplicated `_provider_name()` by importing the shared helper from `job_logic.py` in:
  - `agents/kernel_factory.py`
  - `agents/transcription.py`
- Tightened `VideoAdapter.render_review_notes()` so successful transcription evidence now reports:
  - `"Audio transcription complete. Frame-level visual analysis pending."`
- Kept the old "pending" note for metadata-only video fallback paths.
- Added `_CONSISTENCY_INCONCLUSIVE_THRESHOLD` in `alignment.py` and removed hardcoded fallback verdict thresholds.
- Documented all three transcript/media consistency env vars in `REFERENCE.md`.

### Validation

- Added unit coverage for:
  - transcription-complete review notes in `test_adapters.py`
  - configurable fallback inconclusive threshold behavior in `test_agents.py`
- Validation run:
  - `cd backend && .venv/bin/pytest ../tests/unit/test_adapters.py ../tests/unit/test_agents.py -v`
  - `cd backend && .venv/bin/pytest ../tests/ -q`
- Result: 245 tests passed.

### Notes

- `VideoAdapter.normalize()` now includes `storage_key` only on the successful transcription path so review-note messaging reflects actual behavior instead of attempted fallback.

---

## Section 10: Local E2E Pipeline Smoke Script (2026-04-13)

Added a stateless local smoke-test entrypoint for the real agent chain without Service Bus, repository, or storage dependencies.

### Completed

- Added [scripts/test_e2e_pipeline.py](/Users/karthicks/kAgents/Projects/PFCD-V2/scripts/test_e2e_pipeline.py).
- The script:
  - builds a job via `JobCreateRequest` + `default_job_payload`
  - injects a short inline VTT transcript
  - runs `run_extraction()`, `run_anchor_alignment()`, `run_processing()`, and `run_reviewing()` in order
  - prints the requested summary table
  - exits non-zero only when `sipoc_no_anchor` is present or runtime/env setup fails
- No application code, migrations, repository logic, or test files were changed for this task.

### Validation

- `cd backend && .venv/bin/python -m py_compile ../scripts/test_e2e_pipeline.py`
- `cd backend && .venv/bin/python ../scripts/test_e2e_pipeline.py`
- Local result without live credentials: `Result: FAIL - PFCD_PROVIDER=openai is required.`
- Live operator validation in a network-enabled shell:
  - `cd backend`
  - `export PFCD_PROVIDER=openai`
  - `export OPENAI_API_KEY=...`
  - `export OPENAI_CHAT_MODEL_BALANCED=gpt-4o-mini`
  - `.venv/bin/python ../scripts/test_e2e_pipeline.py`
  - Result: `PASS`
  - Observed output:
    - `Extraction evidence items: 4`
    - `Alignment verdict: inconclusive`
    - `SIPOC rows generated: 4`
    - `SIPOC rows with step_anchor: 4`
    - `SIPOC rows with source_anchor: 4`
    - `Review flags: ['transcript_fallback']`
    - `Blockers: ['NONE']`

### Notes / Open Questions

- The successful live run confirms the primary objective of this script: transcript-only balanced OpenAI processing no longer produces a `sipoc_no_anchor` blocker in the real agent chain.

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

---

## Section 11: Live Status + Handoff (2026-04-10)

This section captures the latest live debugging state before context reset.

### Commits pushed (chronological)

- `caefebf` — worker reconnect loop hardening + deploy runtime checks
- `5f1deaa` — backend/worker deploy workflows changed to readiness polling
- `35cfab6` — added `--track-status false` to `az webapp deploy` commands to avoid ~19m CLI status timeout
- `b8bd8f9` — **critical fix**: `profile_config()` now uses configured Azure OpenAI deployment (`AZURE_OPENAI_DEPLOYMENT_NAME` / `AZURE_OPENAI_DEPLOYMENT`) instead of hardcoded `gpt-4.1-mini`; added `tests/unit/test_job_logic.py`

### What was verified live on Azure

- App Service control-plane states reported `Running` for:
  - `pfcd-dev-api`
  - `pfcd-dev-worker-extracting`
  - `pfcd-dev-worker-processing`
  - `pfcd-dev-worker-reviewing`
- API `/health` returned `status: ok` earlier in session.
- API + workers point to same DB setting:
  - `DATABASE_URL = @Microsoft.KeyVault(.../sql-connection-string)`
- Service Bus queue checks during incident:
  - extracting message consumed (queue `active` moved `1 -> 0`)
  - processing queue drained after manual restart of processing worker (`3 -> 0`)

### Transaction-specific status (`4e252d67-ff64-476d-98b0-a7ec8d3f40a0`)

- Started as `queued`
- Advanced to `processing` (extracting completed)
- Ended `failed` in phase `processing` with:
  - `NotFoundError 404 Resource not found` from `AzureChatCompletion`

Root cause confirmed:
- Azure OpenAI account deployment list contains `gpt-4o-mini`
- old routing selected `gpt-4.1-mini` for balanced profile
- mismatch triggered processing-phase 404

### Reviewing worker check

- Reviewing agent is deterministic (no LLM call in `backend/app/agents/reviewing.py`)
- Same OpenAI-404 issue does **not** apply to reviewing phase directly

### Current blocker

The latest deployment runs containing `b8bd8f9` did not land:

- Workers run `24151722686` (sha `b8bd8f9...`) — failed
  - all worker jobs failed in `Deploy <role> worker`
- Backend run `24151732803` (sha `b8bd8f9...`) — failed
  - failed in `Deploy to Azure App Service`

So production may still be on pre-`b8bd8f9` code (`35cfab6`), which means processing 404 can still occur for new jobs until deploy succeeds.

### Tooling/auth status

- GitHub CLI (`gh`) installed (`2.89.0`)
- `gh auth status` currently shows invalid token for `kartiksiva`
- Need `gh auth login -h github.com` before using `gh run view ... --log-failed` for direct failed-step logs

### Next actions after resume

1. Re-auth `gh` and fetch failed logs for runs:
   - workers: `24151722686`
   - backend: `24151732803`
2. Fix the deploy-step failure (currently failing before verification steps).
3. Redeploy successfully with sha `b8bd8f9`.
4. Create a fresh transaction and verify end-to-end progression:
   - `queued -> processing -> needs_review` (or clear deterministic failure reason if blocked).

---

## Section 12: Manual Deploy Packaging Guardrail (2026-04-10)

Documented a deployment packaging pitfall observed during manual redeploy.

### Problem observed

- Local deploy zips accidentally included `backend/.venv/**`.
- This significantly increased artifact size and caused long Oryx build times (large upload/extract + unnecessary dependency handling), increasing timeout risk.

### Guardrail

- Do **not** include local virtual environments in App Service zip deploy artifacts.
- For Oryx-based deploys, package source files only (`app/`, `alembic/`, `alembic.ini`, `requirements.txt`, etc.).

### Recommended packaging command

```bash
cd backend
zip -rq ../worker.zip . \
  -x '.venv/*' '.venv/**' '*/.venv/*' \
  -x '__pycache__/*' '*/__pycache__/*' \
  -x '*.pyc' '.pytest_cache/*' '.mypy_cache/*' '.DS_Store' '*.log'
cd ..
cp worker.zip backend.zip
```

### Verification check before deploy

```bash
zipinfo -1 worker.zip | rg '^\.venv/' || true
```

- Expected result: no output (no `.venv` entries present).

---

## Section 13: Deployment Pipeline Hardening (2026-04-11)

Four separate issues were identified and fixed in the CI/deployment pipeline. All changes are in `.github/workflows/deploy-backend.yml` and `.github/workflows/deploy-workers.yml` plus the agent import chain.

### Fix 1: venv and dev artifacts excluded from zip (`deploy-backend.yml`, `deploy-workers.yml`)

**Problem:** Backend deploy used `zip -r ../backend.zip .` with no exclusions. Workers used `zip -r ../worker.zip . -x "*.pyc" -x "__pycache__/*"` — excluding bytecode but not virtual environments. Any `venv/`, `.venv/`, or `env/` directory inside `backend/` (common on dev machines or CI runs that install deps in-place) would be bundled into the artifact, bloating it by 200–500 MB and risking Azure zip-deploy size-limit failures or timeouts.

**Fix:** Both workflows now pass a consistent exclusion list to `zip`:
```
-x "venv/*" -x ".venv/*" -x "env/*"
-x "*.pyc" -x "__pycache__/*"
-x ".pytest_cache/*" -x ".coverage"
-x "*.db" -x "*.sqlite3"
-x ".env" -x ".env.*"
-x "storage/*"
```

---

### Fix 2: Worker triple restart cycle eliminated (`deploy-workers.yml`)

**Problem:** For each worker, the previous step order was:
1. `az webapp deploy` (zip, async) → restart #1 — code lands but startup-file not yet set
2. `az webapp config appsettings set` → restart #2 — env vars change
3. `az webapp config set --startup-file` → restart #3 — startup command finally correct

Three restarts per worker (9 total across all three), with verify steps starting to poll after restart #1 but two more restarts still pending. `WEBSITES_CONTAINER_START_TIME_LIMIT=600` was also applied after the deploy restart, so Azure's default 230 s container startup window was active for the deploy restart — enough to kill the process during heavy Python imports.

**Fix:** Reordered to configure-first, deploy-last for all three workers:
1. `az webapp config appsettings set` (includes `WEBSITES_CONTAINER_START_TIME_LIMIT=600`, `WEBSITES_PORT=8000`) — runs first, restart happens with no code yet (no-op)
2. `az webapp config set --startup-file` — runs second, another no-op restart
3. `az webapp deploy` (zip) — final step, triggers the single definitive restart with all config already in place

**Backend:** CORS `appsettings set` was running before the zip deploy, adding a redundant restart. Moved to a post-deploy step (applied after health check passes).

---

### Fix 3: CI test failures from eager semantic-kernel imports (`backend/app/agents/`)

**Problem:** `app/agents/__init__.py` eagerly imported `run_extraction` → `extraction.py` → `from semantic_kernel.connectors.ai.open_ai import ...` at module level. Any test that imported any `app.agents.*` submodule (adapters, alignment, sipoc_validator, evidence) triggered this import chain and failed immediately if `semantic_kernel` was not installed — before any `monkeypatch` could apply. This caused widespread CI failures across tests that had nothing to do with the LLM layer.

**Fix:** SK imports moved inside the functions that actually need them:
- `extraction.py`: `from semantic_kernel...` and `from app.agents.kernel_factory import get_kernel` moved inside `_call_extraction()`
- `processing.py`: same, inside `_call_processing()`
- `kernel_factory.py`: `from azure.identity...`, `from semantic_kernel import Kernel`, and `from semantic_kernel.connectors.ai.open_ai import AzureChatCompletion` moved inside `get_kernel()`
- `app/agents/__init__.py`: removed `run_extraction`, `run_processing`, `run_reviewing` from eager re-exports (SK-dependent; only used by `runner.py`)
- `workers/runner.py`: updated to import directly from `app.agents.extraction`, `app.agents.processing`, `app.agents.reviewing`

SK is now only imported at worker runtime when an LLM call is actually made. All tests run without `semantic_kernel` installed. 134+ tests pass with lightweight deps only.

---

### Fix 4: Deployment verification time reduced (`deploy-workers.yml`, `deploy-backend.yml`)

**Problem:** Total workflow wall time was ~30 minutes, comprising:
- Workers: `az webapp show` state check (60 × 20s = 20 min max) + `az webapp log download` runtime log check (30 × 20s = 10 min max) = 30 min per worker
- Backend: health check (60 × 20s = 20 min max)
- The `az webapp log download` step was the main offender — downloading full log archives every 20s, unreliable (old log entries from prior runs could satisfy the grep), and redundant once `state=Running` was confirmed.

**Fix:**
- Removed all `az webapp log download` runtime log verification steps permanently — `state=Running` is the correct and sufficient signal
- Halved all polling intervals: 20s → 10s
- Workers: 90 × 10s = 15 min max (vs 30 min)
- Backend: 60 × 10s = 10 min max (vs 20 min)

Note: A curl HTTP probe against the worker's public URL was attempted as an additional check, but reverted — Python startup with heavy Azure SDK imports takes longer than the probe window, causing false failures. The `az webapp show state=Running` check is reliable.

**Expected total deployment time:** ~10–15 min vs ~30 min previously.

---

## Section 14: Architecture & Code Review (2026-04-11)

Full read-through of all backend modules, agent layer, workers, tests, and storage by architect/reviewer. Codex is assigned to fix these.

### Critical (fix before next deploy to prod)

**C1 — `/dev/simulate` bypasses API key auth (`main.py:408`)**
Registered on `@app.post` (top-level `app`), not `api_router`. When `PFCD_API_KEY` is set, any unauthenticated caller can advance any job to `NEEDS_REVIEW` and auto-set `user_saved_draft=True`. Fix: move to `api_router`, or add an explicit env guard (`PFCD_ENV=production → 404`).

**C2 — Blocking I/O on async event loop in `finalize_job` (`main.py:298-301`)**
`build_export_pdf`, `build_export_docx`, `build_export_markdown` are blocking (FPDF, python-docx) and called directly inside `async def finalize_job`. Will starve other requests on large drafts. Fix: wrap each in `await anyio.to_thread.run_sync(...)`.

### High Priority

**H1 — Two AgentRun rows created per phase (`runner.py:114,154`)**
`add_agent_run` is called with `status="running"`, then again with `status="success"` — each call generates a new UUID. 6 orphaned "running" rows accumulate per successful job. Fix: insert once, update by run_id to set duration/cost/status on completion.

**H2 — Storage uses connection string, not `DefaultAzureCredential` (`storage.py:31`)**
`BlobServiceClient.from_connection_string()` uses a storage key. Contradicts the project security policy. Fix: switch to `BlobServiceClient(account_url=..., credential=DefaultAzureCredential())`.

**H3 — Kernel instantiated fresh on every agent call (`kernel_factory.py:11`)**
New `Kernel`, new `DefaultAzureCredential`, new token provider per LLM call. Token initialization is expensive (MSI endpoint probes). Fix: `@lru_cache(maxsize=None)` keyed on deployment string, or module-level singleton.

**H4 — `ServiceBusOrchestrator.enqueue()` opens a new AMQP connection per message (`servicebus.py:70`)**
New `ServiceBusClient` created and torn down inside every `enqueue()` call. Fix: hold a persistent client instance, reconnecting on failure.

**H5 — Cost cap declared but never enforced (`job_logic.py:90-104`, `runner.py`)**
`profile_config` returns `cost_cap_usd` ($4/$8) but no code in the worker loop checks cumulative cost against the cap. This is dead configuration.

**H6 — Cost estimate uses hardcoded gpt-4o-mini pricing regardless of actual deployment (`extraction.py:52`, `processing.py:94`)**
`_cost_usd` always applies `$0.15/1M input, $0.60/1M output` even if the deployment is `gpt-4.1` or `gpt-4o`. Cost estimates in `agent_runs` are unreliable.

**H7 — `profile_config` does not differentiate models between BALANCED/QUALITY (`job_logic.py:90-104`)**
Both profiles resolve the same env var deployment name. The CLAUDE.md cost table is aspirational; the code never enforces different models.

### Medium Priority

**M1 — All timestamps stored as `String(64)`, compared lexicographically in SQL (`models.py`, `repository.py:265`)**
`Job.ttl_expires_at < now_iso` works only because `_utc_now()` always produces `+00:00` UTC. One timezone-aware string with an offset suffix would silently sort wrong. All datetime columns should be `DateTime` types.

**M2 — Anchor classification implemented three ways with different regex (`export_builder.py:22`, `sipoc_validator.py:30`, `alignment.py:29`)**
A VTT anchor with fractional seconds (`00:01:15.500-00:01:30.500`) is `timestamp_range` in the sipoc_validator but `section_label` in the export_builder. Extract a single `classify_anchor(anchor) -> str` utility used by all three modules.

**M3 — `_transcript_text_inline` doesn't survive DB roundtrips — implicit contract (`runner.py:122`, `alignment.py:226`)**
Alignment is safe today because it runs in the same phase as extraction (same in-memory job dict). If any future code calls alignment post-extraction after a DB reload, it gets an empty string and silently marks all anchors "inconclusive". Document this as a `# NOTE` in both modules, or load transcript from storage before alignment.

**M4 — `upsert_job` deletes all Draft rows then re-inserts, resetting audit timestamps (`repository.py:174`)**
Delete-then-insert on every upsert resets `generated_at`/`user_reconciled_at` on the Draft row. Should use ON CONFLICT DO UPDATE (upsert by composite PK) to preserve metadata.

**M5 — Stub PDD from `build_draft()` leaks into production exports on processing failure (`job_logic.py:275`)**
The fallback stub (actor "Unknown Speaker", anchor "00:00:00-00:00:10") is used verbatim if reviewing fires without a real draft. Users would receive an export with synthetic placeholder data. The reviewing agent should fail the job instead of proceeding with a stub.

### Low Priority

**L1 — `_utc_now()` defined in three modules with inconsistent return types**
`job_logic.py` and `runner.py` return `str`; `servicebus.py` returns a `datetime` object. Consolidate in a shared utility.

**L2 — Two env var names for the same OpenAI deployment (`job_logic.py:83-87`, `extraction.py:12`)**
`AZURE_OPENAI_DEPLOYMENT_NAME` and `AZURE_OPENAI_DEPLOYMENT` both used. `REFERENCE.md` documents only `AZURE_OPENAI_DEPLOYMENT`; the GitHub secret is `AZURE_OPENAI_DEPLOYMENT_NAME`. Pick one canonical name.

**L3 — `_extract_speaker` heuristic is too permissive (`transcript.py:300-307`)**
`": " in content` with `len(candidate) <= 40` matches process step text like `"Invoice approval: the manager..."`. Produces false-positive speaker names. Needs a stricter heuristic (title case, known name list, or length ≤ 25).

**L4 — `/dev/simulate` sets `user_saved_draft=True` unconditionally, hiding the "finalize without saving" error path in testing**
The test suite cannot exercise that path via the simulate workflow. Separate concern from the auth issue (C1).

### Test Gaps

| Gap | Impact |
|-----|--------|
| No test that `/dev/simulate` is reachable without API key when auth is enabled | Auth bypass in prod goes undetected |
| No test for `_should_skip` deduplication logic with phase ordering | Duplicate processing possible |
| No test for cost cap enforcement | Dead config never detected |
| `test_lifecycle.py` relies on `/dev/simulate` — no test for real 3-phase worker chain with mocked SK | Integration path untested |
| No test for storage mode mismatch (created in blob, loaded in local) | Silent data loss risk |

### Section 14 Implementation Notes (Merged)

Implementation pass completed for Critical (`C1`, `C2`) and High (`H1`–`H7`) findings:

- `C1` fixed: `/dev/jobs/{job_id}/simulate` now enforces API key auth when configured.
- `C2` fixed: `finalize_job` export generation/storage operations are moved off the async event loop (`anyio.to_thread.run_sync(...)`).
- `H1` fixed: phase lifecycle updates a single active `AgentRun` instead of creating duplicate success rows.
- `H2` fixed (dual-mode): blob storage prefers `DefaultAzureCredential` with connection-string fallback.
- `H3` fixed: Semantic Kernel instance creation is cached by `(endpoint, deployment)`.
- `H4` fixed: Service Bus enqueue path reuses client/senders instead of opening a fresh AMQP connection per message.
- `H5` implemented (warn-only): cumulative cost tracking and cap warning flagging.
- `H6` fixed: token cost estimation is deployment-aware (not hardcoded mini pricing).
- `H7` implemented: profile-specific deployment env vars supported with fallback chain.

Code areas touched in the Section 14 implementation pass:

- `backend/app/main.py`
- `backend/app/job_logic.py`
- `backend/app/workers/runner.py`
- `backend/app/repository.py`
- `backend/app/agents/kernel_factory.py`
- `backend/app/agents/extraction.py`
- `backend/app/agents/processing.py`
- `backend/app/servicebus.py`
- `backend/app/storage.py`

Environment variable notes from Section 14 implementation:

- New optional support:
  - `AZURE_OPENAI_DEPLOYMENT_BALANCED`
  - `AZURE_OPENAI_DEPLOYMENT_QUALITY`
  - `AZURE_STORAGE_ACCOUNT_URL`
- Existing vars retained (compatibility):
  - `AZURE_OPENAI_DEPLOYMENT_NAME`
  - `AZURE_OPENAI_DEPLOYMENT`
  - `AZURE_STORAGE_CONNECTION_STRING`

Section 14 pass test updates and validation:

- Updated tests:
  - `tests/integration/test_auth_enforcement.py`
  - `tests/unit/test_job_logic.py`
  - `tests/unit/test_worker.py`
- Validation run:
  - `pytest tests/unit tests/integration -q`
  - Result at pass time: `211 passed`

Follow-up scope not included in Section 14 implementation pass:

- Medium/Low findings (`M1`–`M5`, `L1`–`L4`) remained open at that checkpoint.

---

## Section 15: Semantic Kernel Runtime Hardening (2026-04-11)

Implemented the Semantic Kernel reliability/config hardening pass requested after architecture review.

### Model/deployment resolution hardening

- `job_logic.py` now treats `AZURE_OPENAI_CHAT_DEPLOYMENT_NAME` as canonical.
- Backward-compatible aliases retained:
  - `AZURE_OPENAI_DEPLOYMENT_NAME`
  - `AZURE_OPENAI_DEPLOYMENT`
- Alias usage now logs deprecation warnings.
- Removed silent model fallback; if no deployment is configured, `profile_config()` now raises `RuntimeError` with explicit env guidance.
- Profile-specific overrides (`AZURE_OPENAI_DEPLOYMENT_BALANCED`, `AZURE_OPENAI_DEPLOYMENT_QUALITY`) remain intact.

### Semantic Kernel API version pinning (env-driven)

- `kernel_factory.py` now passes `api_version` explicitly to `AzureChatCompletion`.
- Resolution order:
  - `AZURE_OPENAI_API_VERSION` (if set)
  - default `"2024-10-21"`
- Existing kernel reuse/caching remains in place (`@lru_cache(maxsize=8)`).

### Usage token parsing and cost reliability

- Removed dead module-level `_DEPLOYMENT` env defaults from:
  - `agents/extraction.py`
  - `agents/processing.py`
- Both agents now require `profile_conf["model"]` and fail explicitly if missing.
- Replaced `usage.get("prompt_tokens")` style parsing with shape-safe logic that supports:
  - dict metadata (`{"usage": {...}}`)
  - object metadata (`usage.prompt_tokens`, `usage.completion_tokens`)
  - missing usage metadata (defaults to zero tokens)

### Ops/runtime visibility and config docs

- Worker startup log now includes:
  - `AZURE_OPENAI_CHAT_DEPLOYMENT_NAME`
  - legacy aliases
  - `AZURE_OPENAI_API_VERSION`
- `REFERENCE.md` updated with canonical OpenAI env vars and legacy alias status.
- `infra/dev-bootstrap.sh` now sets:
  - `AZURE_OPENAI_CHAT_DEPLOYMENT_NAME`
  - `AZURE_OPENAI_API_VERSION=2024-10-21`
  - existing `AZURE_OPENAI_DEPLOYMENT_NAME` retained for compatibility.

### Dependency pinning

- `backend/requirements.txt` updated:
  - `semantic-kernel>=1.41.1` -> `semantic-kernel==1.41.2`

### Test coverage updates

- `tests/unit/test_job_logic.py`
  - canonical env preference
  - fallback alias behavior
  - profile-specific override behavior
  - fail-fast when deployment env is missing
- `tests/unit/test_kernel_factory.py` (new)
  - default API version path
  - env-driven API version path
- `tests/unit/test_agents.py`
  - extraction usage parsing with object-style usage metadata
  - processing usage parsing with dict-style metadata
  - missing-usage zero-token default path
- `tests/conftest.py`
  - test harness now sets `AZURE_OPENAI_CHAT_DEPLOYMENT_NAME` default to keep fail-fast config deterministic in tests.

### Validation results

- Targeted tests:
  - `pytest ../tests/unit/test_job_logic.py ../tests/unit/test_agents.py ../tests/unit/test_kernel_factory.py -q`
  - **43 passed**
- Full unit suite:
  - `pytest ../tests/unit -q`
  - **174 passed**
- Full integration suite:
  - `pytest ../tests/integration -q`
  - **44 passed**

---

## Section 16: Section 14 Medium/Low Findings (2026-04-11)

Architect review of deferred `M1`–`M5` and `L1`–`L4` findings from Section 14, plus residual dead code and two architectural gap notes. Full specifications are in `SECTION14_MEDIUM_LOW_FINDINGS_2026-04-11.md`. Codex is assigned to implement.

### Summary of findings

**M1 — Timestamp columns stored as `String(64)` (`models.py`, all tables)**
DB-level date arithmetic and range queries are blocked. TTL comparisons work incidentally by ISO 8601 lexicographic ordering. Fix requires a new Alembic migration to change affected columns to `DateTime(timezone=True)` and repository layer adjustments for ORM serialization.

**M2 — Anchor classification implemented three ways (`alignment.py`, `sipoc_validator.py`, `transcript.py`)**
The three implementations return different type strings (`"unknown"` vs `"missing"`) and apply different regex patterns. A `frame_id` anchor is `"frame_id"` in the validator but `"unknown"` in alignment. Fix: create `backend/app/agents/anchor_utils.py` with canonical `classify_anchor()` and import it from all three callers.

**M3 — `_transcript_text_inline` is non-persistent but silently depended on (`runner.py:131-133`, `extraction.py:129`)**
Field is set by runner, read by extraction, never persisted to DB. It is correctly re-fetched from storage on retry today, but the implicit contract is undocumented. Fix: add explanatory comments in both files and explicitly delete the field from the job dict before `upsert_job` in the extracting phase.

**M4 — `upsert_job` delete-then-recreates all Draft rows (`repository.py:174`)**
`DELETE FROM drafts WHERE job_id=?` on every upsert resets `generated_at` / `user_reconciled_at` audit timestamps. Also a TOCTOU crash window between delete and insert. Fix: apply the same incremental upsert-by-PK pattern used for `AgentRun` (Section 7).

**M5 — Stub PDD from `build_draft()` leaks into production exports (`runner.py:145-147`, `job_logic.py`)**
Reviewing agent runs on a stub draft when processing fails, producing a syntactically valid but placeholder-filled export. Fix: add `"draft_source": "stub"` to `build_draft()` output; reviewing agent adds a BLOCKER flag when `draft_source == "stub"`.

**L1 — `_utc_now()` defined three times with inconsistent return types**
`job_logic.py` and `runner.py` return `str`; `servicebus.py` returns `datetime`. Fix: remove duplicate from `runner.py` (import from `job_logic`); rename `servicebus.py` version to `_utc_now_dt()`.

**L2 — Deprecated deployment env var aliases produce noisy startup warnings**
If Azure App Settings still contain the old `AZURE_OPENAI_DEPLOYMENT_NAME` var, a deprecation warning fires on every worker start. Fix: verify `deploy-workers.yml` uses canonical `AZURE_OPENAI_CHAT_DEPLOYMENT_NAME`; trim startup log to canonical var only.

**L3 — `_extract_speaker` heuristic too permissive (`transcript.py`)**
`"Invoice approval: ..."` and `"Step 3: ..."` are misclassified as speakers. Fix: tighten length cap to 25, reject numeric-start candidates, add known-false-positive prefix list, prefer VTT `<v>` tags when present.

**L4 — `/dev/simulate` sets `user_saved_draft=True` unconditionally (`main.py`)**
Conflates admin tool with user intent. Prevents test coverage of the `409 Draft not saved` error path via simulate. Fix: remove `user_saved_draft = True` from simulate; callers must issue a separate save-draft call.

### Residual dead code (delete alongside M/L pass)

- `extraction.py:49-50` — `_cost_usd()` function (replaced by `estimate_cost_usd` in `job_logic.py`)
- `processing.py:13` — `_DEPLOYMENT` module-level variable (unreferenced)
- `extraction.py:12` (if still present) — same `_DEPLOYMENT` dead variable

### Architectural gap notes (no code change required)

- **Service Bus sender reconnect gap (`servicebus.py:87-88`):** Stale senders after AMQP disconnect cause unnecessary phase retries. Recommended: catch `AMQPConnectionError` in `enqueue()`, evict the cached sender, retry once with a fresh sender.
- **Kernel log placement (`kernel_factory.py:39-45`):** `"Initializing Semantic Kernel"` log fires on every `get_kernel()` call including cache hits. Move inside `_cached_kernel()` so it fires only on cache miss.

### Test gaps assigned for this pass

| Gap | Target file |
|---|---|
| `_should_skip` phase ordering deduplication | `tests/unit/test_worker.py` |
| Cost cap warn-only mode fires correctly | `tests/unit/test_job_logic.py` |
| Storage mode mismatch (blob write, local read) | `tests/unit/test_storage.py` |
| Simulate → finalize without save → 409 | `tests/integration/test_error_cases.py` (after L4 fix) |

---

## Section 17: Section 14 Medium/Low Backlog Implementation (2026-04-11)

Implemented the prioritized Medium (`M1`–`M5`) and Low (`L1`–`L4`) backlog items, plus residual dead-code and test-gap coverage from Section 16.

### Medium items delivered

- **M1 (DateTime migration + ORM serialization + TTL compare)**
  - `models.py`: converted timestamp columns from `String(64)` to `DateTime(timezone=True)` across `jobs`, `drafts`, `agent_runs`, `job_events`.
  - Added Alembic migration: `backend/alembic/versions/20260411_0003_datetime_timestamps.py`.
  - `repository.py`:
    - Added datetime parse/format helpers for safe DB <-> payload conversion.
    - Updated ORM payload serialization to emit ISO strings from datetime columns.
    - Updated `upsert_job` timestamp writes to parse ISO strings into datetime values.
    - Updated `find_expired_jobs` to accept a UTC datetime and compare typed datetimes.
  - `workers/cleanup.py`: TTL scan now passes `datetime.now(timezone.utc)` into repository comparison.

- **M2 (canonical anchor classifier)**
  - Added `backend/app/agents/anchor_utils.py` with canonical `classify_anchor()` returning exactly:
    - `timestamp_range`, `frame_id`, `section_label`, `missing`
  - `sipoc_validator.py` now imports and uses shared `classify_anchor()`.
  - `alignment.py` now imports and uses shared `classify_anchor()` for canonical anchor typing.
  - `export_builder.py` anchor classification now delegates to the shared utility.

- **M3 (`_transcript_text_inline` contract + pop before persistence)**
  - `workers/runner.py`: documented `_transcript_text_inline` as ephemeral, extracting-phase-only working data.
  - Added explicit `job.pop("_transcript_text_inline", None)` before `upsert_job` in extracting success path and extracting terminal-failure path.
  - `agents/extraction.py`: added corresponding contract note in fallback path docs.

- **M4 (Draft upsert by composite PK)**
  - `repository.py`: replaced delete+reinsert draft behavior with incremental upsert-by-composite-key (`job_id`, `draft_kind`) preserving row continuity and audit timestamps.

- **M5 (stub draft source + blocker)**
  - `job_logic.py`: `build_draft()` now sets `draft_source: "stub"`.
  - `agents/reviewing.py`: adds blocker flag `stub_draft_detected` when reviewing a stub draft.

### Low items delivered

- **L1 (`_utc_now` consolidation)**
  - `workers/runner.py`: removed duplicate `_utc_now()` and now imports from `job_logic`.
  - `servicebus.py`: renamed local datetime helper to `_utc_now_dt()`.
  - `agents/processing.py`: replaced inline `datetime.now(...)` with shared `_utc_now()` for generated timestamp defaults.

- **L2 (canonical deployment env var + startup log trim)**
  - `.github/workflows/deploy-workers.yml`: switched worker app settings to `AZURE_OPENAI_CHAT_DEPLOYMENT_NAME` (canonical).
  - `workers/runner.py`: startup log now reports canonical deployment variable only (plus endpoint/API version).

- **L3 (speaker extraction heuristic tightening)**
  - `agents/adapters/transcript.py`:
    - added VTT `<v ...>` speaker-tag preference,
    - reduced speaker cap to 25 chars,
    - rejects numeric-start speaker candidates,
    - added false-positive prefix filters (`step`, `section`, `process`, `invoice`, `task`, `phase`, `action`),
    - constrained candidates to short name-like tokens.

- **L4 (`/dev/simulate` save-state behavior)**
  - `main.py`: `/dev/jobs/{job_id}/simulate` no longer auto-saves drafts; now explicitly sets:
    - `user_saved_draft = False`
    - `user_saved_at = None`

### Dead code cleanup

- Removed obsolete `_cost_usd()` helper from `agents/extraction.py` (replaced by `estimate_cost_usd` flow).
- Verified no remaining dead module-level `_DEPLOYMENT` variable in `agents/processing.py`.

### Additional robustness adjustments during implementation

- `storage.py`: `load_bytes()` now fails fast on storage-mode mismatch:
  - blob metadata in local mode,
  - local metadata in blob mode.
- `main.py`: finalize save-check now accepts persisted draft reconciliation marker (`draft.user_reconciled_at`) in addition to `user_saved_draft` boolean, keeping save-gate deterministic after persistence roundtrips.

### Test coverage updates

Added/updated tests for assigned gaps and new behavior:

- New: `tests/unit/test_anchor_utils.py` (M2 edge cases)
- New: `tests/unit/test_storage.py` (storage mode mismatch)
- Updated: `tests/unit/test_worker.py` (`_should_skip` phase-order dedup path)
- Updated: `tests/unit/test_job_logic.py` (cost-cap warn-only behavior)
- Updated: `tests/integration/test_error_cases.py` (simulate -> finalize without save returns 409)
- Updated: integration fixtures/lifecycle/exports flows to explicitly save draft before finalize where required by gate.

### Validation

- Full suite run:
  - `pytest tests/unit tests/integration -q`
  - **231 passed**, 1 warning (`RequestsDependencyWarning` from local environment).

---

## Section 18: Claude Review — Section 17 M/L Backlog (2026-04-12)

Architect review of all M1–M5, L1–L4, and DC1 items implemented in Section 17.

### Review outcome: All items approved

**M1 (DateTime migration):** `models.py` correctly uses `DateTime(timezone=True)` for all timestamp columns across `jobs`, `drafts`, `agent_runs`, `job_events`. Alembic migration `20260411_0003` covers all affected columns with proper `upgrade()`/`downgrade()` using `op.batch_alter_table` (required for SQLite). Repository layer adds `_to_datetime()`/`_to_iso()` helpers; `find_expired_jobs` now accepts a typed `datetime` argument. Cleanup worker passes `datetime.now(timezone.utc)`. Implementation is correct.

**M2 (anchor_utils.py):** `classify_anchor()` returns exactly `{"timestamp_range", "frame_id", "section_label", "missing"}` with a regex that handles fractional seconds (`00:01:15.500-00:01:30.500`). All three callers (`sipoc_validator.py`, `alignment.py`, `export_builder.py`) delegate to the shared utility. Note: `export_builder.py` retains a thin `_classify_anchor_type()` wrapper for backwards-compat with existing tests — this is acceptable. No divergent classification paths remain.

**M3 (`_transcript_text_inline` cleanup):** Runner documents the ephemeral field with a `NOTE:` comment and `pop`s it before `upsert_job` in both the success path (line ~179) and the terminal-failure path (line ~230). Extraction module documents the fallback reliance in a corresponding note. Contract is now explicit.

**M4 (Draft upsert-by-PK):** `upsert_job` builds `existing_drafts` dict keyed by `draft_kind`, then conditionally creates or updates each draft row in-place. Audit timestamps (`generated_at`, `user_reconciled_at`, `finalized_at`) are preserved across upserts. Pattern is consistent with the AgentRun incremental-insert pattern from Section 7.

**M5 (stub draft detection):** `build_draft()` in `job_logic.py` sets `"draft_source": "stub"` on the fallback payload. Reviewing agent checks `draft.get("draft_source") == "stub"` as the first gate, before PDD completeness or SIPOC validation. Blocker code is `stub_draft_detected`, severity `blocker`, `requires_user_action=True`. Correctly prevents stub exports from reaching finalize.

**L1 (`_utc_now` consolidation):** `runner.py` imports `_utc_now` from `job_logic`. `servicebus.py` local helper renamed to `_utc_now_dt()`. `processing.py` imports `_utc_now` from `job_logic`. Three implementations are now two distinct functions with consistent semantics (str vs datetime).

**L2 (canonical deployment var):** All three worker appsettings blocks in `deploy-workers.yml` use `AZURE_OPENAI_CHAT_DEPLOYMENT_NAME`. Worker startup log reports only canonical var plus endpoint/api_version.

**L3 (speaker heuristic):** `_extract_speaker` now prefers VTT `<v speaker>` tags, rejects candidates longer than 25 chars, rejects numeric-start candidates, and filters known false-positive prefixes (`step`, `section`, `process`, `invoice`, `task`, `phase`, `action`). Implementation in `_is_valid_speaker_candidate()` is clean.

**L4 (`/dev/simulate` save state):** Endpoint now sets `user_saved_draft = False` and `user_saved_at = None`. The finalize gate at `main.py:268-270` checks `user_saved_draft or draft.get("user_reconciled_at")` — simulate no longer short-circuits the 409 path. Note: the mock draft injected by simulate does not set `user_reconciled_at`, so the 409 guard is properly exercisable via simulate → finalize-without-save.

**DC1 (dead code):** `_cost_usd()` is absent from `extraction.py`. No `_DEPLOYMENT` module-level variable in `extraction.py` or `processing.py`. Both agents call `estimate_cost_usd` from `job_logic`. Confirmed clean.

### One observation (non-blocking)

The `export_builder.py` retains `_classify_anchor_type()` as a one-line wrapper around `classify_anchor()`. This is fine — removing it would require updating test imports. Leave as-is.

### Suite verification

- `pytest tests/unit tests/integration -q` → **231 passed**

---

## Section 19: Section 17 Publish (2026-04-12)

Published the approved Section 17 Medium/Low backlog changes to `main`.

### Delivery

- Commit: `5c260bf`
- Branch: `main`
- Remote: `origin`
- Scope: single commit containing the approved M1–M5, L1–L4, and DC1 changes plus associated tests and docs updates listed in `HANDOVER.md` assignment `S17-COMMIT`.

### Notes

- Excluded from commit as instructed: `HANDOVER.md`, `backend.zip`, `worker.zip`, `SECTION14_*.md`, and `frontend/node_modules/`.
- Unrelated local workspace changes (for example `.DS_Store`, `infra/dev-bootstrap.sh`) were intentionally left untouched.

---

## Section 20: Deployment Workflow Hardening (2026-04-12)

Hardened the GitHub Actions Azure deploy workflows after repeated App Service deployment failures caused by Kudu/OneDeploy timeouts and worker config/deploy restart conflicts.

### Backend workflow (`deploy-backend.yml`)

- Added workflow `concurrency` to cancel older in-flight backend deploy runs on the same ref before they overlap with newer pushes.
- Added `timeout-minutes: 30` to the deploy job so the workflow fails deterministically instead of hanging.
- Hardened `az webapp deploy` flags:
  - `--async true`
  - `--enable-kudu-warmup false`
  - `--timeout 1800000`
- Extended backend readiness polling window from 10 minutes to 15 minutes while keeping `/health` as the readiness source of truth.

### Worker workflow (`deploy-workers.yml`)

- Added workflow `concurrency` to prevent overlapping worker deploy workflows from fighting over the same three App Services.
- Added fallback resolution for the worker chat deployment secret:
  - prefer `AZURE_OPENAI_CHAT_DEPLOYMENT_NAME`
  - fall back to legacy `AZURE_OPENAI_DEPLOYMENT_NAME`
- Added explicit validation step to fail fast when neither deployment secret is configured.
- Added per-job `timeout-minutes: 35`.
- Added a config-settle step after `az webapp config appsettings set` / `az webapp config set`:
  - waits for the site to return to `Running`
  - then sleeps an additional 30 seconds before `az webapp deploy`
  - this avoids the Azure-reported `SCM container restart` conflict between management and deploy operations
- Hardened worker `az webapp deploy` flags:
  - `--async true`
  - `--enable-kudu-warmup false`
  - `--timeout 1800000`
- Strengthened worker verification:
  - keep control-plane `state == Running` check
  - add HTTP readiness probe against the worker root endpoint so a deploy only passes when the health server is actually responding

### Validation

- Parsed both workflow files successfully with Ruby YAML loader:
  - `backend workflow yaml ok`
  - `workers workflow yaml ok`
- No application test suite run in this pass; changes are workflow-only.

---

## Section 21: Deployment Options Review (2026-04-12)

Documented deployment remediation options in `DEPLOYMENT_OPTIONS_2026-04-12.md` after the hardened Azure CLI runs for commit `367d2db` still timed out in the actual App Service deploy step.

### Findings captured

- latest backend and worker runs reached the deploy step successfully, then were cancelled by workflow time limits
- earlier worker `SCM container restart` conflicts were mitigated by the workflow hardening pass
- remaining blocker is concentrated in the App Service deploy mechanism (`az webapp deploy` / Kudu / OneDeploy), not in tests or the pre-deploy workflow steps

### Options documented

- keep Azure CLI deploy and raise timeouts further
- keep Azure CLI deploy but separate deploy from verification
- switch to `azure/webapps-deploy` using publish profiles
- move App Service deployments to Run-From-Package
- medium-term move workers to Azure Container Apps

### Recommendation

- same-day recommendation: switch to `azure/webapps-deploy` with publish profiles for backend and all three worker apps
- immediate fallback if that still inherits the same Kudu failure mode: move to Run-From-Package on App Service
- medium-term architecture direction: Azure Container Apps for workers if App Service remains a poor fit for long-running consumers

---

## Section 22: Publish-Profile Deploy Migration (2026-04-12)

Applied the approved deployment follow-up for `S20-FIX` and `DEPLOY-OPT3`.

### Workflow changes

- `deploy-workers.yml`
  - added `sleep 15` at the top of all three config-settle steps (`extracting`, `processing`, `reviewing`) to avoid the pre-restart false-positive `Running` state race
  - replaced all three `az webapp deploy` steps with `azure/webapps-deploy@v3`
  - added explicit secret validation for each worker app name and publish profile before deploy
- `deploy-backend.yml`
  - split package build from deployment for clearer failure boundaries
  - replaced backend `az webapp deploy` with `azure/webapps-deploy@v3`
  - added explicit validation for `AZURE_WEBAPP_NAME` and `AZURE_WEBAPP_PUBLISH_PROFILE`
- `infra/README.md`
  - documented the worker publish-profile secrets and the Azure Portal `Get publish profile` step for each App Service

### Validation

- Parsed `.github/workflows/deploy-backend.yml` and `.github/workflows/deploy-workers.yml` successfully with Ruby YAML loader.
- Ran `git diff --check` on the modified workflow/docs files with no whitespace or merge-marker issues.
- Confirmed the modified workflow files now contain `azure/webapps-deploy@v3` and the worker settle guards, with no remaining `az webapp deploy` calls in those two workflow files.

### Open operational dependency

- GitHub still needs the three new worker publish-profile secrets before the worker workflow can run successfully:
  - `AZURE_WORKER_EXTRACTING_PUBLISH_PROFILE`
  - `AZURE_WORKER_PROCESSING_PUBLISH_PROFILE`
  - `AZURE_WORKER_REVIEWING_PUBLISH_PROFILE`
- No live GitHub Actions run was executed in this pass; this was a workflow/doc update only.

---

## Section 23: Deploy Auth Path Rework (2026-04-12)

Applied follow-up item `DEPLOY-OPT3-REVERT` after confirming the subscription does not support the publish-profile path because SCM basic auth is disabled and publish profiles are redacted.

### Workflow changes

- `deploy-backend.yml`
  - kept `azure/webapps-deploy@v3`
  - removed `publish-profile` input usage
  - removed the backend publish-profile secret validation, keeping only app-name validation
- `deploy-workers.yml`
  - kept the `S20-FIX` `sleep 15` settle guard in all three worker jobs
  - kept `azure/webapps-deploy@v3` for all worker deploy steps
  - removed worker publish-profile secret validation and `publish-profile` inputs
- `infra/README.md`
  - updated deployment guidance to state that `azure/login@v2` supplies the bearer token used by `azure/webapps-deploy@v3`
  - documented that no publish-profile secrets are required on this path

### Validation

- Parsed both workflow files successfully with the Ruby YAML loader after the auth-path rework.
- Ran `git diff --check` on the modified workflow/docs/log files with no whitespace issues.
- Confirmed there are no remaining active `publish-profile` or `*_PUBLISH_PROFILE` references in the backend/worker workflow files.

### Notes

- This section supersedes the operational dependency recorded in Section 22; no new GitHub publish-profile secrets are needed for the current workflow implementation.
- No live GitHub Actions run was executed in this pass; this was a workflow/doc update only.

---

## Section 24: Worker Deploy Timeout Budget Increase (2026-04-12)

Adjusted the worker deployment workflow after the first bearer-token deployment run hit the per-job `35` minute cap while backend deploy succeeded.

### Change

- increased `timeout-minutes` from `35` to `60` for:
  - `deploy-extracting`
  - `deploy-processing`
  - `deploy-reviewing`

### Rationale

- the worker jobs already spend substantial time outside the deploy action itself:
  - config-settle wait after appsettings/startup updates
  - post-deploy control-plane `state == Running` polling
  - post-deploy HTTP readiness probing
- combined with App Service zip deployment latency, `35` minutes leaves too little headroom and can fail the job even when deployment is still progressing normally

### Validation

- workflow YAML still parses after the timeout update
- no application code changed in this pass

---

## Section 25: Repository Cleanup Pass (2026-04-12)

Applied the `REPO-CLEANUP` handover item to reduce root-level noise and stop local artefacts from reappearing in Git status.

### Changes

- root `.gitignore`
  - added `.DS_Store` and `.Rhistory`
  - added `*.zip` for CI/package artefacts
  - added `frontend/node_modules/`
- repository hygiene
  - removed the local session artefacts `backend.zip`, `worker.zip`, `SECTION14_IMPLEMENTATION_NOTES_2026-04-11.md`, `SECTION14_MEDIUM_LOW_FINDINGS_2026-04-11.md`, and `DEPLOYMENT_OPTIONS_2026-04-12.md`
  - untracked `.DS_Store` and `.Rhistory` while leaving the working-tree files in place
- documentation layout
  - created `docs/archive/`
  - moved `NEXT_IMPLEMENTATION.md`, `SUGGESTIONS_FOR_CODEX.md`, `prd-review-20032026.md`, `REVIEW_DOCUMENT_2026-03-21.md`, and `SESSION_SUMMARY_2026-04-01.md` into the archive directory

### Validation

- checked `git status --short` to confirm the cleanup touched only the intended files plus the pre-existing unrelated `infra/dev-bootstrap.sh` modification
- no application tests were run because this pass only reorganized repo files and ignore rules

---

## Section 26: Worker Deployment Race — Root Cause and Remediation Decision (2026-04-12)

### Failure context

GitHub Actions run `24310275264` (commit `5a57e16`, `fix: extend worker deploy timeout budget`) — all three worker deploy jobs failed inside `azure/webapps-deploy@v3`. Error message in each case:

```
Deployment has been stopped due to SCM container restart. The restart can happen due to a management operation on site. Do not perform a management operation and a deployment operation in quick succession.
```

### Root cause (Claude review)

Each deploy job fires **two** sequential Azure control-plane mutations before calling `azure/webapps-deploy@v3`:

1. `az webapp config appsettings set` — triggers Kudu/SCM container restart #1
2. `az webapp config set --startup-file` — triggers restart #2, overlapping #1

The settle guard (`sleep 15` → poll `az webapp show --query state` for `Running` → `sleep 30`) reads the **app container** state, not the SCM/Kudu container state. Azure returns `Running` once the app container stabilises; the Kudu container can still be mid-restart. `azure/webapps-deploy@v3` calls the Kudu OneDeploy API at that moment and is rejected.

### Remediation decision

Two-part fix assigned to Codex as `DEPLOY-FIX2`:

**Part 1 (quickwin):** Remove `az webapp config set --startup-file` from `deploy-workers.yml`. The startup command (`python -m app.workers.runner`) is static and should be set once at provisioning time in `infra/dev-bootstrap.sh`, not on every deploy. This eliminates restart #2. Increase post-`Running` sleep from 30 s to 60 s to give Kudu time to recover from the single remaining restart.

**Part 2 (proper fix, WEBSITE_RUN_FROM_PACKAGE):** Upload `worker.zip` to the `scratch` blob container; generate a short-lived SAS URL; include `WEBSITE_RUN_FROM_PACKAGE=<url>` in the `appsettings set` call alongside all other settings; replace `azure/webapps-deploy@v3` with `az webapp restart`. This consolidates all config into one control-plane operation, eliminates the Kudu OneDeploy call entirely, and removes the race condition by design.

Pre-requisite for Part 2: verify worker managed identities have `Storage Blob Data Reader` on the scratch container (or the storage account).

---

## Section 27: Worker Deploy Race Quickwin (Part 1) (2026-04-12)

Implemented Part 1 of `DEPLOY-FIX2` to reduce worker deployment restarts before the larger `WEBSITE_RUN_FROM_PACKAGE` change.

### Changes

- `.github/workflows/deploy-workers.yml`
  - removed all three `az webapp config set --startup-file "python -m app.workers.runner"` calls from the worker deploy jobs
  - increased the post-`Running` settle delay from `30` seconds to `60` seconds in the extracting, processing, and reviewing settle steps
- `infra/dev-bootstrap.sh`
  - added explicit worker app name defaults:
    - `WORKER_EXTRACTING_NAME`
    - `WORKER_PROCESSING_NAME`
    - `WORKER_REVIEWING_NAME`
  - extended `ensure_app_service()` to provision/configure the three worker App Services on the shared plan
  - sets each worker startup command once at provisioning time to `python -m app.workers.runner`
  - applies worker app settings including `PFCD_WORKER_ROLE`, queue names, Key Vault-backed connection strings, and `AZURE_OPENAI_ENDPOINT`
  - grants each worker app identity `Key Vault Secrets User` on the vault, matching the backend app pattern

### Validation

- parsed `.github/workflows/deploy-workers.yml` successfully with the Ruby YAML loader
- ran `bash -n infra/dev-bootstrap.sh` successfully
- ran `git diff --check` on the modified workflow/bootstrap/log files with no whitespace issues
- confirmed `deploy-workers.yml` no longer mutates worker startup files during CI and now uses `sleep 60` after `state == Running`

### Remaining work

- Part 2 of `DEPLOY-FIX2` is still pending: move workers to `WEBSITE_RUN_FROM_PACKAGE` so the deployment path no longer depends on Kudu OneDeploy timing

---

## Section 28: Worker Package-URL Deploy (Part 2) (2026-04-12)

Implemented Part 2 of `DEPLOY-FIX2` to remove Kudu OneDeploy from the worker deployment path and switch workers to `WEBSITE_RUN_FROM_PACKAGE`.

### Changes

- `.github/workflows/deploy-workers.yml`
  - `build` job now logs into Azure, validates the `AZURE_STORAGE_ACCOUNT` GitHub Actions variable, uploads `worker.zip` to the `scratch` container, generates a 4-hour read SAS, and writes the package URL to `package-url.txt`
  - uploads `package-url.txt` as a new `package-url` workflow artifact
  - each worker deploy job now downloads `package-url`, reads it into `PACKAGE_URL`, and validates it before deployment
  - removed all three `azure/webapps-deploy@v3` steps from the worker workflow
  - each worker deploy now sets `WEBSITE_RUN_FROM_PACKAGE="$PACKAGE_URL"` in the same `az webapp config appsettings set` call as the role/config settings, then forces `az webapp restart`
  - retained the post-restart settle loop plus running/HTTP readiness verification for extracting, processing, and reviewing
- `infra/dev-bootstrap.sh`
  - `ensure_storage_account()` now optionally accepts `SP_CLIENT_ID` and grants that service principal `Storage Blob Data Contributor` on the storage account so CI can upload the package blob
  - `ensure_app_service()` now grants each worker managed identity `Storage Blob Data Reader` on the storage account in addition to `Key Vault Secrets User`
- `REFERENCE.md`
  - documented that `deploy-workers.yml` now deploys through `WEBSITE_RUN_FROM_PACKAGE`
  - added `AZURE_STORAGE_ACCOUNT` under a new GitHub Actions variables table
- `infra/README.md`
  - updated deployment notes to distinguish backend zip deploys from worker package-URL deploys
  - documented the new worker/storage RBAC expectations and the optional `SP_CLIENT_ID` bootstrap override

### Validation

- ran `python3 - <<'PY'` with `yaml.safe_load()` against `.github/workflows/deploy-workers.yml`
- ran `bash -n infra/dev-bootstrap.sh`
- ran `git diff --check -- .github/workflows/deploy-workers.yml infra/dev-bootstrap.sh REFERENCE.md infra/README.md IMPLEMENTATION_SUMMARY.md HANDOVER.md`
- verified by source inspection that worker deploy jobs no longer reference `azure/webapps-deploy@v3` or mutate startup files during CI

### Open question / residual risk

- `WEBSITE_RUN_FROM_PACKAGE` removes the Kudu/Oryx deployment build step. The current worker artifact is still a source zip, so if App Service does not provide all required Python dependencies at runtime, workers may require a follow-up packaging change to include runtime dependencies in the mounted package.

---

## Architecture Decision: Provider Strategy (2026-04-13)

### Decision

V2 will support two LLM provider paths — **Azure OpenAI** (default) and **direct OpenAI** — selected via `PFCD_PROVIDER` env var. Google/Gemini support is dropped.

### Rationale

Individual Azure accounts face model provisioning restrictions (quota approval required for gpt-4o, gpt-4.1, etc.). Direct OpenAI API provides identical models without those constraints. Both providers use the same OpenAI API contract and Semantic Kernel connectors (`AzureChatCompletion` vs `OpenAIChatCompletion`) — no prompt or schema changes required.

Azure remains the deployment and orchestration platform (App Service, Service Bus, Blob Storage, Azure SQL). Provider flexibility applies only to the LLM inference call path.

### V1 Feature Analysis and Port Plan

A full comparison of PFCD V1 (`/Users/karthicks/kAgents/Projects/PFCD`) against V2 was completed (2026-04-13). Key finding: V1 has a working transcript-first pipeline but the wrong architecture for video-first. Porting V2 from V1 is cheaper than rebuilding V1 as video-first.

Four capabilities ported from V1 into V2 as tasks PROC-PROMPT-FIX → PROVIDER-FLEX → VIDEO-TRANSCRIPTION → TEXT-SIMILARITY (see HANDOVER.md for specs):

1. **PROC-PROMPT-FIX** — fix `sipoc_no_anchor` BLOCKER on transcript-only jobs
2. **PROVIDER-FLEX** — `PFCD_PROVIDER` env var; `OpenAIChatCompletion` path in kernel_factory, extraction, processing, job_logic
3. **VIDEO-TRANSCRIPTION** — new `transcription.py`; real Whisper call in `VideoAdapter.normalize()`; update `_normalize_input()` to use video content when no uploaded transcript
4. **TEXT-SIMILARITY** — Jaccard + SequenceMatcher in `alignment.py`; replaces anchor-ratio proxy; reads `_video_transcript_inline` ephemeral field set by VideoAdapter

### Future phases (not yet assigned)

- **MediaPreprocessor** — ffmpeg audio extraction + 10-min chunked Whisper transcription + keyframe selection; unblocks videos > 25 MB and genuine video-first frame evidence
- **Docker workers** — required for ffmpeg availability on Azure App Service
- **Frontend wiring** — adapt V1 Next.js frontend to V2 API contract
- **Job list endpoint** (`GET /api/jobs`) + provider health endpoint

---

## Section 29: MediaPreprocessor for Large Media Transcription (2026-04-13)

Implemented `MEDIA-PREPROCESSOR` to unblock Whisper transcription for video/audio blobs larger than the 24 MB API limit.

### Changes

- `backend/app/agents/media_preprocessor.py`
  - added `is_ffmpeg_available()` to probe `ffmpeg` on `PATH` without raising
  - added `extract_audio_track()` to convert large video files to low-bitrate MP3 via subprocess `ffmpeg`
  - added `split_audio_chunks()` to segment oversize audio into 10-minute chunks with a single-file fallback path
  - added `_shift_ts()` and `merge_vtt_chunks()` to offset per-chunk VTT cue timings and emit one merged `WEBVTT` document
- `backend/app/agents/transcription.py`
  - extracted provider dispatch into `_transcribe_single()` while leaving `_transcribe_with_azure()` and `_transcribe_with_openai()` unchanged
  - replaced the old immediate `file_too_large` skip path with a preprocessing pipeline:
    - probe for `ffmpeg`
    - extract audio from large videos
    - chunk oversize audio
    - transcribe each chunk independently
    - merge successful chunk VTTs with timestamp offsets
  - retained the prior stub fallback when `ffmpeg` is unavailable or extraction fails
  - added cleanup of temporary extraction directories after transcription completes
- `tests/unit/test_media_preprocessor.py`
  - added coverage for `ffmpeg` availability probing, VTT merge behavior, comma-to-dot timestamp normalization, small-file chunk bypass, large-file preprocessing success, and `ffmpeg`-unavailable fallback
- `tests/unit/test_adapters.py`
  - added adapter transparency coverage confirming `VideoAdapter` behaves the same when `transcribe_audio_blob()` returns VTT through the new preprocessing path
- `REFERENCE.md`
  - added `media_preprocessor.py` and its test file to the repo map
  - documented the external `ffmpeg` dependency and the Azure App Service limitation

### Validation

- ran `.venv/bin/pytest ../tests/unit/test_media_preprocessor.py -v`
- ran `.venv/bin/pytest ../tests/unit/test_adapters.py -v`
- ran `.venv/bin/pytest ../tests/ -q`
- final suite result: `253 passed, 1 warning`

### Open question / residual risk

- Azure App Service still does not provide `ffmpeg`, so production use of this path depends on the planned Phase 5b custom-image/Docker worker deployment. Until then, large files continue to fall back to `[transcription_skipped:file_too_large]` in environments without `ffmpeg`.

---

## Section 30: Keyframe Vision Supplement for VideoAdapter (2026-04-13)

Implemented `KEYFRAME-VISION` to add frame-derived evidence for video inputs and supplement audio transcripts with batched multimodal frame analysis.

### Changes

- `backend/app/agents/media_preprocessor.py`
  - added `extract_keyframes()` using subprocess `ffmpeg` with interval sampling, JPEG output, and a hard max-frame cap
  - returns sorted `(frame_path, timestamp_sec)` pairs and degrades to `[]` on missing `ffmpeg` or extraction failures
- `backend/app/agents/vision.py`
  - added direct `httpx` vision-call batching for both provider paths using `_provider_name()`
  - added env-controlled limits for frames per call and frames per job
  - added base64 image packaging into chat-completions `image_url` content items
  - returns concatenated frame-analysis text and degrades to `""` on any error
- `backend/app/agents/adapters/video.py`
  - documented `_frame_descriptions_inline` as a second ephemeral extraction-only field beside `_video_transcript_inline`
  - added optional keyframe extraction + `analyze_frames()` path gated on `storage_key` and `ffmpeg` availability
  - now returns:
    - raw VTT transcript text when only audio transcription is available
    - `FRAME ANALYSIS:` content when only visual analysis is available
    - combined transcript + frame-analysis content when both are available
  - added `has_frame_analysis` metadata and updated review notes to report completed frame analysis
- `backend/app/workers/runner.py`
  - extraction-phase cleanup now drops `_frame_descriptions_inline` anywhere `_video_transcript_inline` is cleared, preserving deterministic persisted payloads
- `tests/unit/test_media_preprocessor.py`
  - added keyframe extraction coverage for `ffmpeg`-missing fallback and tuple/timestamp output
- `tests/unit/test_vision.py`
  - added coverage for empty input, provider routing, exception fallback, and batching behavior
- `tests/unit/test_adapters.py`
  - added frame-analysis adapter coverage and adjusted transcript-only expectations to preserve existing extraction behavior
- `REFERENCE.md`
  - added `vision.py`, `test_vision.py`, and the new vision-related environment variables to the reference map/table

### Validation

- ran `.venv/bin/pytest ../tests/unit/test_media_preprocessor.py -v`
- ran `.venv/bin/pytest ../tests/unit/test_vision.py -v`
- ran `.venv/bin/pytest ../tests/unit/test_adapters.py -v`
- ran `.venv/bin/pytest ../tests/ -q`
- final suite result: `260 passed, 1 warning`

### Open question / residual risk

- Production still depends on both a vision-capable model deployment and `ffmpeg` availability in the worker runtime. Without those, the adapter falls back to transcript-only or metadata-only video evidence as designed.

---

## Section 9: Phase 6 — Frontend Integration (assigned 2026-04-13)

Reviewed and spec'd by Claude. Assigned to Codex via `HANDOVER.md FRONTEND-COMPLETE`.

### Gaps identified in existing frontend

The frontend components (`CreateJob`, `JobStatus`, `DraftReview`, `ExportLinks`, `SipocTable`, `FlagPanel`) are structurally sound and connected to correct API calls. Four critical gaps were found:

1. **API key header absent** — `_fetch` in `api.js` never sends `X-API-Key`. Any deployment with `PFCD_API_KEY` configured silently returns 401 on every call.
2. **Save-draft missing → finalize always 409** — `DraftReview.handleFinalize` calls `finalizeJob` directly. The backend requires `user_saved_draft=True` (set by PUT `/jobs/{id}/draft`). Without calling `saveDraft` first, finalize always returns 409. There is no save-draft function in `api.js` and no save step in the UI.
3. **No job list** — there is no `GET /api/jobs` endpoint in the backend and no list/history view in the frontend. Jobs are unreachable after page refresh.
4. **Dev proxy gap** — Vite dev server proxies `/api` but not `/dev`. The devSimulate button calls `/dev/jobs/{id}/simulate` and always fails locally.

### Spec for Codex

- `frontend/src/api.js` — add VITE_API_KEY header in `_fetch`; add `saveDraft`; add `listJobs`
- `frontend/vite.config.js` — add `/dev` to proxy config
- `frontend/src/components/DraftReview.jsx` — call `saveDraft` before `finalizeJob` in `handleFinalize`
- `backend/app/repository.py` — add `list_jobs(limit=50)` → lightweight summary rows, deleted excluded, most recent first
- `backend/app/main.py` — add `GET /api/jobs` endpoint
- `frontend/src/components/JobList.jsx` (new) — table of recent jobs; clicking a row calls `getJob` then routes to appropriate view
- `frontend/src/App.jsx` — default view `'list'`; add `onSelectJob` routing; `← Jobs` back button
- `tests/unit/test_job_list.py` (new) — 4 tests: empty, rows ordered, deleted excluded, endpoint 200

### Delivered (reviewed 2026-04-13)

All 8 changes implemented as specced, plus one beyond-spec improvement:

- `api.js` — `authHeaders()` helper extracted; `_fetch`, `uploadFile`, and `devSimulate` all send `X-API-Key`; `saveDraft` and `listJobs` added; `DEV_BASE` extracted for `/dev/*` calls
- `vite.config.js` — `/dev` proxy added alongside `/api`
- `DraftReview.jsx` — `saveDraft` called before `finalizeJob` in `handleFinalize`; import updated
- `repository.py` — `list_jobs(limit)` added: SQLAlchemy query filtering `deleted_at IS NULL`, ordered `created_at DESC`, limit-capped
- `main.py` — `GET /api/jobs` at line 206 (before `/jobs/{job_id}` to avoid shadowing); `bounded_limit = max(0, min(limit, 200))` prevents oversized queries
- `JobList.jsx` (new) — status badge colours, source type chips, `selecting` state for per-row loading feedback
- `App.jsx` — default view `'list'`; `onSelectJob` routes to `exports`/`review`/`status` by status; `← Jobs` back button replaces `+ New Job` in nav
- `ExportLinks.jsx` — **beyond spec**: switched from `<a href download>` to `downloadExport()` button calls, which routes through `_fetch` and sends `X-API-Key`; also adds per-format loading state and error display
- `REFERENCE.md` — `VITE_API_KEY` documented

### Validation

- 264 passed, 1 warning (all tests green)
- `npm run build` clean

---

## Section 31: Phase 6 Frontend Integration Completed (2026-04-13)

Implemented `FRONTEND-COMPLETE` to make the React/Vite frontend usable across refreshes and aligned with the backend’s auth and draft-finalize requirements.

### Changes

- `backend/app/repository.py`
  - added `list_jobs(limit=50)` returning lightweight, most-recent-first job summaries
  - excludes soft-deleted rows via `deleted_at is null`
- `backend/app/main.py`
  - added authenticated `GET /api/jobs` endpoint with limit clamped to `0..200`
- `frontend/src/api.js`
  - added `X-API-Key` injection from `VITE_API_KEY` for JSON API requests
  - added `saveDraft(jobId, draft)` and `listJobs()`
  - extended upload and `/dev/jobs/{id}/simulate` requests to send the same API key header so authenticated local/dev flows no longer break on upload or simulate
  - added authenticated export download helper using `fetch` + blob download because plain anchor tags cannot send `X-API-Key`
- `frontend/src/components/DraftReview.jsx`
  - now saves the draft before calling finalize, fixing the backend `409 Draft must be saved before finalize` path
- `frontend/src/components/JobList.jsx`
  - added recent-job list view with status/source badges and row-click job loading
- `frontend/src/App.jsx`
  - switched default route to the new job list
  - added list/create/status/review/exports routing from selected job status
  - added `← Jobs` navigation back to history
- `frontend/src/components/ExportLinks.jsx`
  - switched export actions from raw anchor links to authenticated button-triggered downloads
  - now prefers `finalized_draft` details when loading a completed job from history
- `frontend/vite.config.js`
  - added `/dev` proxy alongside `/api` so local `Simulate → needs_review` works
- `tests/unit/test_job_list.py`
  - added coverage for empty list, ordering, deleted-row exclusion, and `GET /api/jobs`
- `REFERENCE.md`
  - documented `VITE_API_BASE`, `VITE_API_KEY`, and the new `GET /api/jobs` endpoint

### Validation

- ran `.venv/bin/pytest ../tests/unit/test_job_list.py -v`
- ran `.venv/bin/pytest ../tests/ -q`
- ran `cd frontend && npm run build`
- final suite result: `264 passed, 1 warning`

### Open question / residual risk

- The frontend still has no dedicated automated UI/component test coverage. The integration here is validated via backend tests and a production build, but browser-flow regressions would currently be caught only through manual testing.

---

## Section 10: PRD Compliance Gap Analysis + Phase 7 Assignment (2026-04-13)

Full PRD review performed by Claude. Three high-priority gaps identified and specced for Codex.

### Gaps confirmed

**High (blocks v1 acceptance):**
1. **Draft editing UI absent** (§6, §8.9) — DraftReview read-only; `blocked` decision is a dead end in the UI since users can't fix PDD/SIPOC issues that caused blockers.
2. **Speaker resolution UI missing** (§8.1) — no component to resolve `Unknown Speaker` flags; `speaker_resolutions` persists to DB but is never surfaced.
3. **Frame captures not persisted** (§8.10) — frames deleted in `finally` block after vision analysis; export builder has hard-coded "pending Azure Vision integration" note.

**Medium:**
4. Teams metadata (`transcript_speaker_map`) not injected into extraction prompt.
5. OCR not executed — `ocr_enabled` stored but no OCR step runs.
6. `confidence_delta` always 0.0 in agent_runs.

**Confirmed compliant:** all 12 PDD key validators, `requires_user_action` on blockers, SIPOC quality gate, retry/DLQ, `audio_detected`/`frame_extraction_policy` in manifest, `provider_effective` fields, all §9 API contracts.

### Assigned to Codex

| Task | Key change | PRD section |
|------|-----------|-------------|
| `DRAFT-EDIT` | Editable PDD/SIPOC fields; `update_draft` re-runs reviewing + returns updated flags | §6, §8.9 |
| `SPEAKER-RESOLVE` | `SpeakerResolutionPanel` in DraftReview; `_build_speaker_hint` injected into extraction prompt | §8.1 |
| `FRAME-PERSIST` | `upload_frame()` in storage.py; frame keys in VideoAdapter metadata; frame captures in export bundle | §8.10 |

---

## Section 32: Draft Editing + Re-Review on Save (2026-04-13)

Implemented `DRAFT-EDIT` so users can correct blocker-causing PDD/SIPOC fields in the review UI and immediately refresh the deterministic reviewing gate on save.

### Changes

- `backend/app/main.py`
  - `PUT /api/jobs/{job_id}/draft` now persists `user_saved_draft=True` and `user_saved_at`
  - re-runs the pure-Python reviewing gate after each draft save
  - refreshes rerunnable reviewing/SIPOC flags before re-review so resolved blockers actually clear instead of accumulating stale codes
  - extends the save response with updated `review_notes` and `agent_review`
  - updates the dev simulate draft seed to a structurally complete PDD/SIPOC so lifecycle/export tests that save assumptions-only remain valid under the new re-review behavior
- `frontend/src/components/DraftReview.jsx`
  - replaced the read-only PDD/SIPOC display with inline-editable controls
  - added debounced auto-save with live save status (`saving` / `saved` / `error`)
  - updates live flags from the save response so blocker state changes immediately after edits
  - finalization now saves the latest edited draft before posting finalize
  - keeps process steps read-only while making top-level PDD fields and SIPOC cells editable
- `tests/unit/test_draft_edit.py`
  - added coverage for save response shape, blocker clearing after fixing a required field, and blocker re-appearance after blanking a required field

### Validation

- ran `.venv/bin/pytest ../tests/unit/test_draft_edit.py -v`
- ran `.venv/bin/pytest ../tests/ -q`
- ran `cd frontend && npm run build`
- final suite result: `267 passed, 1 warning`

### Open question / residual risk

- `metrics` and other non-string PDD values are editable through generic text controls in the current UI. This satisfies the blocker-resolution workflow, but richer type-aware editing could improve usability in a later pass.

---

## Section 33: Speaker Resolution UI + Teams Speaker Map Hints (2026-04-13)

Implemented `SPEAKER-RESOLVE` to reduce unnecessary `Unknown` actor assignments during extraction and expose persisted speaker-resolution inputs in the review UI.

### Changes

- `backend/app/agents/extraction.py`
  - added `_build_speaker_hint(job)` to format `teams_metadata.transcript_speaker_map` into a prompt hint block
  - appends the hint block to the extraction user prompt when Teams speaker metadata is present
  - stores `speakers_detected` into persisted `agent_signals` so the frontend can surface unknown speakers after API reloads
- `frontend/src/api.js`
  - extended `saveDraft(jobId, draft, speakerResolutions)` to optionally persist `speaker_resolutions`
- `frontend/src/components/DraftReview.jsx`
  - added `SpeakerResolutionPanel` for `Unknown` speakers
  - tracks `speakerResolutions` state separately from the edited draft
  - includes speaker resolutions in debounced saves and finalize-time save
  - sources detected speakers from `job.extracted_evidence.speakers_detected` with `job.agent_signals.speakers_detected` as the persisted fallback
- `tests/unit/test_speaker_resolve.py`
  - added coverage for speaker-hint rendering with and without Teams metadata

### Validation

- ran `.venv/bin/pytest ../tests/unit/test_speaker_resolve.py -v`
- ran `.venv/bin/pytest ../tests/ -q`
- ran `cd frontend && npm run build`
- final suite result: `269 passed, 1 warning`

### Open question / residual risk

- The current speaker-resolution UI uses free-text role assignment, which satisfies PRD §8.1 persistence and editability but does not yet constrain values to known participants/roles from Teams metadata.

---

## Section 34: Frame Capture Persistence + Export Bundle Wiring (2026-04-13)

Implemented `FRAME-PERSIST` so extracted video frames survive temp-dir cleanup, are persisted to evidence storage, and appear in the export bundle metadata for PDF/DOCX/Markdown output.

### Changes

- `backend/app/storage.py`
  - added `upload_frame(job_id, frame_index, jpg_bytes)` with blob upload support and local fallback
  - added `AZURE_STORAGE_CONTAINER_EVIDENCE` support for evidence asset routing
- `backend/app/agents/adapters/video.py`
  - uploads extracted frame JPGs before temp-dir cleanup
  - stores persisted frame keys in both `EvidenceObject.metadata.frame_storage_keys` and persisted `agent_signals.frame_storage_keys`
  - keeps temp-frame cleanup unchanged after persistence
- `backend/app/export_builder.py`
  - collects frame captures from evidence metadata and persisted agent signals
  - links captures to timestamp anchors by midpoint proximity
  - surfaces `frame_captures` in the evidence bundle instead of the old hard-coded pending note
  - adds frame-capture sections to Markdown/PDF/DOCX exports
  - embeds local images when available and falls back to textual storage-key references for blob-backed captures
- `tests/unit/test_frame_persist.py`
  - added coverage for local fallback writes, exception fallback, video-adapter frame key metadata, and bundle inclusion
- `REFERENCE.md`
  - documented `AZURE_STORAGE_CONTAINER_EVIDENCE`

### Validation

- ran `.venv/bin/pytest ../tests/unit/test_frame_persist.py -v`
- ran `.venv/bin/pytest ../tests/ -q`
- final suite result: `273 passed, 1 warning`

### Open question / residual risk

- Export-time image embedding is intentionally local-path-only. Blob-backed frame captures are referenced textually at export time rather than downloaded inline, which keeps export generation simple and deterministic but does not yet embed remote evidence assets directly.
- `rerunnable_codes` in `main.py update_draft` is a hardcoded set that must be kept in sync with `run_reviewing`'s flag output. If new flag codes are added to that function, the set must be updated or stale flags will accumulate on re-edit.

---

## Section 11: Claude PRD Review Outcome (2026-04-13)

All three high-priority PRD gaps from the gap analysis are now resolved. Remaining gaps are medium/low priority.

### Resolved
| Gap | Task | PRD section |
|-----|------|-------------|
| Draft editing + blocker resolution | DRAFT-EDIT | §6, §8.9 |
| Speaker resolution UI + extraction speaker hint | SPEAKER-RESOLVE | §8.1 |
| Frame capture persistence + export bundle | FRAME-PERSIST | §8.10 |

### Still open (medium/low)
| Gap | PRD section | Notes |
|-----|-------------|-------|
| OCR not executed | §8.1, §8.6 | `ocr_enabled` stored but no OCR step runs; vision does LLM description only |
| `confidence_delta` always 0.0 | §8.11 | Column + serialization exist; agents never populate it |
| Application Insights not wired | §8.4, §11 | Python logging only; no telemetry SDK |
| Azure Key Vault at runtime | §8.4, §11 | Env vars used directly; Key Vault provisioned but not read at runtime |
| Pre-processing cost estimate warning | §8.13 | Warning for high-cost quality runs not surfaced before processing starts |

---

## Section 35: Deployment Workflow Hardening (2026-04-14)

Closed the active worker deployment RCA and switched the backend deployment workflow to the same package-URL pattern already used by workers.

### WORKER-BUILD-RCA

- inspected the latest failed `Deploy Workers` manual run (`24387794848`) with `gh`
- root cause was Azure RBAC, not workflow YAML: the failing `Upload worker zip to scratch blob and write package URL` step was authenticating successfully but the GitHub deployment principal lacked storage data-plane write access on `pfcddevstorage`
- identified the GitHub deployment principal as `pfcd-dev-api-gha` and granted it `Storage Blob Data Contributor` on the storage account
- reran `Deploy Workers` run `24387794848`; the `build` job passed on rerun and all three deploy jobs advanced past the original package-upload failure

### DEPLOY-FIX3

- updated `.github/workflows/deploy-backend.yml` to remove `azure/webapps-deploy@v3`
- backend deploy now:
  - validates `AZURE_STORAGE_ACCOUNT`
  - builds `backend.zip`
  - uploads the package to the `scratch` blob container
  - generates a SAS package URL
  - sets `WEBSITE_RUN_FROM_PACKAGE` plus `PFCD_CORS_ORIGINS`
  - restarts the app and waits for the App Service state to settle before health probing
- removed the old post-deploy app-settings step because CORS config is now set in the main deploy step
- updated `infra/README.md` to describe backend package-URL deploys instead of Kudu OneDeploy
- granted `Storage Blob Data Reader` to the API app identity `pfcd-dev-api` on `pfcddevstorage` so the backend app can read its mounted package blob when this workflow is used

### Validation / residual risk

- ran `git diff --check` locally; no whitespace or patch-format issues
- backend workflow was not GitHub-validated in this session because the workflow change is local-only until committed and pushed
- current GitHub Actions deprecation warnings about Node.js 20 remain informational and were not changed as part of this pass

---

## Section 36: Claude Review — WORKER-BUILD-RCA + DEPLOY-FIX3 (2026-04-17)

### Review outcome: Both items approved

**WORKER-BUILD-RCA:** Operator-only fix; no workflow code changes. Root cause correctly identified as missing `Storage Blob Data Contributor` RBAC assignment on `pfcddevstorage` for the GHA service principal `pfcd-dev-api-gha`. Role granted; `Deploy Workers` run `24387794848` build job confirmed passing. No open issues.

**DEPLOY-FIX3:** `.github/workflows/deploy-backend.yml` reviewed against the spec in HANDOVER.md. All spec requirements satisfied:
- `azure/webapps-deploy@v3` removed; no Kudu OneDeploy on the backend deploy path
- `AZURE_STORAGE_ACCOUNT` validation present as a GitHub Actions variable check
- Blob upload + `az storage blob generate-sas` with SAS generation identical to the worker pattern
- `WEBSITE_RUN_FROM_PACKAGE`, `PFCD_CORS_ORIGINS`, `WEBSITES_CONTAINER_START_TIME_LIMIT=600`, `WEBSITES_PORT=8000` set in a single `az webapp config appsettings set` call
- Separate "Apply post-deploy configuration" step removed — CORS setting consolidated into deploy step as specified
- Settle loop: initial `sleep 15`, then polls `az webapp show --query state` for `Running`, then `sleep 60` before exiting
- Health probe: `curl -fsS` against `/health` for up to 60 attempts × 10s = 10 min
- `infra/README.md` updated correctly: describes package-URL deploy for both backend and workers; RBAC requirements for app identities documented

One operational note: the API app identity `pfcd-dev-api` also required `Storage Blob Data Reader` on `pfcddevstorage` so it can mount the package blob at runtime. Codex granted this role as part of the DEPLOY-FIX3 work. This is consistent with how worker identities are configured.

### Suite verification

- `pytest tests/unit tests/integration -q` → **273 passed**, 1 warning

### Next open items

The `Assigned to Codex` queue is now empty. Remaining PRD gaps are medium/low (OCR execution §8.1/§8.6, `confidence_delta` population §8.11, Application Insights §8.4). No new tasks are being assigned at this time.

---

## Section 37: Azure Deployment Review Writeup (2026-04-17)

Reviewed the deployed shape end-to-end from an Azure operations perspective: backend API on App Service, worker services on App Service, frontend on Azure Static Web Apps, bootstrap in `infra/dev-bootstrap.sh`, and the current GitHub Actions workflows.

### What is good

- **Backend deploy path is much healthier now.** `deploy-backend.yml` runs tests before deploy, publishes a package to blob storage, sets `WEBSITE_RUN_FROM_PACKAGE`, restarts the app, waits for App Service state recovery, and then probes `/health`. This is materially safer than the old Kudu/OneDeploy path because startup/config changes happen through one control-plane flow.
- **Worker deploy path matches App Service reality.** `workers/runner.py` starts a tiny HTTP server on port 8000 so App Service warmup probes succeed even though the real workload is Service Bus-driven. That is the right compatibility layer for long-running worker containers on Web Apps.
- **Identity-first Azure access is mostly aligned with the target architecture.** Blob access prefers `DefaultAzureCredential`, Semantic Kernel uses Azure AD tokens for Azure OpenAI, and the infra docs explicitly call out RBAC requirements for package-URL deploys.
- **Provisioning and deployment responsibilities are separated cleanly.** `infra/dev-bootstrap.sh` creates the Azure baseline and the workflows assume the resource graph already exists, which keeps deploys faster and less error-prone.
- **Frontend packaging is simple and production-oriented.** `deploy-frontend.yml` uses `npm ci`, builds once, and uploads the static output directly to Azure Static Web Apps with `skip_app_build: true`, which removes platform-side build variance.

### What is bad / risky

- **Frontend auth config is incomplete for Azure deployment.** The frontend code sends `X-API-Key` only when `VITE_API_KEY` is present, but `deploy-frontend.yml` injects `VITE_API_BASE` only. If `PFCD_API_KEY` is enabled on the backend App Service, the Azure-hosted frontend will fail authenticated API and export calls unless the build also injects `VITE_API_KEY`.
- **Frontend/backend routing is deployment-sensitive but not validated.** The frontend assumes either a linked SWA backend or an explicit `VITE_API_BASE`, yet the workflow only comments on that convention and does not fail fast when the secret is missing or mis-set. A successful frontend deploy can therefore still produce a broken runtime.
- **Backend readiness is stronger than backend config validation.** The workflow verifies `AZURE_STORAGE_ACCOUNT` and app availability, but it does not validate the core runtime inputs that the application actually depends on in Azure (`DATABASE_URL`, Service Bus connection, Azure OpenAI endpoint/deployment, storage account identity path, etc.). The deploy can succeed while the app starts degraded or workers fail on first real job.
- **Worker workflow has no test gate.** Backend deploy runs pytest first; worker deploy does not. Since workers share the same `backend/` package and are sensitive to runtime env wiring, this creates an avoidable gap where worker-only deployment runs can push untested code.
- **Worker workflow is operationally repetitive.** The three deploy jobs are largely copy-paste equivalents. It works, but it increases maintenance cost and drift risk whenever Azure app settings, wait logic, or validation rules change.
- **Azure runtime secret strategy is still hybrid rather than fully Azure-native.** Key Vault is provisioned and documented, but the runtime code still reads env vars directly rather than fetching secrets from Key Vault or relying entirely on App Service Key Vault references. That keeps deployment workable, but it means secret correctness depends heavily on portal/app-settings hygiene.
- **Backend `/health` can report degraded on missing infra metadata even when the app process is up.** That is useful operationally, but it also means deployment readiness is tightly coupled to environment completeness. If bootstrap/app settings drift, the health probe will block rollout even for non-critical metadata omissions.
- **Frontend deployment has no post-deploy smoke check.** Unlike backend/workers, there is no verification that the built SPA can actually reach the configured API origin, so Azure deployment can report success while the user journey is broken.
- **No deployment-time guard exists for ffmpeg-dependent paths.** Video/frame processing depends on ffmpeg, and repo docs already note App Service Linux does not include it by default. That leaves a known Azure production capability gap for worker media processing unless custom images are introduced.

### Recommended Claude review focus

1. Frontend Azure env contract: should `deploy-frontend.yml` require and inject `VITE_API_KEY`, and should it fail fast when deploying a non-linked backend without `VITE_API_BASE`?
2. Backend/worker config validation: decide whether deploy workflows should explicitly validate required runtime settings beyond storage/package-URL inputs.
3. Worker workflow maintainability: decide whether to keep the three explicit jobs or refactor to a matrix/shared action pattern.
4. Runtime secret model: confirm whether env-var-only runtime config is acceptable for this phase, or whether Key Vault references should become the deployment standard.

---

## Section 38: Claude Response to Copilot Azure Review (2026-04-17)

Thank you for the thorough Azure deployment audit. The findings are well-targeted and the severity ordering is accurate. Here is the architectural response to each recommended focus area:

### 1. Frontend Azure env contract — ACCEPTED, assigning to Codex (DEPLOY-FRONTEND-AUTH)

`VITE_API_KEY` must be injected at `npm run build` time alongside `VITE_API_BASE`. The `api.js` code already reads it conditionally — it just isn't wired up in the workflow. `deploy-frontend.yml` will be updated to: (a) fail fast if `VITE_API_BASE` secret is absent, and (b) pass `VITE_API_KEY` as a build-time env var. This is the highest-priority fix — the current Azure-hosted SPA is auth-broken when `PFCD_API_KEY` is active.

A post-deploy step probing `$VITE_API_BASE/health` will also be added (FRONTEND-SMOKE) so that frontend deploy success implies a reachable backend, not just a successful SWA upload.

### 2. Backend/worker config validation — ACCEPTED, scoped, assigning to Codex

**Backend (BACKEND-CONFIG-VALIDATE):** The existing validation step in `deploy-backend.yml` will be extended to assert `DATABASE_URL`, `AZURE_SERVICE_BUS_CONNECTION_STRING`, and `AZURE_OPENAI_ENDPOINT` are non-empty. Fail-fast with a named list of missing vars. This surfaces misconfiguration at deploy time rather than at first job execution.

**Workers (WORKER-TEST-GATE):** A pytest job will be prepended to `deploy-workers.yml` — identical to the backend test gate — with all three deploy jobs gated on it via `needs: test`. Worker-specific runtime config validation (SB connection, role assignment) is already effectively covered by the test suite through integration test patterns; no additional per-worker appsettings validation step is warranted at this stage.

### 3. Worker workflow maintainability — DEFERRED

The three-job pattern is explicit and easy to audit. The correct refactor is a reusable workflow (`.github/workflows/deploy-worker-single.yml` called with `uses:`) rather than a matrix, since App Service worker names differ by role. This is a maintenance improvement, not a correctness fix. Deferring until after the four critical/high items are closed.

### 4. Runtime secret model — ENV-VAR ACCEPTED FOR V1, KEY VAULT DEFERRED

Env-var-only runtime config is acceptable for v1. Key Vault is provisioned (`infra/dev-bootstrap.sh`) and RBAC is documented, but Key Vault references in App Service require additional `az webapp config appsettings set` syntax changes and managed identity `Key Vault Secrets User` grants that add deployment complexity without a v1 user-facing benefit. This will be documented as a known gap in `REFERENCE.md` with the remediation path noted for post-v1.

### Findings accepted as-is (no Codex work)

- **`/health` coupling to env completeness** — intentional; degraded status on missing infra is a feature, not a bug. It surfaces misconfiguration before users encounter it.
- **ffmpeg on App Service Linux** — already documented as a known gap. Resolution requires custom Docker images, which is post-v1 scope.

### Tasks assigned to Codex (from this review)

| ID | Priority | Scope |
|----|----------|-------|
| DEPLOY-FRONTEND-AUTH | Critical | `deploy-frontend.yml`: `VITE_API_KEY` inject + `VITE_API_BASE` fail-fast |
| WORKER-TEST-GATE | High | `deploy-workers.yml`: add pytest job; gate all deploys on it |
| FRONTEND-SMOKE | High | `deploy-frontend.yml`: add backend `/health` probe after SWA upload |
| BACKEND-CONFIG-VALIDATE | Medium | `deploy-backend.yml`: validate `DATABASE_URL`, SB conn, AOAI endpoint |

---

## Section 39: Deployment Workflow Hardening Follow-up (2026-04-17)

Closed the four deployment workflow fixes assigned from the Azure deployment review.

### Completed

- `.github/workflows/deploy-frontend.yml`
  - Added `Validate frontend deployment settings` to fail fast when `VITE_API_BASE` is unset.
  - Injected `VITE_API_KEY` into the frontend build alongside `VITE_API_BASE`.
  - Added a final `/health` probe against `${VITE_API_BASE}` after the Static Web Apps upload step.
- `.github/workflows/deploy-workers.yml`
  - Added a `test` job mirroring the backend CI gate (`actions/setup-python@v5`, `unixodbc-dev`, `pip install -r backend/requirements.txt`, `pytest tests/unit tests/integration -x --tb=short` with `DATABASE_URL=sqlite:///./test-ci.db` and `PYTHONPATH=backend`).
  - Updated `deploy-extracting`, `deploy-processing`, and `deploy-reviewing` to `needs: [test, build]`.
- `.github/workflows/deploy-backend.yml`
  - Extended `Validate backend deployment settings` to fail with a consolidated missing-list when `AZURE_WEBAPP_NAME`, `AZURE_STORAGE_ACCOUNT`, `DATABASE_URL`, `AZURE_SERVICE_BUS_CONNECTION_STRING`, or `AZURE_OPENAI_ENDPOINT` are missing.

### Validation

- Parsed all three workflow YAML files successfully with Ruby `YAML.load_file`.
- `git diff --check` passed for the edited workflow files and handoff board.

### Notes

- No application code changed.
- No test suite was executed locally; validation was limited to workflow structure and diff checks because the changes are GitHub Actions-only.

---

## Section 39: Claude Review — Copilot Azure Review Follow-up Tasks (2026-04-17)

Reviewed all four Codex workflow changes resulting from the Copilot Azure deployment audit (Section 38).

**DEPLOY-FRONTEND-AUTH — Approved**
`deploy-frontend.yml`: validation step added before build fails fast on missing `VITE_API_BASE`; `VITE_API_KEY` injected as build-time env var. Correct ordering: validate → install → build → SWA upload → smoke probe.

**FRONTEND-SMOKE — Approved**
Added as final step in same workflow. 12 × 10s probe (2-minute budget) against `${VITE_API_BASE}/health`. Safe: `VITE_API_BASE` is guaranteed non-empty by the preceding validation step.

**WORKER-TEST-GATE — Approved**
`test` job added to `deploy-workers.yml`. Pattern identical to backend CI gate (`unixodbc-dev`, `PYTHONPATH: backend`, SQLite CI DB). `build` runs in parallel with `test` (faster); all three deploy jobs carry `needs: [test, build]` so deploy is blocked on both. Correct.

**BACKEND-CONFIG-VALIDATE — Approved**
`missing=""` accumulator pattern collects all absent secrets/vars into a single error message — better UX than first-fail-wins on initial environment setup. Validates `AZURE_WEBAPP_NAME`, `AZURE_STORAGE_ACCOUNT`, `DATABASE_URL`, `AZURE_SERVICE_BUS_CONNECTION_STRING`, `AZURE_OPENAI_ENDPOINT`.

**Current deployment pipeline state (post-review):**
- All three workflows have consistent test gates, validation, and post-deploy health probes
- Frontend auth contract is fully wired for Azure-hosted SPA
- No application code changed; 273 tests remain passing (unchanged)

---

## Section 40: Claude Handoff Tasks for Baselining (2026-04-17)

Two follow-up tasks were assigned to Claude so the repository can be used as a clean base for the next implementation pass:

- **`CLAUDE-HANDOVER-CLEANUP`** — reconcile `HANDOVER.md` with actual repo state by removing or relocating stale deployment task specs that are already implemented and approved, so the board reflects reality.
- **`CLAUDE-BASELINE-COMMIT`** — after the board cleanup, create one clean baseline commit containing the already reviewed workflow/documentation updates, with no additional feature work mixed in.

---

## Section 41: Claude Deployment Review Follow-up Queue (2026-04-17)

Added two Claude-owned review/planning items after a fresh Azure deployment pass identified remaining workflow/runtime mismatches.

- **`CLAUDE-BACKEND-DEPLOY-RCA`**
  - Scope: review backend deployment failure mode and plan the correct contract between GitHub Actions validation and App Service Key Vault-backed runtime settings.
  - Evidence: latest backend run `24559639332` failed in `Validate backend deployment settings` because `DATABASE_URL` and `AZURE_SERVICE_BUS_CONNECTION_STRING` were absent from GitHub secrets even though `infra/dev-bootstrap.sh` provisions them as App Service settings via Key Vault references.
- **`CLAUDE-WORKER-PACKAGE-RCA`**
  - Scope: review worker startup path and plan a self-contained `WEBSITE_RUN_FROM_PACKAGE` artifact strategy for Azure App Service workers.
  - Evidence: backend deploy vendors Python dependencies into `antenv`, while worker deploy currently packages source only; this leaves worker startup vulnerable to App Service host/runtime drift and explains intermittent deployment failures on fresh or changed environments.

---

## Section 42: Claude RCA — Backend Deploy Validation + Worker Package Strategy (2026-04-17)

Completed both items from Section 41. Two Codex tasks created.

### CLAUDE-BACKEND-DEPLOY-RCA — Resolved

**Root cause:**
The `Validate backend deployment settings` step in `deploy-backend.yml` (lines 53–64) checks three GitHub secrets that the deploy step never injects and that come from Key Vault-backed App Service settings provisioned by `infra/dev-bootstrap.sh`:
- `DATABASE_URL` — App Service Key Vault ref; absent from GitHub secrets
- `AZURE_SERVICE_BUS_CONNECTION_STRING` — same
- `AZURE_OPENAI_ENDPOINT` — validated but never set by the backend deploy step (only workers set it)

The deploy step only sets `PFCD_CORS_ORIGINS`, `WEBSITES_CONTAINER_START_TIME_LIMIT`, `WEBSITES_PORT`, `WEBSITE_RUN_FROM_PACKAGE`. Additionally `AZURE_RESOURCE_GROUP` is used by all post-deploy steps but not validated.

**Fix (assigned: BACKEND-DEPLOY-VALIDATION-FIX):**
Remove the three spurious `[ -z ... ]` lines from the validation accumulator; add `AZURE_RESOURCE_GROUP`. Surgical change to lines 55–63 only.

### CLAUDE-WORKER-PACKAGE-RCA — Resolved

**Root cause:**
Worker `build` job produces a source-only zip. Under `WEBSITE_RUN_FROM_PACKAGE` the zip is mounted read-only; Azure App Service's Oryx dependency installer does not run in this mode. Any Python import not in the zip fails at worker startup. The backend avoids this by pre-installing all deps into `antenv/lib/python${PY_MINOR}/site-packages` before zipping.

**Fix (assigned: WORKER-VENDORED-DEPS):**
Extend the worker `build` job with: `sudo apt-get install -y unixodbc-dev`, `actions/setup-python@v5 (3.11)`, and `pip install --target antenv/... -r backend/requirements.txt` before the zip step; add `rm -rf antenv` after. Identical pattern to backend.

**Board update:** Both Claude RCA items closed; two Codex tasks placed in Assigned to Codex.

---

## Section 43: Codex Follow-up — Backend Validation + Worker Self-Contained Packages (2026-04-17)

Closed both Codex tasks created from Claude's Section 42 RCA.

### Completed

- `.github/workflows/deploy-backend.yml`
  - Narrowed `Validate backend deployment settings` to check only deploy-time inputs actually consumed by the workflow.
  - Removed `DATABASE_URL`, `AZURE_SERVICE_BUS_CONNECTION_STRING`, and `AZURE_OPENAI_ENDPOINT` from the validation accumulator because those are provisioned as App Service runtime settings rather than injected by this deploy job.
  - Added `AZURE_RESOURCE_GROUP` to validation because the deploy, restart, settle, and health steps all use it directly.
- `.github/workflows/deploy-workers.yml`
  - Extended the `build` job to mirror the backend self-contained package pattern under `WEBSITE_RUN_FROM_PACKAGE`.
  - Added `unixodbc-dev`, `actions/setup-python@v5`, and `pip install --target backend/antenv/lib/python${PY_MINOR}/site-packages -r backend/requirements.txt` before zipping.
  - Added `rm -rf antenv` after packaging to leave the runner workspace clean.

### Validation

- Parsed `.github/workflows/deploy-backend.yml` and `.github/workflows/deploy-workers.yml` successfully with Ruby `YAML.load_file`.
- `git diff --check` passed for the edited workflow files and handoff board.

### Notes

- No application code changed.
- No local test suite was run because the changes are limited to GitHub Actions workflow packaging/validation logic.

---

## Section 43: Codex Review — BACKEND-DEPLOY-VALIDATION-FIX + WORKER-VENDORED-DEPS (2026-04-17)

**BACKEND-DEPLOY-VALIDATION-FIX — Approved**
`deploy-backend.yml` validation step: removed `DATABASE_URL`, `AZURE_SERVICE_BUS_CONNECTION_STRING`, `AZURE_OPENAI_ENDPOINT` from the missing-secret accumulator (all three are App Service Key Vault refs, never injected by this workflow). Added `AZURE_RESOURCE_GROUP`, which is referenced by deploy/wait/health steps but was previously unchecked. Three remaining validated items (`AZURE_WEBAPP_NAME`, `AZURE_STORAGE_ACCOUNT`, `AZURE_RESOURCE_GROUP`) exactly match what the deploy step uses.

**WORKER-VENDORED-DEPS — Approved**
`deploy-workers.yml` `build` job: added `sudo apt-get install -y unixodbc-dev`, `actions/setup-python@v5 (3.11)`, and `pip install --quiet --target backend/antenv/lib/python${PY_MINOR}/site-packages -r backend/requirements.txt` before the zip step; added `rm -rf antenv` after. `antenv/` is included in `worker.zip` (not excluded). Workers now ship fully vendored packages under `WEBSITE_RUN_FROM_PACKAGE` — immune to host/runtime drift. Pattern identical to backend.

Both tasks closed. Board queue now empty.
## Section 59: Codex Delivery — GitHub Issue #19 ACR + Container Apps Environment Bootstrap (2026-04-18)

GitHub issue `#19 Provision Azure Container Registry and Container Apps environment` requested a narrow infrastructure bootstrap update ahead of the Container Apps deployment work in `#20` and `#21`.

### Completed

- Updated [infra/dev-bootstrap.sh](/Users/karthicks/kAgents/Projects/PFCD-V2/infra/dev-bootstrap.sh) to derive and provision the new shared container infrastructure names:
  - `pfcddevregistry` via `CONTAINER_REGISTRY_NAME`
  - `pfcd-dev-logs` via `LOG_ANALYTICS_WORKSPACE_NAME`
  - `pfcd-dev-env` via `CONTAINER_APPS_ENVIRONMENT_NAME`
- Added an ACR provisioning block that creates the registry with the admin user disabled and, when `SP_CLIENT_ID` is supplied, grants the GitHub Actions service principal `AcrPush`.
- Added a Log Analytics workspace provisioning block plus a Container Apps environment provisioning block wired to that workspace via `customerId` and shared key.
- Added a deferred Container App RBAC helper that grants `Storage Blob Data Contributor`, `Azure Service Bus Data Owner`, and `Key Vault Secrets User` to the future API and worker Container App identities once those apps exist.
- Updated the bootstrap script footer to print the ACR login server and shared Container Apps environment name after a run.
- Updated [REFERENCE.md](/Users/karthicks/kAgents/Projects/PFCD-V2/REFERENCE.md) to document the ACR, Log Analytics workspace, Container Apps environment, the optional `SP_CLIENT_ID` bootstrap input, and the new `AZURE_CONTAINER_REGISTRY` GitHub variable expectation for upcoming Container Apps workflows.

### Decisions

- Kept the resource group source of truth aligned to the repository defaults (`app-pfcd-v2`) rather than the issue body's older `pfcd-dev-rg` wording.
- Kept the change scoped to infra bootstrap and reference docs only; no application code or workflow files were modified in this issue.
- Chose a deferred RBAC approach for Container App managed identities because system-assigned identities do not exist until the Container Apps from `#20` and `#21` are created.

### Validation

- Script syntax check:
  - `bash -n infra/dev-bootstrap.sh`
  - result: pass
- Azure CLI command-shape validation with sandbox-safe config path:
  - `AZURE_CONFIG_DIR=/tmp/azcfg az acr create -h`
  - `AZURE_CONFIG_DIR=/tmp/azcfg az containerapp env create -h`
  - `AZURE_CONFIG_DIR=/tmp/azcfg az monitor log-analytics workspace create -h`
  - `AZURE_CONFIG_DIR=/tmp/azcfg az monitor log-analytics workspace get-shared-keys -h`
  - `AZURE_CONFIG_DIR=/tmp/azcfg az containerapp show -h`
  - result: commands and flags used by the new bootstrap blocks are present

### Open follow-up

- The actual repo variable `AZURE_CONTAINER_REGISTRY` and the effective `AcrPush` scope on `AZURE_CREDENTIALS` still need operator-side confirmation in GitHub/Azure; this issue only documents and bootstraps the infra-side expectations.
- The deferred RBAC helper will report skips until the Container Apps from `#20` and `#21` exist, which is expected for this issue's scope.

---

## Section 62: Codex Delivery — GitHub Issue #20 Backend API to Azure Container Apps (2026-04-19)

Executed the first Container Apps migration slice for the backend API by replacing the App Service package deployment workflow with an image-based Azure Container Apps deployment path.

### Completed

- Rewrote [.github/workflows/deploy-backend.yml](/Users/karthicks/kAgents/Projects/PFCD-V2/.github/workflows/deploy-backend.yml) from App Service zip deploy to Azure Container Apps:
  - keeps the existing unit/integration + PostgreSQL smoke test gate
  - installs the Azure Container Apps CLI extension
  - builds `backend/Dockerfile --target api`
  - pushes `pfcd-backend-api:${GITHUB_SHA}` to ACR
  - bootstraps the backend Container App with a public image on first deploy so the system-assigned identity exists before the private-image revision is applied
  - grants the backend Container App identity `AcrPull` on ACR and `Key Vault Secrets User` on the vault
  - renders a YAML manifest for the final backend revision with:
    - external ingress
    - port `8000`
    - HTTP `/health` startup/liveness/readiness probes
    - Key Vault-backed secret refs for `DATABASE_URL`, `AZURE_STORAGE_CONNECTION_STRING`, and `AZURE_SERVICE_BUS_CONNECTION_STRING`
  - verifies the deployed backend using the ACA FQDN and accepts either `200 {"status":"ok"}` or `503 {"status":"degraded"}` from `/health`
- Updated [REFERENCE.md](/Users/karthicks/kAgents/Projects/PFCD-V2/REFERENCE.md):
  - CI/CD section now documents the backend ACA deploy path and the new required GitHub variables
  - Azure infrastructure table now lists `pfcd-[env]-api` as the active backend Container App while keeping the App Service entry marked as legacy during cutover

### Decisions

- Used a two-step ACA deploy shape (`public bootstrap image` -> `role assignment` -> `private ACR image revision`) because system-assigned managed identities do not exist until the Container App resource is created.
- Kept runtime secrets Azure-native by referencing Key Vault from the Container App manifest instead of moving `DATABASE_URL`, storage, and Service Bus connection strings into GitHub secrets.
- Preserved the existing backend app name secret (`AZURE_WEBAPP_NAME`) to keep the migration narrow even though the active resource is now a Container App rather than an App Service Web App.

### Open follow-up

- Worker migration (`#21`) is still required before the platform is fully on Azure Container Apps.
- `infra/dev-bootstrap.sh` still provisions the legacy App Service plan / web apps by default; that drift should be cleaned up after the ACA backend and worker paths are both stable.

---

## Section 63: Codex Delivery — GitHub Issue #21 Workers to Azure Container Apps + KEDA (2026-04-19)

Executed the worker migration slice by replacing the App Service package deployment workflow and warmup shim with a Container Apps + Service Bus scaling path.

### Completed

- Rewrote [.github/workflows/deploy-workers.yml](/Users/karthicks/kAgents/Projects/PFCD-V2/.github/workflows/deploy-workers.yml) from App Service zip deploy to Azure Container Apps:
  - keeps the existing unit/integration + PostgreSQL smoke test gate
  - builds `backend/Dockerfile --target worker`
  - pushes `pfcd-worker:${GITHUB_SHA}` to ACR
  - deploys `extracting`, `processing`, and `reviewing` workers through a matrix job
  - bootstraps each worker Container App with a public image on first deploy so the system-assigned identity exists before the final private-image revision is applied
  - grants each worker identity `AcrPull`, `Key Vault Secrets User`, and `Azure Service Bus Data Owner`
  - renders a YAML manifest for the final worker revision with:
    - ingress disabled
    - `PFCD_WORKER_ROLE` pinned per worker app
    - Key Vault-backed secret refs for `DATABASE_URL`, `AZURE_STORAGE_CONNECTION_STRING`, and `AZURE_SERVICE_BUS_CONNECTION_STRING`
    - an `azure-servicebus` custom scale rule using `identity: system`
- Removed the App Service-only HTTP warmup shim from [backend/app/workers/runner.py](/Users/karthicks/kAgents/Projects/PFCD-V2/backend/app/workers/runner.py), including its HTTP server and threading imports.
- Updated [REFERENCE.md](/Users/karthicks/kAgents/Projects/PFCD-V2/REFERENCE.md) so the repo layout, Azure infrastructure, CI/CD notes, and GitHub Actions variable table now describe the worker ACA/KEDA deployment path rather than the old `WEBSITE_RUN_FROM_PACKAGE` flow.

### Decisions

- Kept worker runtime Service Bus access on the existing `AZURE_SERVICE_BUS_CONNECTION_STRING` path to avoid coupling infrastructure migration with a runtime auth rewrite.
- Used managed identity specifically for the Container Apps Service Bus scaler so queue-depth scaling no longer depends on a scaler-side connection string.
- Left active queue-processing verification to the live Azure deploy path; the repo change establishes the CI/CD and manifest shape, but production validation still needs a real deployment run.

### Open follow-up

- Confirm the worker ACA YAML is accepted by Azure exactly as written and that each Service Bus queue scales its matching worker from zero.
- Complete PostgreSQL cutover cleanup (`#27` Part B) now that backend and worker Container App workflows exist in repo.
