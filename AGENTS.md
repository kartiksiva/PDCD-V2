# Repository Guidelines

## Session Bootstrap Protocol (MANDATORY)

At the start of every session, before writing any code:

1. Read `AGENTS.md` (this file)
2. Read `IMPLEMENTATION_SUMMARY.md` — rolling log of what has been built and what remains
3. Read `prd.md` — authoritative requirements; never modify requirements, only the progress table
4. Read `REFERENCE.md` on demand — file layout, env vars, API/data model, Azure infra, CI/CD

## Issue Workflow (MANDATORY)

For every GitHub issue, always follow this exact order:

1. `git checkout main`
2. `git pull origin main`
3. Create a new branch for the issue (example: `codex/issue-9-upload-url`)
4. Implement only the issue scope on that branch
5. Run relevant tests and record exact commands/results
6. Update the GitHub issue with progress/completion notes
7. Open a pull request from the issue branch to `main`

After completing work:
- `IMPLEMENTATION_SUMMARY.md` → append what was built, decisions made, open questions

`HANDOVER.md` is deprecated. Do not use it for issue tracking or status transitions.

## Implementation Status
- Active implementation details and progress history are maintained in `IMPLEMENTATION_SUMMARY.md`.
- Use this section for concise architectural decisions or operating guidance that affects agent behavior.
- 2026-04-11 backlog pass complete for Section 14 Medium/Low items (`M1`–`M5`, `L1`–`L4`) with matching tests; see latest section in `IMPLEMENTATION_SUMMARY.md` for exact file-level deltas and validation results.

## Project Structure & Module Organization
This repository is currently a planning workspace for **PFCD Video-First v1**.  
The tracked artifacts are:
- `prd.md`: product requirements and implementation scope
- `prd-review-20032026.md`: design review and technical risk notes
- `GEMINI.md`: planning context and execution assumptions

As implementation begins, create a clear split between:
- `backend/` for API/services
- `frontend/` for review/edit UI
- `docs/` for architecture and workflow docs
- `infra/` for Azure templates/infrastructure
- `tests/` for automated checks

## Build, Test, and Development Commands
No runnable application code exists yet in this repository snapshot, so build/test commands are not currently applicable.  
When modules are added, include and maintain commands in this section (examples):
- `npm run dev` or `uvicorn app.main:app --reload`
- `npm test` or `pytest`
- `npm run build` / `docker compose up`

Document required env vars and startup prerequisites next to each command.

## Coding Guidelines (Karpathy Principles)

Apply these on every task:

1. **Think before coding** — state assumptions explicitly; if multiple interpretations exist, surface them rather than picking silently; ask when unclear.
2. **Simplicity first** — minimum code that solves the problem; no speculative features, abstractions for single use, or error handling for impossible scenarios.
3. **Surgical changes** — touch only what the task requires; don't improve adjacent code; match existing style; remove only imports/variables made unused by *your* changes.
4. **Goal-driven execution** — define verifiable success criteria before acting; for multi-step tasks, state a brief plan with a per-step verification check.

---

## Coding Style & Naming Conventions
No style tooling is configured yet.  
Recommended baseline for this project:
- Python: 4-space indent, `snake_case` identifiers, `PascalCase` for classes/dataclasses
- TypeScript/JS: 2-space indent, `camelCase` for variables/functions, `PascalCase` for components/types
- Prefer descriptive names (`transcript_media_consistency`, `evidence_anchor`) over short abbreviations
- Keep API payloads deterministic and versioned (`v1` contract preserved where possible)
- Use formatters/linting (e.g., Black/ruff or Prettier/ESLint) and enforce via CI once available

## Testing Guidelines
No test framework is currently present. Target:
- Unit tests: core evidence, scoring, and contract logic
- Integration tests: API lifecycle (`queued -> completed/failed`) and artifact handoff
- E2E tests: upload → draft review → finalize flow

Test naming convention to adopt: `tests/<layer>/<feature>_test.<ext>` and behavior-focused names such as `test_video_without_audio_forces_review`.

## Commit & Pull Request Guidelines
`git` history is not present in this workspace, so repository-wide commit conventions cannot be inferred from previous commits yet.  
Adopt this default until history is established:
- `feat: add ...`
- `fix: ...`
- `docs: ...`
- `refactor: ...`

PR expectations:
- Brief summary of user-facing change
- Link to PRD section/decision reference
- Explicit validation steps run (or reason if not run)
- Screenshots/log snippets for UI or workflow changes
- Mention any config or Azure resource impact

## Security & Configuration Tips
- Keep secrets (Azure keys, storage SAS, DB creds) in environment variables or Key Vault, never in repo files.
- Track environment differences (`local`, `staging`, `production`) with explicit profiles.
- Redact transcript/video identifiers in logs by default.


<claude-mem-context>
# Memory Context

# [PFCD-V2] recent context, 2026-04-30 9:01pm GMT+5:30

Legend: 🎯session 🔴bugfix 🟣feature 🔄refactor ✅change 🔵discovery ⚖️decision
Format: ID TIME TYPE TITLE
Fetch details: get_observations([IDs]) | Search: mem-search skill

Stats: 50 obs (18,761t read) | 742,924t work | 97% savings

