# PFCD Frontend

This frontend is a Vite + React single-page app.

## Local development

```bash
cd frontend
npm ci
npm run dev
```

## Container runtime

The frontend can now be built and served as a container image:

```bash
cd frontend
docker build -t pfcd-frontend:local .
docker run --rm -p 3000:80 pfcd-frontend:local
curl http://127.0.0.1:3000/health
```

### Build arguments

- `VITE_API_BASE` (optional): API origin baked into the bundle, for example `http://127.0.0.1:8000`
- `VITE_API_KEY` (optional): API key baked into the bundle to preserve the current deploy-time behavior

Example:

```bash
cd frontend
docker build \
  --build-arg VITE_API_BASE=http://127.0.0.1:8000 \
  --build-arg VITE_API_KEY=dev-key \
  -t pfcd-frontend:local .
```

### Local smoke path

Use [docker-compose.smoke.yml](/Users/karthicks/kAgents/Projects/PFCD-V2/frontend/docker-compose.smoke.yml) for a repeatable local startup check:

```bash
cd frontend
VITE_API_BASE=http://127.0.0.1:8000 docker compose -f docker-compose.smoke.yml up --build -d
curl http://127.0.0.1:3000/health
docker compose -f docker-compose.smoke.yml down --remove-orphans
```

What to expect:

- `GET /health` returns `ok`
- `GET /` serves the built SPA with index fallback handled by nginx

## Integrated local stack

Use the repo-level [docker-compose.local.yml](/Users/karthicks/kAgents/Projects/PFCD-V2/docker-compose.local.yml) to run the frontend against the backend container without baking an unreachable Docker hostname into the browser bundle:

```bash
cp docker-compose.local.env.example .env.docker.local
docker compose --env-file .env.docker.local -f docker-compose.local.yml up --build -d
curl http://127.0.0.1:3000/health
curl http://127.0.0.1:8000/health
docker compose -f docker-compose.local.yml down --remove-orphans
```

What changes in this mode:

- `VITE_API_BASE` is left empty so the app talks to same-origin `/api`
- nginx proxies `/api/*` and `/dev/*` to the backend service inside Docker
- backend health is allowed to be `degraded` locally because the integrated stack intentionally omits Azure Service Bus and the worker services
- the example env file lives at [docker-compose.local.env.example](/Users/karthicks/kAgents/Projects/PFCD-V2/docker-compose.local.env.example)

## Notes

- `staticwebapp.config.json` still applies to the existing Azure Static Web Apps deployment path.
- The container runtime uses nginx instead, with its own SPA fallback and health endpoint.
