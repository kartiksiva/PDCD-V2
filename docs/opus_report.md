# Opus Code Review Report — PFCD-V2

**Reviewer:** Claude Opus 4.7
**Date:** 2026-04-30
**Commit:** `e5a65f5` (main)
**Method:** 5 parallel Sonnet review agents (backend HTTP/orchestration, agents/pipeline, workers/export, frontend/streamlit, infra/CI) + inline security sweep.

---

## Executive Summary

| Severity | Count | Primary Risk |
|----------|------:|--------------|
| CRITICAL | 3 | Data breach, silent quality loss |
| HIGH     | 15 | Pipeline DoS, cost blowout, lost edits |
| MEDIUM   | 17 | Memory exhaustion, user-visible bugs |
| LOW      | ~10 | Hygiene, future regression vectors |

**Top-five must-fix (in order):**
1. C1 — Path traversal in PDF/DOCX export
2. C3 — Alignment self-comparison (text similarity broken)
3. H5 + H1 — ffmpeg/SK timeout + Service Bus lock renewal (worker DoS)
4. H6 — 429 retry (known production failure 2026-04-20)
5. H7 — Debounced save race on finalize (data loss for users)

**Clean areas** (no findings): no XSS sinks (no `dangerouslySetInnerHTML`/`innerHTML`/`eval`); no `subprocess(shell=True)`; no hardcoded production secrets in source; CORS validation present; timing-safe API key compare; migration linearity (0001→0006) intact.

---

## CRITICAL

### C1 — Path traversal in export builder
- **File:** `backend/app/export_builder.py:586-591, 888-893`
- **What:** PDF/DOCX frame embed falls back to raw `open(key, "rb")` when `os.path.isabs(key)` or `key.startswith(".")`. `storage_key` originates from `agent_signals.frame_storage_keys` and `evidence_items[*].metadata.frame_storage_keys` — populated from agent output.
- **Impact:** Arbitrary file read by App Service identity. LLM prompt injection or upstream bug → `/etc/passwd`, env files, Azure managed-identity tokens leak via downloaded export. Compliance/data breach.
- **Fix:** Reject any `storage_key` that is absolute or contains `..`. Always route through `ExportStorage` with allowlisted prefix.

### C2 — Evidence hierarchy violates PRD §7
- **File:** `backend/app/agents/evidence.py:41-52`
- **What:** `video only` returns `"low"` despite video being highest tier per PRD §7. CLAUDE.md asserts `has_video + has_audio → "high"` but the video-only path falls through to the `else: strength = "low"` branch.
- **Impact:** Video-only jobs always flagged BLOCKER → false NEEDS_REVIEW spam → manual override required → user trust erosion. Audit failure against PRD.
- **Fix:** Return `"medium"` for `has_video and not has_audio`; reserve `"low"` for no-source case.

### C3 — Alignment self-comparison
- **File:** `backend/app/agents/alignment.py:344-345`
- **What:** `uploaded_transcript = job.get("_transcript_text_inline") or transcript_text`. `transcript_text` already came from same key on line 280. Comparing transcript to itself.
- **Impact:** `transcript_media_consistency.similarity_score ≈ 1.0` always. Real divergence between user transcript and Whisper-derived transcript never surfaces. Bad transcripts pass silently → garbage PDD/SIPOC; output quality unmeasurable.
- **Fix:** Compare `_video_transcript_inline` (Whisper-derived) vs `_transcript_text_inline` (uploaded).

---

## HIGH

### H1 — Missing AutoLockRenewer on Service Bus
- **File:** `backend/app/workers/runner.py:421-444`
- **What:** SK calls take minutes; Service Bus default lock 30-60s; no `AutoLockRenewer` registered.
- **Impact:** Lock loss → `MessageLockLostError` → message redelivered → phase re-runs → 2× LLM cost; under load, retry storm until `_should_skip` deduplicates.
- **Fix:** `azure.servicebus.AutoLockRenewer` per receiver/message; lock_lost callback for safety.

### H2 — Phase-complete + next-enqueue not atomic
- **File:** `runner.py:131-219, 230`
- **What:** Worker calls `upsert_job` → `orchestrator.enqueue(next_phase)` → `complete_message`. No transaction.
- **Impact:** Crash between upsert and enqueue → job stuck in PROCESSING; message already completed → no retry. Operator must manually re-enqueue.
- **Fix:** Outbox pattern (persist `pending_next_phase` marker; sweeper enqueues), or enqueue *before* `complete_message`.

