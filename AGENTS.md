Repository Guidelines

Session Bootstrap Protocol (MANDATORY)

At the start of every session, before writing any code:
	1.	Read AGENTS.md (this file)
	2.	Read the relevant GitHub issue / PR context — use GitHub as the task board and source of truth
	3.	Read IMPLEMENTATION_SUMMARY.md — rolling log of what has been built and what remains
	4.	Read prd.md — authoritative requirements; never modify requirements, only the progress table
	5.	Read REFERENCE.md on demand — file layout, env vars, API/data model, Azure infra, CI/CD

After completing work:
	•	GitHub Issue / PR → update status, summary, and review state
	•	IMPLEMENTATION_SUMMARY.md → append what was built, decisions made, open questions

When picking up an assignment:
	•	GitHub Issue / PR → reflect active ownership and in-progress state there
	•	Self-initiated low-risk maintenance tasks should create or update a GitHub issue where practical; keep IMPLEMENTATION_SUMMARY.md append-only when relevant.

Shared logs are append-only to avoid overwrite conflicts between agents.

⸻

Codex Role Workflow (MANDATORY)

This repository uses a GitHub-first, role-based Codex workflow.

Default task flow:
	1.	Orchestrator
	2.	Planner
	3.	Developer
	4.	Reviewer
	5.	Deployer

Rules:
	•	Every implementation task should move through Planner → Developer → Reviewer → Deployer unless the task is explicitly documentation-only or analysis-only.
	•	Orchestrator owns task routing, task state, final summary, and escalation.
	•	Planner must always run before Developer.
	•	Reviewer must always run after Developer.
	•	Deployer must never proceed if Reviewer reports blocking issues.
	•	For bug fixes, incidents, startup issues, regressions, unstable behavior, and troubleshooting-heavy tasks, Planner and Reviewer must perform explicit troubleshooting duties.

GitHub-first execution model:
	•	GitHub Issues are the external task reference when applicable.
	•	Pull Requests are the implementation and review trail.
	•	CI/CD evidence is the source of truth for build, test, and deployment status.
	•	GitHub Issues and Pull Requests are the coordination surface for agent work in this repository.

⸻

Implementation Status
	•	Active implementation details and progress history are maintained in IMPLEMENTATION_SUMMARY.md.
	•	Use this section for concise architectural decisions or operating guidance that affects agent behavior.
	•	2026-04-11 backlog pass complete for Section 14 Medium/Low items (M1–M5, L1–L4) with matching tests; see latest section in IMPLEMENTATION_SUMMARY.md for exact file-level deltas and validation results.

⸻

Project Structure & Module Organization

This repository is an active implementation workspace for PFCD Video-First v1.
Core repository artifacts include:
	•	prd.md: product requirements and implementation scope
	•	prd-review-20032026.md: design review and technical risk notes
	•	GEMINI.md: planning context and execution assumptions

Implemented repository areas:
	•	backend/ for API/services, agents, workers, and DB migrations
	•	frontend/ for the review/edit UI
	•	docs/ for architecture and workflow docs
	•	infra/ for Azure templates/infrastructure
	•	tests/ for automated unit and integration checks

⸻

Build, Test, and Development Commands

Runnable application code exists in both `backend/` and `frontend/`. Keep this section aligned to the current codebase.
Current commands:
	•	Backend setup: `cd backend && python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt`
	•	DB migrations: `cd backend && alembic upgrade head`
	•	Backend API (local): `cd backend && uvicorn app.main:app --reload --host 127.0.0.1 --port 8000`
	•	Backend workers: `cd backend && PFCD_WORKER_ROLE=extracting python -m app.workers.runner` (swap `extracting` for `processing` or `reviewing` as needed)
	•	Cleanup worker: `cd backend && python -m app.workers.cleanup`
	•	Frontend setup: `cd frontend && npm ci`
	•	Frontend dev: `cd frontend && npm run dev`
	•	Frontend build: `cd frontend && npm run build`
	•	Tests: `cd backend && .venv/bin/pytest ../tests/ -v`

Document required env vars and startup prerequisites next to each command.

⸻

