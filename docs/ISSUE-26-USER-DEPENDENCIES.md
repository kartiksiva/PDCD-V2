# Issue 26: User-Supplied Dependencies and Build Inputs

This note collects the dependencies that a maintainer must provide when running PFCD locally. It focuses on the inputs that come from the user or the machine environment rather than from tracked source files.

## Where to edit values

Use this as the fast decision rule:

- Edit [`.env.docker.local`](/Users/karthicks/kAgents/Projects/PFCD-V2/.env.docker.local) for local Docker runs.
- Export a shell variable for bare-metal local runs under `backend/` or `frontend/`.
- Use GitHub Actions secrets for frontend build-time values and deploy workflow secrets.
- Use Azure Key Vault-backed App Service settings for runtime infrastructure secrets in Azure.

### Source of truth by variable group

| Variable(s) | Where it should come from | Notes |
|---|---|---|
| `PFCD_LOCAL_API_PORT`, `PFCD_LOCAL_FRONTEND_PORT`, `VITE_API_BASE`, `VITE_API_KEY`, `PFCD_API_KEY`, `PFCD_PROVIDER`, `DATABASE_URL`, `UPLOADS_DIR`, `EXPORTS_BASE_PATH`, `PFCD_CORS_ORIGINS`, provider tuning vars | `.env.docker.local` for local Docker | Copy from `docker-compose.local.env.example` and edit there. |
| `PFCD_WORKER_ROLE`, `PFCD_CLEANUP_INTERVAL_SECONDS` | shell env for direct worker/cleanup runs | These are not part of `docker-compose.local.yml`. |
| `VITE_API_BASE`, `VITE_API_KEY`, `AZURE_CREDENTIALS`, app names, deploy-time Azure values | GitHub Actions secrets / variables | Current frontend workflow reads `VITE_*` from GitHub secrets at build time. |
| `DATABASE_URL`, `AZURE_STORAGE_CONNECTION_STRING`, `AZURE_SERVICE_BUS_CONNECTION_STRING` | Azure Key Vault in Azure App Service | Wired by `infra/dev-bootstrap.sh` as `@Microsoft.KeyVault(...)` app settings. |
| `PFCD_API_KEY` | direct app setting today, not Key Vault-backed by current bootstrap | Backend reads it directly from environment. |
| `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_CHAT_DEPLOYMENT_NAME`, related OpenAI deployment names | direct app settings / GitHub secrets today | These are not currently wired through Key Vault by the bootstrap script. |

### Important current caveat

The current repo does **not** treat every secret the same way in Azure:

- Key Vault-backed today:
  - `DATABASE_URL`
  - `AZURE_STORAGE_CONNECTION_STRING`
  - `AZURE_SERVICE_BUS_CONNECTION_STRING`
- Not Key Vault-backed today:
  - `PFCD_API_KEY`
  - `VITE_API_KEY`
  - `AZURE_OPENAI_ENDPOINT`
  - Azure/OpenAI deployment-name settings

So if you are asking "which file do I update?" the answer depends on where you are running:

- local Docker: update `.env.docker.local`
- local bare-metal backend/frontend: export shell env vars
- frontend CI/CD build: update GitHub Actions secrets
- Azure runtime infra secrets already wired by bootstrap: update the Key Vault secret, then restart the app if needed

## Build file map

- `backend/Dockerfile`
  Builds the backend image used by the API and worker runtime targets. It already installs Python dependencies plus native packages such as `ffmpeg`.
- `frontend/Dockerfile`
  Builds the frontend bundle with `VITE_*` build arguments and serves it from nginx.
- `backend/docker-compose.smoke.yml`
  Backend-only startup smoke path. Placeholder Azure values are acceptable because the goal is container startup, not a full end-to-end run.
- `frontend/docker-compose.smoke.yml`
  Frontend-only smoke path. Useful for verifying the bundle and nginx runtime.
- `docker-compose.local.yml`
  Integrated frontend + backend local stack. This is the main file for local Docker development.
- `docker-compose.local.env.example`
  Example user-editable env file for `docker-compose.local.yml`. Copy it to `.env.docker.local` and fill in only the values required by your workflow.

## Machine dependencies supplied by the user

- Python 3.11 plus `venv`
  Needed for bare-metal backend work under `backend/`.
- Node.js 20 plus npm
  Needed for bare-metal frontend work under `frontend/`.
- Docker with Compose support
  Needed for all container-based smoke and integrated local build paths.
- `ffmpeg`
  Needed only when the backend runs outside Docker and you want real large-media preprocessing/transcription behavior.
- PostgreSQL
  Optional. Needed only for PostgreSQL-specific smoke/validation instead of the default SQLite local flow.

## Environment variables by workflow

### 1. Frontend-only local development

Bare minimum:

- `VITE_API_BASE`
  Optional. Set this in local shell env or `.env.docker.local` when the frontend dev server should talk to a non-default backend origin.
- `VITE_API_KEY`
  Optional. Required only if the backend enables `PFCD_API_KEY`. For Azure frontend deploys, this currently comes from GitHub Actions secrets, not Key Vault.

### 2. Backend-only local development

Bare minimum:

- `DATABASE_URL`
  Optional because the backend defaults to SQLite, but this is the main runtime database input. In Azure App Service this is currently Key Vault-backed.

Useful local overrides:

- `UPLOADS_DIR`
- `EXPORTS_BASE_PATH`
- `PFCD_CORS_ORIGINS`
- `PFCD_API_KEY`
  Local-only unless you separately wire it in Azure app settings. This is not currently Key Vault-backed by the bootstrap script.
