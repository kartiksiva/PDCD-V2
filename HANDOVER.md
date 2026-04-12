# HANDOVER.md

Shared coordination board. Read and updated by both Claude and Codex at session start.

- **Claude** adds items to "Assigned to Codex" when assigning work; closes items after review.
- **Codex** moves items to "In Progress" when starting, then "Ready for Claude Review" when done.

---

## Assigned to Codex (not started)

| ID | Task | Notes |
|----|------|-------|
| DEPLOY-FIX2 (Part 2) | Switch workers to WEBSITE_RUN_FROM_PACKAGE | Details below; Part 1 approved |

### DEPLOY-FIX2 — Fix worker SCM restart race (two-part)

**Root cause confirmed (Claude review 2026-04-12):**
Each deploy job fires two Azure control-plane mutations:
1. `az webapp config appsettings set` → triggers Kudu/SCM restart #1
2. `az webapp config set --startup-file` → triggers restart #2 before #1 finishes

`az webapp show --query state` returns `Running` from the app container, not the Kudu/SCM container. So the deploy fires into a still-restarting Kudu and gets the `SCM container restart` error even after the settle guard passes.

---

**Part 1 — Quickwin (unblocks CI immediately):**

The startup-file value (`python -m app.workers.runner`) is static — it never changes between deploys. Remove all three `az webapp config set --startup-file` calls from `deploy-workers.yml`. Set the startup command once at provisioning time in `infra/dev-bootstrap.sh` instead (where `az webapp create` / `az webapp config set` already runs). This eliminates restart #2.

Then increase the post-`Running` sleep from 30 s to 60 s to give Kudu time to recover from the single remaining restart:

```yaml
- name: Wait for extracting worker config restart to settle
  run: |
    sleep 15
    for i in $(seq 1 30); do
      state=$(az webapp show \
        --resource-group ${{ secrets.AZURE_RESOURCE_GROUP }} \
        --name ${{ secrets.AZURE_WORKER_EXTRACTING_NAME }} \
        --query "state" -o tsv)
      echo "extracting config settle $i/30: $state"
      if [ "$state" = "Running" ]; then
        sleep 60
        exit 0
      fi
      sleep 10
    done
    echo "ERROR: extracting worker did not return to Running after config changes"
    exit 1
```

Apply identically to processing and reviewing settle steps.

Also verify `infra/dev-bootstrap.sh` includes `az webapp config set --startup-file "python -m app.workers.runner"` for all three worker apps (or equivalent `COMMAND` appsetting). If it doesn't, add it there.

---

**Part 2 — Proper fix (WEBSITE_RUN_FROM_PACKAGE):**

Restructure so there is no `azure/webapps-deploy@v3` step at all. The zip is mounted from blob storage; Kudu OneDeploy is never called.

**In the `build` job:**
```yaml
- name: Upload worker zip to scratch blob
  run: |
    az storage blob upload \
      --account-name ${{ secrets.AZURE_STORAGE_ACCOUNT }} \
      --container-name scratch \
      --name worker-${{ github.sha }}.zip \
      --file worker.zip \
      --auth-mode login
    expiry=$(date -u -d "+4 hours" +%Y-%m-%dT%H:%MZ 2>/dev/null || date -u -v+4H +%Y-%m-%dT%H:%MZ)
    sas=$(az storage blob generate-sas \
      --account-name ${{ secrets.AZURE_STORAGE_ACCOUNT }} \
      --container-name scratch \
      --name worker-${{ github.sha }}.zip \
      --permissions r \
      --expiry "$expiry" \
      --auth-mode login \
      --as-user \
      -o tsv)
    account=${{ secrets.AZURE_STORAGE_ACCOUNT }}
    echo "PACKAGE_URL=https://${account}.blob.core.windows.net/scratch/worker-${{ github.sha }}.zip?${sas}" >> $GITHUB_ENV
- uses: actions/upload-artifact@v4
  with:
    name: package-url
    path: /dev/null  # URL is passed via env; artifact is the zip already uploaded
```

Or simpler: write the URL to a file and upload that as an artifact, then download it in each deploy job.

**In each deploy job** — replace the `Deploy extracting worker` step with:
```yaml
- name: Deploy extracting worker (WEBSITE_RUN_FROM_PACKAGE)
  run: |
    az webapp config appsettings set \
      --resource-group ${{ secrets.AZURE_RESOURCE_GROUP }} \
      --name ${{ secrets.AZURE_WORKER_EXTRACTING_NAME }} \
      --settings PFCD_WORKER_ROLE=extracting \
        AZURE_OPENAI_ENDPOINT="${{ secrets.AZURE_OPENAI_ENDPOINT }}" \
        AZURE_OPENAI_CHAT_DEPLOYMENT_NAME="${AZURE_OPENAI_CHAT_DEPLOYMENT_NAME_RESOLVED}" \
        WEBSITES_CONTAINER_START_TIME_LIMIT=600 \
        WEBSITES_PORT=8000 \
        WEBSITE_RUN_FROM_PACKAGE="<package-url>"
    az webapp restart \
      --resource-group ${{ secrets.AZURE_RESOURCE_GROUP }} \
      --name ${{ secrets.AZURE_WORKER_EXTRACTING_NAME }}
```