Coding Guidelines (Karpathy Principles)

Apply these on every task:
	1.	Think before coding — state assumptions explicitly; if multiple interpretations exist, surface them rather than picking silently; ask when unclear.
	2.	Simplicity first — minimum code that solves the problem; no speculative features, abstractions for single use, or error handling for impossible scenarios.
	3.	Surgical changes — touch only what the task requires; don’t improve adjacent code; match existing style; remove only imports/variables made unused by your changes.
	4.	Goal-driven execution — define verifiable success criteria before acting; for multi-step tasks, state a brief plan with a per-step verification check.

⸻

Coding Style & Naming Conventions

No style tooling is configured yet.
Recommended baseline for this project:
	•	Python: 4-space indent, snake_case identifiers, PascalCase for classes/dataclasses
	•	TypeScript/JS: 2-space indent, camelCase for variables/functions, PascalCase for components/types
	•	Prefer descriptive names (transcript_media_consistency, evidence_anchor) over short abbreviations
	•	Keep API payloads deterministic and versioned (v1 contract preserved where possible)
	•	Use formatters/linting (e.g., Black/ruff or Prettier/ESLint) and enforce via CI once available

⸻

Testing Guidelines

Pytest is configured for this repository and the codebase already includes unit and integration suites.
Coverage targets:
	•	Unit tests: core evidence, scoring, adapters, agents, exports, and contract logic
	•	Integration tests: API lifecycle (queued -> completed/failed), auth enforcement, error paths, and exports
	•	E2E tests: upload → draft review → finalize flow

Current naming convention: `tests/<layer>/test_*.py` with behavior-focused test names such as `test_video_without_audio_forces_review`.

⸻

Commit & Pull Request Guidelines

Repository history exists, but a strict repository-wide commit convention is not documented in this file.
Use this default unless the team formalizes something stricter:
	•	feat: add ...
	•	fix: ...
	•	docs: ...
	•	refactor: ...

PR expectations:
	•	Brief summary of user-facing change
	•	Link to PRD section/decision reference
	•	Explicit validation steps run (or reason if not run)
	•	Screenshots/log snippets for UI or workflow changes
	•	Mention any config or Azure resource impact

⸻

Security & Configuration Tips
	•	Keep secrets (Azure keys, storage SAS, DB creds) in environment variables or Key Vault, never in repo files.
	•	Track environment differences (local, staging, production) with explicit profiles.
	•	Redact transcript/video identifiers in logs by default.

⸻

Role Definitions

Orchestrator

Responsibilities:
	•	Read the GitHub Issue, Pull Request, and repository context.
	•	Determine whether the work is feature work, bug fix, hotfix, troubleshooting, refactor, documentation, or deployment-related.
	•	Route work to the correct role in the correct order.
	•	Ensure each role output is complete before moving forward.
	•	Request rework when outputs are incomplete, weak, or unsupported by evidence.
	•	Produce the final GitHub-ready task summary.

Orchestrator must:
	•	Track task state clearly.
	•	Reference the relevant Issue / PR in summaries.
	•	Escalate blockers instead of inventing answers.

Orchestrator must not:
	•	Implement production changes unless explicitly required.
	•	Skip Planner or Reviewer.
	•	Mark work complete without evidence.

⸻

Planner

Responsibilities:
	•	Break the task into a concrete execution plan.
	•	Identify impacted files, services, modules, configs, and dependencies.
	•	Define acceptance criteria.
	•	Identify assumptions, risks, and validation needs.
	•	Perform initial troubleshooting analysis for bug, incident, regression, startup, and failure-related work.

Planner troubleshooting duties:
	•	Identify likely root-cause candidates.
	•	Distinguish between code issue, configuration issue, data issue, environment issue, dependency issue, and infrastructure issue.
	•	Recommend the fastest path to isolate the fault.
	•	Identify the logs, traces, metrics, error messages, and reproduction steps that matter most.
	•	Call out whether the issue appears deterministic, intermittent, environment-specific, or data-specific.

