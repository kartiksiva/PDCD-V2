# HANDOVER.md

Shared coordination board. Read and updated by both Claude and Codex at session start.

- **Claude** adds items to "Assigned to Codex" when assigning work; closes items after review.
- **Codex** moves items to "In Progress" when starting, then "Ready for Claude Review" when done.

---

## Assigned to Codex (not started)

| ID | Task | Notes |
|----|------|-------|

## In Progress

| ID | Task | Notes |
|----|------|-------|

---

### KEYFRAME-VISION — Keyframe extraction + multimodal LLM frame analysis

**Context:**
Phase 5 wired chunked Whisper transcription for audio-bearing videos. Phase 5b adds visual evidence from video frames. The PRD requires frame-derived evidence when audio is absent, and frame supplementation when audio is present. The extension point comment at `transcription.py:107` marks where keyframe extraction should hook in. VideoAdapter currently returns metadata-only evidence for no-audio videos; after this task it will return real frame descriptions.

**Cost guard:** 1 hour of video at 5-second intervals = 720 frames. Sending 720 individual LLM calls is unacceptable. Frames are batched: up to `_MAX_FRAMES_PER_CALL` (default 4) images per LLM call, capped at `_MAX_FRAMES_TOTAL` (default 40) frames per job. Both are env-configurable.

**Changes — 4 files:**

---

**1. `backend/app/agents/media_preprocessor.py` — add `extract_keyframes`**

Add one new public function after `split_audio_chunks`:

```python
def extract_keyframes(
    video_path: str,
    output_dir: str,
    sample_interval_sec: int = 5,
    max_frames: int = 40,
) -> list[tuple[str, float]]:
    """Extract keyframes from video_path at sample_interval_sec intervals.

    Returns list of (frame_jpg_path, timestamp_sec) sorted by timestamp.
    Returns [] if ffmpeg is unavailable or extraction fails.
    Capped at max_frames to control downstream LLM cost.
    """
```

Command: `ffmpeg -y -i {video_path} -vf "fps=1/{sample_interval_sec}" -q:v 3 -frames:v {max_frames} {output_dir}/frame_%04d.jpg`

- `-q:v 3` — good quality JPEG, reasonable file size
- `-frames:v {max_frames}` — hard cap enforced by ffmpeg itself
- Read back produced files (glob `frame_*.jpg`), sort by filename, compute `timestamp_sec = index * sample_interval_sec`
- Return `[]` on `FileNotFoundError`, non-zero exit, or any exception. Never raise.

---

**2. New `backend/app/agents/vision.py`**

Single public function. Uses httpx directly (same pattern as `transcription.py`) — no new dependency.

```python
"""Frame-level visual analysis using a vision-capable LLM."""
```

**Constants (all env-configurable):**
```python
_MAX_FRAMES_PER_CALL = int(os.environ.get("PFCD_VISION_FRAMES_PER_CALL", "4"))
_MAX_FRAMES_TOTAL    = int(os.environ.get("PFCD_VISION_MAX_FRAMES", "40"))
_OPENAI_VISION_MODEL = os.environ.get("OPENAI_VISION_MODEL", "gpt-4o-mini")
_AZURE_VISION_DEPLOYMENT = os.environ.get("AZURE_OPENAI_VISION_DEPLOYMENT", "")
```

**`analyze_frames(frames: list[tuple[str, float]], policy: dict) -> str`**

`frames` is a list of `(jpg_path, timestamp_sec)` from `extract_keyframes`.
`policy` is `frame_extraction_policy` from the job manifest.

Algorithm:
1. If `frames` is empty, return `""`.
2. Cap to `_MAX_FRAMES_TOTAL` (take first N).
3. Batch into groups of `_MAX_FRAMES_PER_CALL`.
4. For each batch: build an OpenAI chat completions request with `model`, a system prompt, and a user message containing one `text` content item (describing the timestamp range of this batch) plus one `image_url` item per frame (base64-encoded JPEG: `"data:image/jpeg;base64,{b64}"`).
5. Collect text responses, join with `"\n\n"`.
6. Wrap entire function in `try/except`; on any error log warning and return `""`. Never raise.

**System prompt:**
```
You are a process documentation assistant. For each video frame shown, describe:
1. What the user is doing (actions, clicks, navigation)
2. What application or screen is visible
3. Any visible text that identifies a process step, form field, or transaction

Be concise. Focus on process-relevant actions, not aesthetics.
Output one paragraph per frame, prefixed with the frame timestamp.
```

