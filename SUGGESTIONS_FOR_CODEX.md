# Infrastructure Review & Remediation Plan (PFCD-V2)

## 1. Current Status Summary
The initial Azure bootstrap for the `app-pfcd-v2` environment in `southindia` is **75% complete**.
- **Success:** Resource Group, Storage (Containers), Service Bus (Queue), SQL (Server/DB), Key Vault, App Service Plan, and Cognitive Service Accounts (OpenAI/Speech) are provisioned.
- **Failures:** 
    - OpenAI `gpt-4o-mini` deployment failed due to an unsupported SKU (`Standard` is not available for this model/region; `GlobalStandard` is required).
    - Azure Budget creation is inconclusive due to CLI preview status.
- **Missing Logic:** The bootstrap script provisions a Managed Identity for the Web App but does not grant it RBAC access to the Key Vault.

## 2. Infrastructure Fixes (High Priority)

### A. OpenAI Deployment (Manual or Scripted)
The `gpt-4o-mini` model in `South India` requires the `GlobalStandard` SKU.
- **Action:** Update `infra/dev-bootstrap.sh` to use `GlobalStandard`.
- **Manual Fix (already tested):**
  ```bash
  az cognitiveservices account deployment create \
    --resource-group app-pfcd-v2 \
    --name pfcd-dev-oai \
    --deployment-name gpt-4o-mini \
    --model-format OpenAI \
    --model-name gpt-4o-mini \
    --model-version 2024-07-18 \
    --sku-capacity 1 \
    --sku-name GlobalStandard
  ```

### B. Managed Identity Role Assignment
The Web App identity needs `Key Vault Secrets User` permissions to retrieve SQL and Storage credentials at runtime.
- **Action:** Add the following logic to `infra/dev-bootstrap.sh` inside `ensure_app_service`:
  ```bash
  WEBAPP_PRINCIPAL_ID=$(az webapp identity show --name "$WEBAPP_NAME" --resource-group "$RESOURCE_GROUP" --query principalId -o tsv)
  az role assignment create \
    --assignee-object-id "$WEBAPP_PRINCIPAL_ID" \
    --role "Key Vault Secrets User" \
    --scope "/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RESOURCE_GROUP/providers/Microsoft.KeyVault/vaults/$KEY_VAULT_NAME"
  ```

## 3. Recommended Script Refinements
1.  **SKU Parameterization:** Introduce `OPENAI_SKU_NAME="${OPENAI_SKU_NAME:-GlobalStandard}"` at the top of the script.
2.  **Service Bus Tier:** Note that `Basic` SKU for Service Bus (currently in script) does not support Topics, only Queues. Since the PRD mentions "Queues/Topics", consider upgrading to `Standard` if fan-out is needed later.
3.  **Error Handling:** Add a check to verify if `az consumption budget` is available before execution to prevent noisy "Preview" warnings.

## 4. Next Steps: Skeleton Backend (Week 1)
Once the infrastructure is stable, the following "Skeleton" items are required:
1.  **Directory Structure:** Initialize `backend/`, `frontend/`, `infra/`, and `tests/`.
2.  **API Skeleton:** Fast API (Python 3.11) with the endpoints defined in PRD Section 9.
3.  **Identity Integration:** Implement `DefaultAzureCredential` for all service clients (Blob, Service Bus, SQL, Key Vault).
4.  **Health Check:** Create a `/health` endpoint that verifies connectivity to all provisioned Azure services.

## 5. Verification Commands for Codex
```bash
# Verify OpenAI Deployment
az cognitiveservices account deployment list --resource-group app-pfcd-v2 --name pfcd-dev-oai -o table

# Verify Web App Managed Identity
az webapp identity show --name pfcd-dev-api --resource-group app-pfcd-v2

# Verify Key Vault Secrets Access
az keyvault secret list --vault-name pfcd-dev-kv
```
