# Product Requirements Document
## PFCD Video-First v1 (Fresh Build)

## 1) Product Vision
Build a fresh, video-first process documentation product where Teams recording workflows are the primary source of truth. The system must extract process flow from recording audio/video first, then use uploaded transcript as supportive evidence, not the default driver.

### Azure Native Baseline
- Implement the complete v1 platform on Microsoft Azure services.
- Use Azure managed AI services and Azure storage/eventing for deterministic, auditable, and scalable processing.
- Keep external API contracts stable while constraining runtime to Azure-hosted endpoints.

## 2) Problem
Current transcript-first behavior causes poor outcomes when transcript and video diverge. In meetings, recordings often contain richer, reliable sequence and speaker context, while transcripts can be stale, partial, or mismatched.

## 3) Goals
- Deliver reliable process documentation from video with audio.
- Use transcript only as an assistive signal, especially for Teams recordings.
- Fail gracefully with clear review flags when evidence is weak or misaligned.
- Keep output schema-compatible with existing MVP contracts: PDD + single SIPOC map.
- Preserve a simple internal-demo model: no authentication, async flow, review/edit, finalize, export.
- Deliver the first release as an Azure-native implementation using Azure-managed AI and infrastructure services.
- Support any process discovery video (any domain, team, or workflow type) using a source-agnostic extraction strategy.
- Deliver as an agentic AI pipeline with explicit data extraction, processing, and review agents before user-facing draft creation.

## 4) Non-Goals (v1)
- Not a full RPA orchestration platform.
- Not a legal/compliance repository.
- Not a real-time meeting assistant.
- Not multi-language transcription support.
- Not a generic slide/story generator.
- Not a custom on-prem ML training or inference stack.

## 5) Personas
**Process Analyst**
- Uploads team call/process recordings and wants quick as-is process documentation.

**SME/Manager**
- Reviews draft for correctness and approves/edits before final output.

**Operations Lead**
- Uses outputs to prioritize automation candidates and pain points.

## 6) Core Workflow
- User uploads at least one input (video, audio, transcript).
- API accepts SAS upload metadata and writes objects to Azure Blob Storage (raw and normalized paths).
- Upload handler writes job and manifest metadata to Azure SQL/Cosmos DB and captures Teams transcript markers.
- Orchestration is event-driven via Azure Service Bus Queue / Azure Queue Storage with status updates in database.
- Pipeline resolves evidence precedence using rules below.
- Processing is driven by a common evidence abstraction so different process domains and future supporting document types can be onboarded with the same output schema.
- Media understanding policy is resolved from a normalized `frame_extraction_policy` profile and attached to all frame-derived evidence for repeatable results.
- Agentic execution for each job:
  - **Data Extraction Agent**: extracts media artifacts (audio transcript, key frames, OCR, timing anchors) and normalizes them into evidence objects.
  - **Processing Agent**: applies sequence reconstruction, step extraction, and PDD/SIPOC generation from ranked evidence.
  - **Reviewing Agent**: performs consistency checks, risk/confidence scoring, schema validation, and sets review flags before draft is returned.
- Process extraction builds structured steps + SIPOC + operational facts using Azure AI services.
- Quality checks validate schema, minimum completeness, confidence, and source alignment.
- Draft enters needs_review with assumptions/risks.
- User edits/saves draft.
- Finalize generates export artifacts (persisted in Blob Storage) and marks completed.

## 7) Evidence Priority (NEW)
- **Priority 1**: Video with usable audio
- **Priority 2**: Uploaded transcript (supportive alignment source)
- **Priority 3**: Audio only
- **Priority 4**: Transcript only (fallback)

For video with audio, transcript can only adjust/confirm wording, not replace step sequence.

For video without audio, system must:

- require/allow transcript or separate audio,
- and clearly flag output as frame-first and alignment-limited.

## 8) Functional Requirements

### 8.1 Upload and Ingestion
- Accept at least one file: video, audio, transcript.
- Max size: 500 MB per file.
- Supported transcript formats: `.txt`, `.vtt`.
- Accept and parse Teams metadata when present.
- Teams metadata schema (v1):
  - meeting_id
  - meeting_subject
  - start_time_utc
  - organizer_name (or organizer_id)
  - participants
  - transcript_speaker_map (speaker_id -> display_name/role hints)
  - recording_markers (caption timestamps / turn boundaries, where available)