**Provider routing (private helpers):**

```python
def _call_vision_openai(messages: list[dict]) -> str:
    """POST to OpenAI chat completions with vision content."""
    api_key = os.environ["OPENAI_API_KEY"]
    response = httpx.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json={"model": _OPENAI_VISION_MODEL, "messages": messages, "max_tokens": 1024},
        timeout=60.0,
    )
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]

def _call_vision_azure(messages: list[dict]) -> str:
    """POST to Azure OpenAI chat completions with vision content."""
    from azure.identity import DefaultAzureCredential
    if not _AZURE_VISION_DEPLOYMENT:
        raise ValueError("AZURE_OPENAI_VISION_DEPLOYMENT is not set")
    endpoint = os.environ["AZURE_OPENAI_ENDPOINT"].rstrip("/")
    api_version = os.environ.get("AZURE_OPENAI_API_VERSION", "2024-10-21")
    url = f"{endpoint}/openai/deployments/{_AZURE_VISION_DEPLOYMENT}/chat/completions?api-version={api_version}"
    credential = DefaultAzureCredential()
    token = credential.get_token("https://cognitiveservices.azure.com/.default")
    response = httpx.post(
        url,
        headers={"Authorization": f"Bearer {token.token}"},
        json={"messages": messages, "max_tokens": 1024},
        timeout=60.0,
    )
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]
```

Use `_provider_name()` from `app.job_logic` to route between the two.

**Do not use** Semantic Kernel for vision calls — httpx direct (same pattern as transcription.py) keeps tests simple and avoids SK image API instability.

---

**3. `backend/app/agents/adapters/video.py` — wire frame analysis into `normalize()`**

Import at top:
```python
from app.agents.media_preprocessor import extract_keyframes
from app.agents.vision import analyze_frames
```

In `normalize()`, after the existing transcription block, add frame analysis. The updated logic:

```python
storage_key = video_meta.get("storage_key")
frame_policy = video_meta.get("frame_extraction_policy") or {}
interval = frame_policy.get("sample_interval_sec", 5)

# Step 1: transcription (existing — unchanged)
transcript_text: str = ""
if has_audio and storage_key:
    raw = transcribe_audio_blob(storage_key)
    if raw and not raw.startswith("[transcription"):
        transcript_text = raw
        job["_video_transcript_inline"] = raw

# Step 2: keyframe visual analysis (new)
frame_descriptions: str = ""
if storage_key and is_ffmpeg_available():
    import tempfile
    tmp_dir = tempfile.mkdtemp(prefix="pfcd_frames_")
    try:
        frames = extract_keyframes(storage_key, tmp_dir, interval)
        if frames:
            frame_descriptions = analyze_frames(frames, frame_policy)
            if frame_descriptions:
                job["_frame_descriptions_inline"] = frame_descriptions
    finally:
        import shutil
        shutil.rmtree(tmp_dir, ignore_errors=True)

# Step 3: build EvidenceObject from available content
if transcript_text or frame_descriptions:
    parts = []
    if transcript_text:
        parts.append(f"AUDIO TRANSCRIPT:\n{transcript_text}")
    if frame_descriptions:
        parts.append(f"FRAME ANALYSIS:\n{frame_descriptions}")
    content_text = "\n\n".join(parts)
    anchors = [
        f"{_format_seconds(s)}-{_format_seconds(e)}"
        for s, e in parse_vtt_cues(transcript_text)
    ] if transcript_text else []
    confidence = 0.90 if (transcript_text and frame_descriptions) else 0.85
    return EvidenceObject(
        source_type="video", document_type="video",
        content_text=content_text, anchors=anchors,
        confidence=confidence,
        metadata={
            "has_audio": has_audio,
            "frame_policy": frame_policy,
            "duration_hint_sec": manifest.get("duration_hint_sec"),
            "storage_key": storage_key,
            "has_frame_analysis": bool(frame_descriptions),
        },
    )
```

**Ephemeral field:** `_frame_descriptions_inline` must be popped before job persistence — document in the module docstring alongside the existing `_video_transcript_inline` note.

**Worker cleanup:** In `backend/app/workers/runner.py`, wherever `_video_transcript_inline` is popped, also pop `_frame_descriptions_inline`.

