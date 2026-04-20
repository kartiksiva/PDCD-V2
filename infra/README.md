# PFCD Dev Azure Bootstrap (app-pfcd-v2)

This folder contains an executable script to create a **development** Azure environment in
`app-pfcd-v2` (southindia) with explicit dev tagging and cost-focused configuration.

## What it creates
- Storage account + containers (`uploads`, `evidence`, `exports`, `scratch`)
- Service Bus namespace + phase queues (`extracting`, `processing`, `reviewing`)
- Key Vault + secret entries
- Azure Database for PostgreSQL Flexible Server + database
- App Service Plan + Linux Web App (`PYTHON:3.11`)
- Azure OpenAI + Speech accounts
- Application Insights (workspace-based) + Key Vault-backed connection string wiring to API/workers
- Azure Monitor alerting baseline (API 5xx, queue DLQ alerts, readiness failure query alert)
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

## Verification
- `az resource list --resource-group app-pfcd-v2`
- `az webapp config appsettings list --name pfcd-dev-api --resource-group app-pfcd-v2 --query \"[?starts_with(name, 'AZURE') || starts_with(name, 'APP_') || starts_with(name, 'COST_')].[name, value]\" -o table`
- `az keyvault secret list --vault-name pfcd-dev-kv`
- `az servicebus queue show --resource-group app-pfcd-v2 --namespace-name pfcd-dev-bus --name extracting`
- `az monitor app-insights component show --app pfcd-dev-appi --resource-group app-pfcd-v2`
- `az monitor metrics alert list --resource-group app-pfcd-v2 -o table`
- `az monitor scheduled-query list --resource-group app-pfcd-v2 -o table`
- `curl -sS https://<api-host>/health/readiness`

## Deployment
- App Service startup command is set to `uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}`.
- Backend GitHub Actions deploys upload `backend.zip` to the `scratch` blob container, generate a SAS package URL, and set `WEBSITE_RUN_FROM_PACKAGE` on the API app.
- Worker GitHub Actions deploys upload `worker.zip` to the `scratch` blob container, generate a SAS package URL, and set `WEBSITE_RUN_FROM_PACKAGE` on each worker app.
- No App Service publish-profile secrets are required for backend or worker deploys on this path.

Key Vault-backed settings created by the script:
- `DATABASE_URL` -> secret `postgres-connection-string`
- `AZURE_STORAGE_CONNECTION_STRING` -> secret `storage-connection-string`
- `AZURE_SERVICE_BUS_CONNECTION_STRING` -> secret `service-bus-connection-string`

App Service build:
- API and worker package-URL deploys require the app managed identities to have `Storage Blob Data Reader` on the storage account, and the CI service principal to have `Storage Blob Data Contributor` when uploading the package blob.

After updating bootstrap settings, rerun `infra/dev-bootstrap.sh` and restart the App Service:
```bash
az webapp restart --name pfcd-dev-api --resource-group app-pfcd-v2
```

## Environment overrides
- `RESOURCE_GROUP`, `AZURE_LOCATION`, `PROJECT_NAME`, `ENVIRONMENT_NAME`
- `APP_SERVICE_PLAN`, `WEBAPP_NAME`, `SPEECH_ACCOUNT_LOCATION`
- `OPENAI_DEPLOYMENT_NAME`, `OPENAI_MODEL_NAME`, `OPENAI_MODEL_VERSION`
- `OPENAI_SKU_NAME`, `SERVICE_BUS_SKU`
- `SERVICE_BUS_QUEUE_EXTRACTING`, `SERVICE_BUS_QUEUE_PROCESSING`, `SERVICE_BUS_QUEUE_REVIEWING`
- `APP_INSIGHTS_NAME`, `ALERT_ACTION_GROUP_NAME`, `ALERT_EMAIL` (optional; if `ALERT_EMAIL` is unset, alerts are created without notification actions)
- `SP_CLIENT_ID` (optional; grants the CI service principal blob-write access on the storage account)
- `MONTHLY_BUDGET`, `BUDGET_NAME`, `POSTGRES_ADMIN_USER`, `POSTGRES_ADMIN_PASSWORD`