- Persist parsed speaker identity to support actor assignment before step extraction.
- For step extraction, unresolved speakers default to `Unknown Speaker` and are surfaced as `warning`-severity review flags.
- Review UI must allow manual resolution of `Unknown Speaker` to existing role/team participants (where available) before finalize.
- Unresolved speaker mappings may be edited and persisted back to manifest as `speaker_resolutions`.
- Speaker resolution does not trigger automatic re-extraction; it updates draft actor/role values and marks those steps as user-reconciled.
- Input model is `source_type` and `document_type` aware:
  - baseline source types: `video`, `audio`, `transcript`
  - extension point for future source types: `doc` (process notes, SOPs, checklists, etc.) and additional extractors.
- Persist `input_manifest` with:
  - source types, MIME, duration (where available), upload size
  - `audio_detected` (boolean)
  - `video_has_audio` (detected/declared)
  - `transcript_declared_vs_detected` mismatch flags
  - `frame_extraction_policy` for deterministic evidence capture:
    - `sample_interval_sec` (default 5)
    - `scene_change_threshold` (default 0.68)
    - `ocr_enabled` (boolean, default true)
    - `ocr_trigger` (`scene_change_only`, `always`, `text_density`)
    - `frame_anchor_format` (`timestamp_range`, `frame_id_only`)

### 8.2 Document-type extensibility (platform-level)
- Define a plugin adapter contract for new input/document types (`IProcessEvidenceAdapter`) with:
  - `detect()` -> source/doc type detection and validation
  - `normalize()` -> canonical evidence objects
  - `extract_facts()` -> optional structured evidence snippets
  - `render_review_notes()` -> provenance and confidence notes
- New document types map into canonical evidence model:
  - timestamps/anchors (or section markers when no native timing is available)
  - actor/action observations
  - source confidence
- Onboarding a new type must not change public API contracts (`/api/jobs*`), only additive fields.
- New document type adapter must emit `document_type_manifest` and confidence score for review notes.

### 8.3 Provider and Model Routing
- Provider options are Azure-native profiles (all hosted in Azure):
  - `azure_openai`: Azure OpenAI chat/vision models (for extraction, normalization, schema conversion)
  - `azure_speech`: Azure AI Speech for high-fidelity audio transcription
  - `azure_vision`: Azure AI Vision for frame analysis and OCR
  - `azure_ollama` (optional): Self-managed Ollama container on Azure VM/AKS for experimentation
- Model plan is chosen by provider profile and processing profile (`balanced`, `quality`).
- Video-with-audio defaults to Azure multi-modal + transcript path for the selected provider profile.
- If transcript-only is selected, run transcript-first with Azure media-understanding optional/disabled by policy.
- If no transcript and no audio in video, perform frame-only + optional OCR via Azure Vision, with explicit quality penalty.
- `provider_effective` records actual resolved Azure deployment names (for example `gpt-4o`, `gpt-4.1-mini`, `azure-ocr-v1`) after policy/routing overrides.

### 8.3.1 Agent Routing Profiles
- Data Extraction Agent uses speech/vision profile with higher tolerance for noisy streams and frame dropout.
- Processing Agent uses profile-appropriate reasoning model for sequence extraction and schema normalization.
- Reviewing Agent uses deterministic low-cost profile with strict schema/conformance and policy rules.
- Profile (`balanced`, `quality`) sets cost/time budgets and validation strictness independently per agent.
- Deployment matrix (Azure):
  - Balanced:
    - Extraction: `azure_speech` + `azure_vision.fast-frame`, `sample_interval_sec` 5, scene-change only for OCR
    - Processing: `azure_openai` `gpt-4.1-mini` with capped token window
    - Reviewing: `azure_openai` `gpt-4.1-mini` deterministic parser mode
  - Quality:
    - Extraction: `azure_speech` + `azure_vision.premium-frame`, dense scene analysis + OCR triggers
    - Processing: `azure_openai` `gpt-4o` with richer prompt templates
    - Reviewing: `azure_openai` `gpt-4.1` with stricter conformance instructions
- Per-profile cost budget:
  - Balanced target: USD 2–4 per hour source media
  - Quality target: USD 4–8 per hour source media
- Each agent includes `cost_estimate_usd` and `cost_cap_usd` against its profile-specific envelope.