Planner output should include:
	•	Task Summary
	•	Scope
	•	Likely Impacted Areas
	•	Root-Cause Hypotheses
	•	Troubleshooting Plan
	•	Implementation Plan
	•	Acceptance Criteria
	•	Risks
	•	Validation Plan

Planner must not:
	•	Write production code as part of planning.
	•	Expand scope without justification.
	•	Guess silently when evidence is missing.

⸻

Developer

Responsibilities:
	•	Implement the approved plan.
	•	Keep the change narrow and targeted.
	•	Update or add tests when required.
	•	Note any blockers, tradeoffs, or deviations from the plan.

Developer must:
	•	Follow the approved plan unless new evidence requires change.
	•	Explain any deviation from the plan.
	•	Avoid unrelated cleanup unless required for correctness or safety.

Developer must not:
	•	Rewrite large areas of code without clear need.
	•	Change requirements on the fly.
	•	Ignore known risks raised by Planner or Reviewer.

⸻

Reviewer

Responsibilities:
	•	Review the implementation for correctness, regressions, maintainability, and risk.
	•	Verify acceptance criteria.
	•	Check test coverage and quality.
	•	Perform post-change troubleshooting validation for bug, incident, regression, startup, and failure-related work.

Reviewer troubleshooting duties:
	•	Validate whether the change addresses the likely root cause or only reduces symptoms.
	•	Check whether alternate failure paths remain open.
	•	Check whether the fix introduces new operational risk.
	•	Evaluate rollback difficulty and production safety.
	•	Identify missing observability, monitoring, or follow-up actions.

Reviewer output should include:
	•	Review Verdict
	•	Blocking Issues
	•	Non-Blocking Issues
	•	Troubleshooting Findings
	•	Regression Risks
	•	Test Gaps
	•	Deployment Risks
	•	Recommendation

Reviewer must:
	•	Be explicit about blocker vs non-blocker findings.
	•	Use evidence from code, tests, and task context.
	•	Push back on weak fixes.

Reviewer must not:
	•	Approve changes without enough evidence.
	•	Treat symptom suppression as root-cause resolution without justification.

⸻

Deployer

Responsibilities:
	•	Prepare deployment notes.
	•	Confirm readiness for release based on review and CI/CD evidence.
	•	Define rollback guidance.
	•	Define post-deployment verification checks.
	•	Summarize deployment-related risks and required follow-up.

Deployer must:
	•	Verify that Reviewer has not reported blockers.
	•	Use actual build/test/deployment evidence where available.
	•	Document release verification steps.

Deployer must not:
	•	Claim deployment success without evidence.
	•	Override blocking review findings.
	•	Skip rollback considerations for risky changes.

⸻

GitHub Tracking Rules
	•	Every task should map to a GitHub Issue when applicable.
	•	Every implementation should map to a Pull Request.
	•	PR descriptions should reference the related Issue.
	•	Final summaries should include:
	•	Task Type
	•	GitHub Issue reference if applicable
	•	Pull Request reference if applicable
	•	What Changed
	•	Why It Changed
	•	Tests Run
	•	Outstanding Risks
	•	Deployment Status
	•	Rollback Notes if relevant
	•	Recommended Next Step

Suggested status labels:
	•	status:triage
	•	status:planned
	•	status:in-dev
	•	status:in-review
	•	status:ready-to-deploy
	•	status:deployed
	•	status:blocked

Suggested type labels:
	•	type:feature
	•	type:bug
	•	type:hotfix
	•	type:troubleshooting
	•	type:refactor

⸻

Troubleshooting Policy

For bug, hotfix, incident, startup, regression, and unstable-behavior tasks:
	•	Planner must provide root-cause hypotheses and diagnostic steps.
	•	Developer should prefer targeted fixes over broad refactors.
	•	Reviewer must assess whether the fix addresses root cause, not just symptoms.
	•	Deployer must define post-deployment verification steps.

Preferred troubleshooting sequence:
	1.	Understand the failure.
	2.	Reproduce the failure when feasible.
	3.	Isolate the likely fault domain.
	4.	Propose the smallest safe fix.
	5.	Validate behavior with tests or evidence.
	6.	Assess regression risk.
	7.	Define post-deployment verification.