### H3 — Retry path missing `upsert_job`
- **File:** `runner.py:251-261`
- **What:** Failure-path `update_agent_run` mutates in-memory `job` only; permanent-failure branch calls `upsert_job`, retry branch doesn't.
- **Impact:** Failed AgentRun lifecycle row never persisted → next message reload shows stale snapshot → cost tracking wrong; debugging crashes harder.
- **Fix:** `self.repo.upsert_job(job_id, job)` after failure mutation, before retry enqueue.

### H4 — Kernel cache + per-call `asyncio.run()`
- **File:** `backend/app/agents/kernel_factory.py:16, 38`
- **What:** SK kernel objects cached via `lru_cache`. Each call uses `asyncio.run()` which creates+destroys event loop. Cached `httpx.AsyncClient` bound to dead loop.
- **Impact:** 2nd job in same worker process → `RuntimeError: Event loop is closed` → phase fails → worker restart cycle.
- **Fix:** Drop cache, or rebuild per loop, or run a single long-lived loop in worker.

### H5 — ffmpeg subprocess no timeout
- **File:** `backend/app/agents/media_preprocessor.py:24, 39, 75, 116`
- **What:** All four `subprocess.run(["ffmpeg", ...])` calls lack `timeout=`.
- **Impact:** Pathological/malformed video → worker hangs indefinitely → SB lock loss (compounds H1) → message redelivered → another worker hangs → all 3 workers wedged → pipeline DoS.
- **Fix:** `subprocess.run(..., timeout=N)` on every call; on TimeoutExpired, kill and return None/empty.

### H6 — No 429 retry on Whisper / Vision
- **Files:** `transcription.py:48-71`, `vision.py:73-110`
- **What:** `httpx.post` + `raise_for_status` caught by broad `except Exception` → empty transcript / `""` vision result without distinct signal.
- **Impact:** Confirmed production failure (memory log 2026-04-20). Quota spike → all batches fail → empty transcript → garbage PDD → retries hit same 429 → permanent failure loop.
- **Fix:** Bounded exponential backoff on 429/5xx; record per-batch outcome in `agent_signals`; surface quota-distinct error.

### H7 — Debounced save race on finalize
- **File:** `frontend/src/components/DraftReview.jsx:232-285`
- **What:** `scheduleSave` debounces 1500 ms. `handleFinalize` clears timer, calls explicit `saveDraft`, then `finalizeJob`. In-flight save (started ~1.4s prior) can land *after* explicit save.
- **Impact:** User edits clobbered by older payload → finalized SOP has stale data → wrong process documentation shipped.
- **Fix:** `inFlightSavePromise` ref; await before next save; await all pending before finalize.

### H8 — Module-level ENGINE defeats `from_env()`
- **File:** `backend/app/db.py:29`
- **What:** `ENGINE = create_engine(DATABASE_URL)` at import. `JobRepository.from_env()` cannot reconfigure.
- **Impact:** Tests can't isolate DB via monkeypatch; CLAUDE.md `from_env()` factory pattern violated; env rotation requires worker restart.
- **Fix:** Lazy engine construction in `JobRepository.__init__` or first-use.

### H9 — ServiceBus sender not thread-safe
- **File:** `backend/app/servicebus.py:83-93`
- **What:** Module-level `ORCHESTRATOR` singleton; concurrent `enqueue` via `anyio.to_thread.run_sync` races `_senders.get` / `__enter__`.
- **Impact:** Duplicate senders, leaked AMQP links, eventual SB connection exhaustion → enqueue 503 → API 5xx.
- **Fix:** `threading.Lock` around sender creation; same for `_get_enqueue_client`.

### H10 — SIPOC `valid_anchor_count` ignores invalid step refs
- **File:** `backend/app/agents/sipoc_validator.py:128`
- **What:** Row with `step_anchor=["bogus-step"]` and valid `source_anchor` counts as `valid_anchor_count += 1`. Quality gate at line 190 passes.
- **Impact:** SIPOC with all-bogus step refs slips through → exported SOP rows unanchored → reviewers can't trace evidence → PRD §8.8 compliance fail.
- **Fix:** `has_step_anchor and not invalid_step_refs and has_source_anchor`.

### H11 — `setdefault` doesn't overwrite empty PDD
- **File:** `backend/app/agents/processing.py:382-394`
- **What:** LLM returns `pdd.frequency = ""` → `setdefault` skips → reviewer warning checks `== "Needs Review"` → empty bypasses gate.
- **Impact:** Empty `frequency`/`SLA` fields in finalized PDD; reviewer never warns; customer receives blank fields.
- **Fix:** `pdd["frequency"] = pdd.get("frequency") or "Needs Review"` (and equivalents).

