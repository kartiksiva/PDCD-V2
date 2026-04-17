# Repository Guidelines

## Session Bootstrap Protocol (MANDATORY)

At the start of every session, before writing any code:

1. Read `AGENTS.md` (this file)
2. Read `HANDOVER.md` — work assignment board; pick up items from "Assigned to Codex"
3. Read `IMPLEMENTATION_SUMMARY.md` — rolling log of what has been built and what remains
4. Read `prd.md` — authoritative requirements; never modify requirements, only the progress table
5. Read `REFERENCE.md` on demand — file layout, env vars, API/data model, Azure infra, CI/CD

After completing work:
- `HANDOVER.md` → move item from "Assigned to Codex" / "In Progress" to "Ready for Claude Review"
- `IMPLEMENTATION_SUMMARY.md` → append what was built, decisions made, open questions

When picking up an assignment:
- `HANDOVER.md` → move item from "Assigned to Codex" to "In Progress"

Shared logs are append-only to avoid overwrite conflicts between agents.

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