**Do not change:** the metadata-only fallback path at the bottom of `normalize()` — it still runs when `storage_key` is absent.

Also update `render_review_notes()`: if `evidence_obj.metadata.get("has_frame_analysis")` is True, append `"Frame-level visual analysis complete."` instead of the existing pending note.

---

**4. `tests/unit/`**

**`tests/unit/test_media_preprocessor.py` — add two tests:**
- `test_extract_keyframes_returns_empty_when_ffmpeg_unavailable` — monkeypatch `subprocess.run` to raise `FileNotFoundError`; assert returns `[]`
- `test_extract_keyframes_returns_list_of_tuples` — monkeypatch `subprocess.run` to succeed (returncode=0) and glob to return `["frame_0001.jpg", "frame_0002.jpg"]`; assert returns `[("frame_0001.jpg", 0), ("frame_0002.jpg", 5)]` (with default interval=5)

**New `tests/unit/test_vision.py`:**
- `test_analyze_frames_returns_empty_on_empty_input` — `analyze_frames([], {})` returns `""`
- `test_analyze_frames_calls_openai_provider` — monkeypatch `_provider_name` to `"openai"`, `_call_vision_openai` to return `"Frame 1: User opens SAP."`; assert result contains that string
- `test_analyze_frames_returns_empty_on_exception` — monkeypatch `_call_vision_openai` to raise `httpx.HTTPError`; assert returns `""`
- `test_analyze_frames_batches_frames` — monkeypatch `_MAX_FRAMES_PER_CALL=2`, supply 5 frames, monkeypatch `_call_vision_openai` to return `"ok"`; assert `_call_vision_openai` called 3 times (ceil(5/2))

**`tests/unit/test_adapters.py` — add one test:**
- `test_video_adapter_normalize_with_frame_analysis` — monkeypatch `transcribe_audio_blob` to return stub (no audio path), `is_ffmpeg_available` to True, `extract_keyframes` to return `[("/tmp/f.jpg", 0.0)]`, `analyze_frames` to return `"Frame: user opens SAP."`; assert `ev.content_text` contains `"FRAME ANALYSIS"` and `job["_frame_descriptions_inline"]` is set.

**Do not change:** `test_agents.py`, `test_worker.py`, `test_export_builder.py`, migration files, `sipoc_validator.py`, `reviewing.py`, `processing.py`.

---

**New env vars — document in `REFERENCE.md`:**

```
PFCD_VISION_FRAMES_PER_CALL=4        # images per LLM call (cost control)
PFCD_VISION_MAX_FRAMES=40            # max frames extracted per job (cost cap)
OPENAI_VISION_MODEL=gpt-4o-mini      # vision model for PFCD_PROVIDER=openai
AZURE_OPENAI_VISION_DEPLOYMENT=      # Azure deployment name for vision (required on azure path)
```

---

**Verification:**
```bash
cd backend
.venv/bin/pytest ../tests/unit/test_media_preprocessor.py -v   # includes new keyframe tests
.venv/bin/pytest ../tests/unit/test_vision.py -v               # all vision tests pass
.venv/bin/pytest ../tests/unit/test_adapters.py -v             # includes new frame-analysis adapter test
.venv/bin/pytest ../tests/ -q                                   # full suite green
```

Commit as: `feat: add keyframe extraction and multimodal frame analysis (Phase 5b)`

---

---

### FRONTEND-COMPLETE — Phase 6 Frontend Integration

**Context:**
All backend phases are complete (260 tests passing). The frontend components exist and are well-structured, but have four critical gaps that must be fixed before the app is usable end-to-end:

1. `api.js` never sends `X-API-Key` → all requests silently fail when `PFCD_API_KEY` is configured
2. `DraftReview` has no save-draft call → `finalizeJob` always returns 409 (backend enforces `user_saved_draft=True` via the PUT draft endpoint)
3. No job list/history → jobs are unreachable after page refresh
4. Vite dev server has no `/dev` proxy → the "Simulate → needs_review" dev button is broken locally

**Changes — 7 files modified, 1 new frontend file, 1 new test file:**

---

**1. `frontend/src/api.js` — 3 targeted additions**

**a) `X-API-Key` header in `_fetch`:**