### H12 — `_apply_source_type_defaults` clobbers per-item attribution
- **File:** `backend/app/agents/extraction.py:489`
- **What:** Unconditionally overwrites every item with `primary_source_type`.
- **Impact:** Frame OCR vs video transcript indistinguishable downstream → evidence-strength downgrade rules misfire → wrong confidence on deliverable.
- **Fix:** Only overwrite when item.source_type missing/invalid.

### H13 — `dev-bootstrap.sh` undefined vars under `set -u`
- **File:** `infra/dev-bootstrap.sh:193-194`
- **What:** `$SQL_SERVER_NAME` and `$SQL_DATABASE_NAME` referenced; never defined (vestigial Azure SQL era).
- **Impact:** Fresh shell run aborts at line 193 → onboarding broken → new dev environments un-provisionable.
- **Fix:** Delete both lines.

### H14 — Migration 0006 SQLite-incompatible
- **File:** `backend/alembic/versions/20260420_0006_add_extracted_evidence.py:22-24`
- **What:** Plain `op.add_column("jobs", ...)` with `server_default="{}"`. SQLite ALTER TABLE limitations require `batch_alter_table`. Default literal not properly quoted.
- **Impact:** Local dev `alembic upgrade head` may fail or leave malformed column. Future migrations on `jobs` may corrupt schema.
- **Fix:** Wrap in `with op.batch_alter_table("jobs") as batch_op:`; use `server_default=sa.text("'{}'")`.

### H15 — Non-UUID upload IDs
- **Files:** `frontend/src/api.js:82-85`, `streamlit_app/api_client.py:67`
- **What:** Fallback `upload-${Date.now()}-${random}` when `crypto.randomUUID` missing. Streamlit always uses `upload-${hex}`.
- **Impact:** Backend UUID validation may 422 → upload broken on older Safari/non-HTTPS dev; Streamlit upload always hits this path.
- **Fix:** Real UUID polyfill (`[1e7]+...replace`).

---

## MEDIUM

| ID | File:Line | Issue | Impact | Fix |
|----|-----------|-------|--------|-----|
| M1 | `main.py:111-114` | Manifest written non-atomically | Crash mid-write → truncated JSON → upload state lost | Temp + `os.replace` |
| M2 | `main.py:552-594, 522` | Upload reads full body to RAM (500MB cap) | 3 concurrent uploads → 1.5GB → OOM kill | Stream + size accounting |
| M3 | `main.py:73-87` | CORS validation raises at import | Bad config → opaque process startup failure | Move to `_lifespan` |
| M4 | `main.py:715-779` | `update_draft` second `upsert_job` skips version recheck | Concurrent edit+finalize race → lost update | Single transaction RMW |
| M5 | `storage.py:121-134` | Storage mode mismatch hard-fails | Local→blob migration → historical exports inaccessible | Graceful fallback |
| M6 | `job_logic.py:419-439` | Client-supplied `storage_key` not validated | Possible arbitrary file read inside server | Constrain to `UPLOADS_DIR` |
| M7 | `export_builder.py:171-183` | `_format_date` mangles tz-aware ISO | SOP date column shows raw ISO instead of `30-Apr-2026` | `datetime.fromisoformat(s.replace("Z","+00:00"))` |
| M8 | `export_builder.py:496-611` | PDF builder unbounded frame memory | 40 high-res frames → worker OOM during export | Cap per-frame + total |
| M9 | `cleanup.py:52-67` | `purge_pending_jobs` partial-purge on storage error | Orphaned blobs → cost creep + GDPR retention violation | Transactional purge + max-retry counter |
| M10 | `cleanup.py:77-82` | `time.sleep` blocks SIGTERM | App Service rolling restart hangs 5min → hard kill mid-purge | `Event.wait` |
| M11 | `frontend/src/api.js:101-108` | Auth header sent to non-same-origin URLs | `X-API-Key` leak to Azure Blob diagnostic logs | Same-origin gate |
| M12 | `frontend/src/api.js:72-74` | Dead `exportUrl` helper (unauthenticated) | Future regression vector | Delete |
| M13 | `streamlit_app/app.py:467-484` | Re-downloads exports on every render | Multi-MB GET ×4 per rerun → bandwidth + cost | Lazy fetch on click |
| M14 | `backend/requirements.txt` | `azure-ai-agents>=1.2.0b3`, `pydantic>=2.11.0` | Beta bump silently breaks CI/prod | Pin or lockfile |
| M15 | `deploy-backend.yml` + `deploy-workers.yml` | Same PG smoke test runs twice per push | 2× CI minutes, 2× flake exposure | `workflow_call` reusable |
| M16 | `reviewing.py:114` | Speaker check uses substring `"Unknown"` | False-positive flags on `"John Unknown-Smith"` | Exact-match comparison |
| M17 | `processing.py:294-315` | JSON parser accepts incomplete shape | Confusing `sipoc_empty` blocker masks real parse-shape bug | Validate `pdd`/`sipoc` keys present |