### 8.4 Azure Native Azure Services Mapping
- Upload/API and job control: Azure App Service / Azure Container Apps (or Azure Functions for lightweight endpoints).
- Async orchestration: Azure Service Bus queue, optional Azure Durable Functions for stepwise fan-out/fan-in.
- File storage: Azure Blob Storage (raw uploads, normalized media, exports, signed URLs).
- State and metadata: Azure SQL Database (transactional job state) or Cosmos DB (document model option).
- Processing:
  - Azure AI Speech for transcript and confidence scoring.
  - Azure AI Vision for frames/OCR and visual understanding.
  - Azure OpenAI for structured extraction, normalization, and schema conversion.
- Security and secrets: Azure Key Vault.
- Monitoring: Azure Monitor + Application Insights for tracing, latency, errors, and cost metrics.
- Retention: Blob lifecycle management + SQL/Cosmos TTL policies enforce 7-day cleanup.
- Queue and handoff reliability:
  - Every queue message must carry `job_id`, `agent`, `attempt`, and deterministic `payload_hash`.
  - Use checkpointing by phase (`extracting`, `processing`, `reviewing`, `finalizing`).
  - Transient failures are retried with exponential backoff; after `max_retries`, message moves to DLQ for operator replay.
  - Reprocessing is idempotent by checkpoint key and persisted `agent_runs`.
- Agent execution pattern:
  - Dedicated worker services per role: Data Extraction, Processing, Reviewing.
  - Orchestrator hands off immutable artifacts between workers through queue topics.
  - Worker outputs persisted as `evidence_graph`, `draft_candidate`, and `review_snapshot`.

### 8.5 Media + Transcript Consistency
- New alignment check runs when both video and transcript exist.
- Use first N seconds overlap and token/sequence similarity on normalized text.
- Verdict values: `match`, `inconclusive`, `suspected_mismatch`.
- On inconclusive or suspected_mismatch, lower confidence and surface in review notes.
- Mismatch should reduce trust in transcript statements and favor frame/audio-derived sequence.

### 8.6 Step Extraction
- Output step list must represent process actions, not transcript fragments.
- Remove transcript-only artifacts (timestamps, cue numbers, prompt lines, facilitator questions).
- Collapse near-duplicate adjacent steps with same actor/action context.
- Always include source anchors (timestamp ranges or frame IDs) where available.
- Each step includes:
  - summary
  - actor/role
  - system/application
  - input/output
  - exception text (if observed)
  - source evidence anchors

- Frame-derived anchors must include:
  - policy used (`sample_interval_sec`, `scene_change_threshold`, `ocr_trigger`)
  - frame timestamp range
  - optional OCR region and confidence score.

### 8.7 PDD Document
- Required PDD keys:
  - purpose
  - scope
  - triggers
  - preconditions
  - steps
  - roles
  - systems
  - business_rules
  - exceptions
  - outputs
  - metrics
  - risks
- Keep language conservative: no invented roles/systems/assumptions not evidenced.

### 8.8 SIPOC
- Single consolidated map output:
  - supplier
  - input
  - process_step
  - output
  - customer
- Each row must include provenance:
  - `step_anchor` (one or more linked process step IDs)
  - `source_anchor` (timestamp/frame/section)
- At least one SIPOC row must include a valid `step_anchor` and `source_anchor` for quality-gate pass.
- Rows with missing links must include `anchor_missing_reason`.
- `frame_id_only` anchors are allowed only when timestamp extraction is unavailable (fallback path).

### 8.9 Review/Finalize
- If critical extraction fields are missing or low confidence, draft shows Needs Review markers.
- Draft always includes assumptions and confidence summary.
- Review UI shows warning band when video/transcript mismatch is detected.
- Finalize allowed only after user saves reviewed draft.
- Draft is shown only after Reviewing Agent emits `agent_review` and attaches review flags/blockers.
- Finalize state transitions:
  - If any `review_notes.flags[].severity == blocker` exists, finalize is blocked until user resolves the blocker in draft.
  - `warning` and `info` severities may still allow finalize, with warning summary shown in the draft header.

### 8.10 Exports
- Markdown, JSON, PDF, DOCX from finalized state only.
- Export content must match persisted finalized draft.
- Evidence media in exports:
  - PDF/DOCX exports include referenced frame captures and OCR snippets only when they are linked to at least one PDD step or SIPOC row.
  - Include evidence bundle manifest section listing frame image URIs/IDs, anchor ranges, and confidence scores.
  - Unsupported binary assets are omitted with a clear “Evidence not included in this export format” note.

