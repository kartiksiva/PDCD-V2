# PFCD Video-First v1 — Next Implementation To-Do List

**Current state:** Skeleton phase approved. API contract, state machine, SQL schema, Service Bus
orchestration, and export scaffolding are implemented. All agent logic is stubbed.

**Next phase:** Functional Implementation (Weeks 2–6, per PRD §14 milestones).

---

## Phase 2 — Agent Implementation (Weeks 2–4)

### 2.1 Data Extraction Agent (`extracting` phase)
> PRD §6, §8.3.1, §8.5 | OBS-02

- [ ] Integrate **Azure AI Speech** SDK for audio transcription from video/audio inputs
  - Accept `.mp4`, `.wav`, `.mp3`; extract audio track before transcription
  - Capture word-level timestamps and speaker diarization output
  - Persist raw transcript to `evidence/` blob container
- [ ] Integrate **Azure AI Vision** for key-frame extraction and OCR
  - Apply `frame_extraction_policy` from `input_manifest` (`sample_interval_sec`, `scene_change_threshold`)
  - Respect `ocr_trigger` policy (`scene_change_only`, `always`, `text_density`)
  - Store extracted frames in `evidence/` blob container with `frame_anchor_format`
- [ ] Normalise all extracted artifacts into canonical evidence objects:
  - `source`, `anchor` (timestamp range or frame ID), `confidence`, `actor`, `text_snippet`
- [ ] Persist evidence graph to blob storage as `evidence_graph.json` per job
- [ ] Implement `audio_detected` heuristic (silence ratio / waveform RMS)
- [ ] Detect `transcript_declared_vs_detected` mismatch and write to `input_manifest`
- [ ] Emit `agent_runs` entry with `duration_ms`, `cost_estimate_usd`, `confidence_delta`
- [ ] Add cost pre-flight warning when `estimated_cost_usd > cost_cap_usd * 0.8` (PRD §8.13)

### 2.2 Processing Agent (`processing` phase)
> PRD §6, §8.3.1, §8.6, §8.7, §8.8

- [ ] Implement **sequence reconstruction** using ranked evidence (video > audio > transcript; PRD §7)
- [ ] Build **step extraction** against Azure OpenAI (profile-routed: `gpt-4.1-mini` / `gpt-4o`)
  - Remove transcript-only artifacts (cue numbers, VTT timestamps, facilitator noise)
  - Collapse near-duplicate adjacent steps with same actor/action context
  - Each step must carry `summary`, `actor`, `system`, `input`, `output`, `exception`, `source_anchors`
- [ ] Generate **PDD document** with all required keys (PRD §8.7):
  `purpose`, `scope`, `triggers`, `preconditions`, `steps`, `roles`, `systems`,
  `business_rules`, `exceptions`, `outputs`, `metrics`, `risks`
- [ ] Generate **SIPOC map** (PRD §8.8):
  - Each row: `supplier`, `input`, `process_step`, `output`, `customer`
  - Each row must include `step_anchor` and `source_anchor`; missing links require `anchor_missing_reason`
- [ ] Persist `draft_candidate` artifact to blob storage
- [ ] Emit `agent_runs` entry with cost and duration

### 2.3 Reviewing Agent (`reviewing` phase)
> PRD §8.9, §8.11, §8.12, §10

- [ ] Implement **transcript/video alignment check** (PRD §8.5):
  - Compare first-N-seconds overlap using token/sequence similarity
  - Set `transcript_media_consistency.verdict`: `match` | `inconclusive` | `suspected_mismatch`
  - Populate `similarity_score`
  - On mismatch: reduce confidence, add `WARNING` review flag
- [ ] Implement **evidence strength scoring**:
  - `high` = video + audio + transcript aligned
  - `medium` = video + audio only, or transcript confirmed
  - `low` = frame-only or transcript-fallback
  - `insufficient` = no usable inputs
- [ ] Implement **quality gates** (PRD §10):
  - PDD contains all required keys
  - SIPOC has at least one row with valid `step_anchor` and `source_anchor`
  - JSON schema validation against PDD/SIPOC schemas
  - If evidence strength is `insufficient`, force `BLOCKER` flag and hold draft
- [ ] Set `agent_review.decision`: `approve_for_draft` | `needs_review` | `blocked`
- [ ] Populate `review_notes.flags[]` with `code`, `severity`, `message`, `requires_user_action`
- [ ] Annotate assumptions and confidence reductions for all `needs_review` transitions
- [ ] Persist `review_snapshot` artifact to blob storage
- [ ] Emit `agent_runs` entry with cost and duration

