#!/usr/bin/env bash

set -euo pipefail

RESOURCE_GROUP="${RESOURCE_GROUP:-app-pfcd-v2}"
LOCATION="${AZURE_LOCATION:-southindia}"
ENVIRONMENT="${ENVIRONMENT_NAME:-dev}"
PROJECT="${PROJECT_NAME:-pfcd}"
SUBSCRIPTION_ID="${SUBSCRIPTION_ID:-$(az account show --query id -o tsv)}"
MONTHLY_BUDGET="${MONTHLY_BUDGET:-150}"
BUDGET_NAME="${BUDGET_NAME:-${PROJECT}-${ENVIRONMENT}-budget}"

APP_SERVICE_PLAN="${APP_SERVICE_PLAN:-${PROJECT}-${ENVIRONMENT}-asp}"
WEBAPP_NAME="${WEBAPP_NAME:-${PROJECT}-${ENVIRONMENT}-api}"
WORKER_EXTRACTING_NAME="${WORKER_EXTRACTING_NAME:-${PROJECT}-${ENVIRONMENT}-worker-extracting}"
WORKER_PROCESSING_NAME="${WORKER_PROCESSING_NAME:-${PROJECT}-${ENVIRONMENT}-worker-processing}"
WORKER_REVIEWING_NAME="${WORKER_REVIEWING_NAME:-${PROJECT}-${ENVIRONMENT}-worker-reviewing}"
CONTAINER_REGISTRY_NAME="${CONTAINER_REGISTRY_NAME:-${PROJECT}${ENVIRONMENT}registry}"
CONTAINER_REGISTRY_SKU="${CONTAINER_REGISTRY_SKU:-Basic}"
CONTAINER_APPS_ENVIRONMENT_NAME="${CONTAINER_APPS_ENVIRONMENT_NAME:-${PROJECT}-${ENVIRONMENT}-env}"
LOG_ANALYTICS_WORKSPACE_NAME="${LOG_ANALYTICS_WORKSPACE_NAME:-${PROJECT}-${ENVIRONMENT}-logs}"
APP_INSIGHTS_NAME="${APP_INSIGHTS_NAME:-${PROJECT}-${ENVIRONMENT}-appi}"
ALERT_ACTION_GROUP_NAME="${ALERT_ACTION_GROUP_NAME:-${PROJECT}-${ENVIRONMENT}-ops-ag}"
ALERT_EMAIL="${ALERT_EMAIL:-}"
STORAGE_ACCOUNT="${STORAGE_ACCOUNT:-${PROJECT}${ENVIRONMENT}storage}"
SERVICE_BUS_NAMESPACE="${SERVICE_BUS_NAMESPACE:-${PROJECT}-${ENVIRONMENT}-bus}"
SERVICE_BUS_QUEUE="${SERVICE_BUS_QUEUE:-jobs}"
SERVICE_BUS_QUEUE_EXTRACTING="${SERVICE_BUS_QUEUE_EXTRACTING:-extracting}"
SERVICE_BUS_QUEUE_PROCESSING="${SERVICE_BUS_QUEUE_PROCESSING:-processing}"
SERVICE_BUS_QUEUE_REVIEWING="${SERVICE_BUS_QUEUE_REVIEWING:-reviewing}"
SERVICE_BUS_SKU="${SERVICE_BUS_SKU:-Standard}"
POSTGRES_SERVER_NAME="${POSTGRES_SERVER_NAME:-${PROJECT}-${ENVIRONMENT}-pg}"
POSTGRES_DATABASE_NAME="${POSTGRES_DATABASE_NAME:-${PROJECT}-${ENVIRONMENT}-jobs}"
KEY_VAULT_NAME="${KEY_VAULT_NAME:-${PROJECT}-${ENVIRONMENT}-kv}"
OPENAI_ACCOUNT_NAME="${OPENAI_ACCOUNT_NAME:-${PROJECT}-${ENVIRONMENT}-oai}"
SPEECH_ACCOUNT_NAME="${SPEECH_ACCOUNT_NAME:-${PROJECT}-${ENVIRONMENT}-speech}"
SPEECH_ACCOUNT_LOCATION="${SPEECH_ACCOUNT_LOCATION:-eastus}"

OPENAI_DEPLOYMENT_NAME="${OPENAI_DEPLOYMENT_NAME:-gpt-4o-mini}"
OPENAI_MODEL_NAME="${OPENAI_MODEL_NAME:-gpt-4o-mini}"
OPENAI_MODEL_VERSION="${OPENAI_MODEL_VERSION:-2024-07-18}"
OPENAI_SKU_CAPACITY="${OPENAI_SKU_CAPACITY:-1}"
OPENAI_SKU_NAME="${OPENAI_SKU_NAME:-GlobalStandard}"

POSTGRES_VERSION="${POSTGRES_VERSION:-16}"
POSTGRES_SKU_NAME="${POSTGRES_SKU_NAME:-Standard_B1ms}"
POSTGRES_TIER="${POSTGRES_TIER:-Burstable}"
POSTGRES_STORAGE_SIZE="${POSTGRES_STORAGE_SIZE:-32}"
POSTGRES_ADMIN_USER="${POSTGRES_ADMIN_USER:-pfcdadmin}"
POSTGRES_ADMIN_PASSWORD="${POSTGRES_ADMIN_PASSWORD:-$(openssl rand -base64 30 | tr -dc 'A-Za-z0-9' | head -c 24)}"

