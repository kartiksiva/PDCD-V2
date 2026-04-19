# Issue #17 Docker / Azure Container Apps Impact Analysis

Source issue: [GitHub issue #17](https://github.com/kartiksiva/PDCD-V2/issues/17)

Assumption: "azure app container service" refers to Azure Container Apps. This document evaluates moving the current backend and worker runtime from Linux App Service package deploys to Docker images deployed on Azure Container Apps, while keeping the existing frontend Static Web App unless there is a separate reason to migrate it.

## Task Summary

Issue #17 asks for a narrow, codebase-grounded analysis of the impact of moving to a Docker-based deployment model because the current App Service path has been operationally fragile.

This is an analysis-only deliverable. It does not implement containers yet.

## Current Deployment Shape

- Frontend deploys to Azure Static Web Apps from `frontend/dist`.
- Backend API deploys to Linux App Service via zip package + `WEBSITE_RUN_FROM_PACKAGE`.
- Three workers (`extracting`, `processing`, `reviewing`) each deploy to separate Linux App Services via the same package-URL pattern.
- Azure SQL, Blob Storage, Service Bus, Key Vault, Azure OpenAI, and Azure Speech are already external managed services and are not tightly coupled to App Service as a platform choice.

## Why The Current App Service Path Is Fragile

The recent repo history shows repeated operational fixes around App Service package startup rather than application logic:

- Backend and worker workflows now pre-vendor Python dependencies into `antenv/.../site-packages` before zipping because `WEBSITE_RUN_FROM_PACKAGE` does not run an install step.
- Deploy workflows must set `PYTHONPATH` manually so the mounted package can find vendored dependencies.
- The backend workflow must override startup to `python -m uvicorn ...` because the `uvicorn` executable is not available in PATH in the mounted package model.
- Workers run a tiny HTTP server only so Azure App Service warmup probes do not kill non-HTTP queue consumers.
- The repo already documents `ffmpeg` as a better fit for custom images than App Service-hosted Python.

Taken together, the current deployment is workable, but it is platform-shaped in ways that increase operational complexity and make runtime behavior harder to reason about.

## Impact Assessment

### 1. Runtime Packaging

Impact: positive

Moving to Docker removes the current dependency on zip packaging, Oryx/package-URL behavior, `WEBSITE_RUN_FROM_PACKAGE`, and manual `PYTHONPATH` stitching. The image can contain:

- Python dependencies already installed
- native OS packages such as `unixodbc-dev` or the runtime equivalents required by `pyodbc`
- `ffmpeg` for media preprocessing
- an explicit startup command

This is the strongest technical reason to move.

### 2. Backend API Hosting

Impact: low-to-medium code impact, medium infra impact

The FastAPI app is already container-friendly:

- it starts with `uvicorn`
- it exposes `/health`
- it reads configuration from environment variables
- it depends on external services rather than local host resources

If env var names are preserved, backend application code changes should be minimal or unnecessary. Most work shifts to Dockerfiles, CI/CD, and Azure resource provisioning.

### 3. Worker Hosting Model

Impact: medium platform impact, low app-code impact

The workers are long-running Service Bus consumers, which fits container hosting better than App Service. In the current code, `backend/app/workers/runner.py` starts an HTTP server only for App Service warmup. Under Azure Container Apps:

- that warmup-specific shim becomes optional rather than mandatory
- workers can run as non-public containers
- scaling can be tied more naturally to queue demand later

To keep migration scope narrow, the current long-running worker loop can stay as-is initially. The first move does not require a rewrite to jobs or event-driven tasks.

### 4. External Service Dependencies

Impact: low

Azure SQL, Service Bus, Blob Storage, Key Vault, Azure OpenAI, and Azure Speech remain the same. The code already talks to them through environment variables and Azure SDKs. This limits migration risk because the application contract with those services does not need to change.

### 5. Secrets and Identity

Impact: medium infra impact

The code relies on env vars and `DefaultAzureCredential` in several places. That is favorable for containers. The main migration work is operational:

- define secrets for Container Apps
- decide which settings stay as plain env vars and which are projected from Key Vault
- attach managed identity with equivalent permissions

If the same environment variable names are preserved, code churn should stay low.

### 6. Networking and Frontend Integration

Impact: low

The frontend already uses `VITE_API_BASE`, so pointing it at a Container Apps HTTPS endpoint is straightforward. This supports a narrow migration where:

- frontend stays on Static Web Apps
- only the backend origin changes

No frontend architecture rewrite is required.

### 7. CI/CD

Impact: high workflow impact

This is the biggest non-code change area. The current backend and worker workflows are built around:

- zip creation
- scratch blob upload
- SAS package URLs
- `az webapp config appsettings set`
- App Service restarts and settle loops

A Docker/Container Apps move would replace those with:

- image build
- registry push
- container deployment/update
- revision or rollout verification

This is a substantial workflow simplification long-term, but it is still real migration work.

### 8. Infrastructure Provisioning

Impact: high infra impact

`infra/dev-bootstrap.sh` and `infra/README.md` currently provision and describe App Service Plan + four Web Apps. A Container Apps migration requires new provisioning for at least:

- Container Apps environment
- Azure Container Registry
- one API container app
- three worker container apps, or another worker topology chosen explicitly

This is the main area where "move to Docker" becomes more than a deploy-script tweak.

## Strongest Benefits Of The Move

1. Removes App Service package-deploy fragility that already required multiple remediation passes.
2. Lets the runtime include `ffmpeg` and native dependencies directly instead of depending on host assumptions.
3. Fits queue workers better because they are not naturally HTTP services.
4. Makes local and CI behavior closer to production because the same container image can be exercised across environments.

## Main Risks

1. CI/CD and infra work is larger than the application-code work.
2. Container Apps scaling for queue workers should be designed intentionally; a rushed change could keep the current always-on cost profile without gaining the full benefit.
3. Secrets, managed identity, and outbound connectivity to SQL/Service Bus/Storage must be validated carefully during migration.
4. If the move is done all at once, failure isolation becomes harder because API, workers, and infra are all changing together.

## Recommended Narrow Migration Path

### Phase 1: Prove the runtime model

- Add one shared Python base image for `backend/`.
- Add explicit container commands for:
  - API: `python -m uvicorn app.main:app --host 0.0.0.0 --port 8000`
  - workers: `python -m app.workers.runner`
- Install native dependencies and `ffmpeg` in the image.
- Run the existing test suite against the same codebase before changing Azure hosting.

### Phase 2: Migrate the API first

- Create a single Azure Container App for the backend API with public ingress.
- Keep env var names identical to the current app where possible.
- Point `VITE_API_BASE` at the new API endpoint.
- Leave workers on the existing platform during the first cut so rollback stays simple.

### Phase 3: Migrate workers second

- Move `extracting`, `processing`, and `reviewing` to separate non-public container apps.
- Keep the current worker loop initially.
- Revisit queue-driven autoscaling only after the baseline container deployment is stable.

### Phase 4: Remove App Service-specific code and workflow assumptions

- Delete package-URL deploy logic.
- Delete App Service warmup-specific worker shims if no longer needed.
- Update infra/bootstrap and runbooks to Container Apps terminology and checks.

## Recommendation

Moving to Docker on Azure Container Apps is a good fit for this repository and directly addresses the failure modes that have consumed recent deployment work. The migration is justified, but it should be treated primarily as an infrastructure and delivery change, not an application rewrite.

The narrowest safe path is:

1. keep the application contracts unchanged
2. preserve current environment variable names
3. containerize once for a shared runtime
4. migrate the API first
5. migrate workers after the API path is proven

## Suggested Next Implementation Task

If issue #17 turns into execution work, the next narrow task should be:

"Add production-ready Dockerfiles plus a local container smoke path for the backend API and worker runtime, without changing Azure infrastructure yet."

That would validate the runtime move before mixing in ACR, Container Apps, and identity changes.
