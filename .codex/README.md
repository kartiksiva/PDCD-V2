# Codex Workflow

## Agents

- `orchestrator`: routes work, enforces role order, tracks blockers, and produces the final summary.
- `planner`: defines scope, impacted areas, risks, acceptance criteria, and validation.
- `developer`: implements the approved plan with the smallest safe change set.
- `reviewer`: checks correctness, regressions, root-cause coverage, and deployment risk.
- `deployer`: prepares release notes, rollback notes, and post-deploy checks.

## Expected Flow

`orchestrator -> planner -> developer -> reviewer -> deployer`

Use this flow for implementation work. Documentation-only or analysis-only tasks can stop earlier when appropriate.

## How To Invoke In Codex

Start with the orchestrator and point it at the repository task context. The orchestrator should route the task through the other agents in order and keep the work GitHub-first.

Example feature prompt:

```text
Use the orchestrator workflow for this repository. Plan, implement, review, and prepare deployment notes for GitHub Issue #123. Use the GitHub issue and PR as the coordination trail and produce the final GitHub-ready summary.
```

Example troubleshooting prompt:

```text
Use the orchestrator workflow for this repository to investigate a startup regression. Planner must provide root-cause hypotheses and diagnostic steps before any code change. Reviewer must confirm whether the fix addresses root cause or only symptoms.
```

## Guardrails

- Planner first for implementation tasks.
- Reviewer is mandatory after developer work.
- Deployer runs only after reviewer clears blockers.