readonly COMMON_TAGS="Environment=$ENVIRONMENT Project=$PROJECT CostProfile=development"

info() { echo "[pfcd-bootstrap] $*"; }
fatal() { echo "[pfcd-bootstrap] ERROR: $*" >&2; exit 1; }

ensure_tagged_resource() {
  local kind=$1
  local name=$2
  shift 2
  local create_cmd=("$@")
  if az "$kind" show "$name" >/dev/null 2>&1; then
    info "exists: $name"
    return
  fi
  info "creating: $name"
  "${create_cmd[@]}"
}

ensure_rg() {
  if az group show --name "$RESOURCE_GROUP" >/dev/null 2>&1; then
    info "using existing resource group: $RESOURCE_GROUP"
  else
    az group create --name "$RESOURCE_GROUP" --location "$LOCATION" --tags $COMMON_TAGS --output none
  fi
}

ensure_storage_account() {
  local existing_name="$STORAGE_ACCOUNT"
  local user_object_id
  user_object_id="$(az ad signed-in-user show --query id -o tsv)"
  local storage_scope
  storage_scope="/subscriptions/${SUBSCRIPTION_ID}/resourceGroups/${RESOURCE_GROUP}/providers/Microsoft.Storage/storageAccounts/${existing_name}"

  if ! az storage account show --resource-group "$RESOURCE_GROUP" --name "$existing_name" >/dev/null 2>&1; then
    az storage account create \
      --name "$existing_name" \
      --resource-group "$RESOURCE_GROUP" \
      --location "$LOCATION" \
      --sku Standard_LRS \
      --kind StorageV2 \
      --min-tls-version TLS1_2 \
      --allow-shared-key-access true \
      --tags $COMMON_TAGS \
      --output none
  fi

  az role assignment create \
    --assignee-object-id "$user_object_id" \
    --role "Storage Blob Data Contributor" \
    --scope "$storage_scope" \
    --output none >/dev/null \
    || true

  # Grant the CI service principal blob write access when its client ID is provided.
  if [[ -n "${SP_CLIENT_ID:-}" ]]; then
    local sp_object_id
    sp_object_id="$(az ad sp show --id "$SP_CLIENT_ID" --query id -o tsv 2>/dev/null || true)"
    if [[ -n "$sp_object_id" ]]; then
      az role assignment create \
        --assignee-object-id "$sp_object_id" \
        --role "Storage Blob Data Contributor" \
        --scope "$storage_scope" \
        --output none >/dev/null \
        || true
    fi
  fi

  for container in uploads evidence exports scratch; do
    az storage container create \
      --account-name "$existing_name" \
      --name "$container" \
      --auth-mode login \
      --public-access off \
      --output none
  done
}

ensure_servicebus() {
  if ! az servicebus namespace show --resource-group "$RESOURCE_GROUP" --name "$SERVICE_BUS_NAMESPACE" >/dev/null 2>&1; then
  az servicebus namespace create \
      --name "$SERVICE_BUS_NAMESPACE" \
      --resource-group "$RESOURCE_GROUP" \
      --location "$LOCATION" \
      --sku "$SERVICE_BUS_SKU" \
      --tags $COMMON_TAGS \
      --output none
  fi

  if ! az servicebus queue show --resource-group "$RESOURCE_GROUP" --namespace-name "$SERVICE_BUS_NAMESPACE" --name "$SERVICE_BUS_QUEUE" >/dev/null 2>&1; then
    az servicebus queue create \
      --resource-group "$RESOURCE_GROUP" \
      --namespace-name "$SERVICE_BUS_NAMESPACE" \
      --name "$SERVICE_BUS_QUEUE" \
      --max-size 1024 \
      --default-message-time-to-live "P7D" \
      --max-delivery-count 6 \
      --output none
  fi

  for queue in "$SERVICE_BUS_QUEUE_EXTRACTING" "$SERVICE_BUS_QUEUE_PROCESSING" "$SERVICE_BUS_QUEUE_REVIEWING"; do
    if ! az servicebus queue show --resource-group "$RESOURCE_GROUP" --namespace-name "$SERVICE_BUS_NAMESPACE" --name "$queue" >/dev/null 2>&1; then
      az servicebus queue create \
        --resource-group "$RESOURCE_GROUP" \
        --namespace-name "$SERVICE_BUS_NAMESPACE" \
        --name "$queue" \
        --max-size 1024 \
        --default-message-time-to-live "P7D" \
        --max-delivery-count 6 \
        --output none
    fi
  done
}