### 8.11 Agentic Workflow Contracts
- Per-job artifacts and checkpoints required:
  - `agent_runs.extraction`
  - `agent_runs.processing`
  - `agent_runs.review`
- Additive fields to persist:
  - `agent_runs[]` with `agent`, `model`, `profile`, `status`, `duration_ms`, `cost_estimate_usd`, `confidence_delta`
  - `review_notes.flags[]` with `code`, `severity` (`blocker` | `warning` | `info`), `message`, `requires_user_action`
  - `agent_signals.transcript_media_alignment`
  - `agent_signals.evidence_strength`
- `agent_review.decision` (`approve_for_draft` | `needs_review` | `blocked`)
- Quality gating: `agent_review.decision` must be present before draft exposure.
- Draft gating and blocker handling:
  - `approve_for_draft`: system may render draft directly.
  - `needs_review`: draft is shown with warning/assurance markers; finalize allowed after explicit user save.
  - `blocked`: finalize is disabled until a user action clears blocker flags.
- `agent_runs` entries are the source of truth for idempotent resume and retry behavior.

### 8.12 Agent State Machine (v1)
- External job status remains: `queued`, `processing`, `needs_review`, `finalizing`, `completed`, `failed`, `expired`, `deleted`.
- Internal agent phases (for orchestration and tracing) follow:
  - `extracting` -> Data Extraction Agent running
  - `processing` -> Processing Agent running
  - `reviewing` -> Reviewing Agent running
  - `draft_ready` -> reviewing complete, draft candidate exists
- Transition rules:
  - `queued` -> `extracting`
  - `extracting` successful -> `processing`, failed transient -> retry from `extracting` with capped backoff, exhausted -> `failed`
  - `processing` successful -> `reviewing`, incomplete -> `needs_review`
  - `reviewing` success and decision `approve_for_draft` -> `draft_ready`
  - `reviewing` success and decision `needs_review` -> `draft_ready` with `warning` markers
  - `reviewing` success and decision `blocked` -> `needs_review` with blocker flags
  - `draft_ready` + any low-confidence or missing critical fields -> `needs_review`
  - `draft_ready` + user saves reviewed draft -> `finalizing` internal path
  - finalize success -> `completed`, finalize failure -> `failed`
- Invariant:
  - `finalize` API is effective only after a persisted user-reviewed draft exists and reviewing artifacts are present.
- On any transient bus, storage, or worker error, system rehydrates from last completed phase checkpoint and retries the next incomplete agent only.
- Any non-terminal state (`queued`, `extracting`, `processing`, `reviewing`, `needs_review`, `finalizing`) may transition directly to `deleted` on delete request.
- Deletion on active state cancels pending agent work and emits a terminal `deleted` state.

## 9) API and Contracts
Retain existing endpoints:

- `POST /api/jobs`
- `GET /api/jobs/{job_id}`
- `GET /api/jobs/{job_id}/draft`
- `PUT /api/jobs/{job_id}/draft`
- `POST /api/jobs/{job_id}/finalize`
- `GET /api/jobs/{job_id}/exports/{format}`
- `DELETE /api/jobs/{job_id}`

DELETE behavior:
- Job status transitions to `deleted`.
- In-progress pipeline runs are cancelled (best-effort with eventual consistency).
- User-visible draft and export references are immediately unavailable.
- Raw artifacts and normalized intermediates are marked for cleanup and removed by the 7-day retention job unless already hard-deleted.
- `GET /api/jobs/{job_id}` returns `status` from the full set in §8.12/§11 (`queued`, `processing`, `needs_review`, `finalizing`, `completed`, `failed`, `expired`, `deleted`).

Additive fields in job payload/progress:

- `input_manifest.video.audio_detected`
- `input_manifest.video.audio_declared`
- `input_manifest.video.frame_extraction_policy`
- `input_manifest.teams_metadata`
- `transcript_media_consistency.verdict`
- `transcript_media_consistency.similarity_score`
- `review_notes.flags` entries for mismatch/fragmentation
- `review_notes.flags[].severity`
- `provider_effective` when pipeline overrides UI selection
- `provider_effective.deployment` and `provider_effective.profile` fields to preserve Azure route resolution details.

