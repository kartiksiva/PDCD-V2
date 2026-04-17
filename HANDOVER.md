# HANDOVER.md

Shared coordination board. Read and updated by both Claude and Codex at session start.

- **Claude** adds items to "Assigned to Codex" when assigning work; closes items after review.
- **Codex** moves items to "In Progress" when starting, then "Ready for Claude Review" when done.

---

## Assigned to Codex (not started)

| ID | Task | Notes |
|----|------|-------|
| — | | |

---

## In Progress (Codex working)

| ID | Task | Started |
|----|------|---------|
| — | | |

---

## On Hold

| ID | Task | Reason |
|----|------|--------|
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
| CLAUDE-BASELINE-COMMIT | Create baseline commit from approved deployment/doc updates | 2026-04-17 | Complete — all workflow and doc changes from this session committed as a single reviewed baseline |
| CLAUDE-HANDOVER-CLEANUP | Reconcile HANDOVER.md with actual repo state | 2026-04-17 | Complete — removed all stale task spec bodies; board now reflects current reality |
| DEPLOY-FRONTEND-AUTH | Inject `VITE_API_KEY` in frontend build; fail-fast on missing `VITE_API_BASE` | 2026-04-17 | Approved — validation step + `VITE_API_KEY` env var in build step; post-deploy smoke probe added in same workflow |
| WORKER-TEST-GATE | Add pytest gate to `deploy-workers.yml` | 2026-04-17 | Approved — `test` job added; all three deploy jobs carry `needs: [test, build]`; pattern matches backend |
| FRONTEND-SMOKE | Post-deploy `/health` probe in frontend workflow | 2026-04-17 | Approved — 12×10s probe after SWA upload; inherits `VITE_API_BASE` safely |
| BACKEND-CONFIG-VALIDATE | Assert `DATABASE_URL`, SB conn string, AOAI endpoint in backend deploy | 2026-04-17 | Approved — `missing=""` accumulator reports all absent secrets in one error message |
| AZURE-DEPLOY-REVIEW | Copilot Azure deployment review — 8 findings triaged; 4 Codex tasks created | 2026-04-17 | Approved — critical: VITE_API_KEY inject + VITE_API_BASE fail-fast; worker test gate; frontend smoke probe; backend config validation. Worker matrix refactor, Key Vault migration, and ffmpeg deferred. See Section 38 in IMPLEMENTATION_SUMMARY.md |
| DEPLOY-FIX3 | Switch backend to `WEBSITE_RUN_FROM_PACKAGE` | 2026-04-17 | Approved — `azure/webapps-deploy@v3` removed; blob upload + SAS URL + `WEBSITE_RUN_FROM_PACKAGE` appsetting applied; `PFCD_CORS_ORIGINS` folded into single `az webapp config appsettings set` call; separate post-deploy config step removed; `infra/README.md` updated; 273 tests passing |
| WORKER-BUILD-RCA | Investigate and fix worker build failure in `deploy-workers.yml` | 2026-04-17 | Approved — operator action only; root cause: `pfcd-dev-api-gha` service principal lacked `Storage Blob Data Contributor` on `pfcddevstorage`; role granted; `Deploy Workers` run `24387794848` build job passed; no workflow code change required |
| DEPLOY-FIX2 (Part 2) | Switch workers to `WEBSITE_RUN_FROM_PACKAGE` | 2026-04-14 | Complete — workflow code was pre-implemented; operator completed RBAC assignments + GitHub variable; workers deploying via blob-mounted ZIP |
| FRAME-PERSIST | Persist frame captures to storage; surface in export bundle | 2026-04-13 | Approved — `upload_frame()` in storage.py; keys in VideoAdapter metadata + agent_signals; `_timestamp_to_seconds` + anchor-linking in export_builder; "pending" note removed; 273 tests pass |
| SPEAKER-RESOLVE | Speaker resolution UI + teams_metadata in extraction prompt | 2026-04-13 | Approved — `_build_speaker_hint` injected into extraction prompt; `SpeakerResolutionPanel` in DraftReview; `saveDraft` extended with speakerResolutions; 269 tests |
| DRAFT-EDIT | Editable PDD/SIPOC in DraftReview + re-review on save | 2026-04-13 | Approved — `rerunnable_codes` pre-filter + `run_reviewing` re-run in `update_draft`; `review_notes`/`agent_review` in response; `EditablePddSection`, `EditableSipocTable`, debounced auto-save, `liveFlags` in DraftReview; 267 tests |
| FRONTEND-COMPLETE | Phase 6 frontend integration — API key header, save-draft fix, job list | 2026-04-13 | Approved — `X-API-Key` header in `_fetch` + upload; `saveDraft` before finalize; `GET /api/jobs` + `list_jobs()`; `JobList.jsx`; `ExportLinks` switched to `downloadExport` (auth on downloads); 264 tests pass |
| KEYFRAME-VISION | Keyframe extraction + multimodal LLM frame analysis | 2026-04-13 | Approved — `vision.py` added; `extract_keyframes` in preprocessor; VideoAdapter combines AUDIO TRANSCRIPT + FRAME ANALYSIS; confidence 0.90 when both; 260 tests pass |
| MEDIA-PREPROCESSOR | ffmpeg audio extraction + chunked Whisper transcription | 2026-04-13 | Approved — `media_preprocessor.py` added; `transcription.py` refactored with `_transcribe_single` + pipeline; temp dir cleanup in `finally`; 253 tests pass |
| E2E-PIPELINE-TEST | Add local e2e pipeline smoke test script | 2026-04-13 | Approved — `scripts/test_e2e_pipeline.py` added; live run PASS; 4/4 SIPOC rows have step_anchor + source_anchor; no sipoc_no_anchor blocker |
| REVIEW-FLAGS-L1L2L3 | Three low-severity cleanup items from Phase 1 review | 2026-04-13 | Approved — `_provider_name()` deduplicated; `render_review_notes()` gates on storage_key; `_CONSISTENCY_INCONCLUSIVE_THRESHOLD` replaces hardcoded 0.5; 245 tests pass |
| PROC-PROMPT-FIX | Strengthen processing prompt so SIPOC anchors are reliably generated | 2026-04-13 | Approved — `_SIPOC_SCHEMA` concrete examples; 4 explicit anchor rules; anchor assertion test added; 243 tests pass |
| PROVIDER-FLEX | Add `PFCD_PROVIDER` env var; support direct OpenAI alongside Azure OpenAI | 2026-04-13 | Approved — `kernel_factory.py`, `extraction.py`, `processing.py`, `job_logic.py` updated; `REFERENCE.md` updated |
| VIDEO-TRANSCRIPTION | Wire real Whisper transcription into VideoAdapter | 2026-04-13 | Approved — `transcription.py` added; `VideoAdapter.normalize()` calls real Whisper; `_normalize_input()` merges video+uploaded content |
| TEXT-SIMILARITY | Replace anchor-ratio consistency proxy with real text similarity | 2026-04-13 | Approved — Jaccard+SequenceMatcher in `alignment.py`; env-configurable thresholds; 4 new tests |
| DEPLOY-FIX2 (Part 1) | Remove startup-file mutation from deploy workflow; widen settle sleep to 60 s | 2026-04-12 | Approved — `az webapp config set --startup-file` removed; `sleep 60` in all settle steps |
| REPO-CLEANUP | Delete artefacts, fix .gitignore, archive historical docs | 2026-04-12 | Approved — `dfb88ff`; clean working tree |