ensure_key_vault() {
  if ! az keyvault show --name "$KEY_VAULT_NAME" >/dev/null 2>&1; then
    az keyvault create \
      --name "$KEY_VAULT_NAME" \
      --resource-group "$RESOURCE_GROUP" \
      --location "$LOCATION" \
      --sku standard \
      --enable-rbac-authorization true \
      --tags $COMMON_TAGS \
      --output none
  fi

  local user_object_id
  user_object_id="$(az ad signed-in-user show --query id -o tsv)"
  az role assignment create \
    --assignee-object-id "$user_object_id" \
    --assignee-principal-type User \
    --role "Key Vault Secrets Officer" \
    --scope "/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RESOURCE_GROUP/providers/Microsoft.KeyVault/vaults/$KEY_VAULT_NAME" \
    --output none \
    || true

  az keyvault secret set --vault-name "$KEY_VAULT_NAME" --name "storage-account-name" --value "$STORAGE_ACCOUNT" --output none
  az keyvault secret set --vault-name "$KEY_VAULT_NAME" --name "service-bus-namespace" --value "$SERVICE_BUS_NAMESPACE" --output none
  az keyvault secret set --vault-name "$KEY_VAULT_NAME" --name "service-bus-queue" --value "$SERVICE_BUS_QUEUE" --output none
  az keyvault secret set --vault-name "$KEY_VAULT_NAME" --name "service-bus-queue-extracting" --value "$SERVICE_BUS_QUEUE_EXTRACTING" --output none
  az keyvault secret set --vault-name "$KEY_VAULT_NAME" --name "service-bus-queue-processing" --value "$SERVICE_BUS_QUEUE_PROCESSING" --output none
  az keyvault secret set --vault-name "$KEY_VAULT_NAME" --name "service-bus-queue-reviewing" --value "$SERVICE_BUS_QUEUE_REVIEWING" --output none
  az keyvault secret set --vault-name "$KEY_VAULT_NAME" --name "sql-server-name" --value "$SQL_SERVER_NAME" --output none
  az keyvault secret set --vault-name "$KEY_VAULT_NAME" --name "sql-db-name" --value "$SQL_DATABASE_NAME" --output none

  local storage_conn
  storage_conn="$(az storage account show-connection-string --resource-group "$RESOURCE_GROUP" --name "$STORAGE_ACCOUNT" --query connectionString -o tsv)"
  if [[ -n "$storage_conn" ]]; then
    az keyvault secret set --vault-name "$KEY_VAULT_NAME" --name "storage-connection-string" --value "$storage_conn" --output none
  fi

  local service_bus_conn
  service_bus_conn="$(az servicebus namespace authorization-rule keys list \
    --resource-group "$RESOURCE_GROUP" \
    --namespace-name "$SERVICE_BUS_NAMESPACE" \
    --name RootManageSharedAccessKey \
    --query primaryConnectionString -o tsv)"
  if [[ -n "$service_bus_conn" ]]; then
    az keyvault secret set --vault-name "$KEY_VAULT_NAME" --name "service-bus-connection-string" --value "$service_bus_conn" --output none
  fi
}

ensure_postgres() {
  if ! az postgres flexible-server show --name "$POSTGRES_SERVER_NAME" --resource-group "$RESOURCE_GROUP" >/dev/null 2>&1; then
    az postgres flexible-server create \
      --name "$POSTGRES_SERVER_NAME" \
      --resource-group "$RESOURCE_GROUP" \
      --location "$LOCATION" \
      --admin-user "$POSTGRES_ADMIN_USER" \
      --admin-password "$POSTGRES_ADMIN_PASSWORD" \
      --sku-name "$POSTGRES_SKU_NAME" \
      --tier "$POSTGRES_TIER" \
      --storage-size "$POSTGRES_STORAGE_SIZE" \
      --version "$POSTGRES_VERSION" \
      --public-access 0.0.0.0 \
      --database-name "$POSTGRES_DATABASE_NAME" \
      --output none
  fi

  az postgres flexible-server update \
    --name "$POSTGRES_SERVER_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --admin-password "$POSTGRES_ADMIN_PASSWORD" \
    --output none \
    || true

  if ! az postgres flexible-server db show \
      --resource-group "$RESOURCE_GROUP" \
      --server-name "$POSTGRES_SERVER_NAME" \
      --database-name "$POSTGRES_DATABASE_NAME" >/dev/null 2>&1; then
    az postgres flexible-server db create \
      --resource-group "$RESOURCE_GROUP" \
      --server-name "$POSTGRES_SERVER_NAME" \
      --database-name "$POSTGRES_DATABASE_NAME" \
      --output none
  fi

  az keyvault secret set --vault-name "$KEY_VAULT_NAME" --name "postgres-admin-user" --value "$POSTGRES_ADMIN_USER" --output none
  az keyvault secret set --vault-name "$KEY_VAULT_NAME" --name "postgres-admin-password" --value "$POSTGRES_ADMIN_PASSWORD" --output none

  local postgres_conn
  postgres_conn="postgresql+psycopg://${POSTGRES_ADMIN_USER}:${POSTGRES_ADMIN_PASSWORD}@${POSTGRES_SERVER_NAME}.postgres.database.azure.com:5432/${POSTGRES_DATABASE_NAME}?sslmode=require"
  az keyvault secret set --vault-name "$KEY_VAULT_NAME" --name "postgres-connection-string" --value "$postgres_conn" --output none

  info "PostgreSQL admin password is stored in Key Vault as 'postgres-admin-password'"
}

ensure_container_registry() {
  local registry_scope
  registry_scope="/subscriptions/${SUBSCRIPTION_ID}/resourceGroups/${RESOURCE_GROUP}/providers/Microsoft.ContainerRegistry/registries/${CONTAINER_REGISTRY_NAME}"

  if ! az acr show --resource-group "$RESOURCE_GROUP" --name "$CONTAINER_REGISTRY_NAME" >/dev/null 2>&1; then
    az acr create \
      --name "$CONTAINER_REGISTRY_NAME" \
      --resource-group "$RESOURCE_GROUP" \
      --location "$LOCATION" \
      --sku "$CONTAINER_REGISTRY_SKU" \
      --admin-enabled false \
      --tags $COMMON_TAGS \
      --output none
  fi

  if [[ -n "${SP_CLIENT_ID:-}" ]]; then
    local sp_object_id
    sp_object_id="$(az ad sp show --id "$SP_CLIENT_ID" --query id -o tsv 2>/dev/null || true)"
    if [[ -n "$sp_object_id" ]]; then
      az role assignment create \
        --assignee-object-id "$sp_object_id" \
        --assignee-principal-type ServicePrincipal \
        --role "AcrPush" \
        --scope "$registry_scope" \
        --output none >/dev/null \
        || true
    fi
  fi
}

