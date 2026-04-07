# CLAUDE.md — AI Assistant Guide for PDCD-V2

This file provides context, conventions, and workflows for AI assistants working on this repository.

---

## Session Bootstrap Protocol (MANDATORY)

**At the start of every task or session, before writing any code or making any changes:**

1. Read `CLAUDE.md` (this file) — conventions, rules, status
2. Read `IMPLEMENTATION_SUMMARY.md` — rolling log of what has been built and what remains
3. Read `prd.md` — authoritative product requirements; never modify requirements, only the progress section
4. Read `REFERENCE.md` only when navigating files, setting up the environment, writing infra/config code, or checking API/data model details

These files are the persistent project memory. Context is cleared between sessions, so these files are the only source of truth for current project state.

**After completing any meaningful work:**

Update these files to reflect the new state:
- `CLAUDE.md` → update Implementation Status section (date, Done/Not-yet lists)
- `IMPLEMENTATION_SUMMARY.md` → append a new subsection or update the relevant section with what was built, bugs fixed, design decisions made
- `prd.md` → update the Implementation Progress milestone table at the bottom only; never edit requirements
- `REFERENCE.md` → update only when APIs, infra naming, file layout, or env vars actually change (it is stable reference, not a session log)

Keep updates factual and concise. Future Claude sessions depend on these files being accurate.

---

## Project Overview

**PFCD Video-First v1** is an Azure-native process documentation system. It ingests video/audio/transcript evidence, runs agentic extraction and review pipelines, and produces structured process documentation (PDD + SIPOC) in multiple export formats.

The system has completed its skeleton phase. The API, state machine, SQL schema, Azure orchestration, and core agent layer (extraction, processing, reviewing, alignment, evidence strength) are all implemented. Real LLM calls use Semantic Kernel 1.x via `DefaultAzureCredential`.

Reference documents:
- `prd.md` — authoritative product requirements and evidence hierarchy rules
- `AGENTS.md` — repository coding and PR guidelines
- `GEMINI.md` — architecture overview and planning context
- `REVIEW_CLOSURE_2026-03-21.md` — skeleton approval status and conditions

For file layout, tech stack, env vars, API endpoints, data model, Azure infra, and CI/CD details → see `REFERENCE.md`

---

## Authentication

All `/api/*` endpoints require the `X-API-Key` header when `PFCD_API_KEY` is set.

| Scenario | Result |
|----------|--------|
| `PFCD_API_KEY` unset | Auth disabled — all requests pass (local dev) |
| Header absent, auth enabled | `401 Unauthorized` |
| Header present but wrong | `403 Forbidden` |
| Header matches `PFCD_API_KEY` | Request proceeds normally |

`/health` is always public regardless of `PFCD_API_KEY`.

Uses `secrets.compare_digest` to prevent timing attacks. Implemented in `backend/app/auth.py`.

---

## Job State Machine

```
QUEUED → PROCESSING → NEEDS_REVIEW → FINALIZING → COMPLETED
                                                 ↘ FAILED
```

- `JobStatus` enum defined in `backend/app/job_logic.py`
- Transitions driven by Service Bus worker phases (extracting → processing → reviewing)
- `phase_attempt` tracks retry count per phase
- `error` field (JSON TEXT) stores exception details on failure

---

## Code Conventions

### Python Style

- **Indent:** 4 spaces
- **Classes:** `PascalCase` (e.g., `JobRepository`, `ExportStorage`)
- **Functions/methods/variables:** `snake_case`
- **Constants:** `UPPER_SNAKE_CASE` (e.g., `MAX_UPLOAD_BYTES`)
- **Private helpers:** `_leading_underscore` (e.g., `_utc_now`, `_serialize`)
- **Enums:** `PascalCase` class, `UPPER_CASE` members (e.g., `JobStatus.QUEUED`, `ReviewSeverity.BLOCKER`)

### Async Pattern

All blocking DB operations are wrapped:
```python
result = await anyio.to_thread.run_sync(JOB_REPO.get_job, job_id)
```

FastAPI endpoints use `async def` throughout.

### Factory Pattern

Services use `from_env()` classmethods for construction:
```python
JOB_REPO = JobRepository.from_env()
EXPORT_STORAGE = ExportStorage.from_env()
ORCHESTRATOR = ServiceBusOrchestrator()
```

This keeps environment variable reading isolated and makes testing via monkeypatch easy.

### Repository Pattern

All persistence goes through `JobRepository` in `repository.py`. Do not access `SessionLocal` or ORM models directly from endpoints — call repository methods.

### Context Managers

- `session_scope()` in `db.py` wraps DB sessions with commit/rollback
- `_lifespan()` in `main.py` handles app startup (calls `JOB_REPO.init_db()`)