---

## LOW

| ID | File:Line | Issue | Impact |
|----|-----------|-------|--------|
| L1 | `auth.py:15` | Reads env per request | Ops can disable auth at runtime by unsetting env (surprising) |
| L2 | `deploy-backend.yml:223-226`, `deploy-workers.yml:294-295` | `PFCD_API_KEY` plaintext in ACA YAML | Visible to RBAC readers; rotation friction |
| L3 | `pytest.ini:6-8` | Missing `postgres` marker | `--strict-markers` would fail |
| L4 | `extraction.py:25-108` | `{transcript_text}` interpolation | Theoretical prompt injection; mitigated by `response_format=json_object` |
| L5 | `runner.py:286` | `2 ** attempt` no exponent cap | Cosmetic (cap=60s anyway) |
| L6 | `docker-compose.local.yml:155, 202` | worker-processing/reviewing missing `build:` | Local dev quirk if started in wrong order |
| L7 | `frontend/src/components/SipocTable.jsx` vs `EditableSipocTable` | Column drift | Future dev confusion |
| L8 | `streamlit_app/app.py:240-248` | `confirm_cost` button lost on rerun | User must re-upload to confirm cost |
| L9 | `kernel_factory.py:55` | Cache key includes api_key | Key rotation requires worker restart |
| L10 | `media_preprocessor.py:14` + `transcription.py:26` | `_MAX_TRANSCRIPTION_BYTES = 24MB` duplicated | Drift risk |

---

## Action Plan

### Phase A — Stop the bleed (1-2 days)
Land before any new feature work. Each is a self-contained PR.

| Order | ID | Task | Owner | PR Branch Suggestion |
|------:|----|------|-------|----------------------|
| A1 | C1 | Reject absolute / `..` storage_key in export_builder; route through ExportStorage | Codex | `codex/c1-export-path-traversal` |
| A2 | C3 | Fix alignment to compare `_video_transcript_inline` vs `_transcript_text_inline` | Codex | `codex/c3-alignment-selfcompare` |
| A3 | H5 | Add `timeout=` to all 4 ffmpeg `subprocess.run` calls + kill on TimeoutExpired | Codex | `codex/h5-ffmpeg-timeout` |
| A4 | H1 | Register `AutoLockRenewer` on SB receiver | Codex | `codex/h1-sb-lock-renewer` |
| A5 | H6 | Bounded exp backoff on 429/5xx in transcription.py + vision.py; surface quota error | Codex | `codex/h6-quota-retry` |
| A6 | H7 | `inFlightSavePromise` ref in DraftReview.jsx; await before next save | Codex | `codex/h7-finalize-race` |
| A7 | H13 | Delete vestigial `$SQL_SERVER_NAME` lines in dev-bootstrap.sh | Codex | `codex/h13-bootstrap-cleanup` |

**Acceptance:** all 7 PRs merged, 273+ tests still passing, smoke `/health` green, e2e pipeline test runs end-to-end on a real video without hang.

---

### Phase B — Correctness & atomicity (3-5 days)

| Order | ID | Task |
|------:|----|------|
| B1 | C2 | Fix evidence hierarchy: video-only → `medium`; verify against PRD §7 |
| B2 | H10 | SIPOC `valid_anchor_count` requires no-invalid-refs + step + source |
| B3 | H11 | Replace `setdefault` with `or "Needs Review"` for empty-string defense |
| B4 | H12 | Preserve LLM-assigned `source_type`; only fill when missing |
| B5 | H2 | Outbox pattern: persist `pending_next_phase`; sweeper enqueues |
| B6 | H3 | `upsert_job` after failed `update_agent_run` in retry branch |
| B7 | H9 | `threading.Lock` around SB sender + enqueue client creation |
| B8 | H14 | Re-author migration 0006 with `batch_alter_table` + `sa.text("'{}'")` |
| B9 | H15 | UUID polyfill in api.js + api_client.py |