ensure_log_analytics_workspace() {
  if ! az monitor log-analytics workspace show \
    --resource-group "$RESOURCE_GROUP" \
    --workspace-name "$LOG_ANALYTICS_WORKSPACE_NAME" >/dev/null 2>&1; then
    az monitor log-analytics workspace create \
      --resource-group "$RESOURCE_GROUP" \
      --workspace-name "$LOG_ANALYTICS_WORKSPACE_NAME" \
      --location "$LOCATION" \
      --tags $COMMON_TAGS \
      --output none
  fi
}

ensure_app_insights() {
  local workspace_id
  workspace_id="$(az monitor log-analytics workspace show \
    --resource-group "$RESOURCE_GROUP" \
    --workspace-name "$LOG_ANALYTICS_WORKSPACE_NAME" \
    --query id -o tsv)"

  if ! az monitor app-insights component show \
      --app "$APP_INSIGHTS_NAME" \
      --resource-group "$RESOURCE_GROUP" >/dev/null 2>&1; then
    az monitor app-insights component create \
      --app "$APP_INSIGHTS_NAME" \
      --location "$LOCATION" \
      --resource-group "$RESOURCE_GROUP" \
      --workspace "$workspace_id" \
      --application-type web \
      --tags $COMMON_TAGS \
      --output none
  fi

  local appi_conn
  appi_conn="$(az monitor app-insights component show \
    --app "$APP_INSIGHTS_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --query connectionString -o tsv)"
  if [[ -n "$appi_conn" ]]; then
    az keyvault secret set \
      --vault-name "$KEY_VAULT_NAME" \
      --name "application-insights-connection-string" \
      --value "$appi_conn" \
      --output none
  fi
}

ensure_container_apps_environment() {
  local workspace_customer_id workspace_shared_key
  workspace_customer_id="$(az monitor log-analytics workspace show \
    --resource-group "$RESOURCE_GROUP" \
    --workspace-name "$LOG_ANALYTICS_WORKSPACE_NAME" \
    --query customerId -o tsv)"
  workspace_shared_key="$(az monitor log-analytics workspace get-shared-keys \
    --resource-group "$RESOURCE_GROUP" \
    --workspace-name "$LOG_ANALYTICS_WORKSPACE_NAME" \
    --query primarySharedKey -o tsv)"

  if ! az containerapp env show \
    --resource-group "$RESOURCE_GROUP" \
    --name "$CONTAINER_APPS_ENVIRONMENT_NAME" >/dev/null 2>&1; then
    az containerapp env create \
      --name "$CONTAINER_APPS_ENVIRONMENT_NAME" \
      --resource-group "$RESOURCE_GROUP" \
      --location "$LOCATION" \
      --logs-destination log-analytics \
      --logs-workspace-id "$workspace_customer_id" \
      --logs-workspace-key "$workspace_shared_key" \
      --tags $COMMON_TAGS \
      --output none
  fi
}

assign_container_app_runtime_roles() {
  local storage_scope service_bus_scope key_vault_scope container_app_name container_app_principal_id
  storage_scope="/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RESOURCE_GROUP/providers/Microsoft.Storage/storageAccounts/$STORAGE_ACCOUNT"
  service_bus_scope="/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RESOURCE_GROUP/providers/Microsoft.ServiceBus/namespaces/$SERVICE_BUS_NAMESPACE"
  key_vault_scope="/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RESOURCE_GROUP/providers/Microsoft.KeyVault/vaults/$KEY_VAULT_NAME"

  for container_app_name in \
    "$WEBAPP_NAME" \
    "$WORKER_EXTRACTING_NAME" \
    "$WORKER_PROCESSING_NAME" \
    "$WORKER_REVIEWING_NAME"; do
    container_app_principal_id="$(az containerapp show \
      --name "$container_app_name" \
      --resource-group "$RESOURCE_GROUP" \
      --query identity.principalId -o tsv 2>/dev/null || true)"

    if [[ -z "$container_app_principal_id" || "$container_app_principal_id" == "null" ]]; then
      info "container app identity not available yet for: $container_app_name (RBAC deferred until app exists)"
      continue
    fi

    az role assignment create \
      --assignee-object-id "$container_app_principal_id" \
      --assignee-principal-type ServicePrincipal \
      --role "Storage Blob Data Contributor" \
      --scope "$storage_scope" \
      --output none \
      || true
    az role assignment create \
      --assignee-object-id "$container_app_principal_id" \
      --assignee-principal-type ServicePrincipal \
      --role "Azure Service Bus Data Owner" \
      --scope "$service_bus_scope" \
      --output none \
      || true
    az role assignment create \
      --assignee-object-id "$container_app_principal_id" \
      --assignee-principal-type ServicePrincipal \
      --role "Key Vault Secrets User" \
      --scope "$key_vault_scope" \
      --output none \
      || true
  done
}