### Error Handling

- Use `HTTPException` with appropriate status codes (400, 409, 410, 413, 503)
- Store exception details in the `error` JSON field on the job record
- Do not add error handling for scenarios that cannot happen; trust internal guarantees

### Timestamps

Always use `datetime.now(timezone.utc).isoformat()` for UTC timestamps stored as ISO 8601 strings.

### IDs

Use `str(uuid4())` for all new identifiers.

---

## Evidence Hierarchy (from PRD)

When working on extraction or review logic, respect this priority order:

1. **Video** (highest evidence value)
2. **Audio/transcript** derived from video
3. **Standalone transcript**
4. **Document/slide** (lowest)

If video and transcript conflict, video evidence takes precedence. This rule must be implemented in the evidence scoring and review phase.

---

## Cost Profiles

| Profile | Model | Cost Cap |
|---------|-------|----------|
| `balanced` | GPT-4o-mini | $4 |
| `quality` | GPT-4o | $8 |

Track per-run estimates in the `agent_runs.cost_estimate_usd` column. Respect profile caps when scheduling agent calls.

---

## Commit Style

Follow conventional commits:

```
feat: add transcript alignment engine
fix: correct phase retry counter reset
docs: update API endpoint table in README
refactor: extract evidence scoring to separate module
chore: bump SQLAlchemy to 2.0.38
```

---

## PR Guidelines

- Brief summary of user-facing change
- Link to relevant PRD section or decision
- List validation steps actually run
- Note any Azure resource or config impact
- Include log snippets for workflow changes

---

## Security Rules

- **Never** hardcode secrets, connection strings, or credentials
- All secrets go in environment variables or Azure Key Vault
- Redact transcript/video identifiers in logs by default
- Use `DefaultAzureCredential` — do not use storage shared keys or SAS tokens in application code
- Validate file size at the API boundary (`MAX_UPLOAD_BYTES = 500 * 1024 * 1024`)

---

## Current Implementation Status (as of 2026-04-07)

**Done:**
- FastAPI endpoints and job lifecycle API
- SQL schema and Alembic migration
- Job state machine (QUEUED → COMPLETED/FAILED)
- Service Bus message queuing and worker framework
- Blob/local export storage abstraction
- Azure infrastructure bootstrap script
- TTL/cleanup worker (`workers/cleanup.py` — expiry scan + data purge)
- Static API key authentication (X-API-Key header, 401/403, timing-safe)
- Real agent logic: extraction (SK + asyncio.run) and processing (SK + asyncio.run)
- Semantic Kernel migration (replaces `openai` SDK, uses `DefaultAzureCredential`)
- Transcript/video anchor alignment engine (`alignment.py` — VTT cue parsing, 2s tolerance, confidence penalty, first-60s consistency scoring, numeric `similarity_score`, PRD §8.5 verdict; full token similarity pending Azure Speech)
- Evidence strength computation (`evidence.py` — PRD-compliant source hierarchy, confidence degradation)
- Worker App Service deployment workflow (`deploy-workers.yml` — parallel extracting/processing/reviewing)
- `IProcessEvidenceAdapter` contract + `TranscriptAdapter` (VTT/TXT) + `VideoAdapter` (metadata stub) + `AdapterRegistry`
- Extraction agent uses adapter-normalized content (VTT cleaned, inline anchors, `document_type_manifests` stored)
- SIPOC schema validation (`sipoc_validator.py` — per-row field check, step_anchor cross-ref, anchor classification, quality gate)
- Evidence-linked PDF/DOCX/Markdown exports (`export_builder.py` — evidence bundle manifest, OCR snippets, anchor cross-ref, real DOCX via python-docx; PRD §8.10)
- 205 tests passing (162 unit + 43 integration)
- CI test step in GitHub Actions (`deploy-backend.yml` — `test` job gates `deploy`; pytest over unit + integration with SQLite)
- Bug-fix pass (2026-04-07): OCR anchor field, alignment verdict computation + media gate, runner dead-branch cleanup, AgentRun incremental insert, transcript_mismatch guard in reviewing agent
- Azure end-to-end deployment validated (2026-04-07): all four App Services running (pfcd-dev-api + 3 workers); fixed worker 504 deploy timeout (`--async true`), semantic-kernel pre-release dep (`azure-ai-agents>=1.2.0b3`), worker ContainerTimeout (health HTTP server in runner.py), correct OpenAI endpoint (`southindia.api.cognitive.microsoft.com`), `Cognitive Services OpenAI User` RBAC assigned to all managed identities; `AZURE_OPENAI_ENDPOINT` and `AZURE_OPENAI_DEPLOYMENT_NAME` wired into deploy-workers.yml via GitHub secrets