---

## Phase 2 — Adapter & Extensibility (Week 2–3)

### 2.4 `IProcessEvidenceAdapter` pattern
> PRD §8.2 | OBS-02

- [ ] Define `IProcessEvidenceAdapter` abstract base class with:
  - `detect(input_file) -> bool`
  - `normalize(input_file, blob_client) -> List[EvidenceObject]`
  - `extract_facts(evidence) -> List[StructuredFact]`
  - `render_review_notes(evidence) -> List[ReviewFlag]`
- [ ] Implement concrete adapters:
  - `VideoAdapter` — wraps Azure Speech + Vision extraction
  - `AudioAdapter` — wraps Azure Speech transcription only
  - `TranscriptAdapter` — parses `.txt` / `.vtt` with speaker/timestamp extraction
- [ ] Wire adapter selection into the `extracting` worker via `source_type` routing
- [ ] Ensure new adapters do not change public API contracts (additive fields only)

---

## Phase 2 — Infrastructure Upgrades

### 2.5 Service Bus tier upgrade
> OBS-01 | PRD §8.4

- [ ] Upgrade Service Bus namespace from `Basic` to `Standard` SKU in `infra/dev-bootstrap.sh`
  - Required for Topics/Subscriptions if parallel agent fan-out is added later
  - Update `README.md` verification commands to reflect new tier

### 2.6 Azure Monitor integration
> PRD §8.4, §11

- [ ] Enable **Application Insights** on the App Service and worker processes
- [ ] Emit structured telemetry events for:
  - Job state transitions
  - Agent run durations and costs
  - Queue depth and processing latency
- [ ] Configure Azure Monitor alerts:
  - Job failure rate > 5% in 15 min
  - Agent cost exceeding profile cap
  - Service Bus DLQ message count > 0
- [ ] Add `budget alert` for dev environment (non-blocking; manual portal step per `IMPLEMENTATION_SUMMARY.md`)

### 2.7 Blob SAS upload path
> PRD §8.1, §8.4

- [ ] Add `POST /api/jobs/{job_id}/upload-url` endpoint returning a time-limited Azure Blob SAS URL
  per input file so clients upload directly to Blob Storage (bypassing the API for large files)
- [ ] Validate upload completion before transitioning job to `QUEUED` → `extracting`
- [ ] Store raw upload path in `input_manifest` for extraction worker

---

## Phase 3 — Exports, Retention, Quality (Week 4–5)

### 3.1 Evidence-linked PDF/DOCX export
> PRD §8.10

- [ ] Embed referenced **frame captures** in PDF/DOCX when linked to at least one PDD step or SIPOC row
- [ ] Include **OCR snippet** and confidence score alongside each frame in the export
- [ ] Add **evidence bundle manifest** section listing:
  - Frame image URIs/IDs, anchor ranges, and confidence scores
- [ ] For formats that cannot embed binary assets (Markdown, JSON) add clear
  `"Evidence not included in this export format"` note with manifest reference

### 3.2 TTL and cleanup worker
> PRD §8.4, §11

- [ ] Implement a TTL worker that runs on a schedule (daily cron or Azure Function timer):
  - Scans `jobs` where `ttl_expires_at < NOW()` and `cleanup_pending = true`
  - Deletes blob artifacts from `uploads/`, `evidence/`, `exports/` containers
  - Sets `status = expired` and clears `cleanup_pending`
- [ ] Confirm blob lifecycle management policy is set in `infra/dev-bootstrap.sh`
  (7-day auto-delete on `uploads/` and `evidence/` containers)

### 3.3 Speaker resolution reconciliation
> PRD §8.1

- [ ] On `PUT /api/jobs/{job_id}/draft` with `speaker_resolutions`:
  - Apply resolution mapping to `draft.pdd.steps[].actor` values
  - Mark affected steps as `user_reconciled_at = now()`
  - Persist updated resolutions back to `input_manifest.speaker_resolutions`
- [ ] Surface unresolved `Unknown Speaker` actors as `WARNING`-severity review flags

### 3.4 Cost estimation pre-flight
> PRD §8.13

- [ ] Before dispatching `extracting` message, compute estimated cost from:
  - `input_manifest.video.duration_hint_sec` × per-minute rate for selected profile
