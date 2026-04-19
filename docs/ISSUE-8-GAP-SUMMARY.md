# Issue #8 Gap Summary

Source issue: [GitHub issue #8](https://github.com/kartiksiva/PDCD-V2/issues/8)

Scope: compare the current repository state against `prd.md` and identify the highest-signal implementation gaps. This summary is based on the current codebase, not only on prior handoff notes.

## Overall read

The repository is no longer in an early scaffold state. The core async lifecycle, review/edit loop, export generation, worker orchestration, speaker resolution, frame persistence, and transcript/media alignment are implemented and covered by unit plus integration tests.

The biggest remaining gaps are no longer around basic CRUD or draft generation. They are concentrated in:

1. truly Azure-native media understanding and routing
2. ingestion and cost-governance workflows promised by the PRD but not exposed in API/UI
3. operational readiness features such as readiness probes, monitoring, and alerting
4. broader source-type support beyond transcript and video

## Section-by-section status

| PRD area | Status | Notes |
|---|---|---|
| §8.1 Upload and ingestion | Partial | Uploads work, but the flow is direct file upload plus local path persistence, not SAS upload metadata and Blob-first ingestion. |
| §8.2 Adapter extensibility | Partial | Adapter contract exists, but only `transcript` and `video` are registered today. |
| §8.3 Provider and model routing | Partial | Profile selection exists, but routing is still chat-model-centric and does not implement the full Azure Speech/Vision/OpenAI matrix from the PRD. |
| §8.4 Azure-native mapping | Partial | Core Azure resources exist, but monitoring/readiness/ops hooks are incomplete. |
| §8.5 Media + transcript consistency | Mostly implemented | First-window alignment and text similarity are present. |
| §8.6 Step extraction | Partial | Transcript-driven extraction is strong; frame-only and audio-only fidelity still trail the PRD intent. |
| §8.7 PDD | Implemented | Required keys, review gating, and editable review UI are present. |
| §8.8 SIPOC | Implemented | Provenance, validation, and blocker gating are present. |
| §8.9 Review/finalize | Implemented | Review flags, save-before-finalize, blocker enforcement, and edit loop are present. |
| §8.10 Exports | Partial | Linked evidence is exported, but referenced frame media is still metadata-first rather than embedded evidence assets. |
| §8.11 Agentic workflow contracts | Mostly implemented | `agent_runs`, decisions, flags, checkpoints, retries, and payload hashes exist. |

## Highest-confidence gaps

### 1. Upload/integration path is not yet Blob-first or SAS-based

PRD expectation:
- API accepts SAS upload metadata.
- Upload handler writes Blob-backed metadata and orchestration state.
- Future-friendly endpoint for upload URL generation.

Current code:
- `backend/app/main.py` exposes `POST /api/upload`, reads the full file into memory, and writes it to `UPLOADS_DIR`.
- `frontend/src/api.js` uploads with multipart form-data directly to that endpoint.
- There is no `POST /api/jobs/{job_id}/upload-url` flow, no SAS handoff, and no client-side Blob upload flow.

Impact:
- Local/dev flow works, but the ingestion contract still differs from the PRD’s Azure-native upload design.
- Large-file behavior is bounded by the API process rather than offloaded to Blob uploads.

### 2. The pipeline is still transcript-first in key places instead of fully video-first

PRD expectation:
- Video with audio is the primary source of truth.
- Transcript should support alignment and wording, not dominate sequence extraction.
- Video without audio should still use frame/OCR evidence with explicit penalties.

Current code:
- `backend/app/agents/extraction.py` builds extraction content with uploaded transcript preferred over video-derived content when both exist.
- `backend/app/agents/adapters/video.py` still documents metadata-only fallback behavior and keeps `extract_facts()` as a stub.
- `backend/app/agents/vision.py` performs frame analysis through chat-completions vision prompts, not Azure AI Vision OCR/frame pipelines.

Impact:
- The product works for transcript-rich jobs, but the PRD’s stronger video-first claim is only partially true in the current implementation.
- Frame-first and audio-only quality remains more limited than the requirements imply.

### 3. Provider routing does not yet implement the PRD’s Azure Speech/Vision/OpenAI matrix

PRD expectation:
- Separate routing across `azure_openai`, `azure_speech`, `azure_vision`, and optional `azure_ollama`.
- Distinct agent routing profiles for extraction, processing, and reviewing.
- `provider_effective` should reflect the resolved Azure deployments used per capability.

Current code:
- `backend/app/job_logic.py` resolves profile config to one chat deployment plus cost cap.
- Speech transcription lives in `backend/app/agents/transcription.py`, but routing is effectively OpenAI/Azure OpenAI oriented.
- Vision analysis in `backend/app/agents/vision.py` also routes through OpenAI-compatible chat endpoints.

Impact:
- The system has profile-aware model selection, but not the full multimodal provider plan described in the PRD.
- `provider_effective` is narrower than the requirement implies.

### 4. Cost governance is informational only; confirmation flow is missing

PRD expectation:
- Estimate cost before or during execution.
- Warn around 80% of cap.
- Require explicit confirmation through `POST /api/jobs/{job_id}/confirm-cost` for higher-cost scenarios.

Current code:
- `backend/app/job_logic.py` tracks cumulative estimated spend and adds a `cost_cap_exceeded` warning after the cap is crossed.
- There is no `confirm-cost` endpoint in `backend/app/main.py`.
- `frontend/src/components/CreateJob.jsx` has no cost-review or confirmation UX.

Impact:
- The repository tracks cost after work has already started, but it does not yet implement the PRD’s user-facing cost gate.

### 5. Teams metadata is accepted by the backend contract but not captured by the UI

PRD expectation:
- Capture Teams metadata such as meeting id, subject, organizer, participants, speaker map, and recording markers.
- Use that metadata to improve actor assignment and review.

Current code:
- `backend/app/job_logic.py` accepts `teams_metadata`.
- `backend/app/agents/extraction.py` uses `teams_metadata.transcript_speaker_map` as a speaker hint.
- `frontend/src/components/CreateJob.jsx` has no form fields for Teams metadata entry or upload-side metadata capture.

Impact:
- Backend support exists, but the end-to-end product flow still cannot reliably collect the metadata the PRD expects.

### 6. Source-type extensibility is only partially realized

PRD expectation:
- Baseline support for `video`, `audio`, and `transcript`, with extension points for `doc` and future evidence types.

Current code:
- `backend/app/agents/adapters/base.py` defines a clean adapter contract.
- `backend/app/agents/adapters/registry.py` registers only `TranscriptAdapter` and `VideoAdapter`.
- `frontend/src/components/CreateJob.jsx` lets users classify files as `audio` or `document`, but there is no dedicated audio or document adapter path in the registry.

Impact:
- The API contract is extensible, but audio/document uploads still fall through the system with much less structured handling than the PRD suggests.

### 7. Exports include evidence linkage, but not full embedded evidence media

PRD expectation:
- PDF/DOCX exports include referenced frame captures and OCR snippets when linked to PDD/SIPOC content.

Current code:
- `backend/app/export_builder.py` builds a linked evidence bundle and includes frame capture metadata.
- The exports list frame capture keys and notes, but do not embed image binaries into PDF or DOCX output.

Impact:
- Evidence traceability is present, but the richer export presentation from the PRD is still only partially complete.

### 8. Operational readiness features are still missing

PRD expectation:
- Azure Monitor + Application Insights integration.
- Alerts for failures, DLQ growth, and cost overruns.
- Readiness checks beyond the existing health endpoint.

Current code:
- `backend/app/main.py` exposes `/health`, but there is no `/health/readiness`.
- `infra/dev-bootstrap.sh` provisions core Azure resources, but does not provision Application Insights or alert rules.
- Worker retry/dead-letter behavior exists in `backend/app/workers/runner.py`, but there is no operator-facing DLQ/replay workflow in the repo.

Impact:
- Runtime behavior is much stronger than before, but production-style observability is still behind the PRD.

## What is already strong

These areas look materially implemented and should not be re-triaged as primary gaps:

- Async job lifecycle and persistence in `backend/app/main.py`, `backend/app/repository.py`, and worker flow.
- Review gating and deterministic reviewer logic in `backend/app/agents/reviewing.py`.
- SIPOC validation and blocker enforcement in `backend/app/agents/sipoc_validator.py`.
- Draft edit/save/re-review and speaker resolution UI in `frontend/src/components/DraftReview.jsx`.
- Export generation for JSON, Markdown, PDF, and DOCX in `backend/app/export_builder.py`.
- Frame capture persistence in `backend/app/storage.py` and `backend/app/agents/adapters/video.py`.
- Unit and integration coverage under `tests/unit/` and `tests/integration/`.

## Recommended next implementation order

1. Add the missing ingestion and cost-governance contracts: `upload-url`, `confirm-cost`, and corresponding frontend UX.
2. Close the end-to-end Teams metadata gap by adding UI capture and persistence for the backend fields that already exist.
3. Finish true source-type coverage by adding at least an audio adapter and a minimal document adapter path.
4. Replace the remaining video-analysis shortcuts with the intended Azure-native speech/vision routing, especially for frame-first and audio-first cases.
5. Add operational readiness work: `/health/readiness`, Application Insights, and alert definitions.

## Reviewer-ready verdict

Issue #8 is best understood as a documentation/planning issue, not a request for a broad implementation spike. The repository has a solid core, but the PRD still overstates completeness around Azure-native ingestion, media routing, cost confirmation, operational readiness, and non-transcript source handling.