⸻

Change Scope Policy
	•	Prefer minimal, reversible changes.
	•	Avoid mixing feature work with opportunistic refactoring.
	•	If refactoring is necessary for the task, explain why.
	•	If a larger structural issue is discovered, document it separately instead of quietly expanding scope.

⸻

Testing Policy
	•	Identify the tests relevant to the changed area.
	•	Run the most relevant tests feasible within the environment.
	•	If tests cannot be run, say so clearly and explain why.
	•	For high-risk changes, recommend additional validation steps.

⸻

Deployment Policy
	•	No deployment-ready verdict without review evidence.
	•	No production-complete claim without deployment evidence.
	•	Every risky change should include rollback guidance.
	•	Every production-impacting change should include post-deployment checks.

⸻

Output Quality Standard

All role outputs should be:
	•	concise
	•	evidence-based
	•	explicit about uncertainty
	•	aligned to the GitHub task context
	•	written so a human maintainer can act on them immediately

Avoid vague statements such as:
	•	“looks fine”
	•	“probably fixed”
	•	“should work”

Prefer statements such as:
	•	“The issue is likely caused by X because Y and Z.”
	•	“This change addresses the retry path in file A but does not change timeout behavior in file B.”
	•	“Tests cover the happy path but not the failure path for malformed input.”

⸻

Default Final Summary Format

When work is complete, the final summary should include:
	•	Task Type
	•	GitHub Issue
	•	Pull Request
	•	What Changed
	•	Why It Changed
	•	Tests Run
	•	Outstanding Risks
	•	Deployment Status
	•	Rollback Notes
	•	Recommended Next Step

⸻


<claude-mem-context>
# Memory Context

# [PFCD-V2] recent context, 2026-04-19 10:33pm GMT+5:30

Legend: 🎯session 🔴bugfix 🟣feature 🔄refactor ✅change 🔵discovery ⚖️decision
Format: ID TIME TYPE TITLE
Fetch details: get_observations([IDs]) | Search: mem-search skill

Stats: 50 obs (19,535t read) | 635,646t work | 97% savings