- `PFCD_MAX_RETRIES`

Worker and cleanup process settings:

- `PFCD_WORKER_ROLE`
  Required only when starting `python -m app.workers.runner` directly.
- `PFCD_CLEANUP_INTERVAL_SECONDS`
  Optional only for `python -m app.workers.cleanup`.

Provider/runtime settings become operationally required only when you want real agent execution rather than API startup:

- `PFCD_PROVIDER`
- `AZURE_OPENAI_ENDPOINT`
- `AZURE_OPENAI_CHAT_DEPLOYMENT_NAME`
- `AZURE_OPENAI_API_VERSION`
- `AZURE_OPENAI_WHISPER_DEPLOYMENT`
- `AZURE_OPENAI_VISION_DEPLOYMENT`
- `AZURE_OPENAI_DEPLOYMENT_NAME`
- `AZURE_OPENAI_DEPLOYMENT`
- `AZURE_OPENAI_DEPLOYMENT_BALANCED`
- `AZURE_OPENAI_DEPLOYMENT_QUALITY`
- `OPENAI_API_KEY`
- `OPENAI_CHAT_MODEL_BALANCED`
- `OPENAI_CHAT_MODEL_QUALITY`
- `OPENAI_TRANSCRIPTION_MODEL`
- `OPENAI_VISION_MODEL`

Current ownership:

- local runs: shell env or `.env.docker.local`
- Azure deploy/runtime path today: direct app settings / GitHub secrets, not Key Vault-backed by current bootstrap

Tuning knobs:

- `PFCD_VISION_FRAMES_PER_CALL`
- `PFCD_VISION_MAX_FRAMES`
- `PFCD_CONSISTENCY_MATCH_THRESHOLD`
- `PFCD_CONSISTENCY_INCONCLUSIVE_THRESHOLD`
- `PFCD_CONSISTENCY_MISMATCH_THRESHOLD`

### 3. Integrated local Docker stack

Primary entrypoint:

```bash
cp docker-compose.local.env.example .env.docker.local
docker compose --env-file .env.docker.local -f docker-compose.local.yml up --build -d
```

Values most users will touch first:

- `PFCD_LOCAL_API_PORT`
- `PFCD_LOCAL_FRONTEND_PORT`
- `VITE_API_BASE`
  Leave blank for the integrated stack so nginx proxies same-origin `/api`.
- `VITE_API_KEY`
- `PFCD_API_KEY`
- `PFCD_PROVIDER`
- `DATABASE_URL`
- `UPLOADS_DIR`
- `EXPORTS_BASE_PATH`
- `PFCD_CORS_ORIGINS`

Optional Azure/OpenAI/OpenAI pass-through values are also exposed in the compose file now, so users do not need to edit YAML to try a different provider or real agent credentials.
Worker-only variables such as `PFCD_WORKER_ROLE` are intentionally not part of this integrated stack because `docker-compose.local.yml` only runs the API and frontend services.

The file you edit for this mode is [`.env.docker.local`](/Users/karthicks/kAgents/Projects/PFCD-V2/.env.docker.local).

### 4. Azure-backed local or deployed runs

These move the app from a local smoke path toward operational behavior:

- `AZURE_STORAGE_CONNECTION_STRING` or `AZURE_STORAGE_ACCOUNT_URL` / `AZURE_STORAGE_ACCOUNT_NAME`
- `AZURE_STORAGE_CONTAINER_EVIDENCE`
- `AZURE_STORAGE_CONTAINER_EXPORTS`
- `AZURE_SERVICE_BUS_CONNECTION_STRING`
- `AZURE_SERVICE_BUS_QUEUE_EXTRACTING`
- `AZURE_SERVICE_BUS_QUEUE_PROCESSING`
- `AZURE_SERVICE_BUS_QUEUE_REVIEWING`

Current ownership in Azure:

- `DATABASE_URL`, `AZURE_STORAGE_CONNECTION_STRING`, `AZURE_SERVICE_BUS_CONNECTION_STRING`
  - Key Vault-backed by the current bootstrap and exposed to App Service as Key Vault references
- `AZURE_SERVICE_BUS_QUEUE_*`, `KEYVAULT_NAME`, `AZURE_OPENAI_ACCOUNT_NAME`, `AZURE_SPEECH_ACCOUNT_NAME`
  - direct app settings today
- `AZURE_OPENAI_ENDPOINT` and deployment-name settings
  - direct app settings / deploy secrets today, not Key Vault-backed by current bootstrap

The following values are currently most relevant to `/health` diagnostics and Azure environment parity:

- `AZURE_SERVICE_BUS_NAMESPACE`
- `KEYVAULT_NAME`
- `AZURE_SQL_SERVER_NAME`
- `AZURE_SQL_DATABASE_NAME`
- `AZURE_OPENAI_ACCOUNT_NAME`
- `AZURE_SPEECH_ACCOUNT_NAME`

## Practical guidance

- Use placeholder Azure values for smoke tests where the goal is only to prove the container starts.
- Use real provider, storage, and queue settings only when you want processing behavior instead of a degraded-but-running local stack.
- Keep local secrets in `.env.docker.local` or shell env vars, not in tracked files.
- For the current Azure setup, do not assume `PFCD_API_KEY` or `VITE_API_KEY` are in Key Vault; check GitHub secrets and App Service settings first.
- Repo-local scratch data should stay out of Git; `.env.docker.local`, `backend/storage/`, and repo-root `storage/` are ignored.
