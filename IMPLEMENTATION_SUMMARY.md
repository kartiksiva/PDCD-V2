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
- `kernel_factory.py`: builds SK `Kernel` using `DefaultAzureCredential` + `AzureOpenAIChatCompletion`
- `extraction.py`: `_call_extraction` (async SK invocation) + `run_extraction` synchronous wrapper via `asyncio.run`
- `processing.py`: `_call_processing` (async SK invocation) + `run_processing` synchronous wrapper via `asyncio.run`
- `reviewing.py`: pure-Python reviewing agent (no LLM call; deterministic quality-gate logic)
- `openai_client.py`: retained for reference only; unused in production path

### Anchor Alignment Engine (`alignment.py`)

- `run_anchor_alignment(manifest, extraction_result)` validates VTT cue timestamps against section-label anchors produced by extraction
- VTT cue parsing with 2-second tolerance window for timestamp matching
- Confidence penalty applied when anchor count falls below threshold or cues are missing
- Emits `anchor_alignment_summary` signal persisted to `agent_signals` in job payload
- Verdict values: `match`, `inconclusive`, `suspected_mismatch` (per PRD §8.5)

### Evidence Strength Computation (`evidence.py`)

- `compute_evidence_strength(manifest, extraction_result)` implements PRD §7 source hierarchy:
  - `has_video + has_audio` → `"high"` (Priority 1)
  - `has_video + transcript` (no audio) → `"medium"` (Priority 2)
  - `audio_only` → `"medium"` (Priority 3)
  - `transcript_only` → `"low"` (Priority 4)
- Confidence degradation: mean confidence < 0.60 downgrades strength by one tier
- Bug fix: `has_video + has_audio` with no transcript was incorrectly returning `"medium"`; now correctly returns `"high"`
- `evidence_strength` initial sentinel in `default_job_payload()` changed from `"medium"` to `None` to distinguish uncomputed from computed-medium

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

## Outstanding Items

| Item | Status |
|------|--------|
| Evidence-linked PDF/DOCX rendering (frame captures, OCR snippets, evidence bundle manifest) | Not started |
| Integration and E2E tests | Not started |
| CI test step in GitHub Actions workflow | Not started |