- [ ] If `estimated_cost_usd > cost_cap_usd * 0.8` OR quality profile duration > 90 min:
  - Return `202 Accepted` with `cost_warning` payload instead of immediately enqueuing
  - Client must confirm via `POST /api/jobs/{job_id}/confirm-cost` to proceed
- [ ] Persist `cost_warning` in job payload

---

## Phase 3 — Testing and CI

### 3.5 Integration tests
> PRD §12 acceptance criteria

- [ ] Add `tests/integration/` layer (requires `AZURE_SERVICE_BUS_CONNECTION_STRING`)
  - Full job lifecycle: `POST /api/jobs` → worker phases → `NEEDS_REVIEW`
  - Finalize with no blockers → `COMPLETED` + all exports accessible
  - Finalize blocked by `BLOCKER` flag → 409 returned
- [ ] Acceptance scenario tests (PRD §12):
  - Video + audio + matching transcript → steps align to recorded sequence
  - Video + audio + unrelated transcript → mismatch flag, reduced confidence
  - Video without audio + transcript → frame-first markers, reduced confidence
  - Transcript-only fallback → valid draft with explicit source assumptions

### 3.6 CI pipeline hardening
> `REVIEW_CLOSURE_2026-03-21.md` OBS-04

- [ ] Add `pytest tests/unit/` step to `.github/workflows/deploy-backend.yml`
  - Run before zip deploy; fail the pipeline on any test failure
- [ ] Add dependency caching for `requirements.txt` in CI
- [ ] Add integration test job (gated on `AZURE_SERVICE_BUS_CONNECTION_STRING` secret availability)
- [ ] Enforce linting: add `ruff` check step to CI

### 3.7 Pre-flight Azure dependency check
> PRD §13 risks

- [ ] Add `GET /health/readiness` endpoint that actively probes:
  - Azure SQL connectivity (lightweight `SELECT 1`)
  - Service Bus namespace reachable
  - Blob Storage container accessible
  - Azure OpenAI deployment responds to a minimal prompt
  - Azure Speech endpoint accessible
- [ ] Emit a startup warning log if any dependency is unavailable (non-fatal for local dev)

---

## Phase 4 — Frontend (Week 5)

### 4.1 Review/Edit UI
> PRD §8.9, §5 personas

- [ ] Scaffold `frontend/` (React or vanilla JS; to be decided)
- [ ] Job creation form: file picker, profile selector, Teams metadata input
- [ ] Job status polling page with phase progress indicator
- [ ] Draft review view:
  - PDD step list with inline edit (summary, actor, system)
  - SIPOC table with source anchor links
  - Review flags panel (BLOCKER / WARNING / INFO)
  - Warning band when `transcript_media_consistency.verdict == suspected_mismatch`
  - Speaker resolution input (map `Unknown Speaker` → named role)
- [ ] Save draft → `PUT /api/jobs/{job_id}/draft`
- [ ] Finalize button (disabled when blockers exist)
- [ ] Export download links (JSON, Markdown, PDF, DOCX)

---

## Tracking: Open Items from Review Closure

| ID | Item | Status |
|----|------|--------|
| OBS-01 | Service Bus `Basic` → `Standard` SKU | ☐ Pending (§2.5) |
| OBS-02 | `IProcessEvidenceAdapter` pattern | ☐ Pending (§2.4) |
| OBS-03 | Real evidence precedence logic | ☐ Pending (§2.2) |
| OBS-04 | Durable persistence (done) + integration tests | ✅ Done / ☐ Tests pending |
| OBS-05 | Full SIPOC schema validation + quality gates | ☐ Pending (§2.3) |
| OBS-06 | Azure OpenAI deployment region confirmation | ☐ Manual step — re-run bootstrap with supported model/version |

---

## Tracking: Code Review Fixes (all done)

| Fix | Status |
|-----|--------|
| ServiceBus resource leak in `receive()` | ✅ Fixed |
| Race condition on finalize / FINALIZING guard | ✅ Fixed |
| Worker status guards for terminal states | ✅ Fixed |
| Async/sync mismatches (`lifespan`, `enqueue`) | ✅ Fixed |
| Structured logging throughout | ✅ Fixed |
| DB indexes on `agent_runs.job_id`, `job_events.job_id` | ✅ Fixed |
| Session type hint, path traversal, null draft guard | ✅ Fixed |
| PDF encoding bug (`ln=True`, em-dash) | ✅ Fixed |
| Worker + export + storage tests (14 new) | ✅ Fixed |
