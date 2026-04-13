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
STORAGE_ACCOUNT="${STORAGE_ACCOUNT:-${PROJECT}${ENVIRONMENT}storage}"
SERVICE_BUS_NAMESPACE="${SERVICE_BUS_NAMESPACE:-${PROJECT}-${ENVIRONMENT}-bus}"
SERVICE_BUS_QUEUE="${SERVICE_BUS_QUEUE:-jobs}"
SERVICE_BUS_QUEUE_EXTRACTING="${SERVICE_BUS_QUEUE_EXTRACTING:-extracting}"
SERVICE_BUS_QUEUE_PROCESSING="${SERVICE_BUS_QUEUE_PROCESSING:-processing}"
SERVICE_BUS_QUEUE_REVIEWING="${SERVICE_BUS_QUEUE_REVIEWING:-reviewing}"
SERVICE_BUS_SKU="${SERVICE_BUS_SKU:-Standard}"
SQL_SERVER_NAME="${SQL_SERVER_NAME:-${PROJECT}-${ENVIRONMENT}-sql}"
SQL_DATABASE_NAME="${SQL_DATABASE_NAME:-${PROJECT}-${ENVIRONMENT}-jobs}"
KEY_VAULT_NAME="${KEY_VAULT_NAME:-${PROJECT}-${ENVIRONMENT}-kv}"
OPENAI_ACCOUNT_NAME="${OPENAI_ACCOUNT_NAME:-${PROJECT}-${ENVIRONMENT}-oai}"
SPEECH_ACCOUNT_NAME="${SPEECH_ACCOUNT_NAME:-${PROJECT}-${ENVIRONMENT}-speech}"
SPEECH_ACCOUNT_LOCATION="${SPEECH_ACCOUNT_LOCATION:-eastus}"

OPENAI_DEPLOYMENT_NAME="${OPENAI_DEPLOYMENT_NAME:-gpt-4o-mini}"
OPENAI_MODEL_NAME="${OPENAI_MODEL_NAME:-gpt-4o-mini}"
OPENAI_MODEL_VERSION="${OPENAI_MODEL_VERSION:-2024-07-18}"
OPENAI_SKU_CAPACITY="${OPENAI_SKU_CAPACITY:-1}"
OPENAI_SKU_NAME="${OPENAI_SKU_NAME:-GlobalStandard}"

SQL_ADMIN_USER="${SQL_ADMIN_USER:-pfcd_admin}"
SQL_ADMIN_PASSWORD="${SQL_ADMIN_PASSWORD:-$(openssl rand -base64 24 | tr -dc 'A-Za-z0-9' | head -c 24)}"

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

ensure_sql() {
  if ! az sql server show --name "$SQL_SERVER_NAME" --resource-group "$RESOURCE_GROUP" >/dev/null 2>&1; then
    az sql server create \
      --name "$SQL_SERVER_NAME" \
      --resource-group "$RESOURCE_GROUP" \
      --location "$LOCATION" \
      --admin-user "$SQL_ADMIN_USER" \
      --admin-password "$SQL_ADMIN_PASSWORD" \
      --enable-public-network true \
      --minimal-tls-version "1.2" \
      --output none
  fi

  az sql server update \
    --name "$SQL_SERVER_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --admin-password "$SQL_ADMIN_PASSWORD" \
    --output none \
    || true

  if ! az sql db show --name "$SQL_DATABASE_NAME" --server "$SQL_SERVER_NAME" --resource-group "$RESOURCE_GROUP" >/dev/null 2>&1; then
    az sql db create \
      --name "$SQL_DATABASE_NAME" \
      --resource-group "$RESOURCE_GROUP" \
      --server "$SQL_SERVER_NAME" \
      --edition Basic \
      --output none
  fi

  az keyvault secret set --vault-name "$KEY_VAULT_NAME" --name "sql-admin-user" --value "$SQL_ADMIN_USER" --output none
  az keyvault secret set --vault-name "$KEY_VAULT_NAME" --name "sql-admin-password" --value "$SQL_ADMIN_PASSWORD" --output none

  local sql_conn
  sql_conn="mssql+pyodbc://${SQL_ADMIN_USER}:${SQL_ADMIN_PASSWORD}@${SQL_SERVER_NAME}.database.windows.net:1433/${SQL_DATABASE_NAME}?driver=ODBC+Driver+18+for+SQL+Server&Encrypt=yes&TrustServerCertificate=yes"
  az keyvault secret set --vault-name "$KEY_VAULT_NAME" --name "sql-connection-string" --value "$sql_conn" --output none

  info "SQL admin password is stored in Key Vault as 'sql-admin-password'"
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
      AZURE_SQL_SERVER_NAME="$SQL_SERVER_NAME" \
      AZURE_SQL_DATABASE_NAME="$SQL_DATABASE_NAME" \
      AZURE_OPENAI_ACCOUNT_NAME="$OPENAI_ACCOUNT_NAME" \
      AZURE_SPEECH_ACCOUNT_NAME="$SPEECH_ACCOUNT_NAME" \
      AZURE_OPENAI_CHAT_DEPLOYMENT_NAME="$OPENAI_DEPLOYMENT_NAME" \
      AZURE_OPENAI_DEPLOYMENT_NAME="$OPENAI_DEPLOYMENT_NAME" \
      AZURE_OPENAI_API_VERSION="2024-10-21" \
      AZURE_OPENAI_MODEL_NAME="$OPENAI_MODEL_NAME" \
      AZURE_OPENAI_MODEL_VERSION="$OPENAI_MODEL_VERSION" \
      AZURE_OPENAI_SKU_NAME="$OPENAI_SKU_NAME" \
      APP_COST_PROFILE=development \
      DATABASE_URL="@Microsoft.KeyVault(SecretUri=https://${KEY_VAULT_NAME}.vault.azure.net/secrets/sql-connection-string)" \
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
        AZURE_SQL_SERVER_NAME="$SQL_SERVER_NAME" \
        AZURE_SQL_DATABASE_NAME="$SQL_DATABASE_NAME" \
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
        DATABASE_URL="@Microsoft.KeyVault(SecretUri=https://${KEY_VAULT_NAME}.vault.azure.net/secrets/sql-connection-string)" \
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
ensure_sql
ensure_app_service
ensure_cognitive_services
ensure_budget

info "Bootstrap complete for environment '$ENVIRONMENT' in $RESOURCE_GROUP"
az resource show --ids "/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RESOURCE_GROUP/providers/Microsoft.Web/sites/$WEBAPP_NAME" --query "defaultHostName" -o tsv | sed 's|^|API host: https://|' | sed 's|$|/|' | tr -d '\n'
echo
  if ! az sql server firewall-rule show --resource-group "$RESOURCE_GROUP" --server "$SQL_SERVER_NAME" --name "AllowAzureServices" >/dev/null 2>&1; then
    az sql server firewall-rule create \
      --resource-group "$RESOURCE_GROUP" \
      --server "$SQL_SERVER_NAME" \
      --name "AllowAzureServices" \
      --start-ip-address "0.0.0.0" \
      --end-ip-address "0.0.0.0" \
      --output none
  fi
