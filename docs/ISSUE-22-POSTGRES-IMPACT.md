# Issue 22: Postgres Migration Impact Analysis

GitHub issue: [#22](https://github.com/kartiksiva/PDCD-V2/issues/22)

## Orchestrator Summary

- Task type: `type:refactor`
- Repository workflow followed: bootstrap docs read, issue pulled from GitHub, planner completed before developer analysis
- Scope kept narrow: this document assesses migration impact only; it does not implement the database move or `pgvector`

## Planner

### Task Summary

Assess the impact of replacing the current Azure SQL Server / `pyodbc` production path with PostgreSQL so the platform can adopt `pgvector` later if RAG becomes part of scope.

### Scope

- inspect current application persistence code, migrations, tests, packaging, CI, and Azure bootstrap scripts
- identify what is already database-dialect-neutral and what is coupled to SQL Server / ODBC
- recommend the smallest safe migration path

Out of scope:

- implementing PostgreSQL support
- adding embeddings, retrieval, chunking, or RAG APIs
- redesigning unrelated backend modules

### Likely Impacted Areas

- `backend/app/db.py`: engine bootstrap is generic, but driver/runtime selection changes here first
- `backend/app/models.py`: ORM layer is mostly portable; any PostgreSQL-specific optimization should be additive
- `backend/alembic/versions/*.py`: schema baseline and replays must be validated against PostgreSQL
- `backend/requirements.txt`: SQL Server driver dependency must change
- `.github/workflows/deploy-backend.yml`
- `.github/workflows/deploy-workers.yml`
- `backend/Dockerfile`
- `infra/dev-bootstrap.sh`
- `infra/README.md`
- `backend/README.md`
- `REFERENCE.md`

### Root-Cause Hypotheses

1. The main blocker to PostgreSQL is not the repository or ORM code. It is the infrastructure and packaging layer, which still assumes Azure SQL Server and ODBC everywhere.
2. A fresh PostgreSQL bootstrap is likely to fail if we replay the current initial migration unchanged, because boolean defaults are written as `sa.text("0")`, which is SQL Server / SQLite-friendly but should be reviewed for PostgreSQL DDL compatibility.
3. The current automated tests understate migration risk because they only exercise SQLite, so they do not validate PostgreSQL DDL, timestamp behavior, or future `pgvector` extension setup.

### Troubleshooting Plan

1. Map all SQL Server / ODBC references in app code, infra, CI, and runtime images.
2. Separate true schema portability issues from operational coupling.
3. Define the smallest path that unlocks PostgreSQL first and defers `pgvector` schema work until RAG is actually approved.
4. Identify the validation path that would prove migration readiness before any production cutover.

### Implementation Plan

1. Replace `pyodbc` with a PostgreSQL driver such as `psycopg[binary]`.
2. Provision Azure Database for PostgreSQL Flexible Server and move `DATABASE_URL` to a PostgreSQL connection string.
3. Update Alembic baseline compatibility for PostgreSQL, especially server defaults and fresh-database replay.
4. Remove ODBC-specific OS packages from CI and container builds once SQL Server support is no longer needed.
5. Add one PostgreSQL validation path before cutover:
   - `alembic upgrade head` against disposable PostgreSQL
   - repository/API smoke test against PostgreSQL
6. Treat `pgvector` as a follow-up schema feature, not part of the initial driver/database migration.

### Acceptance Criteria

- the repo has a concrete, file-level impact assessment for a PostgreSQL move
- the assessment distinguishes low-risk code changes from higher-risk infra/runtime work
- the recommendation explains whether PostgreSQL migration should be bundled with `pgvector` or sequenced separately

### Risks

- migration work touches API, workers, CI, Docker, and Azure bootstrap in one sweep
- SQLite-only tests can mask PostgreSQL-specific failures until late
- if SQL Server and PostgreSQL support are mixed temporarily, dependency/runtime complexity increases during rollout

### Validation Plan

- document-level validation now: source inspection of impacted files
- future implementation validation:
  - run Alembic on disposable PostgreSQL
  - run targeted repository/integration tests with PostgreSQL
  - verify API `/health`, job creation, worker persistence, finalize, and export flow after cutover

## Developer Findings

### What Is Already Easy To Move

- The persistence layer is mostly SQLAlchemy ORM and standard `select()` / `delete()` usage, not vendor SQL.
- `backend/app/db.py` only special-cases SQLite thread handling. Non-SQLite URLs already flow through generic SQLAlchemy engine creation.
- The schema is simple: seven tables, string primary keys, timestamps, floats, booleans, and JSON-like payloads stored as `Text`.

### What Actually Carries The Migration Cost

#### 1. Infrastructure and runtime assumptions are still SQL Server-specific

- `infra/dev-bootstrap.sh` provisions Azure SQL Server + SQL Database, creates `sql-connection-string`, and injects SQL Server-specific app settings.
- `infra/README.md`, `REFERENCE.md`, and `backend/README.md` all document Azure SQL Server as the production database.
- Current operational naming also bakes in SQL Server semantics via:
  - `AZURE_SQL_SERVER_NAME`
  - `AZURE_SQL_DATABASE_NAME`
  - Key Vault secret `sql-connection-string`

This means the biggest change surface is infra and operations, not business logic.

#### 2. Packaging and CI are paying SQL Server driver tax today

- `backend/requirements.txt` pins `pyodbc==5.2.0`.
- `.github/workflows/deploy-backend.yml` and `.github/workflows/deploy-workers.yml` both install `unixodbc-dev`.
- `backend/Dockerfile` installs `unixodbc`, `unixodbc-dev`, and `msodbcsql18`.

Moving to PostgreSQL would simplify the container and CI stack after the cutover because those ODBC packages could be removed.

#### 3. Migration replay needs a PostgreSQL pass before cutover

- `backend/alembic/versions/20260401_0001_init.py` uses boolean defaults like `sa.text("0")`.
- That baseline was clearly written to work with SQLite and the original Azure SQL Server assumption.
- Before any PostgreSQL rollout, the team should validate whether the current migration chain cleanly boots a brand-new PostgreSQL database. If not, the safest fix is a new PostgreSQL-safe baseline or a small migration correction before rollout.

#### 4. Current schema does not yet exploit PostgreSQL strengths

- JSON-heavy fields such as `provider_effective`, `teams_metadata`, `agent_signals`, `agent_review`, and draft/export payloads are stored as `Text`, not `JSONB`.
- That is fine for a first database move, but it means PostgreSQL by itself will not deliver better queryability until a later schema pass.
- Likewise, `pgvector` would still need new tables or columns for embeddings, plus chunking/indexing logic. The current schema has no embedding storage path.

### Recommended Migration Sequence

#### Phase 1: PostgreSQL compatibility cutover

- change driver and connection string
- stand up Azure Database for PostgreSQL Flexible Server
- validate Alembic against PostgreSQL
- update bootstrap, docs, CI, and container packaging

#### Phase 2: PostgreSQL confidence hardening

- add at least one PostgreSQL integration test path in CI
- optionally convert selected `Text` JSON payloads to `JSONB` if operational queries need them

#### Phase 3: `pgvector` only if RAG is approved

- introduce chunk model
- introduce embedding generation pipeline
- add vector table/indexes and retrieval logic
- keep this as a separate issue/PR trail

### Recommendation

Proceed with PostgreSQL as a standalone migration only if the team wants the platform option for `pgvector` soon. Do not combine the initial database switch with RAG implementation. The current codebase is portable enough that the app-layer migration should be moderate, but the infra/CI/runtime sweep is the real work and deserves its own implementation issue.

## Reviewer

### Review Verdict

`approved-for-planning`

### Blocking Issues

- Do not scope `pgvector` or RAG into the same implementation PR as the base PostgreSQL migration.
- Do not cut over production before proving `alembic upgrade head` on a clean PostgreSQL instance.

### Non-Blocking Issues

- Secret and env-var names remain SQL Server-specific and will be confusing if PostgreSQL is introduced without renaming or documenting compatibility.
- SQLite can remain for fast unit tests, but it is not enough as the only database validation path after migration.

### Troubleshooting Findings

- The issue is deterministic and architectural, not intermittent.
- The fault domain is concentrated in infra/bootstrap/runtime packaging, with only light application-code changes required.
- The fastest isolation step for future implementation is a disposable PostgreSQL smoke environment plus Alembic replay.

### Regression Risks

- timestamp and boolean DDL behavior may differ from current SQLite-backed tests
- partial rollout could leave API and workers on mismatched drivers or connection strings
- removing ODBC packages too early would break any environment still pointed at SQL Server

### Test Gaps

- no PostgreSQL migration test
- no PostgreSQL-backed repository or API smoke test
- no extension setup coverage for `pgvector`

### Deployment Risks

- Azure bootstrap currently provisions the wrong database service for the target state
- CI and container images will continue to carry SQL Server runtime dependencies until explicitly cleaned up

### Recommendation

Create a follow-on implementation issue for "PostgreSQL driver + Azure PostgreSQL bootstrap + Alembic validation + CI smoke test". Keep `pgvector` as a separate dependent issue once the base database move is stable.

## Deployer

### Deployment Readiness

Not deployment-ready. This issue delivered analysis only.

### Rollback Notes

Not applicable yet because no runtime or infrastructure changes were applied.

### Future Post-Deployment Checks

- verify `DATABASE_URL` points to PostgreSQL for API and all workers
- run `alembic upgrade head`
- create a job, confirm persistence, draft retrieval, finalize, and export flows
- confirm workers can read/write the same PostgreSQL database
- if `pgvector` is later enabled, verify extension creation and vector index health separately