**Acceptance:** evidence hierarchy unit tests cover all 8 source-combo cells; SIPOC validator tests cover bogus-ref case; migration 0006 round-trips on SQLite; UUID-rejecting backend test exists.

---

### Phase C — Stability & infra (3-5 days)

| Order | ID | Task |
|------:|----|------|
| C1 | H4 | Drop `lru_cache` on kernel; rebuild per asyncio.run, OR refactor worker to single long-lived loop |
| C2 | H8 | Lazy engine init in JobRepository; remove module-level ENGINE |
| C3 | M1 | Atomic manifest write (temp + os.replace) |
| C4 | M2 | Stream uploads to disk with size accounting |
| C5 | M3 | Move CORS validation into `_lifespan` |
| C6 | M4 | Wrap `update_draft` RMW in single transaction |
| C7 | M8 | Cap PDF frame size + count |
| C8 | M9 | Transactional `purge_job_data` + max-retry counter |
| C9 | M10 | `Event.wait` + SIGTERM handler in cleanup loop |

---

### Phase D — Hygiene (parallel to A–C, ~1 day total)

| ID | Task |
|----|------|
| M5 | Storage-mode fallback for historical exports |
| M6 | Validate client `storage_key` inside `UPLOADS_DIR` |
| M7 | `_format_date` rewrite using `datetime.fromisoformat` |
| M11 | Same-origin gate on `X-API-Key` in api.js |
| M12 | Delete `exportUrl` helper |
| M13 | Lazy export download in Streamlit |
| M14 | Pin `azure-ai-agents` and `pydantic` exactly; or adopt `uv pip compile` lockfile |
| M15 | Extract reusable `workflow_call` for PG smoke |
| M16 | Exact-match speaker comparison |
| M17 | Validate parsed processing JSON shape |
| L1-L10 | Batch into single hygiene PR |

---

## Risk-Tier Summary

| Tier | Issues | Worst-case Outcome |
|------|--------|--------------------|
| Data breach | C1, M11, L2 | Secrets exfil via PDF; API key in Azure logs |
| Pipeline DoS | H5, H4, H1 | All 3 workers wedged; restart loop |
| Cost blowout | H1, H6 | 2× LLM spend; 429 retry storm |
| Silent quality loss | C2, C3, H10, H11, H12, M16, M17 | Wrong PDD/SIPOC shipped without warning |
| Data loss | H2, H7, M1, M4 | Lost user edits; stuck jobs requiring manual intervention |
| User-visible bugs | M7, M13, H15, L8 | Broken upload subset; slow Streamlit; wrong dates |
| Infra brittleness | H13, H14, M3, M14 | Onboarding broken; opaque deploy; CI flake |

---

## Acceptance Gate Before Phase 8 Start

The following must hold before the next PRD phase begins:

1. All Phase A items merged + verified in dev environment
2. C2/H10/H11/H12 (Phase B silent-quality issues) merged — output trustworthy
3. End-to-end pipeline run on a real 10-min video succeeds without manual intervention
4. CI green; 273+ tests passing; `e2e_pipeline.py` PASS

---

## File Inventory Reviewed

- `backend/app/main.py`, `repository.py`, `db.py`, `servicebus.py`, `storage.py`, `auth.py`, `job_logic.py`, `models.py`
- `backend/app/agents/extraction.py`, `processing.py`, `reviewing.py`, `alignment.py`, `evidence.py`, `sipoc_validator.py`, `anchor_utils.py`, `kernel_factory.py`, `media_preprocessor.py`, `transcription.py`, `vision.py`
- `backend/app/agents/adapters/transcript.py`, `video.py`, `registry.py`
- `backend/app/workers/runner.py`, `cleanup.py`
- `backend/app/export_builder.py`
- `frontend/src/api.js`, `App.jsx`, `components/*.jsx`
- `streamlit_app/app.py`, `api_client.py`
- `.github/workflows/deploy-backend.yml`, `deploy-frontend.yml`, `deploy-workers.yml`
- `infra/dev-bootstrap.sh`, `infra/README.md`
- `docker-compose.local.yml`
- `backend/alembic/versions/*.py`, `backend/requirements.txt`
- `tests/conftest.py`, `pytest.ini`, `scripts/test_e2e_pipeline.py`

---

*End of report.*
