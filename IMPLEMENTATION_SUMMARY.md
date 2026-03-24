# Azure Dev Bootstrap Implementation Summary

## Scope
I implemented the Azure plan for this repository in `app-pfcd-v2` using the existing bootstrap flow.

## Completed items

- Updated `infra/dev-bootstrap.sh` to provision a full development footprint in an idempotent way.
  - Resource group reuse: `app-pfcd-v2`
  - Storage account with containers: `uploads`, `evidence`, `exports`, `scratch`
  - Service Bus namespace + `jobs` queue
  - Key Vault + required secrets
  - SQL Server + SQL Database
  - App Service Plan + Linux Web App (`PYTHON:3.11`)
  - Azure OpenAI account
  - Azure Speech account (with location override support)
- Added dev metadata and cost labeling:
  - `Environment=dev`
  - `Project=pfcd`
  - `CostProfile=development`
- Added app settings wiring for runtime dependencies:
  - storage, service bus, key vault, SQL, OpenAI, Speech
- Added Key Vault RBAC handling (`Key Vault Secrets Officer`) for modern auth mode compatibility.
- Implemented resilient error handling for known Azure CLI/API edge cases (non-blocking fallback where appropriate).
- Updated `infra/README.md` with:
  - correct repo path
  - `SPEECH_ACCOUNT_LOCATION=eastus` guidance
  - model/version override guidance for OpenAI retries
  - verification commands and caveats

## Fixes made during implementation

- Switched to AAD-auth container creation for storage to avoid shared-key/permission conflicts.
- Corrected Service Bus namespace naming pattern.
- Adjusted OpenAI deployment arguments to remove deprecated `scale-settings` parameter.
- Added explicit non-blocking guidance for budget creation due preview/API compatibility.

## Current state (post-run)

- Bootstrap script executes successfully through most resources.
- Resource group `app-pfcd-v2` is present in subscription `768495f7-c716-4839-9093-bd3b23b147ba`.
- Outstanding items remain:
  - OpenAI deployment is not yet active; requires a region-supported model/version in rerun.
  - Azure budget is not reliably creatable through current CLI preview command path and should be configured manually (portal/API alternative).

## Next actions for completion

1. Run bootstrap again with a supported OpenAI model/version pair.
2. Create and verify budget in Azure portal (or compatible API version) with dev labeling and spend alerts.

## Reviewer Summary (Short)

- **Status:** In progress (core provisioning complete, final validation pending)
- **What is done:** `infra/dev-bootstrap.sh` now creates all major dev resources, applies dev tags/cost profile, and wires webapp settings and Key Vault secrets.
- **What was fixed:** resource naming constraints, Azure RBAC compatibility, storage permissions model, deprecated OpenAI deployment flag.
- **Current gaps:** OpenAI deployment requires a supported model/version for the region; budget creation is blocked by CLI/API preview mismatch and must be done manually.
- **Suggested approval checklist:**
  - [x] Idempotent bootstrap script
  - [x] Documentation updated
  - [ ] OpenAI deployment exists in region
  - [ ] Cost budget created and alert rule verified
