# PFCD Dev Azure Bootstrap (app-pfcd-v2)

This folder contains an executable script to create a **development** Azure environment in
`app-pfcd-v2` (southindia) with explicit dev tagging and cost-focused configuration.

## What it creates
- Storage account + containers (`uploads`, `evidence`, `exports`, `scratch`)
- Service Bus namespace + `jobs` queue
- Key Vault + secret entries
- Azure SQL Server + SQL Database
- App Service Plan + Linux Web App (`PYTHON:3.11`)
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
- Set `SERVICE_BUS_SKU` to `Standard` if topics are enabled in a later phase; `Basic` is default for queue-only flow.
- If the deployment step fails, export a supported model version string for your region and rerun with:
  `OPENAI_MODEL_NAME=<name> OPENAI_MODEL_VERSION=<version> bash infra/dev-bootstrap.sh`
- Key Vault access is granted via `Key Vault Secrets Officer` role assignment to the signed-in user.
- Budget creation is intentionally non-blocking in the script to account for command API differences.

## Verification
- `az resource list --resource-group app-pfcd-v2`
- `az webapp config appsettings list --name pfcd-dev-api --resource-group app-pfcd-v2 --query \"[?starts_with(name, 'AZURE') || starts_with(name, 'APP_') || starts_with(name, 'COST_')].[name, value]\" -o table`
- `az keyvault secret list --vault-name pfcd-dev-kv`
- `az servicebus queue show --resource-group app-pfcd-v2 --namespace-name pfcd-dev-bus --name jobs`

## Deployment
- App Service startup command is set to `uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}`.
- GitHub Actions deploy uses the App Service publish profile stored as `AZURE_WEBAPP_PUBLISH_PROFILE`.
  - Set repo secrets: `AZURE_WEBAPP_NAME` (e.g., `pfcd-dev-api`) and `AZURE_WEBAPP_PUBLISH_PROFILE`.

Key Vault-backed settings created by the script:
- `DATABASE_URL` -> secret `sql-connection-string`
- `AZURE_STORAGE_CONNECTION_STRING` -> secret `storage-connection-string`

## Environment overrides
- `RESOURCE_GROUP`, `AZURE_LOCATION`, `PROJECT_NAME`, `ENVIRONMENT_NAME`
- `APP_SERVICE_PLAN`, `WEBAPP_NAME`, `SPEECH_ACCOUNT_LOCATION`
- `OPENAI_DEPLOYMENT_NAME`, `OPENAI_MODEL_NAME`, `OPENAI_MODEL_VERSION`
- `OPENAI_SKU_NAME`, `SERVICE_BUS_SKU`
- `MONTHLY_BUDGET`, `BUDGET_NAME`, `SQL_ADMIN_USER`, `SQL_ADMIN_PASSWORD`