ensure_app_service() {
  local storage_scope
  storage_scope="/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RESOURCE_GROUP/providers/Microsoft.Storage/storageAccounts/$STORAGE_ACCOUNT"

  if ! az appservice plan show --name "$APP_SERVICE_PLAN" --resource-group "$RESOURCE_GROUP" >/dev/null 2>&1; then
    az appservice plan create \
      --name "$APP_SERVICE_PLAN" \
      --resource-group "$RESOURCE_GROUP" \
      --location "$LOCATION" \
      --sku B1 \
      --is-linux \
      --number-of-workers 1 \
      --tags $COMMON_TAGS \
      --output none
  fi

  if ! az webapp show --name "$WEBAPP_NAME" --resource-group "$RESOURCE_GROUP" >/dev/null 2>&1; then
    az webapp create \
      --resource-group "$RESOURCE_GROUP" \
      --plan "$APP_SERVICE_PLAN" \
      --name "$WEBAPP_NAME" \
      --runtime "PYTHON:3.11" \
      --assign-identity \
      --output none
  fi

  az webapp config set \
    --name "$WEBAPP_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --startup-file "uvicorn app.main:app --host 0.0.0.0 --port \${PORT:-8000}" \
    --output none

  az webapp config appsettings set \
    --name "$WEBAPP_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --settings \
      SCM_DO_BUILD_DURING_DEPLOYMENT=true \
      ENVIRONMENT_NAME="$ENVIRONMENT" \
      AZURE_STORAGE_ACCOUNT_NAME="$STORAGE_ACCOUNT" \
      AZURE_SERVICE_BUS_NAMESPACE="$SERVICE_BUS_NAMESPACE" \
      AZURE_SERVICE_BUS_QUEUE="$SERVICE_BUS_QUEUE" \
      AZURE_SERVICE_BUS_QUEUE_EXTRACTING="$SERVICE_BUS_QUEUE_EXTRACTING" \
      AZURE_SERVICE_BUS_QUEUE_PROCESSING="$SERVICE_BUS_QUEUE_PROCESSING" \
      AZURE_SERVICE_BUS_QUEUE_REVIEWING="$SERVICE_BUS_QUEUE_REVIEWING" \
      KEYVAULT_NAME="$KEY_VAULT_NAME" \
      AZURE_POSTGRES_SERVER_NAME="$POSTGRES_SERVER_NAME" \
      AZURE_POSTGRES_DATABASE_NAME="$POSTGRES_DATABASE_NAME" \
      AZURE_OPENAI_ACCOUNT_NAME="$OPENAI_ACCOUNT_NAME" \
      AZURE_SPEECH_ACCOUNT_NAME="$SPEECH_ACCOUNT_NAME" \
      AZURE_OPENAI_CHAT_DEPLOYMENT_NAME="$OPENAI_DEPLOYMENT_NAME" \
      AZURE_OPENAI_DEPLOYMENT_NAME="$OPENAI_DEPLOYMENT_NAME" \
      AZURE_OPENAI_API_VERSION="2024-10-21" \
      AZURE_OPENAI_MODEL_NAME="$OPENAI_MODEL_NAME" \
      AZURE_OPENAI_MODEL_VERSION="$OPENAI_MODEL_VERSION" \
      AZURE_OPENAI_SKU_NAME="$OPENAI_SKU_NAME" \
      APP_COST_PROFILE=development \
      DATABASE_URL="@Microsoft.KeyVault(SecretUri=https://${KEY_VAULT_NAME}.vault.azure.net/secrets/postgres-connection-string)" \
      AZURE_STORAGE_CONNECTION_STRING="@Microsoft.KeyVault(SecretUri=https://${KEY_VAULT_NAME}.vault.azure.net/secrets/storage-connection-string)" \
      AZURE_SERVICE_BUS_CONNECTION_STRING="@Microsoft.KeyVault(SecretUri=https://${KEY_VAULT_NAME}.vault.azure.net/secrets/service-bus-connection-string)" \
      AZURE_STORAGE_CONTAINER_EXPORTS="exports" \
    --output none

  local webapp_principal_id
  webapp_principal_id="$(az webapp identity show --name "$WEBAPP_NAME" --resource-group "$RESOURCE_GROUP" --query principalId -o tsv 2>/dev/null || true)"
  if [[ -n "$webapp_principal_id" ]]; then
    az role assignment create \
      --assignee-object-id "$webapp_principal_id" \
      --role "Key Vault Secrets User" \
      --scope "/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RESOURCE_GROUP/providers/Microsoft.KeyVault/vaults/$KEY_VAULT_NAME" \
      --output none \
      || true
  fi

  local worker_name worker_role worker_principal_id
  for worker_role in extracting processing reviewing; do
    case "$worker_role" in
      extracting)
        worker_name="$WORKER_EXTRACTING_NAME"
        ;;
      processing)
        worker_name="$WORKER_PROCESSING_NAME"
        ;;
      reviewing)
        worker_name="$WORKER_REVIEWING_NAME"
        ;;
    esac

    if ! az webapp show --name "$worker_name" --resource-group "$RESOURCE_GROUP" >/dev/null 2>&1; then
      az webapp create \
        --resource-group "$RESOURCE_GROUP" \
        --plan "$APP_SERVICE_PLAN" \
        --name "$worker_name" \
        --runtime "PYTHON:3.11" \
        --assign-identity \
        --output none
    fi

    az webapp config set \
      --name "$worker_name" \
      --resource-group "$RESOURCE_GROUP" \
      --startup-file "python -m app.workers.runner" \
      --output none

    az webapp config appsettings set \
      --name "$worker_name" \
      --resource-group "$RESOURCE_GROUP" \
      --settings \
        SCM_DO_BUILD_DURING_DEPLOYMENT=true \
        ENVIRONMENT_NAME="$ENVIRONMENT" \
        PFCD_WORKER_ROLE="$worker_role" \
        AZURE_STORAGE_ACCOUNT_NAME="$STORAGE_ACCOUNT" \
        AZURE_SERVICE_BUS_NAMESPACE="$SERVICE_BUS_NAMESPACE" \
        AZURE_SERVICE_BUS_QUEUE="$SERVICE_BUS_QUEUE" \
        AZURE_SERVICE_BUS_QUEUE_EXTRACTING="$SERVICE_BUS_QUEUE_EXTRACTING" \
        AZURE_SERVICE_BUS_QUEUE_PROCESSING="$SERVICE_BUS_QUEUE_PROCESSING" \
        AZURE_SERVICE_BUS_QUEUE_REVIEWING="$SERVICE_BUS_QUEUE_REVIEWING" \
        KEYVAULT_NAME="$KEY_VAULT_NAME" \
        AZURE_POSTGRES_SERVER_NAME="$POSTGRES_SERVER_NAME" \
        AZURE_POSTGRES_DATABASE_NAME="$POSTGRES_DATABASE_NAME" \
        AZURE_OPENAI_ACCOUNT_NAME="$OPENAI_ACCOUNT_NAME" \
        AZURE_SPEECH_ACCOUNT_NAME="$SPEECH_ACCOUNT_NAME" \
        AZURE_OPENAI_ENDPOINT="https://${OPENAI_ACCOUNT_NAME}.openai.azure.com/" \
        AZURE_OPENAI_CHAT_DEPLOYMENT_NAME="$OPENAI_DEPLOYMENT_NAME" \
        AZURE_OPENAI_DEPLOYMENT_NAME="$OPENAI_DEPLOYMENT_NAME" \
        AZURE_OPENAI_API_VERSION="2024-10-21" \
        AZURE_OPENAI_MODEL_NAME="$OPENAI_MODEL_NAME" \
        AZURE_OPENAI_MODEL_VERSION="$OPENAI_MODEL_VERSION" \
        AZURE_OPENAI_SKU_NAME="$OPENAI_SKU_NAME" \
        APP_COST_PROFILE=development \
        WEBSITES_CONTAINER_START_TIME_LIMIT=600 \
        WEBSITES_PORT=8000 \
        DATABASE_URL="@Microsoft.KeyVault(SecretUri=https://${KEY_VAULT_NAME}.vault.azure.net/secrets/postgres-connection-string)" \
        AZURE_STORAGE_CONNECTION_STRING="@Microsoft.KeyVault(SecretUri=https://${KEY_VAULT_NAME}.vault.azure.net/secrets/storage-connection-string)" \
        AZURE_SERVICE_BUS_CONNECTION_STRING="@Microsoft.KeyVault(SecretUri=https://${KEY_VAULT_NAME}.vault.azure.net/secrets/service-bus-connection-string)" \
        AZURE_STORAGE_CONTAINER_EXPORTS="exports" \
      --output none

    worker_principal_id="$(az webapp identity show --name "$worker_name" --resource-group "$RESOURCE_GROUP" --query principalId -o tsv 2>/dev/null || true)"
    if [[ -n "$worker_principal_id" ]]; then
      az role assignment create \
        --assignee-object-id "$worker_principal_id" \
        --role "Key Vault Secrets User" \
        --scope "/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RESOURCE_GROUP/providers/Microsoft.KeyVault/vaults/$KEY_VAULT_NAME" \
        --output none \
        || true
      az role assignment create \
        --assignee-object-id "$worker_principal_id" \
        --role "Storage Blob Data Reader" \
        --scope "$storage_scope" \
        --output none \
        || true
    fi
  done
}