Replace the existing `_fetch` header line so it reads the key from the env:
```js
headers: {
  'Content-Type': 'application/json',
  ...(import.meta.env.VITE_API_KEY ? { 'X-API-Key': import.meta.env.VITE_API_KEY } : {}),
  ...options.headers,
},
```

**b) Add `saveDraft` function** (after `finalizeJob`):
```js
export async function saveDraft(jobId, draft) {
  const res = await _fetch(`/jobs/${jobId}/draft`, {
    method: 'PUT',
    body: JSON.stringify({ pdd: draft.pdd, sipoc: draft.sipoc, assumptions: draft.assumptions }),
  })
  return res.json()
}
```

**c) Add `listJobs` function** (after `saveDraft`):
```js
export async function listJobs() {
  const res = await _fetch('/jobs')
  return res.json()
}
```

---

**2. `frontend/vite.config.js` — add `/dev` proxy**

Add `/dev` alongside the existing `/api` proxy so devSimulate works locally:
```js
server: {
  proxy: {
    '/api': 'http://localhost:8000',
    '/dev': 'http://localhost:8000',
  },
},
```

---

**3. `frontend/src/components/DraftReview.jsx` — auto-save before finalize**

Import `saveDraft` at the top:
```js
import { finalizeJob, saveDraft } from '../api'
```

In `handleFinalize`, call `saveDraft` first, then `finalizeJob`:
```js
async function handleFinalize() {
  setError(null)
  setLoading(true)
  try {
    await saveDraft(job.job_id, draft)
    const data = await finalizeJob(job.job_id)
    onFinalized(data)
  } catch (err) {
    const detail = err.data?.detail
    setError(typeof detail === 'string' ? detail : detail?.message ?? err.message)
  } finally {
    setLoading(false)
  }
}
```

No other changes to DraftReview.

---

**4. `backend/app/repository.py` — add `list_jobs` method**

Add after `get_job`:
```python
def list_jobs(self, limit: int = 50) -> list[dict]:
    """Return lightweight job summaries, most recent first, excluding deleted."""
    with session_scope() as session:
        rows = session.execute(
            select(Job)
            .where(Job.deleted_at.is_(None))
            .order_by(Job.created_at.desc())
            .limit(limit)
        ).scalars().all()
        return [
            {
                "job_id": r.job_id,
                "status": r.status,
                "created_at": self._to_iso(r.created_at),
                "updated_at": self._to_iso(r.updated_at),
                "profile_requested": r.profile_requested,
                "has_video": r.has_video,
                "has_audio": r.has_audio,
                "has_transcript": r.has_transcript,
                "current_phase": r.current_phase,
            }
            for r in rows
        ]
```

---

**5. `backend/app/main.py` — add `GET /api/jobs` endpoint**

Add after the `POST /jobs` route (after `@api_router.post("/jobs", status_code=201)` block, around line 205):
```python
@api_router.get("/jobs")
async def list_jobs(limit: int = 50) -> List[Dict[str, Any]]:
    return await anyio.to_thread.run_sync(lambda: repo.list_jobs(limit=min(limit, 200)))
```

---

**6. New `frontend/src/components/JobList.jsx`**

Shows recent jobs in a table. Clicking a row fetches the full job and calls `onSelectJob(job)`.

