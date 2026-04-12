# PFCD-V2 Review Pack for Gemini

## Request

Please review this implementation against the PFCD Video-First v1 PRD and the `prd-review-20032026.md` risk notes.

## Scope of this pass

- Implemented immediate plan actions from the latest run.
- Focus: infra bootstrap hardening + backend API skeleton for job lifecycle.
- No frontend/review UI behavior implementation yet.

## Files changed

- `infra/dev-bootstrap.sh`
- `infra/README.md`
- `backend/app/main.py`
- `backend/requirements.txt`
- `backend/README.md`
- `frontend/.gitkeep`
- `tests/.gitkeep`
- `AGENTS.md`/`SUGGESTIONS_FOR_CODEX.md` used as planning context only.

## Implemented behavior summary

### Infrastructure

- Added configurable deployment and bus SKUs:
  - `OPENAI_SKU_NAME` (default: `GlobalStandard`)
  - `SERVICE_BUS_SKU` (default: `Basic`)
- OpenAI deployment now uses `OPENAI_SKU_NAME`.
- Web app now stores additional runtime Azure OpenAI settings:
  - `AZURE_OPENAI_DEPLOYMENT_NAME`
  - `AZURE_OPENAI_MODEL_NAME`
  - `AZURE_OPENAI_MODEL_VERSION`
  - `AZURE_OPENAI_SKU_NAME`
- Added managed-identity Key Vault role assignment for web app:
  - role: `Key Vault Secrets User`
- Documented the above and env var extensions in `infra/README.md`.

### Backend (skeleton)

Implemented [FastAPI] endpoints in `backend/app/main.py`:
- `POST /api/jobs`
- `GET /api/jobs/{job_id}`
- `GET /api/jobs/{job_id}/draft`
- `PUT /api/jobs/{job_id}/draft`
- `POST /api/jobs/{job_id}/finalize`
- `GET /api/jobs/{job_id}/exports/{format}`
- `DELETE /api/jobs/{job_id}`
- `GET /health`

Other behaviors:
- In-memory job store (`dict`) with async simulated pipeline tasks.
- File size cap:
  - returns `413` when any input file > 500 MB.
- Agent skeleton phases:
  - extraction, processing, reviewing placeholder runs.
  - status model includes `queued`, `needs_review`, `finalizing`, `completed`, `failed`, `deleted`, etc.
- Draft guardrails:
- `GET /draft` returns 409 when draft unavailable.
- `PUT /draft` persists changes + speaker mappings.
- `POST /finalize` requires:
  - draft exists
  - user has saved draft
  - no blocker severity flags
- Exports:
  - `json`, `markdown`, `pdf`, `docx` routes available.
  - `pdf`/`docx` currently placeholders.
- `DELETE /api/jobs/{job_id}` transitions terminal deleted and cancels running pipeline task.

## API contract checks against PRD

### Implemented / aligned
- Endpoint set from PRD preserved.
- Additive metadata fields included in job payloads:
  - `input_manifest`, `transcript_media_consistency`, `provider_effective`, `review_notes.flags`, `agent_runs`.
- Status transitions now include reviewer/finalize gating logic.
- `transcript_media_consistency.verdict` present in default draft flow.

### Missing (must be implemented next)
- Real persistence (Azure SQL/Cosmos) and idempotent resume/retry checkpoints.
- Real Service Bus orchestration.
- Actual transcript-video alignment engine and evidence-strength computation.
- Real PDF/DOCX evidence-linked export rendering.
- Retry policy details, DLQ semantics, and cleanup workers.
- Schema validation / stricter reviewer decision gates (`approve_for_draft`, `needs_review`, `blocked`) with persistence.
- TTL/cleanup logic + cost telemetry.

## Risks introduced / open

- No durable storage: job/state loss on process restart.
- PDF/DOCX placeholders not yet compliant with PRD export traceability requirements.
- Error handling is simplified for skeleton path.
- No authentication/authorization layer yet.
- No worker-level partitioning by source type/doc-type adapters.

## Questions for Gemini review

1. Are the current state transitions and blocker checks in finalize behavior consistent with PRD §8.12 and §8.9?
2. Does payload shape for job metadata match additive contract intent, or are required fields still missing for this stage?
3. Is using `Basic` Service Bus + queue-only bootstrap acceptable for v1, given fan-out is deferred?
4. Do infra role assignments look correct (`webapp identity -> Key Vault Secrets User`) for runtime secret access in AAD-only mode?
5. Any critical mismatch between this skeleton and the planned evidence/adapter model that should be fixed before next implementation cycle?

## Suggested next implementation order (for follow-up)

1. Add Azure SQL/Service Bus-backed repositories and async worker services.
2. Implement transcript/media extraction adapters + consistency scoring.
3. Implement strong review schema + quality gates and blocker remediation.
4. Implement evidence-rich exports (PDF/DOCX embedding) with image manifest.
5. Add tests for job lifecycle and finalize/gating edge cases.

## Quick commands

```bash
# start backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

# inspect infra vars for bootstrap
cat infra/README.md
```
