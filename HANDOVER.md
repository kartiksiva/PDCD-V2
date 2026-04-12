# HANDOVER.md

Shared coordination board. Read and updated by both Claude and Codex at session start.

- **Claude** adds items to "Assigned to Codex" when assigning work; closes items after review.
- **Codex** moves items to "In Progress" when starting, then "Ready for Claude Review" when done.

---

## Assigned to Codex (not started)

| ID | Task | Notes |
|----|------|-------|
| — | | |

### REVIEW-FLAGS-L1L2L3 — Phase 1 review cleanup (L1, L2, L3)

Three non-blocking items raised during Claude's review of PROC-PROMPT-FIX / PROVIDER-FLEX / VIDEO-TRANSCRIPTION / TEXT-SIMILARITY. Bundle as one commit.

**L1 — Extract `_provider_name()` to avoid duplication**

`_provider_name()` is defined identically in `kernel_factory.py`, `transcription.py`, and `job_logic.py`. Extract it to `job_logic.py` only (it's already there), and replace the other two definitions with an import:

```python
from app.job_logic import _provider_name
```

Remove the local `_provider_name` definitions from `kernel_factory.py` and `transcription.py`.

**L2 — Fix `render_review_notes()` in VideoAdapter when transcription succeeded**

`VideoAdapter.render_review_notes()` always appends `"Azure Vision / Speech integration pending — frame content is not yet analyzed."` This is false when Whisper transcription returned real VTT content.

Change: if `evidence_obj.metadata.get("storage_key")` is set (meaning transcription was attempted), replace the pending note with `"Audio transcription complete. Frame-level visual analysis pending."`. If `storage_key` is absent, keep the existing note unchanged.

**L3 — Use configurable thresholds in the anchor-ratio fallback branch of `run_anchor_alignment()`**

In `alignment.py`, the anchor-ratio branch (lines ~329–336) uses hardcoded `0.8` and `0.5` thresholds while the text-similarity branch uses `_CONSISTENCY_MATCH_THRESHOLD` and `_CONSISTENCY_MISMATCH_THRESHOLD`. Make both branches consistent: replace the hardcoded `0.8` with `_CONSISTENCY_MATCH_THRESHOLD` and `0.5` with a new constant `_CONSISTENCY_INCONCLUSIVE_THRESHOLD = float(os.environ.get("PFCD_CONSISTENCY_INCONCLUSIVE_THRESHOLD", "0.50"))`. Document `PFCD_CONSISTENCY_INCONCLUSIVE_THRESHOLD` in `REFERENCE.md`.

**Do not change:** any test fixtures, migration files, `sipoc_validator.py`, `reviewing.py`, `processing.py`, `extraction.py`.

**Verification:**
```bash
cd backend
.venv/bin/pytest ../tests/ -v   # all 243+ tests pass
```

Commit as: `refactor: deduplicate _provider_name, fix review notes, align consistency thresholds`

---

### PROC-PROMPT-FIX — Strengthen processing prompt for SIPOC anchor generation

**Observed failure (2026-04-12):**
Transcript-only job with `balanced` profile (GPT-4o-mini) reaches `NEEDS_REVIEW` with a `sipoc_no_anchor` BLOCKER on every run. The PDD content (purpose, scope, steps, roles) is correct. The SIPOC content fields (supplier, input, process_step, output, customer) are present. But `step_anchor` and `source_anchor` are empty or null on every SIPOC row, so `valid_anchor_count == 0` and the quality gate fires.

**Root cause:**
`processing.py` `_USER_PROMPT_TEMPLATE` asks for the full PDD + SIPOC in one JSON response. GPT-4o-mini meets the content requirements but drops the cross-reference anchor fields under the complexity load.

**Fix — three changes:**

**1. `backend/app/agents/processing.py` — `_SIPOC_SCHEMA`**

Replace abstract placeholder strings with concrete examples so the LLM can pattern-match:
```python
_SIPOC_SCHEMA = """\
[
  {
    "step_anchor": ["step-01"],
    "source_anchor": "00:01:23-00:02:45",
    "supplier": "string",
    "input": "string",
    "process_step": "string",
    "output": "string",
    "customer": "string",
    "anchor_missing_reason": null
  }
]"""
```

**2. `backend/app/agents/processing.py` — `_USER_PROMPT_TEMPLATE` rules block**

Remove the existing vague anchor rule:
```
- source_anchor must reference timestamps from evidence; set anchor_missing_reason if unavailable
```

Replace with these four explicit rules:
```
- step_anchor MUST be a non-empty JSON array with at least one PDD step ID from the steps list above (e.g. ["step-01"]). Never leave step_anchor as [] or null.
- source_anchor MUST be a non-empty string copied verbatim from an evidence item anchor value above (timestamp range "HH:MM:SS-HH:MM:SS" or section label). Never leave source_anchor as "" or null.
- If the closest available anchor is approximate, still use it and explain in anchor_missing_reason. Do not leave source_anchor blank as a way of signalling uncertainty.
- anchor_missing_reason must be null when both anchors are present; a short explanation string when source_anchor is approximate or step_anchor coverage is partial.
```

**3. `tests/unit/test_agents.py` — add anchor assertion test**

Add `test_processing_agent_sipoc_rows_have_anchors` after `test_processing_agent_populates_draft`. The new test must assert that every SIPOC row in the mock LLM response has `len(row["step_anchor"]) >= 1` and `row["source_anchor"] != ""`. Also update the existing mock LLM response fixture used by `test_processing_agent_populates_draft` to include proper `step_anchor` and `source_anchor` on all SIPOC rows — the current fixture may have empty anchors which allows the test to pass without exercising the quality gate path.

**Do not change:** `sipoc_validator.py`, `reviewing.py`, `extraction.py`, `alignment.py`, or migration files.

**Verification:**
```bash
cd backend
.venv/bin/pytest ../tests/unit/test_agents.py -v   # all existing + new test pass
.venv/bin/pytest ../tests/ -v                       # full suite stays green
```
Manual: `POST /dev/simulate` on local instance → `review_notes.flags` must not contain `sipoc_no_anchor`.

Commit as: `fix: strengthen processing prompt SIPOC anchor rules; add anchor assertion test`

---

---

### PROVIDER-FLEX — Add `PFCD_PROVIDER` env var; support direct OpenAI alongside Azure OpenAI

**Context (2026-04-13):**
Individual Azure accounts have model provisioning restrictions. Direct OpenAI API gives access to the same models (gpt-4o, gpt-4.1, etc.) without Azure quota constraints. Both providers speak the same OpenAI API shape — no prompt or schema changes required. `PFCD_PROVIDER=azure_openai` remains the default.

**Changes — 4 files:**

**1. `backend/app/agents/kernel_factory.py`**

Add a second cached builder for the direct OpenAI path and export `get_chat_service(deployment: str)` that returns the service object directly (so callers don't need to know which SK type to look up):

```python
PFCD_PROVIDER = os.environ.get("PFCD_PROVIDER", "azure_openai")

@lru_cache(maxsize=8)
def _cached_kernel_openai(api_key: str, model: str):
    from semantic_kernel import Kernel
    from semantic_kernel.connectors.ai.open_ai import OpenAIChatCompletion
    kernel = Kernel()
    kernel.add_service(OpenAIChatCompletion(ai_model_id=model, api_key=api_key))
    return kernel

def get_kernel(deployment: str):
    if PFCD_PROVIDER == "openai":
        api_key = os.environ["OPENAI_API_KEY"]
        return _cached_kernel_openai(api_key, deployment)
    # existing azure path unchanged
    ...

def get_chat_service(deployment: str):
    """Return the chat completion service for the active provider."""
    from semantic_kernel.connectors.ai.open_ai import (
        AzureChatCompletion, OpenAIChatCompletion,
    )
    kernel = get_kernel(deployment)
    if PFCD_PROVIDER == "openai":
        return kernel.get_service(type=OpenAIChatCompletion)
    return kernel.get_service(type=AzureChatCompletion)
```

**2. `backend/app/agents/extraction.py`**

- Replace `from semantic_kernel.connectors.ai.open_ai import AzureChatCompletion, AzureChatPromptExecutionSettings` with `OpenAIChatPromptExecutionSettings` (works for both providers in SK)
- Replace `svc = kernel.get_service(type=AzureChatCompletion)` with `from app.agents.kernel_factory import get_chat_service; svc = get_chat_service(deployment)`
- Replace `AzureChatPromptExecutionSettings(response_format=...)` with `OpenAIChatPromptExecutionSettings(response_format=...)`
- Pass `deployment` through to `get_chat_service` — use the same `deployment` arg already passed to `_call_extraction`

**3. `backend/app/agents/processing.py`**

Same two substitutions as extraction.py — `get_chat_service` and `OpenAIChatPromptExecutionSettings`.

**4. `backend/app/job_logic.py`**

Rename `_default_openai_deployment()` to `_default_chat_model()` and `_profile_openai_deployment()` to `_profile_chat_model()`. When `PFCD_PROVIDER == "openai"`, read `OPENAI_CHAT_MODEL_BALANCED` / `OPENAI_CHAT_MODEL_QUALITY` instead of the Azure deployment env vars:

```python
def _profile_chat_model(profile: Profile) -> str:
    provider = os.environ.get("PFCD_PROVIDER", "azure_openai")
    if provider == "openai":
        if profile == Profile.QUALITY:
            return os.environ.get("OPENAI_CHAT_MODEL_QUALITY", "gpt-4o")
        return os.environ.get("OPENAI_CHAT_MODEL_BALANCED", "gpt-4o-mini")
    # existing azure logic unchanged
    ...
```

Update all callers of `_profile_openai_deployment` → `_profile_chat_model`.

**New env vars (document in `REFERENCE.md` under the env vars table):**

```
PFCD_PROVIDER=azure_openai          # default; set to "openai" for direct OpenAI
OPENAI_API_KEY=sk-...               # required when PFCD_PROVIDER=openai
OPENAI_CHAT_MODEL_BALANCED=gpt-4o-mini   # optional; default shown
OPENAI_CHAT_MODEL_QUALITY=gpt-4o         # optional; default shown
```

**Do not change:** `reviewing.py` (no LLM calls), `sipoc_validator.py`, `alignment.py`, `evidence.py`, migration files, test fixtures.

**Verification:**
```bash
cd backend
.venv/bin/pytest ../tests/unit/test_agents.py -v        # all pass
.venv/bin/pytest ../tests/ -v                           # full suite green
# Spot-check: kernel_factory returns OpenAIChatCompletion when PFCD_PROVIDER=openai
PFCD_PROVIDER=openai OPENAI_API_KEY=sk-test python -c \
  "from app.agents.kernel_factory import get_kernel; print(get_kernel('gpt-4o-mini'))"
```

Add a `test_kernel_factory_openai_provider` test in `tests/unit/test_agents.py` that monkeypatches `PFCD_PROVIDER=openai` and `OPENAI_API_KEY=test-key` and asserts `get_kernel()` returns a kernel with `OpenAIChatCompletion` service registered.

Commit as: `feat: add PFCD_PROVIDER env var; support direct OpenAI alongside Azure OpenAI`

---

### VIDEO-TRANSCRIPTION — Wire real Whisper transcription into VideoAdapter

**Context:** `VideoAdapter.normalize()` currently returns a metadata string stub. This task replaces it with a real Whisper API call so video jobs produce actual transcript content for the extraction LLM. Depends on PROVIDER-FLEX being merged first.

**Changes — 3 files:**

**1. New `backend/app/agents/transcription.py`**

Single public function `transcribe_audio_blob(storage_key: str) -> str`:
- Returns VTT-formatted transcript text, or a stub string on failure/skip
- Reads `PFCD_PROVIDER` to decide which endpoint to call
- **Azure path:** POST to `{AZURE_OPENAI_ENDPOINT}/openai/deployments/{AZURE_OPENAI_WHISPER_DEPLOYMENT}/audio/transcriptions?api-version={AZURE_OPENAI_API_VERSION}` with `response_format=vtt`. Auth: `DefaultAzureCredential` bearer token for `https://cognitiveservices.azure.com/.default`. Use `httpx` (already in deps).
- **OpenAI path:** POST to `https://api.openai.com/v1/audio/transcriptions` with `model={OPENAI_TRANSCRIPTION_MODEL}` (default `whisper-1`) and `response_format=vtt`. Auth: `Authorization: Bearer {OPENAI_API_KEY}`.
- **File size check before calling API:** if the file at `storage_key` is > 24 MB, skip transcription and return `"[transcription_skipped:file_too_large — chunked transcription pending MediaPreprocessor]"` with a `logger.warning`. This prevents hard failures on large files until MediaPreprocessor is implemented.
- **Graceful failure:** wrap the HTTP call in try/except; on any error return `"[transcription_failed:{ExceptionType}]"` and log the error. Never raise — the adapter must not crash extraction.
- `storage_key` is a local file path (workers run on the same machine as uploads in dev). Read the file with `open(storage_key, "rb")`.

```python
def transcribe_audio_blob(storage_key: str) -> str:
    """Transcribe audio/video file at storage_key using Whisper. Returns VTT text."""
    ...
```

**2. `backend/app/agents/adapters/video.py` — `VideoAdapter.normalize()`**

- Import `transcribe_audio_blob` from `app.agents.transcription`
- If `has_audio` is True and `video_meta.get("storage_key")` is set: call `transcribe_audio_blob(storage_key)`
- If transcription returns non-stub VTT text (does not start with `"[transcription"`):
  - Set `content_text` to the VTT text (replaces metadata string)
  - Parse VTT cue timestamp ranges from the text and populate `anchors` list (reuse `parse_vtt_cues` from `alignment.py`, convert to `"HH:MM:SS-HH:MM:SS"` strings)
  - Set `confidence` to `0.85` (upgraded from `0.75` — real transcription is higher quality)
  - Store the VTT text in `job["_video_transcript_inline"]` (ephemeral field; popped before persistence — document this in the module docstring, same note pattern as `_transcript_text_inline` in extraction.py)
- If `has_audio` is False or `storage_key` is absent or transcription returns a stub: fall back to existing metadata string behavior unchanged

**3. `backend/app/agents/extraction.py` — `_normalize_input()`**

Change the content selection logic (currently transcript-only):

```python
# Build content for LLM: prefer uploaded transcript; supplement with video transcription
transcript_content = ""
video_content = ""

for adapter in adapters:
    ev = adapter.normalize(job)
    ...
    if ev.source_type == "transcript" and ev.content_text:
        transcript_content = ev.content_text
    elif ev.source_type == "video" and ev.content_text and not ev.content_text.startswith("["):
        video_content = ev.content_text

if transcript_content and video_content:
    # Both present: give LLM both, labelled, so it can cross-reference
    content_text = f"VIDEO TRANSCRIPT:\n{video_content}\n\nUPLOADED TRANSCRIPT:\n{transcript_content}"
elif transcript_content:
    content_text = transcript_content
elif video_content:
    content_text = video_content
```

**New env vars (add to `REFERENCE.md`):**

```
AZURE_OPENAI_WHISPER_DEPLOYMENT=whisper   # Azure: name of the Whisper deployment
OPENAI_TRANSCRIPTION_MODEL=whisper-1      # OpenAI: default shown
```

**Worker cleanup:** In `backend/app/workers/runner.py`, wherever `_transcript_text_inline` is popped before job persistence, also pop `_video_transcript_inline` using the same pattern.

**Do not change:** `alignment.py`, `processing.py`, `reviewing.py`, `sipoc_validator.py`, migration files.

**Verification:**
```bash
cd backend
.venv/bin/pytest ../tests/unit/test_adapters.py -v    # VideoAdapter tests pass
.venv/bin/pytest ../tests/ -v                          # full suite green
```

Add `test_video_adapter_normalize_with_transcription` in `tests/unit/test_adapters.py` — monkeypatch `transcribe_audio_blob` to return a short VTT string, assert `ev.content_text` equals the VTT text, `ev.confidence == 0.85`, and `ev.anchors` is non-empty.

Add `test_normalize_input_video_only` and `test_normalize_input_video_and_transcript` in `tests/unit/test_agents.py` asserting the content_text labelling logic in `_normalize_input`.

Commit as: `feat: wire real Whisper transcription into VideoAdapter`

---

### TEXT-SIMILARITY — Replace anchor-ratio consistency proxy with real text similarity

**Context:** `alignment.py`'s `_consistency_score_from_anchors()` computes a proxy score from VTT anchor validity, not actual text content comparison. PRD §8.5 requires "token/sequence similarity on normalized text." Now that VideoAdapter produces real VTT text, this can be implemented properly. The algorithm is ported from V1 `transcript_media_consistency.py`.

**Changes — 1 file: `backend/app/agents/alignment.py`**

**Add three pure-Python helpers at the top of the file:**

```python
import os
from difflib import SequenceMatcher

_SPEAKER_LABEL_RE = re.compile(
    r"^(?:\*{0,2})?(?:[A-Z][A-Za-z'`.\-]+(?:\s+[A-Z][A-Za-z'`.&()/:\-]+){0,5})"
    r"(?:\s*\([^)]+\))?\s*:\s*",
    re.MULTILINE,
)
_VTT_CUE_LINE_RE = re.compile(
    r"^(?:WEBVTT|\d+|\d{2,}:\d{2}(?::\d{2})?\.\d{3}\s+-->\s+.*)$",
    re.IGNORECASE | re.MULTILINE,
)

_CONSISTENCY_MATCH_THRESHOLD = float(os.environ.get("PFCD_CONSISTENCY_MATCH_THRESHOLD", "0.80"))
_CONSISTENCY_MISMATCH_THRESHOLD = float(os.environ.get("PFCD_CONSISTENCY_MISMATCH_THRESHOLD", "0.30"))


def _normalize_for_similarity(text: str, max_chars: int = 2000) -> str:
    """Strip VTT noise and speaker labels; lowercase; truncate."""
    cleaned = _VTT_CUE_LINE_RE.sub("", str(text or ""))
    cleaned = _SPEAKER_LABEL_RE.sub("", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip().lower()
    return cleaned[:max_chars].rsplit(" ", 1)[0].strip() if len(cleaned) > max_chars else cleaned


def _tokenize(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text))


def _text_similarity_score(text_a: str, text_b: str) -> float:
    """Jaccard token overlap (0.4) + SequenceMatcher ratio (0.6). Returns 0.0–1.0."""
    a = _normalize_for_similarity(text_a)
    b = _normalize_for_similarity(text_b, max_chars=max(len(a), 1))
    if not a or not b:
        return 0.0
    tokens_a, tokens_b = _tokenize(a), _tokenize(b)
    if not tokens_a or not tokens_b:
        return 0.0
    jaccard = len(tokens_a & tokens_b) / max(len(tokens_a | tokens_b), 1)
    seq = SequenceMatcher(a=a, b=b).ratio()
    return round(jaccard * 0.4 + seq * 0.6, 3)
```

**Update `run_anchor_alignment()`:**

After the existing anchor-validation loop (which still runs as before), add a text-similarity block:

```python
# PRD §8.5: real text similarity when video transcript is available
video_transcript: str = job.get("_video_transcript_inline") or ""
uploaded_transcript: str = job.get("_transcript_text_inline") or transcript_text

consistency_method = "anchor_validity_proxy"

if has_media and video_transcript and uploaded_transcript:
    text_score = _text_similarity_score(video_transcript, uploaded_transcript)
    if text_score >= _CONSISTENCY_MATCH_THRESHOLD:
        verdict = "match"
    elif text_score <= _CONSISTENCY_MISMATCH_THRESHOLD:
        verdict = "suspected_mismatch"
    else:
        verdict = "inconclusive"
    similarity_score = text_score
    consistency_method = "text_similarity"
    # overwrite the anchor-ratio score computed above
```

Update `anchor_alignment_summary["consistency_method"]` to use the `consistency_method` variable (no longer hardcoded string).

**Keep `_consistency_score_from_anchors()` unchanged** — it still runs first and its output is overwritten if text similarity is available. This means the fallback (transcript-only jobs with no video) continues to work.

**Do not change:** `VideoAdapter`, `extraction.py`, `processing.py`, `reviewing.py`, `sipoc_validator.py`, migration files.

**Verification:**
```bash
cd backend
.venv/bin/pytest ../tests/unit/test_agents.py -v    # all pass including alignment tests
.venv/bin/pytest ../tests/ -v                        # full suite green
```

Add `test_text_similarity_score_match`, `test_text_similarity_score_mismatch`, `test_text_similarity_score_identical`, and `test_run_anchor_alignment_uses_text_similarity_when_video_transcript_present` in `tests/unit/test_agents.py`. The last test should monkeypatch `_video_transcript_inline` on the job dict and assert `consistency_method == "text_similarity"` in the summary.

Commit as: `feat: replace anchor-ratio consistency proxy with real text similarity`

---

## On Hold

| ID | Task | Reason |
|----|------|--------|
| DEPLOY-FIX2 (Part 2) | Switch workers to `WEBSITE_RUN_FROM_PACKAGE` | Deployment is currently working; deferred until prompt quality issues are resolved. Full task spec preserved below. |

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

**In the `build` job** — add these steps after the existing `Build zip` step and before the existing `upload-artifact` step for the zip:
```yaml
- uses: azure/login@v2
  with:
    creds: '${{ secrets.AZURE_CREDENTIALS }}'
- name: Upload worker zip to scratch blob and write package URL
  run: |
    az storage blob upload \
      --account-name ${{ vars.AZURE_STORAGE_ACCOUNT }} \
      --container-name scratch \
      --name worker-${{ github.sha }}.zip \
      --file worker.zip \
      --auth-mode login \
      --overwrite true
    expiry=$(date -u -d "+4 hours" +%Y-%m-%dT%H:%MZ 2>/dev/null || date -u -v+4H +%Y-%m-%dT%H:%MZ)
    sas=$(az storage blob generate-sas \
      --account-name ${{ vars.AZURE_STORAGE_ACCOUNT }} \
      --container-name scratch \
      --name worker-${{ github.sha }}.zip \
      --permissions r \
      --expiry "$expiry" \
      --auth-mode login \
      --as-user \
      -o tsv)
    account=${{ vars.AZURE_STORAGE_ACCOUNT }}
    echo "https://${account}.blob.core.windows.net/scratch/worker-${{ github.sha }}.zip?${sas}" > package-url.txt
- uses: actions/upload-artifact@v4
  with:
    name: package-url
    path: package-url.txt
```

**In each deploy job** — add a download step after `actions/download-artifact` (worker-zip) and before the configure step:
```yaml
- uses: actions/download-artifact@v4
  with:
    name: package-url
- name: Read package URL
  run: echo "PACKAGE_URL=$(cat package-url.txt)" >> $GITHUB_ENV
```

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
        WEBSITE_RUN_FROM_PACKAGE="$PACKAGE_URL"
    az webapp restart \
      --resource-group ${{ secrets.AZURE_RESOURCE_GROUP }} \
      --name ${{ secrets.AZURE_WORKER_EXTRACTING_NAME }}
```

Remove `azure/webapps-deploy@v3` entirely from all three deploy jobs. Remove `az webapp config set --startup-file` (already removed in Part 1). The `appsettings set` now consolidates config + package reference into a single control-plane operation.

**Pre-requisite — Storage Blob Data Reader for worker identities:**
The three worker managed identities currently have `Key Vault Secrets User` only (see `infra/dev-bootstrap.sh` line ~362). Add `Storage Blob Data Reader` on the storage account scope inside the same `for worker_role` loop, immediately after the KV role assignment:
```bash
az role assignment create \
  --assignee-object-id "$worker_principal_id" \
  --role "Storage Blob Data Reader" \
  --scope "/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RESOURCE_GROUP/providers/Microsoft.Storage/storageAccounts/$STORAGE_ACCOUNT" \
  --output none \
  || true
```

**Pre-requisite — GitHub secret:**
`AZURE_STORAGE_ACCOUNT` is not a credential — it is a resource name. Add it as a **GitHub Actions Variable** (Settings → Secrets and Variables → Actions → Variables tab), not a secret, so it is auditable. The value is the storage account name provisioned by `infra/dev-bootstrap.sh` — defaults to `pfcddevstorage` (formula: `$PROJECT$ENVIRONMENT storage` with no separator). Reference it in the workflow as `${{ vars.AZURE_STORAGE_ACCOUNT }}`. Document it in `REFERENCE.md` under a new "GitHub Variables" row (distinct from the secrets table).

No other new secrets are needed. The existing `AZURE_CREDENTIALS` service principal is reused.

**Pre-requisite — service principal needs blob write permission:**
The `build` job must upload the zip to the `scratch` container. This requires the service principal in `AZURE_CREDENTIALS` to have **`Storage Blob Data Contributor`** on the storage account. Currently `infra/dev-bootstrap.sh` only assigns this role to the signed-in user (line ~87).

`AZURE_CLIENT_ID` is already a repository secret (the service principal's client ID). Add an optional block inside `ensure_storage_account` that accepts `SP_CLIENT_ID` as an env var, looks up the object ID, and assigns the role:

```bash
# Grant SP blob write if SP_CLIENT_ID is provided (pass secrets.AZURE_CLIENT_ID when running from CI)
if [[ -n "${SP_CLIENT_ID:-}" ]]; then
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
```

When running the bootstrap locally: `SP_CLIENT_ID=<value of AZURE_CLIENT_ID secret> bash infra/dev-bootstrap.sh`. For local runs without the var set, the block is skipped harmlessly. No new secret is needed — `AZURE_CLIENT_ID` is already present in the repository.

**Pre-requisite — `WEBSITE_RUN_FROM_PACKAGE` note:**
When `WEBSITE_RUN_FROM_PACKAGE` is set to a URL, Azure mounts the zip read-only at `/home/site/wwwroot`. The app cannot write to that path. Verify workers do not write to the working directory at runtime (they use blob storage for exports and SQLite is not used in production — this should be fine, but confirm).

**Constraints:**
- Do not hardcode storage account names — use `${{ vars.AZURE_STORAGE_ACCOUNT }}`
- SAS token expiry must be long enough to cover deploy + verify steps (4 hours is safe)
- Pass the package URL between `build` and deploy jobs by writing it to a file (`package-url.txt`), uploading as an artifact (name: `package-url`), and downloading in each deploy job — the `GITHUB_ENV` approach only works within a single job
- Do not change `deploy-backend.yml` — this task is workers only

**Operator steps — before and after (do not skip):**

Before Codex starts:
1. Go to GitHub → Actions → "Deploy Workers" → ··· → **Disable workflow**. This prevents the half-complete workflow from firing on intermediate commits.

After Codex commits:
2. Go to GitHub → Actions → "Deploy Workers" → ··· → **Enable workflow**.
3. Add the GitHub Actions Variable: Settings → Secrets and Variables → Actions → **Variables** tab → New repository variable → Name: `AZURE_STORAGE_ACCOUNT`, Value: `pfcddevstorage`.
4. Run the updated `infra/dev-bootstrap.sh` with `SP_CLIENT_ID=<value of AZURE_CLIENT_ID secret>` to assign the `Storage Blob Data Contributor` role to the service principal on the storage account.
5. Trigger a manual run: GitHub → Actions → "Deploy Workers" → Run workflow → main.

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
| REVIEW-FLAGS-L1L2L3 | Three low-severity cleanup items from Phase 1 review | local changes (not committed) |

---

## Recently Closed

| ID | Task | Closed | Outcome |
|----|----- |--------|---------|
| PROC-PROMPT-FIX | Strengthen processing prompt so SIPOC anchors are reliably generated | 2026-04-13 | Approved — `_SIPOC_SCHEMA` concrete examples; 4 explicit anchor rules; `test_processing_agent_sipoc_rows_have_anchors` added; 243 tests pass |
| PROVIDER-FLEX | Add `PFCD_PROVIDER` env var; support direct OpenAI alongside Azure OpenAI | 2026-04-13 | Approved — `kernel_factory.py`, `extraction.py`, `processing.py`, `job_logic.py` updated; `REFERENCE.md` updated; 4 kernel factory tests added. L1 flag: `_provider_name()` duplicated in 3 modules — assign cleanup |
| VIDEO-TRANSCRIPTION | Wire real Whisper transcription into VideoAdapter | 2026-04-13 | Approved — `transcription.py` added; `VideoAdapter.normalize()` calls real Whisper; `_normalize_input()` merges video+uploaded content; `_video_transcript_inline` popped in both success and failure paths. L2 flag: `render_review_notes()` shows "pending" note even on transcription success |
| TEXT-SIMILARITY | Replace anchor-ratio consistency proxy with real text similarity | 2026-04-13 | Approved — Jaccard+SequenceMatcher in `alignment.py`; env-configurable thresholds; 4 new tests. L3 flag: anchor-ratio fallback branch still uses hardcoded thresholds instead of the configurable constants |
| DEPLOY-FIX2 (Part 2) | Switch workers to WEBSITE_RUN_FROM_PACKAGE | 2026-04-12 | Approved — `azure/webapps-deploy@v3` removed; `WEBSITE_RUN_FROM_PACKAGE` via blob SAS URL; SP blob role in bootstrap; worker identity blob reader added; one minor cosmetic flag (settle step log label) — non-blocking |
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
