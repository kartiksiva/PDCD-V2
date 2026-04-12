# HANDOVER.md

Shared coordination board. Read and updated by both Claude and Codex at session start.

- **Claude** adds items to "Assigned to Codex" when assigning work; closes items after review.
- **Codex** moves items to "In Progress" when starting, then "Ready for Claude Review" when done.

---

## Assigned to Codex (not started)

| ID | Task | Notes |
|----|------|-------|
| — | | |

### S20-FIX — Config-settle race fix

In `deploy-workers.yml`, each "Wait for … worker config restart to settle" step polls `az webapp show --query "state"` immediately after `az webapp config appsettings set`. If the Azure control plane hasn't yet registered the restart, the first poll returns `"Running"` (pre-restart), the step exits after 30s, and `az webapp deploy` fires before the restart cycle has completed — the exact race it was meant to prevent.

**Fix:** add `sleep 15` at the top of each of the three settle steps, before the `for` loop:

```yaml
- name: Wait for extracting worker config restart to settle
  run: |
    sleep 15
    for i in $(seq 1 30); do
      ...
```

Apply identically to all three workers (`extracting`, `processing`, `reviewing`). No other changes needed.

---

### DEPLOY-OPT3 — Switch to `azure/webapps-deploy@v3` (Path A — no publish profile)

Replace `az webapp deploy` with `azure/webapps-deploy@v3` in both workflows. **Do not use `publish-profile`** — SCM basic auth is disabled on this subscription and publish profiles are redacted. Instead, rely on the `azure/login@v2` step already in the workflow; the action will authenticate to Kudu using a bearer token from the logged-in service principal.

**No new secrets required.**

**Workflow change** — replace the `az webapp deploy` step with:
```yaml
- uses: azure/webapps-deploy@v3
  with:
    app-name: ${{ secrets.AZURE_WEBAPP_NAME }}
    package: ./backend.zip
```
Apply equivalent blocks for each worker (substitute `AZURE_WORKER_EXTRACTING_NAME`, etc.).

**Keep as-is:**
- `azure/login@v2` step (still needed — provides credentials for both `az webapp config` calls and the deploy action)
- S20-FIX `sleep 15` in config-settle steps
- HTTP readiness probe and state poll steps
- Concurrency groups and `timeout-minutes`

**Fallback if Option 3 still fails:** move to `WEBSITE_RUN_FROM_PACKAGE` (upload zip to blob, set appsetting, restart). Medium-term: move workers to Container Apps with KEDA Service Bus scaler.

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
|----|------|--------|---------|
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