## 10) Quality Gates (MVP)
- PDD includes all required keys.
- SIPOC has at least one valid row.
- At least one SIPOC row must include non-empty `step_anchor` and `source_anchor`.
- JSON schema validates.
- If evidence strength is weak, status must remain needs_review.
- Completed jobs require finalized and validated draft.
- Reviewing Agent must annotate assumptions and confidence reductions for all `needs_review` transitions.
- Draft finalization is blocked when any `review_notes.flags[].severity == blocker` exists.

## 11) Non-Functional Requirements
- Async processing with tracked status states:
  - queued
  - processing
  - finalizing
  - needs_review
  - completed
  - failed
  - expired
  - deleted
- Per-job cost and duration caps enforceable by profile.
- TTL: 7 days for files and artifacts.
- Cost target by profile:
  - balanced: USD 2–4 per hour source media
  - quality: USD 4–8 per hour source media
- API contract stable; additive metadata changes only.
- Azure resource quotas, job timeout, and budget alerts enforce per-job caps.
- Secrets and credentials are managed through Azure Key Vault (not embedded in code/config).
- All state transitions and processing metrics are emitted for Azure Monitor dashboards and alerting.

## 12) Acceptance Criteria
Given a Teams video+audio + matching transcript:

- Steps align to recorded sequence.
- Transcript text appears in evidence notes where it improves clarity.
- No VTT or facilitator prompt noise in process steps.

Given Teams video+audio + unrelated transcript:

- mismatch flag appears
- confidence is reduced
- output still generated but marked review-safe

Given video without audio + transcript:

- sequence is derived from frames + transcript
- output includes frame-evidence context marker
- user clearly informed about reduced confidence areas.

Given transcript-only fallback:

- valid draft generated with explicit source assumptions.

## 13) Risks and Mitigations
- OCR/visual-only ambiguity -> include confidence penalty and explicit assumptions.
- Overtrusting transcript -> enforce evidence precedence checks and review flags.
- Fragmented transcripts -> stop sentence-level noise and keep only operational actions.
- Provider drift in output formatting -> template-first prompt and deterministic post-normalization.
- New document-type onboarding risk -> require adapter-level tests and confidence contracts before release enablement.
- Agentic orchestration risk -> enforce idempotent handoffs and immutable artifacts between agents.
- Azure runtime dependency risk:
  - Azure AI Speech regional availability, model quota, and Azure OpenAI vision access approvals can delay Week 2/3 delivery.
  - Add pre-flight dependency check + fail-fast warning in staging before user-facing release.

## 14) Milestones
- **Week 1**: Skeleton backend, job lifecycle, ingestion contracts, file validation.
- **Week 2**: Video understanding agent and evidence precedence logic (assumes Speech/Vision + model access and quotas provisioned).
- **Week 3**: Process extraction model v1 with transcript cleanup and mismatch scoring.
- **Week 4**: PDD/SIPOC generator + quality-agent.
- **Week 5**: Review/edit frontend, finalize + exports.
- **Week 6**: Retention + end-to-end tests and hardening (transcript mismatch, no-audio video, video+transcript).

## 8.13 Upload Size Policy
- Default max upload size remains 500 MB per file.
- If a file exceeds 500 MB, the API returns `413` with a clear remediation message and suggests:
  - trim/re-encode source media, or
  - use segmented upload via external Azure Blob SAS in future release (post-v1).
- For quality profile runs where input bitrate and duration predict high cost risk:
  - surface estimate warning before processing starts when:
    - `estimated_cost_usd > cost_cap_usd * 0.8`, or
    - quality profile source duration > 90 minutes.
  - warning payload includes `estimated_cost_usd`, `cost_cap_usd`, and expected duration.

---

## Implementation Progress (as of 2026-04-05)

| Milestone | Status |
|-----------|--------|
| Week 1: Infrastructure & skeleton API | ✅ Complete |
| Week 2: Agent layer (extraction, processing, reviewing) | ✅ Complete |
| Week 3: Alignment + evidence strength | ✅ Complete |
| Week 4: Adapter pattern, SIPOC validation | ✅ Complete |
| Week 5: Evidence-linked exports | 🔲 Not started |
| Week 6: Integration/E2E tests, CI test step | 🔲 Not started |