ensure_cognitive_services() {
  if ! az cognitiveservices account show --name "$OPENAI_ACCOUNT_NAME" --resource-group "$RESOURCE_GROUP" >/dev/null 2>&1; then
    az cognitiveservices account create \
      --name "$OPENAI_ACCOUNT_NAME" \
      --resource-group "$RESOURCE_GROUP" \
      --location "$LOCATION" \
      --kind OpenAI \
      --sku S0 \
      --tags $COMMON_TAGS \
      --yes \
      --output none
  fi

  if ! az cognitiveservices account deployment show \
    --resource-group "$RESOURCE_GROUP" \
    --name "$OPENAI_ACCOUNT_NAME" \
    --deployment-name "$OPENAI_DEPLOYMENT_NAME" >/dev/null 2>&1; then
  if ! az cognitiveservices account deployment create \
      --resource-group "$RESOURCE_GROUP" \
      --name "$OPENAI_ACCOUNT_NAME" \
      --deployment-name "$OPENAI_DEPLOYMENT_NAME" \
      --model-format OpenAI \
      --model-name "$OPENAI_MODEL_NAME" \
      --model-version "$OPENAI_MODEL_VERSION" \
      --sku-capacity "$OPENAI_SKU_CAPACITY" \
      --sku-name "$OPENAI_SKU_NAME" \
      --output none; then
      info "OpenAI deployment may need a model/version update for this region."
      info "Use Azure portal or run a manual command with a supported deployment name/model/version for $OPENAI_ACCOUNT_NAME."
    fi
  fi

  if ! az cognitiveservices account show --name "$SPEECH_ACCOUNT_NAME" --resource-group "$RESOURCE_GROUP" >/dev/null 2>&1; then
    az cognitiveservices account create \
      --name "$SPEECH_ACCOUNT_NAME" \
      --resource-group "$RESOURCE_GROUP" \
      --location "$SPEECH_ACCOUNT_LOCATION" \
      --kind SpeechServices \
      --sku S0 \
      --tags $COMMON_TAGS \
      --yes \
      --output none
  fi
}