### Apr 20, 2026
315 9:55a 🟣 docker-compose.local.yml — Three Worker Services Added for Full Local Pipeline
317 9:59a 🟣 PFCD-V2 Local Docker Stack — All 5 Containers Running Including 3 Workers
318 " 🔵 PFCD-V2 Workers — All Three Connected to Azure Service Bus and Listening
319 " 🟣 Job e97bbf65 Manually Re-enqueued to Extracting Queue
322 10:00a 🔵 PFCD-V2 Pipeline — Extracting Succeeds, Processing Permanently Fails on OpenAI 429 Quota Exceeded
324 " 🔵 PFCD-V2 Local Stack — PFCD_PROVIDER=openai Set in .env.docker.local, OpenAI Account Has No Quota
326 10:13a 🔵 PFCD-V2 Local Docker Stack — All 5 Containers Running, Workers Connected to Service Bus
327 " 🔵 PFCD-V2 Worker-Processing Env — Provider Mismatch Confirmed: openai + Azure Endpoint
329 " 🔵 Two Different OPENAI_API_KEY Values — Shell Env vs .env.docker.local
331 10:14a ✅ PFCD-V2 Stack Restarted with Shell OPENAI_API_KEY Unset — Containers Pick Key from .env.docker.local Only
333 " 🔵 Worker-Processing Now Receives .env.docker.local Key — But PFCD_PROVIDER Still "openai"
335 10:15a 🔵 Job e97bbf65 Full Failure Trace — SK Uses OpenAIChatCompletion Despite provider_effective=azure_openai
337 " 🔵 sk-proj- API Key Works for gpt-4o-mini — gpt-5.4-mini Fails with max_tokens Incompatibility
341 10:16a 🔴 .env.docker.local Model Names Downgraded — gpt-5.4-mini → gpt-4o-mini, gpt-5.4 → gpt-4o
344 " ✅ PFCD-V2 Stack Restarted — Workers Now Use gpt-4o-mini/gpt-4o, Correct API Key Confirmed
346 10:20a 🔵 extraction.py and processing.py — SK Connector Uses OpenAIChatPromptExecutionSettings, No max_tokens Passed
347 " 🔵 Installed SK OpenAIChatPromptExecutionSettings Supports Both max_tokens and max_completion_tokens
350 " 🟣 extraction.py and processing.py — max_completion_tokens Added via PFCD_MAX_COMPLETION_TOKENS Env Var
354 10:22a 🔵 PFCD-V2 API Container Storage Path — /app/storage/uploads/manual/ Confirmed Writable
356 1:34p 🟣 Issue #16 — Readiness Probe + App Insights + Alerting Baseline Implemented
357 2:01p ✅ Issue #16 Readiness + Monitoring Committed on codex/issue-16-readiness-appinsights-alerts
358 2:29p ✅ Issue #16 Draft PR #56 Created — Readiness Probe + Monitoring Baseline
359 " 🔵 GET /health/readiness — Full Contract and Response Schema
361 2:47p 🔵 Issue #9 — Retry/Back-off Work Assignment Picked Up
362 " 🔵 GitHub Issue #9 — SAS/Blob-First Ingestion, Not Retry Logic
363 " ✅ HANDOVER.md — Issue #9 Moved to In Progress
366 2:48p 🔵 Current Upload Architecture — Full Code Map Before SAS Migration
368 2:51p 🟣 SAS/Blob-First Upload Infrastructure Added to main.py
369 2:53p 🟣 SAS/Blob-First Upload Endpoints + Frontend Migration Complete
370 " 🔴 _resolve_input_files Missing append Before continue
372 " ✅ Issue #9 Marked Complete — HANDOVER.md + IMPLEMENTATION_SUMMARY.md Updated
375 3:00p ✅ Issue #9 Committed on codex/fix-issue-9 Branch
376 3:01p ✅ AGENTS.md — Issue Workflow Updated, HANDOVER.md Deprecated
379 3:02p 🔵 Issue #9 Commit on codex/fix-issue-9 but Working Tree Now on main With Same Unstaged Changes
380 3:03p 🔵 Git Write Failures Caused by Sandbox Permission Restrictions + 98% Full Disk
### Apr 30, 2026
398 6:46p 🔵 PFCD-V2 docs/ Folder Structure — opus_report.md Found as Untracked File
399 6:47p 🔵 PFCD-V2 Opus 4.7 Code Review — 3 Critical, 15 High, 17 Medium Findings with 4-Phase Action Plan
400 " 🔵 PFCD-V2 Pipeline Rules — 18 Extraction + 24 Processing + 16 Reviewing Deterministic Rules Documented
404 6:49p 🔵 C1 Path Traversal in export_builder.py — Exact Lines Confirmed via Code Inspection
405 " 🔵 C3 Alignment Self-Comparison — Line 345 Confirmed; uploaded_transcript Fallback Equals transcript_text
406 " 🔵 H5 ffmpeg Timeout — All 4 subprocess.run() Calls Confirmed Missing timeout= Parameter
407 " 🔵 H7 Finalize Race Confirmed — DraftReview.jsx:232-282 Has No inFlightSavePromise Guard
408 " 🔵 H1 No AutoLockRenewer + H13 Bootstrap Vestigial Vars — Both Confirmed via Code Inspection
409 " 🔵 H11 setdefault Empty-String Miss + M13 Streamlit Re-download — Both Confirmed
410 7:03p 🔵 PFCD-84 Issue Identified — Streamlit App Main Shell & Navigation
411 " 🔵 Streamlit App Skeleton Already Exists in streamlit_app/
412 7:08p 🔵 Streamlit App Docker Config — Dockerfile Missing, Compose Files Present
413 7:09p 🔵 GitHub Issue #84 True Scope — Phase A: 9 Critical/High Fixes (Not Streamlit)
414 " 🔴 C1 Path Traversal Fix — export_builder.py Frame Storage Key Validation
415 " 🔵 Git Commit Blocked — .git/index.lock Operation Not Permitted in Sandbox

Access 743k tokens of past work via get_observations([IDs]) or mem-search skill.
</claude-mem-context>