### Apr 18, 2026
100 2:15a 🔵 Backend Dockerfile Still Installs msodbcsql18 — Stale ODBC Artifact Post-PostgreSQL Migration
104 2:16a 🔵 Health Endpoint Required Env List Includes Azure SQL Legacy Vars, Missing PostgreSQL Vars
105 2:18a 🟣 Issue #26 — Env Var Dependency Docs + .gitignore + Compose File Expansion Implemented
106 " 🔵 Real OPENAI_API_KEY in Developer Shell — Exposed via docker compose config Output
139 10:31p 🔵 GitHub Issue #19 — Full Scope: ACR + Container Apps Environment Provisioning
140 11:02p 🔵 Azure CLI Sandbox Permission Block — Workaround via AZURE_CONFIG_DIR
141 " 🔵 PFCD-V2 Azure Infrastructure — Current Resource Naming Pattern Confirmed
142 11:03p 🔵 GitHub Issues #19/#20/#21 — ACA Migration Full Scope Confirmed
146 " ⚖️ Issue #19 Implementation Plan — Narrow Infra + Doc Updates Only
147 11:04p 🟣 dev-bootstrap.sh — ACR + Log Analytics + ACA Environment Provisioning Added
149 " ✅ REFERENCE.md — ACA/ACR Resources Added to Azure Infrastructure Table
150 " 🔵 dev-bootstrap.sh Full Diff — SQL→PostgreSQL Rename Already in Working Tree
153 11:05p ✅ ISSUE-19-ACA-INFRA — Moved to Ready for Claude Review in HANDOVER.md
156 11:06p 🟣 Issue #19 Complete — ACR + ACA Environment Bootstrap Delivered
158 11:19p 🔵 PFCD-V2 Pre-Commit Working Tree State — Full Delta Before Git Commit
159 11:23p 🔵 GitHub CLI Auth Token Expired — kartiksiva Account
161 11:27p ✅ GitHub Issue #19 — ACA Bootstrap Status Comment Posted
164 11:30p 🔵 Issue #19 Code Review — Blocking Bug: Postgres Password Special Chars Break DSN URL
165 11:31p 🔴 dev-bootstrap.sh — Postgres Password Charset Fixed (Blocking Bug Resolved)
166 " ✅ dev-bootstrap.sh Full Diff Confirmed — Azure SQL → PostgreSQL + ACA Infrastructure
169 " 🔵 PFCD-V2 Working Tree on main Branch — PR Creation Requires New Branch
170 " 🔵 git switch -c codex/issue-19-aca-infra Fails — Namespace Conflict in .git/refs/heads
172 11:32p 🔵 Codex Sandbox Blocks git Branch Creation — .git/refs Write Denied
174 " 🔵 Codex Sandbox Pattern — git Branch/Commit Ops Require require_escalated + prefix_rule
176 11:34p 🔵 Codex Sandbox Blocks git index Writes — git add/apply --cached Requires Escalation
178 11:35p ✅ Issue #19 Patch Staged — All Four Files Cleanly Indexed on codex-issue-19-aca-infra Branch
180 11:36p 🔵 Staged Index vs Working Tree Diverge — Issue #19 Commit Intentionally Excludes PostgreSQL Migration
182 " 🔵 Pre-Commit Check — Staged IMPLEMENTATION_SUMMARY.md Has Extra Blank Line at EOF
184 11:37p 🔴 Staged IMPLEMENTATION_SUMMARY.md EOF Whitespace Fixed via git update-index
185 " 🔵 PFCD-V2 Working Tree State Before Issue #27 — Large Uncommitted Delta
186 11:39p 🟣 Issue #19 — Commit d25a135 on Branch codex/issue19 Pushed to GitHub
187 " ✅ Issue #27 Part A — SQL Server References Purged from Compose Files and Dockerfile
188 11:40p 🔵 App Service Startup RCA — Three Compounding Root Causes Identified
189 " 🔵 IMPLEMENTATION_SUMMARY.md Sections 44–58 — Full Uncommitted History Confirmed
### Apr 19, 2026
190 2:06p 🔵 PFCD-V2 Codebase State — Full Audit Before Issue #27 Work
191 2:07p 🔵 GitHub Remote URL Typo — PDCD-V2 Instead of PFCD-V2
192 " 🟣 Issue #19 ACA Infra — ACR + Log Analytics + Container Apps Environment Added to dev-bootstrap.sh
195 2:08p 🟣 ACA Migration — Backend + Workers CI/CD Fully Rewritten from App Service to Container Apps
196 " 🟣 PostgreSQL Migration Complete — pyodbc Replaced, Bootstrap Fully Migrated, Alembic Fixed
203 2:09p 🟣 Docker Artifacts Complete — backend/Dockerfile Multi-Target, Frontend Nginx, Full Local Compose Stack
204 " 🟣 PostgreSQL Smoke Test — Full API Lifecycle Against Real PostgreSQL via PFCD_POSTGRES_SMOKE_DATABASE_URL
209 2:10p 🔵 SQL Server Purge Confirmed Complete — Zero pyodbc/MSSQL References Remain in Active Code
213 " 🔵 KEDA Service Bus Scaler Config — Workers Scale to Zero, messageCount=1 Triggers Scale-Up
215 2:11p ✅ Section 61 — Doc Coherence Pass: AGENTS.md, CLAUDE.md, REFERENCE.md, copilot-instructions.md
220 3:01p 🔵 GitHub Issue #34 Does Not Exist in PFCD-V2 Repo
221 " 🔵 GitHub Remote Is kartiksiva/PDCD-V2, Not karthicks/PFCD-V2
222 " 🔵 Issue #27 Branch Has Large Uncommitted Working Tree
223 3:02p 🔵 Issue #34 — ACA Deploy Verification + Legacy Worker Rollback Regressions
225 " 🔵 Issue #34 — Four Regressions Confirmed via Code Inspection
227 3:03p 🔵 Working Tree Contains All Four Issue #34 Regressions — Uncommitted ACA Migration

Access 636k tokens of past work via get_observations([IDs]) or mem-search skill.
</claude-mem-context>