ensure_monitor_alerting_baseline() {
  local action_group_id api_id extracting_queue_id processing_queue_id reviewing_queue_id appi_id

  if [[ -n "$ALERT_EMAIL" ]]; then
    if ! az monitor action-group show \
        --name "$ALERT_ACTION_GROUP_NAME" \
        --resource-group "$RESOURCE_GROUP" >/dev/null 2>&1; then
      az monitor action-group create \
        --name "$ALERT_ACTION_GROUP_NAME" \
        --resource-group "$RESOURCE_GROUP" \
        --short-name "pfcdops" \
        --action email pfcdops "$ALERT_EMAIL" \
        --output none
    fi
  else
    info "ALERT_EMAIL not set; creating metric alerts without action-group notifications"
  fi

  action_group_id="$(az monitor action-group show \
    --name "$ALERT_ACTION_GROUP_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --query id -o tsv 2>/dev/null || true)"

  api_id="$(az webapp show --name "$WEBAPP_NAME" --resource-group "$RESOURCE_GROUP" --query id -o tsv)"
  extracting_queue_id="$(az servicebus queue show --resource-group "$RESOURCE_GROUP" --namespace-name "$SERVICE_BUS_NAMESPACE" --name "$SERVICE_BUS_QUEUE_EXTRACTING" --query id -o tsv)"
  processing_queue_id="$(az servicebus queue show --resource-group "$RESOURCE_GROUP" --namespace-name "$SERVICE_BUS_NAMESPACE" --name "$SERVICE_BUS_QUEUE_PROCESSING" --query id -o tsv)"
  reviewing_queue_id="$(az servicebus queue show --resource-group "$RESOURCE_GROUP" --namespace-name "$SERVICE_BUS_NAMESPACE" --name "$SERVICE_BUS_QUEUE_REVIEWING" --query id -o tsv)"
  appi_id="$(az monitor app-insights component show --app "$APP_INSIGHTS_NAME" --resource-group "$RESOURCE_GROUP" --query id -o tsv)"

  if ! az monitor metrics alert show --name "${PROJECT}-${ENVIRONMENT}-api-5xx" --resource-group "$RESOURCE_GROUP" >/dev/null 2>&1; then
    if [[ -n "$action_group_id" ]]; then
      az monitor metrics alert create \
        --name "${PROJECT}-${ENVIRONMENT}-api-5xx" \
        --resource-group "$RESOURCE_GROUP" \
        --scopes "$api_id" \
        --condition "total Http5xx > 5" \
        --window-size 5m \
        --evaluation-frequency 1m \
        --severity 2 \
        --description "PFCD API 5xx spike" \
        --action "$action_group_id" \
        --output none
    else
      az monitor metrics alert create \
        --name "${PROJECT}-${ENVIRONMENT}-api-5xx" \
        --resource-group "$RESOURCE_GROUP" \
        --scopes "$api_id" \
        --condition "total Http5xx > 5" \
        --window-size 5m \
        --evaluation-frequency 1m \
        --severity 2 \
        --description "PFCD API 5xx spike" \
        --output none
    fi
  fi

  if ! az monitor metrics alert show --name "${PROJECT}-${ENVIRONMENT}-dlq-extracting" --resource-group "$RESOURCE_GROUP" >/dev/null 2>&1; then
    if [[ -n "$action_group_id" ]]; then
      az monitor metrics alert create \
        --name "${PROJECT}-${ENVIRONMENT}-dlq-extracting" \
        --resource-group "$RESOURCE_GROUP" \
        --scopes "$extracting_queue_id" \
        --condition "total DeadletteredMessages > 0" \
        --window-size 5m \
        --evaluation-frequency 5m \
        --severity 2 \
        --description "PFCD extracting queue dead-lettered messages" \
        --action "$action_group_id" \
        --output none
    else
      az monitor metrics alert create \
        --name "${PROJECT}-${ENVIRONMENT}-dlq-extracting" \
        --resource-group "$RESOURCE_GROUP" \
        --scopes "$extracting_queue_id" \
        --condition "total DeadletteredMessages > 0" \
        --window-size 5m \
        --evaluation-frequency 5m \
        --severity 2 \
        --description "PFCD extracting queue dead-lettered messages" \
        --output none
    fi
  fi

  if ! az monitor metrics alert show --name "${PROJECT}-${ENVIRONMENT}-dlq-processing" --resource-group "$RESOURCE_GROUP" >/dev/null 2>&1; then
    if [[ -n "$action_group_id" ]]; then
      az monitor metrics alert create \
        --name "${PROJECT}-${ENVIRONMENT}-dlq-processing" \
        --resource-group "$RESOURCE_GROUP" \
        --scopes "$processing_queue_id" \
        --condition "total DeadletteredMessages > 0" \
        --window-size 5m \
        --evaluation-frequency 5m \
        --severity 2 \
        --description "PFCD processing queue dead-lettered messages" \
        --action "$action_group_id" \
        --output none
    else
      az monitor metrics alert create \
        --name "${PROJECT}-${ENVIRONMENT}-dlq-processing" \
        --resource-group "$RESOURCE_GROUP" \
        --scopes "$processing_queue_id" \
        --condition "total DeadletteredMessages > 0" \
        --window-size 5m \
        --evaluation-frequency 5m \
        --severity 2 \
        --description "PFCD processing queue dead-lettered messages" \
        --output none
    fi
  fi

  if ! az monitor metrics alert show --name "${PROJECT}-${ENVIRONMENT}-dlq-reviewing" --resource-group "$RESOURCE_GROUP" >/dev/null 2>&1; then
    if [[ -n "$action_group_id" ]]; then
      az monitor metrics alert create \
        --name "${PROJECT}-${ENVIRONMENT}-dlq-reviewing" \
        --resource-group "$RESOURCE_GROUP" \
        --scopes "$reviewing_queue_id" \
        --condition "total DeadletteredMessages > 0" \
        --window-size 5m \
        --evaluation-frequency 5m \
        --severity 2 \
        --description "PFCD reviewing queue dead-lettered messages" \
        --action "$action_group_id" \
        --output none
    else
      az monitor metrics alert create \
        --name "${PROJECT}-${ENVIRONMENT}-dlq-reviewing" \
        --resource-group "$RESOURCE_GROUP" \
        --scopes "$reviewing_queue_id" \
        --condition "total DeadletteredMessages > 0" \
        --window-size 5m \
        --evaluation-frequency 5m \
        --severity 2 \
        --description "PFCD reviewing queue dead-lettered messages" \
        --output none
    fi
  fi

  if ! az monitor scheduled-query show --name "${PROJECT}-${ENVIRONMENT}-readiness-failures" --resource-group "$RESOURCE_GROUP" >/dev/null 2>&1; then
    if [[ -n "$action_group_id" ]]; then
      az monitor scheduled-query create \
        --name "${PROJECT}-${ENVIRONMENT}-readiness-failures" \
        --resource-group "$RESOURCE_GROUP" \
        --scopes "$appi_id" \
        --condition "count 'requests | where name == \"GET /health/readiness\" and success == false' > 0" \
        --evaluation-frequency 5m \
        --window-size 5m \
        --severity 2 \
        --description "PFCD readiness endpoint failing" \
        --action "$action_group_id" \
        --output none \
        || info "Scheduled query alert creation requires updated monitor extension; create manually if needed."
    else
      az monitor scheduled-query create \
        --name "${PROJECT}-${ENVIRONMENT}-readiness-failures" \
        --resource-group "$RESOURCE_GROUP" \
        --scopes "$appi_id" \
        --condition "count 'requests | where name == \"GET /health/readiness\" and success == false' > 0" \
        --evaluation-frequency 5m \
        --window-size 5m \
        --severity 2 \
        --description "PFCD readiness endpoint failing" \
        --output none \
        || info "Scheduled query alert creation requires updated monitor extension; create manually if needed."
    fi
  fi
}