```jsx
import React, { useEffect, useState } from 'react'
import { listJobs, getJob } from '../api'

const STATUS_STYLES = {
  completed:    'bg-green-100 text-green-800',
  needs_review: 'bg-amber-100 text-amber-800',
  failed:       'bg-red-100 text-red-800',
  processing:   'bg-indigo-100 text-indigo-700',
  queued:       'bg-gray-100 text-gray-600',
}

export default function JobList({ onSelectJob, onNewJob }) {
  const [jobs, setJobs] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [selecting, setSelecting] = useState(null)

  useEffect(() => {
    listJobs()
      .then(data => setJobs(data.jobs ?? data))
      .catch(err => setError(err.message))
      .finally(() => setLoading(false))
  }, [])

  async function handleSelect(jobId) {
    setSelecting(jobId)
    try {
      const full = await getJob(jobId)
      onSelectJob(full)
    } catch (err) {
      setError(err.message)
    } finally {
      setSelecting(null)
    }
  }

  if (loading) return <div className="text-center text-gray-500 py-12">Loading jobs…</div>

  return (
    <div className="bg-white rounded-xl shadow p-6 space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-semibold">Recent Jobs</h2>
        <button
          onClick={onNewJob}
          className="bg-indigo-600 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-indigo-700"
        >
          + New Job
        </button>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-300 text-red-700 rounded p-3 text-sm">{error}</div>
      )}

      {jobs.length === 0 && !error && (
        <div className="text-center py-12 text-gray-400">
          <p className="text-sm">No jobs yet.</p>
          <button onClick={onNewJob} className="mt-3 text-indigo-600 text-sm hover:underline">Create your first job</button>
        </div>
      )}

      {jobs.length > 0 && (
        <div className="overflow-x-auto">
          <table className="min-w-full text-sm">
            <thead>
              <tr className="border-b text-left text-xs text-gray-500 uppercase tracking-wide">
                <th className="pb-2 pr-4">Job ID</th>
                <th className="pb-2 pr-4">Status</th>
                <th className="pb-2 pr-4">Sources</th>
                <th className="pb-2 pr-4">Profile</th>
                <th className="pb-2">Created</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {jobs.map(job => (
                <tr
                  key={job.job_id}
                  onClick={() => handleSelect(job.job_id)}
                  className="hover:bg-gray-50 cursor-pointer transition-colors"
                >
                  <td className="py-2 pr-4 font-mono text-xs text-gray-600">
                    {selecting === job.job_id ? (
                      <span className="text-indigo-500 animate-pulse">Loading…</span>
                    ) : (
                      job.job_id.slice(0, 8) + '…'
                    )}
                  </td>
                  <td className="py-2 pr-4">
                    <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${STATUS_STYLES[job.status] ?? 'bg-gray-100 text-gray-600'}`}>
                      {job.status}
                    </span>
                  </td>
                  <td className="py-2 pr-4">
                    <div className="flex gap-1">
                      {job.has_video    && <span className="px-1.5 py-0.5 bg-purple-100 text-purple-700 rounded text-xs">video</span>}
                      {job.has_audio    && <span className="px-1.5 py-0.5 bg-blue-100 text-blue-700 rounded text-xs">audio</span>}
                      {job.has_transcript && <span className="px-1.5 py-0.5 bg-teal-100 text-teal-700 rounded text-xs">transcript</span>}
                    </div>
                  </td>
                  <td className="py-2 pr-4 text-gray-600 capitalize">{job.profile_requested ?? '—'}</td>
                  <td className="py-2 text-gray-500 text-xs font-mono">
                    {job.created_at ? new Date(job.created_at).toLocaleString() : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
```

---

**7. `frontend/src/App.jsx` — add list view as default + routing from job list**

Full replacement:
```jsx
import React, { useState } from 'react'
import CreateJob from './components/CreateJob'
import JobStatus from './components/JobStatus'
import DraftReview from './components/DraftReview'
import ExportLinks from './components/ExportLinks'
import JobList from './components/JobList'

export default function App() {
  const [view, setView] = useState('list')
  const [jobId, setJobId] = useState(null)
  const [job, setJob] = useState(null)

  function onJobCreated(id) { setJobId(id); setView('status') }
  function onJobReady(jobData) { setJob(jobData); setView('review') }
  function onFinalized(jobData) { setJob(jobData); setView('exports') }
  function onNewJob() { setJobId(null); setJob(null); setView('create') }

  function onSelectJob(fullJob) {
    setJob(fullJob)
    setJobId(fullJob.job_id)
    const s = fullJob.status
    if (s === 'completed') {
      setView('exports')
    } else if (s === 'needs_review') {
      setView('review')
    } else {
      setView('status')
    }
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <nav className="bg-white border-b px-6 py-3 flex items-center gap-4">
        <button
          onClick={() => { setView('list'); setJobId(null); setJob(null) }}
          className="font-semibold text-indigo-700 text-lg hover:text-indigo-800"
        >
          PFCD
        </button>
        {jobId && <span className="text-xs text-gray-400 font-mono">{jobId}</span>}
        {view !== 'list' && (
          <button
            onClick={() => { setView('list'); setJobId(null); setJob(null) }}
            className="ml-auto text-sm text-indigo-600 hover:underline"
          >
            ← Jobs
          </button>
        )}
      </nav>
      <main className="max-w-4xl mx-auto py-8 px-4">
        {view === 'list'    && <JobList onSelectJob={onSelectJob} onNewJob={onNewJob} />}
        {view === 'create'  && <CreateJob onCreated={onJobCreated} />}
        {view === 'status'  && <JobStatus jobId={jobId} onReady={onJobReady} />}
        {view === 'review'  && <DraftReview job={job} onFinalized={onFinalized} />}
        {view === 'exports' && <ExportLinks job={job} />}
      </main>
    </div>
  )
}
```

---

**8. `tests/unit/test_job_list.py` — 4 tests**

Use the same SQLite in-memory pattern as existing unit tests (`tmp_path` fixture).

- `test_list_jobs_empty` — fresh DB → `repo.list_jobs()` returns `[]`
- `test_list_jobs_returns_rows_most_recent_first` — upsert 2 jobs with different `created_at` values; assert list returns them in descending order
- `test_list_jobs_excludes_deleted` — upsert job with `deleted_at` set to a timestamp; assert not returned in list
- `test_list_jobs_endpoint_returns_200` — use FastAPI `TestClient`, call `GET /api/jobs`; assert 200 and `isinstance(response.json(), list)`

**Do not change:** existing test files, `reviewing.py`, `processing.py`, `extraction.py`, `sipoc_validator.py`, migration files.

---

**New env var — document in `REFERENCE.md`:**
```
VITE_API_KEY=   # Client-side API key for X-API-Key header (set in .env.local for dev)
```

---

**Verification:**
```bash
cd backend
.venv/bin/pytest ../tests/unit/test_job_list.py -v      # all 4 new tests pass
.venv/bin/pytest ../tests/ -q                            # full suite green (264+ tests)
```

Also verify manually:
- `cd frontend && npm run dev` — app loads to job list
- Submit a job → status → (simulate if needed) → review → finalize → exports
- Reload page → job still visible in list; click row → routes to correct view

Commit as: `feat: Phase 6 frontend integration — job list, save-draft fix, API key header`

---

## On Hold

| ID | Task | Reason |
|----|------|--------|
| DEPLOY-FIX2 (Part 2) | Switch workers to `WEBSITE_RUN_FROM_PACKAGE` | Deployment is currently working; deferred. Full spec below. |

### DEPLOY-FIX2 (Part 2) — Switch workers to `WEBSITE_RUN_FROM_PACKAGE`

Restructure so there is no `azure/webapps-deploy@v3` step at all. The zip is mounted from blob storage; Kudu OneDeploy is never called.

**In the `build` job** — add these steps after the existing `Build zip` step:
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
      --permissions r --expiry "$expiry" --auth-mode login --as-user -o tsv)
    account=${{ vars.AZURE_STORAGE_ACCOUNT }}
    echo "https://${account}.blob.core.windows.net/scratch/worker-${{ github.sha }}.zip?${sas}" > package-url.txt
- uses: actions/upload-artifact@v4
  with:
    name: package-url
    path: package-url.txt
```

**In each deploy job** — replace the deploy step with:
```yaml
- name: Deploy worker (WEBSITE_RUN_FROM_PACKAGE)
  run: |
    az webapp config appsettings set \
      --resource-group ${{ secrets.AZURE_RESOURCE_GROUP }} \
      --name ${{ secrets.AZURE_WORKER_<ROLE>_NAME }} \
      --settings PFCD_WORKER_ROLE=<role> \
        WEBSITE_RUN_FROM_PACKAGE="$PACKAGE_URL"
    az webapp restart \
      --resource-group ${{ secrets.AZURE_RESOURCE_GROUP }} \
      --name ${{ secrets.AZURE_WORKER_<ROLE>_NAME }}
```

Remove `azure/webapps-deploy@v3` from all three deploy jobs.

**Pre-requisites:**
- Worker managed identities need `Storage Blob Data Reader` on the storage account.
- Service principal in `AZURE_CREDENTIALS` needs `Storage Blob Data Contributor` (add optional SP block in `ensure_storage_account` gated on `SP_CLIENT_ID` env var).
- Add `AZURE_STORAGE_ACCOUNT` as a GitHub Actions **Variable** (not secret).

**Operator steps:**
1. Disable "Deploy Workers" workflow before Codex starts.
2. Re-enable after commit.
3. Add GitHub Variable `AZURE_STORAGE_ACCOUNT=pfcddevstorage`.
4. Run `SP_CLIENT_ID=<AZURE_CLIENT_ID> bash infra/dev-bootstrap.sh` to assign SP blob role.
5. Trigger manual run to validate.

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