Remove `azure/webapps-deploy@v3` entirely from all three deploy jobs. Remove `az webapp config set --startup-file` (already removed in Part 1). The `appsettings set` now consolidates config + package reference into a single control-plane operation.

**Pre-requisite:** the three worker App Services' system-assigned managed identities must have `Storage Blob Data Reader` on the scratch container (or on the storage account). Verify this in `infra/dev-bootstrap.sh` or add the role assignment there.

**Constraints:**
- Do not hardcode storage account names — use `${{ secrets.AZURE_STORAGE_ACCOUNT }}`
- SAS token expiry must be long enough to cover deploy + verify steps (4 hours is safe)
- Add `AZURE_STORAGE_ACCOUNT` to the secrets table in `REFERENCE.md` if not already present
- Do not change `deploy-backend.yml` — this task is workers only

Commit as: `fix: switch workers to WEBSITE_RUN_FROM_PACKAGE, remove startup-file mutation`

---

## In Progress (Codex working)

| ID | Task | Started |
|----|------|---------|
| — | | |

---

## Ready for Claude Review (Codex complete)

| ID | Task | PR / Commit |
|----|------|-------------|
| — | | |

---

## Recently Closed

| ID | Task | Closed | Outcome |
|----|----- |--------|---------|
| DEPLOY-FIX2 (Part 1) | Remove startup-file mutation from deploy workflow; widen settle sleep to 60 s; set startup in bootstrap | 2026-04-12 | Approved — `az webapp config set --startup-file` removed from all 3 deploy jobs; `sleep 60` in all settle steps; bootstrap sets startup at provision time |
| WORKER-DEPLOY-FAIL-20260412 | Review latest worker deployment failure and decide next remediation path | 2026-04-12 | Reviewed — root cause: two-restart race (appsettings set + startup-file set); remedy: DEPLOY-FIX2 assigned |
| REPO-CLEANUP | Delete artefacts, fix .gitignore, archive historical docs | 2026-04-12 | Approved — `dfb88ff`; clean working tree; 8 root docs; 5 archived to `docs/archive/` |
| S20-FIX | Config-settle `sleep 15` in all three worker settle steps | 2026-04-12 | Approved — present in all three workers; race addressed |
| DEPLOY-OPT3 + REVERT | Switch both workflows to `azure/webapps-deploy@v3`, no publish-profile | 2026-04-12 | Approved — bearer token auth via `azure/login`; no `az webapp deploy` remains; worker name validation added |
| S17-COMMIT | Commit and push all Section 17 M/L changes | 2026-04-12 | Approved — `5c260bf` pushed to main; 231 tests passing |
| S20-REVIEW | Review `fix: harden azure deployment workflows` (367d2db) | 2026-04-12 | Approved with one flag: config-settle race → S20-FIX assigned to Codex |
| DEPLOY-OPTIONS | Review deployment remediation options (`DEPLOYMENT_OPTIONS_2026-04-12.md`) | 2026-04-12 | Approved — Option 3 (`azure/webapps-deploy` + publish profiles) → DEPLOY-OPT3 assigned; S20-FIX bundled |
| M1 | Alembic migration: timestamp columns → `DateTime(timezone=True)` | 2026-04-12 | Approved — migration correct, ORM helpers, TTL compare updated |
| M2 | Canonical `anchor_utils.py` `classify_anchor()` | 2026-04-12 | Approved — all three callers use shared util; regex covers fractional seconds |
| M3 | Document + pop `_transcript_text_inline` before persistence | 2026-04-12 | Approved — ephemeral field documented and explicitly removed in both success and failure paths |
| M4 | Draft upsert-by-composite-PK (no delete-then-insert) | 2026-04-12 | Approved — audit timestamps preserved; incremental upsert pattern consistent with AgentRun |
| M5 | `draft_source: "stub"` + `stub_draft_detected` BLOCKER in reviewing | 2026-04-12 | Approved — reviewing agent correctly gates on stub before all other checks |
| L1 | Consolidate `_utc_now()` — runner imports from job_logic; servicebus renamed to `_utc_now_dt()` | 2026-04-12 | Approved — three definitions removed/renamed; processing agent uses shared util |
| L2 | `deploy-workers.yml` uses canonical `AZURE_OPENAI_CHAT_DEPLOYMENT_NAME`; startup log trimmed | 2026-04-12 | Approved — all three worker appsettings blocks use canonical var |
| L3 | `_extract_speaker` heuristic tightened: VTT `<v>` tag preference, 25-char cap, numeric-start rejection, prefix filter | 2026-04-12 | Approved — false-positive risk substantially reduced |
| L4 | `/dev/simulate` no longer sets `user_saved_draft=True` | 2026-04-12 | Approved — sets `user_saved_draft=False, user_saved_at=None`; 409 path now testable |
| DC1 | Dead code removed: `_cost_usd()` in `extraction.py`, `_DEPLOYMENT` var in `processing.py`/`extraction.py` | 2026-04-12 | Approved — no dead references remain |