apply_app_insights_appsettings() {
  local app_name
  for app_name in "$WEBAPP_NAME" "$WORKER_EXTRACTING_NAME" "$WORKER_PROCESSING_NAME" "$WORKER_REVIEWING_NAME"; do
    az webapp config appsettings set \
      --name "$app_name" \
      --resource-group "$RESOURCE_GROUP" \
      --settings \
        APPLICATIONINSIGHTS_CONNECTION_STRING="@Microsoft.KeyVault(SecretUri=https://${KEY_VAULT_NAME}.vault.azure.net/secrets/application-insights-connection-string)" \
        APPINSIGHTS_PROFILERFEATURE_VERSION=disabled \
        APPINSIGHTS_SNAPSHOTFEATURE_VERSION=disabled \
      --output none
  done
}

ensure_budget() {
  local start_date end_date
  start_date="$(date -u +"%Y-%m-01")"
  end_date="$(date -u -v +1y +"%Y-12-31" 2>/dev/null || date -u -d "+12 months" +"%Y-12-31")"
  if ! az consumption budget show --budget-name "$BUDGET_NAME" >/dev/null 2>&1; then
    az consumption budget create \
      --budget-name "$BUDGET_NAME" \
      --category "cost" \
      --amount "$MONTHLY_BUDGET" \
      --time-grain "monthly" \
      --start-date "$start_date" \
      --end-date "$end_date" \
      --output none \
      || info "Budget creation requires CLI/API version adjustment for your environment. Create manually in portal."
  fi
}

az account set --subscription "$SUBSCRIPTION_ID" --only-show-errors >/dev/null

ensure_rg
ensure_storage_account
ensure_servicebus
ensure_key_vault
ensure_postgres
ensure_container_registry
ensure_log_analytics_workspace
ensure_app_insights
ensure_container_apps_environment
assign_container_app_runtime_roles
ensure_app_service
apply_app_insights_appsettings
ensure_cognitive_services
ensure_monitor_alerting_baseline
ensure_budget

info "Bootstrap complete for environment '$ENVIRONMENT' in $RESOURCE_GROUP"
echo "Container registry: ${CONTAINER_REGISTRY_NAME}.azurecr.io"
echo "Container Apps environment: ${CONTAINER_APPS_ENVIRONMENT_NAME}"
az resource show --ids "/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RESOURCE_GROUP/providers/Microsoft.Web/sites/$WEBAPP_NAME" --query "defaultHostName" -o tsv | sed 's|^|API host: https://|' | sed 's|$|/|' | tr -d '\n'
echo
