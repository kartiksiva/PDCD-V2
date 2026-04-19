# PFCD Backend (Skeleton)

This is the first runnable backend skeleton for the Video-First v1 API contract.

- Framework: FastAPI
- Entry point: `backend/app/main.py`

## Quick start

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

## Container runtime

The backend now ships a shared Docker build in [Dockerfile](/Users/karthicks/kAgents/Projects/PFCD-V2/backend/Dockerfile) with two runtime targets:

- `api`: FastAPI container started with `python -m uvicorn app.main:app --host 0.0.0.0 --port 8000`
- `worker`: queue-consumer container started with `python -m app.workers.runner` and `PFCD_WORKER_ROLE` supplied at runtime

The image includes the native dependencies that have been awkward on App Service, primarily `ffmpeg` for media preprocessing plus the Python dependencies from `requirements.txt`.

### Local smoke path

Use [docker-compose.smoke.yml](/Users/karthicks/kAgents/Projects/PFCD-V2/backend/docker-compose.smoke.yml) to prove the containerized runtime starts before any Azure hosting changes:

```bash
cd backend
docker compose -f docker-compose.smoke.yml build
PFCD_SMOKE_API_PORT=8010 docker compose -f docker-compose.smoke.yml up -d api
curl http://127.0.0.1:8010/health
docker compose -f docker-compose.smoke.yml up worker-extracting
```

What to expect:

- `curl http://127.0.0.1:8010/health` returns a JSON health payload from the API container
- `worker-extracting` logs `Worker starting for phase extracting`
- with the placeholder Service Bus connection string, the worker keeps running and retries receiver setup, which is enough to prove container startup and entry into the listener loop locally

If `8000` is free on your machine, you can omit `PFCD_SMOKE_API_PORT` and use the default host port mapping.

Tear down the smoke stack with:

```bash
cd backend
docker compose -f docker-compose.smoke.yml down --remove-orphans
```

### Frontend integration

Use the repo-level [docker-compose.local.yml](/Users/karthicks/kAgents/Projects/PFCD-V2/docker-compose.local.yml) when you want the frontend and backend running together:

```bash
cp docker-compose.local.env.example .env.docker.local
docker compose --env-file .env.docker.local -f docker-compose.local.yml up --build -d
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:3000/health
docker compose -f docker-compose.local.yml down --remove-orphans
```

Notes:

- the frontend proxies `/api/*` and `/dev/*` to the backend container, so the browser can stay on `http://127.0.0.1:3000`
- the backend is expected to report `status=degraded` locally until Azure Service Bus and the other Azure-backed settings are supplied
- `POST /api/upload` and `POST /api/jobs` still work locally; jobs remain queued until workers and a real Service Bus connection are added
- the example env file lives at [docker-compose.local.env.example](/Users/karthicks/kAgents/Projects/PFCD-V2/docker-compose.local.env.example)

## Worker start (Service Bus)

Start each worker with a role-specific environment variable:

```bash
export AZURE_SERVICE_BUS_CONNECTION_STRING="Endpoint=sb://..."
export AZURE_SERVICE_BUS_QUEUE_EXTRACTING=extracting
export AZURE_SERVICE_BUS_QUEUE_PROCESSING=processing
export AZURE_SERVICE_BUS_QUEUE_REVIEWING=reviewing

# Extraction worker
PFCD_WORKER_ROLE=extracting python -m app.workers.runner

# Processing worker
PFCD_WORKER_ROLE=processing python -m app.workers.runner

# Reviewing worker
PFCD_WORKER_ROLE=reviewing python -m app.workers.runner
```

## Endpoints

- `POST /api/jobs`
- `GET /api/jobs/{job_id}`
- `GET /api/jobs/{job_id}/draft`
- `PUT /api/jobs/{job_id}/draft`
- `POST /api/jobs/{job_id}/finalize`
- `GET /api/jobs/{job_id}/exports/{format}`
- `DELETE /api/jobs/{job_id}`
- `GET /health`

## Notes

- Job payloads are persisted via SQL (default: local SQLite).
- Export payloads for PDF/DOCX are placeholders.
- This baseline includes:
  - fixed file-size guard (413 on >500MB),
  - agent run placeholders and state transitions,
  - review blocker checks on finalize,
  - speaker resolution persistence in draft payloads.

## Persistence and storage

The backend now persists job payloads to a SQL database and stores exports in Blob Storage
when configured.

### Alembic migrations

```bash
cd backend
alembic upgrade head
```

Required/optional environment variables:

- `DATABASE_URL` (optional, default: `sqlite:///./pfcd.db`)
- PostgreSQL example:
  - `postgresql+psycopg://<user>:<password>@<server>:5432/<database>?sslmode=require`
- `AZURE_STORAGE_CONNECTION_STRING` (optional, enables Blob exports)
- `AZURE_STORAGE_CONTAINER_EXPORTS` (optional, default: `exports`)
- `EXPORTS_BASE_PATH` (optional, default: `./storage/exports` for local exports)
- `AZURE_SERVICE_BUS_CONNECTION_STRING` (required for orchestration)
- `AZURE_SERVICE_BUS_QUEUE_EXTRACTING` (default: `extracting`)
- `AZURE_SERVICE_BUS_QUEUE_PROCESSING` (default: `processing`)
- `AZURE_SERVICE_BUS_QUEUE_REVIEWING` (default: `reviewing`)
- `PFCD_MAX_RETRIES` (optional, default: 3)
