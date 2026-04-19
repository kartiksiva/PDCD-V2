# PFCD Dev Azure Bootstrap (app-pfcd-v2)

This folder contains an executable script to create a **development** Azure environment in
`app-pfcd-v2` (southindia) with explicit dev tagging and cost-focused configuration.

## What it creates
- Storage account + containers (`uploads`, `evidence`, `exports`, `scratch`)
- Service Bus namespace + phase queues (`extracting`, `processing`, `reviewing`)
- Key Vault + secret entries
- Azure Database for PostgreSQL Flexible Server + database
- Azure Container Registry + Log Analytics workspace + Azure Container Apps environment
- Legacy App Service Plan + Linux Web Apps (`PYTHON:3.11`) only when `PROVISION_LEGACY_APP_SERVICE=true`
- Azure OpenAI + Speech accounts
- Cost budget hook (best effort; may require manual portal step depending on CLI/API)

## Run

```bash
az login
cd /Users/karthicks/kAgents/Projects/PFCD-V2
SPEECH_ACCOUNT_LOCATION=eastus bash infra/dev-bootstrap.sh
```

## Notes
- `SPEECH_ACCOUNT_LOCATION` defaults to `eastus` because Speech region availability is limited by subscription/model parity.
- OpenAI deployment is parameterized with `OPENAI_SKU_NAME` (default `GlobalStandard`) and model/version overrides; use one supported pair for your region.
- `SERVICE_BUS_SKU` defaults to `Standard` for multi-queue orchestration.
- If the deployment step fails, export a supported model version string for your region and rerun with:
  `OPENAI_MODEL_NAME=<name> OPENAI_MODEL_VERSION=<version> bash infra/dev-bootstrap.sh`
- Key Vault is created with RBAC enabled; access is granted via `Key Vault Secrets Officer` role assignment to the signed-in user.
- PostgreSQL flexible server is created with public access for Azure-hosted services and a PostgreSQL `DATABASE_URL` that uses `sslmode=require`.
- Budget creation is intentionally non-blocking in the script to account for command API differences.
- The bootstrap is now ACA-first. Legacy App Service resources are opt-in for rollback only: `PROVISION_LEGACY_APP_SERVICE=true bash infra/dev-bootstrap.sh`.

## Verification
- `az resource list --resource-group app-pfcd-v2`
- `az containerapp env show --name pfcd-dev-env --resource-group app-pfcd-v2`
- `az keyvault secret list --vault-name pfcd-dev-kv`
- `az servicebus queue show --resource-group app-pfcd-v2 --namespace-name pfcd-dev-bus --name extracting`

## Deployment
- Backend GitHub Actions deploys build/push `backend/Dockerfile --target api` and update the API Azure Container App.
- Worker GitHub Actions deploys build/push `backend/Dockerfile --target worker` and update the three worker Azure Container Apps with Service Bus scaling.
- Legacy App Service provisioning remains available as a rollback path, but it is no longer the default bootstrap mode.

Key Vault-backed settings created by the script:
- `DATABASE_URL` -> secret `postgres-connection-string`
- `AZURE_STORAGE_CONNECTION_STRING` -> secret `storage-connection-string`
- `AZURE_SERVICE_BUS_CONNECTION_STRING` -> secret `service-bus-connection-string`

## Environment overrides
- `RESOURCE_GROUP`, `AZURE_LOCATION`, `PROJECT_NAME`, `ENVIRONMENT_NAME`
- `APP_SERVICE_PLAN`, `WEBAPP_NAME`, `PROVISION_LEGACY_APP_SERVICE`, `SPEECH_ACCOUNT_LOCATION`
- `OPENAI_DEPLOYMENT_NAME`, `OPENAI_MODEL_NAME`, `OPENAI_MODEL_VERSION`
- `OPENAI_SKU_NAME`, `SERVICE_BUS_SKU`
- `SERVICE_BUS_QUEUE_EXTRACTING`, `SERVICE_BUS_QUEUE_PROCESSING`, `SERVICE_BUS_QUEUE_REVIEWING`
- `SP_CLIENT_ID` (optional; grants the CI service principal blob-write access on the storage account)
- `MONTHLY_BUDGET`, `BUDGET_NAME`, `POSTGRES_ADMIN_USER`, `POSTGRES_ADMIN_PASSWORD`
- `POSTGRES_SERVER_NAME`, `POSTGRES_DATABASE_NAME`, `POSTGRES_VERSION`, `POSTGRES_SKU_NAME`, `POSTGRES_TIER`, `POSTGRES_STORAGE_SIZE`
