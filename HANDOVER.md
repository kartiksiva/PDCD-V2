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

### DRAFT-EDIT — Editable PDD/SIPOC + re-review on save

**Context:**
`DraftReview.jsx` is read-only. When the reviewing agent emits a `blocker` flag (e.g. `pdd_incomplete` for a missing PDD field, or `sipoc_no_anchor` for missing anchors), the Finalize button is disabled and the user has no way to fix the problem. PRD §6 requires "User edits/saves draft"; PRD §8.9 requires blockers to be user-resolvable before finalize. This task makes PDD fields and SIPOC rows inline-editable and ensures that after a save the reviewing quality gate is re-evaluated against the updated content.

**Changes — 3 files:**

---

**1. `backend/app/main.py` — re-run reviewing in `update_draft`, extend response**

After `await _repo_upsert_job(job_id, job)` and before the `return`, add:

```python
# Re-run the pure-Python reviewing gate so flags reflect the edited draft.
from app.agents.reviewing import run_reviewing
run_reviewing(job, {})
await _repo_upsert_job(job_id, job)
```

Change the `return` statement to also include `review_notes` and `agent_review`:

```python
return {
    "job_id": job_id,
    "status": job["status"],
    "draft": job["draft"],
    "review_notes": job["review_notes"],
    "agent_review": job["agent_review"],
    "speaker_resolutions": job["speaker_resolutions"],
    "user_saved_draft": True,
}
```

`run_reviewing` is pure-Python (no LLM), so this is synchronous and fast (< 5 ms). No timeout risk.

---

**2. `frontend/src/components/DraftReview.jsx` — editable fields + debounced auto-save**

**State additions at top of `DraftReview` component:**
```jsx
const [editedDraft, setEditedDraft] = useState(() => job?.draft ?? {})
const [liveFlags, setLiveFlags]     = useState(() => job?.review_notes?.flags ?? [])
const [saveState, setSaveState]     = useState('idle') // 'idle' | 'saving' | 'saved' | 'error'
const saveTimer = useRef(null)
```

Sync on prop change:
```jsx
useEffect(() => {
  setEditedDraft(job?.draft ?? {})
  setLiveFlags(job?.review_notes?.flags ?? [])
}, [job?.job_id])
```

**Debounced auto-save helper:**
```jsx
function scheduleSave(nextDraft) {
  clearTimeout(saveTimer.current)
  setSaveState('saving')
  saveTimer.current = setTimeout(async () => {
    try {
      const result = await saveDraft(job.job_id, nextDraft)
      setLiveFlags(result.review_notes?.flags ?? liveFlags)
      setSaveState('saved')
    } catch {
      setSaveState('error')
    }
  }, 1500)
}
```

**Field update helpers:**
```jsx
function setPddField(key, value) {
  const next = { ...editedDraft, pdd: { ...(editedDraft.pdd ?? {}), [key]: value } }
  setEditedDraft(next)
  scheduleSave(next)
}

function setSipocRow(idx, field, value) {
  const rows = [...(editedDraft.sipoc ?? [])]
  rows[idx] = { ...rows[idx], [field]: value }
  const next = { ...editedDraft, sipoc: rows }
  setEditedDraft(next)
  scheduleSave(next)
}
```

**Replace `PddSection` with `EditablePddSection`** — a new private component inside the same file. For all PDD keys except `steps` (which stays read-only), render:
- A small label showing the field name
- A `<textarea>` or `<input>` depending on value type
- For array fields (`roles`, `systems`): display as comma-separated text input, parse back to array on save

```jsx
const _PDD_STRING_KEYS = ['purpose','scope','triggers','preconditions','business_rules','exceptions','outputs','metrics','risks']
const _PDD_LIST_KEYS   = ['roles','systems']

function EditablePddSection({ pdd, onChange }) {
  const pddObj = pdd ?? {}
  return (
    <div className="space-y-3">
      {_PDD_STRING_KEYS.map(key => (
        <div key={key}>
          <label className="text-xs font-semibold text-gray-500 uppercase tracking-wide block mb-1">{key.replace(/_/g,' ')}</label>
          <textarea
            className="w-full border rounded p-2 text-sm resize-y min-h-[48px] focus:ring-1 focus:ring-indigo-400 outline-none"
            value={pddObj[key] ?? ''}
            onChange={e => onChange(key, e.target.value)}
            placeholder={`Enter ${key.replace(/_/g,' ')}…`}
          />
        </div>
      ))}
      {_PDD_LIST_KEYS.map(key => (
        <div key={key}>
          <label className="text-xs font-semibold text-gray-500 uppercase tracking-wide block mb-1">{key.replace(/_/g,' ')} (comma-separated)</label>
          <input
            type="text"
            className="w-full border rounded p-2 text-sm focus:ring-1 focus:ring-indigo-400 outline-none"
            value={Array.isArray(pddObj[key]) ? pddObj[key].join(', ') : (pddObj[key] ?? '')}
            onChange={e => onChange(key, e.target.value.split(',').map(s => s.trim()).filter(Boolean))}
            placeholder={`e.g. Analyst, Manager`}
          />
        </div>
      ))}
      {/* Steps remain read-only */}
      {(pddObj.steps ?? []).length > 0 && (
        <div>
          <h4 className="text-sm font-semibold text-gray-700 mb-2">Process Steps (read-only)</h4>
          <ol className="space-y-2">
            {(pddObj.steps ?? []).map((step, idx) => (
              <li key={idx} className="bg-gray-50 rounded p-3 text-sm">
                <div className="flex items-start gap-2">
                  <span className="flex-shrink-0 w-5 h-5 rounded-full bg-indigo-100 text-indigo-700 text-xs font-bold flex items-center justify-center">{idx+1}</span>
                  <div>
                    <p className="font-medium">{step.summary ?? step.id}</p>
                    <div className="flex flex-wrap gap-3 mt-1 text-xs text-gray-500">
                      {step.actor && <span>Actor: <strong>{step.actor}</strong></span>}
                      {step.system && <span>System: <strong>{step.system}</strong></span>}
                      {step.source_anchor && <span className="font-mono">@ {step.source_anchor}</span>}
                    </div>
                  </div>
                </div>
              </li>
            ))}
          </ol>
        </div>
      )}
    </div>
  )
}
```

**Replace `SipocTable` call with inline editable table.** Keep `SipocTable.jsx` unchanged for read-only uses elsewhere. Inline the editable version directly in `DraftReview`:

```jsx
function EditableSipocTable({ sipoc, onRowChange }) {
  if (!sipoc || sipoc.length === 0) return <p className="text-sm text-gray-400 italic">No SIPOC rows.</p>
  const EDITABLE = ['supplier','input','process_step','output','customer','source_anchor']
  return (
    <div className="overflow-x-auto">
      <table className="min-w-full text-sm border-collapse">
        <thead>
          <tr className="bg-indigo-50">
            {[...EDITABLE, 'step_anchor', 'anchor_missing_reason'].map(h => (
              <th key={h} className="border border-indigo-100 px-2 py-1 text-left text-xs font-semibold text-indigo-700 whitespace-nowrap">
                {h.replace(/_/g,' ')}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sipoc.map((row, idx) => (
            <tr key={idx} className={idx % 2 === 0 ? 'bg-white' : 'bg-gray-50'}>
              {EDITABLE.map(field => (
                <td key={field} className="border border-gray-200 px-1 py-1">
                  <input
                    type="text"
                    className="w-full bg-transparent text-sm outline-none focus:ring-1 focus:ring-indigo-300 rounded px-1"
                    value={row[field] ?? ''}
                    onChange={e => onRowChange(idx, field, e.target.value)}
                  />
                </td>
              ))}
              <td className="border border-gray-200 px-1 py-1">
                <input
                  type="text"
                  className="w-full bg-transparent text-sm outline-none focus:ring-1 focus:ring-indigo-300 rounded px-1 font-mono"
                  value={Array.isArray(row.step_anchor) ? row.step_anchor.join(', ') : (row.step_anchor ?? '')}
                  onChange={e => onRowChange(idx, 'step_anchor', e.target.value.split(',').map(s=>s.trim()).filter(Boolean))}
                  placeholder="ev-01, ev-02"
                />
              </td>
              <td className="border border-gray-200 px-1 py-1">
                <input
                  type="text"
                  className="w-full bg-transparent text-sm outline-none focus:ring-1 focus:ring-indigo-300 rounded px-1 italic text-gray-400"
                  value={row.anchor_missing_reason ?? ''}
                  onChange={e => onRowChange(idx, 'anchor_missing_reason', e.target.value)}
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
```

**Render body changes:**
- Replace `<PddSection pdd={pdd} />` with `<EditablePddSection pdd={editedDraft.pdd} onChange={setPddField} />`
- Replace `<SipocTable sipoc={sipoc} />` with `<EditableSipocTable sipoc={editedDraft.sipoc} onRowChange={setSipocRow} />`
- Replace `<FlagPanel flags={flags} />` with `<FlagPanel flags={liveFlags} />`
- Replace `blockers` computation with `const blockers = liveFlags.filter(f => f.severity?.toLowerCase() === 'blocker')`
- Add save state indicator below flags panel:
```jsx
{saveState === 'saving' && <p className="text-xs text-gray-400 animate-pulse">Saving…</p>}
{saveState === 'saved'  && <p className="text-xs text-green-600">Draft saved.</p>}
{saveState === 'error'  && <p className="text-xs text-red-500">Save failed — changes not persisted.</p>}
```
- `handleFinalize` uses `editedDraft`:
```jsx
await saveDraft(job.job_id, editedDraft)
const data = await finalizeJob(job.job_id)
```

---

**3. `tests/unit/test_draft_edit.py` (new) — 3 tests**

Use the `TestClient`/monkeypatch pattern from other unit tests (reload main with SQLite tmp DB, no API key).

- `test_update_draft_response_includes_review_notes` — POST a job, simulate to `needs_review`, PUT /draft with valid pdd+sipoc; assert response contains `review_notes` and `agent_review` keys.
- `test_update_draft_re_review_clears_pdd_blocker` — Insert a job whose draft has `pdd.purpose = None`; PUT /draft with `pdd.purpose = "Test Purpose"` (all other required keys present); assert response `review_notes.flags` contains no flag with `code == "pdd_incomplete"`.
- `test_update_draft_re_review_triggers_pdd_blocker` — Insert a job with a complete draft; PUT /draft with `pdd.purpose = ""` (empty string); assert response `review_notes.flags` contains a flag with `code == "pdd_incomplete"` and `severity == "blocker"`.

**Do not change:** `SipocTable.jsx` (still used in `JobList` context), existing test files.

---

**Verification:**
```bash
cd backend && .venv/bin/pytest ../tests/unit/test_draft_edit.py -v
.venv/bin/pytest ../tests/ -q   # full suite green
```

Also test manually: start dev server + frontend, submit a job, simulate, open DraftReview — verify fields are editable, saving shows "Draft saved.", flags update after editing.

Commit as: `feat: editable PDD/SIPOC in DraftReview with re-review on save (PRD §8.9)`

---

### SPEAKER-RESOLVE — Speaker resolution UI + teams_metadata in extraction

**Context:**
PRD §8.1 explicitly requires: "Review UI must allow manual resolution of `Unknown Speaker` to existing role/team participants before finalize." The backend already has `speaker_resolutions` in the DB schema and `PUT /draft` accepts it. The reviewing agent emits an `unknown_speaker` warning when `"Unknown" in speakers_detected`. Two gaps: (1) the extraction prompt doesn't use `teams_metadata.transcript_speaker_map` to pre-assign speakers, so "Unknown" fires more than necessary; (2) the DraftReview UI never surfaces speakers or provides resolution inputs. This task fixes both.

**Changes — 4 files:**

---

**1. `backend/app/agents/extraction.py` — inject speaker map into extraction prompt**

In `_USER_PROMPT_TEMPLATE`, add a conditional speaker map section. Modify `run_extraction` (or the function that builds the user content) to inject the map when present.

Add a private helper after the template:

```python
def _build_speaker_hint(job: Dict[str, Any]) -> str:
    """Return a speaker-hint block from teams_metadata.transcript_speaker_map, or ''."""
    teams = job.get("teams_metadata") or {}
    speaker_map = teams.get("transcript_speaker_map") or {}
    if not speaker_map:
        return ""
    lines = "\n".join(f"  - {sid}: {name}" for sid, name in speaker_map.items())
    return f"\nKnown speaker identities (use these for actor assignment):\n{lines}\n"
```

In the function that constructs the user prompt content (where `_USER_PROMPT_TEMPLATE.format(transcript_text=...)` is called), append the speaker hint:

```python
speaker_hint = _build_speaker_hint(job)
user_content = _USER_PROMPT_TEMPLATE.format(transcript_text=content_text) + speaker_hint
```

Find the exact call site — it's in `run_extraction` where `_USER_PROMPT_TEMPLATE` is formatted. Replace the `.format(transcript_text=content_text)` call with the above two lines.

---

**2. `frontend/src/api.js` — include `speaker_resolutions` in `saveDraft`**

Change the `saveDraft` signature and body to accept an optional `speakerResolutions` argument:

```js
export async function saveDraft(jobId, draft, speakerResolutions = null) {
  const body = { pdd: draft.pdd, sipoc: draft.sipoc, assumptions: draft.assumptions }
  if (speakerResolutions !== null) body.speaker_resolutions = speakerResolutions
  const res = await _fetch(`/jobs/${jobId}/draft`, {
    method: 'PUT',
    body: JSON.stringify(body),
  })
  return res.json()
}
```

---

**3. `frontend/src/components/DraftReview.jsx` — add `SpeakerResolutionPanel`**

Add a new private component at the top of the file (before `DraftReview`):

```jsx
const _UNKNOWN_PATTERN = /unknown/i

function SpeakerResolutionPanel({ speakers, resolutions, onChange }) {
  const unknown = (speakers ?? []).filter(s => _UNKNOWN_PATTERN.test(s))
  if (unknown.length === 0) return null
  return (
    <div className="rounded-lg border border-amber-200 bg-amber-50 p-4 space-y-3">
      <p className="text-sm font-medium text-amber-800">
        {unknown.length} unknown speaker{unknown.length > 1 ? 's' : ''} — assign roles before finalizing.
      </p>
      {unknown.map(speaker => (
        <div key={speaker} className="flex items-center gap-3">
          <span className="text-sm text-amber-700 font-mono flex-shrink-0 w-32 truncate" title={speaker}>{speaker}</span>
          <input
            type="text"
            placeholder="e.g. Process Analyst, Manager"
            value={resolutions?.[speaker] ?? ''}
            onChange={e => onChange({ ...(resolutions ?? {}), [speaker]: e.target.value })}
            className="flex-1 border rounded px-2 py-1 text-sm focus:ring-1 focus:ring-indigo-400 outline-none"
          />
        </div>
      ))}
    </div>
  )
}
```

In the `DraftReview` component body, add:
```jsx
const [speakerResolutions, setSpeakerResolutions] = useState(() => job?.speaker_resolutions ?? {})
const detectedSpeakers = (job?.extracted_evidence ?? job?.agent_signals ?? {})?.speakers_detected
  ?? []
```

Add a `scheduleResolutionSave` that calls `scheduleSave(editedDraft, speakerResolutions)` — or modify `scheduleSave` to always pass the current `speakerResolutions`. The simplest: adjust `scheduleSave` to take optional speaker resolutions, defaulting to current state:

```jsx
function scheduleSave(nextDraft, nextResolutions) {
  clearTimeout(saveTimer.current)
  setSaveState('saving')
  saveTimer.current = setTimeout(async () => {
    try {
      const result = await saveDraft(job.job_id, nextDraft, nextResolutions ?? speakerResolutions)
      setLiveFlags(result.review_notes?.flags ?? liveFlags)
      setSaveState('saved')
    } catch {
      setSaveState('error')
    }
  }, 1500)
}
```

Render the `SpeakerResolutionPanel` after `FlagPanel` in the review card:
```jsx
<SpeakerResolutionPanel
  speakers={detectedSpeakers}
  resolutions={speakerResolutions}
  onChange={res => { setSpeakerResolutions(res); scheduleSave(editedDraft, res) }}
/>
```

Update `handleFinalize` to pass `speakerResolutions`:
```jsx
await saveDraft(job.job_id, editedDraft, speakerResolutions)
```

**Note:** `speakers_detected` is in `job.extracted_evidence.speakers_detected` (set by the extraction agent). If not present, the panel is hidden. This is correct — it only appears when the pipeline ran and found unknown speakers.

---

**4. `tests/unit/test_speaker_resolve.py` (new) — 2 tests (backend only)**

- `test_extraction_prompt_includes_speaker_map_when_teams_metadata_present` — build a job dict with `teams_metadata.transcript_speaker_map = {"spk_001": "Alice (Manager)", "spk_002": "Bob"}`, call `_build_speaker_hint(job)`, assert result contains `"Alice (Manager)"` and `"Bob"`.
- `test_extraction_prompt_empty_when_no_teams_metadata` — call `_build_speaker_hint({})`, assert returns `""`.

**Do not change:** `reviewing.py` (unknown_speaker flag already works correctly), `sipoc_validator.py`, existing test files.

---

**Verification:**
```bash
cd backend && .venv/bin/pytest ../tests/unit/test_speaker_resolve.py -v
.venv/bin/pytest ../tests/ -q
```

Manual: submit a job with teams_metadata including transcript_speaker_map; verify speaker names appear as actors in extraction output rather than "Unknown".

Commit as: `feat: speaker resolution UI + inject teams speaker map into extraction (PRD §8.1)`

---

### FRAME-PERSIST — Persist frame captures to storage; surface in export bundle

**Context:**
PRD §8.10: "PDF/DOCX exports include referenced frame captures… only when they are linked to at least one PDD step or SIPOC row." Currently, extracted JPG frames are deleted immediately after `analyze_frames` returns (in the `finally: shutil.rmtree` block of `VideoAdapter.normalize()`). No image bytes reach the export layer. This task persists frames to the `evidence` blob container (or local `evidence/` path in dev mode) and threads the storage keys through to `export_builder`, which can then embed images in PDF/DOCX when they are anchor-linked.

**Changes — 4 files:**

---

**1. `backend/app/storage.py` — add `upload_frame` function**

Add a module-level function (not a method on `ExportStorage`) that uploads a single frame JPG. It constructs its own storage client using the `evidence` container:

```python
_EVIDENCE_CONTAINER = os.environ.get("AZURE_STORAGE_CONTAINER_EVIDENCE", "evidence")

def upload_frame(job_id: str, frame_index: int, jpg_bytes: bytes) -> str | None:
    """Upload a frame JPEG to the evidence container.

    Returns the storage key (blob path or local file path) on success, None on any failure.
    Never raises.
    """
    try:
        account_url = os.environ.get("AZURE_STORAGE_ACCOUNT_URL")
        if not account_url:
            account_name = os.environ.get("AZURE_STORAGE_ACCOUNT_NAME")
            if account_name:
                account_url = f"https://{account_name}.blob.core.windows.net"
        connection_string = os.environ.get("AZURE_STORAGE_CONNECTION_STRING")

        blob_name = f"{job_id}/frames/frame_{frame_index:04d}.jpg"

        if account_url:
            from azure.identity import DefaultAzureCredential
            client = BlobServiceClient(account_url=account_url, credential=DefaultAzureCredential())
            blob_client = client.get_blob_client(_EVIDENCE_CONTAINER, blob_name)
            blob_client.upload_blob(
                jpg_bytes,
                overwrite=True,
                content_settings=ContentSettings(content_type="image/jpeg"),
            )
            return blob_name
        if connection_string:
            client = BlobServiceClient.from_connection_string(connection_string)
            blob_client = client.get_blob_client(_EVIDENCE_CONTAINER, blob_name)
            blob_client.upload_blob(
                jpg_bytes,
                overwrite=True,
                content_settings=ContentSettings(content_type="image/jpeg"),
            )
            return blob_name

        # Local fallback
        base = os.environ.get("EXPORTS_BASE_PATH", DEFAULT_EXPORT_BASE_PATH)
        local_path = os.path.join(base, job_id, "frames", f"frame_{frame_index:04d}.jpg")
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        with open(local_path, "wb") as fh:
            fh.write(jpg_bytes)
        return local_path

    except Exception as exc:
        logger.warning("Frame upload failed for job %s frame %d: %s", job_id, frame_index, exc)
        return None
```

---

**2. `backend/app/agents/adapters/video.py` — upload frames before temp dir cleanup**

Import at top:
```python
from app.storage import upload_frame
```

In `normalize()`, after `frames = extract_keyframes(...)` and before `analyze_frames`, upload each frame. Insert this block:

```python
frame_storage_keys: list[tuple[str, float]] = []
for i, (frame_path, ts) in enumerate(frames):
    try:
        with open(frame_path, "rb") as fh:
            jpg_bytes = fh.read()
    except OSError:
        continue
    storage_key = upload_frame(job_id, i, jpg_bytes)
    if storage_key:
        frame_storage_keys.append((storage_key, ts))
```

Get `job_id` from `job.get("job_id", "unknown")` (add this near the top of `normalize()` alongside existing field reads).

After `analyze_frames` runs, include `frame_storage_keys` in the `EvidenceObject.metadata`:

```python
"has_frame_analysis": bool(frame_descriptions),
"frame_storage_keys": frame_storage_keys,   # list of (storage_key, timestamp_sec)
```

The `shutil.rmtree` in the `finally` block is unchanged — local temp files are still cleaned up; the uploaded copies are now in persistent storage.

---

**3. `backend/app/export_builder.py` — include frame captures in evidence bundle**

In `build_evidence_bundle`, after the OCR snippet loop, add a frame capture collection pass:

```python
# Collect frame captures from video evidence metadata
frame_captures: list[dict] = []
for item in evidence_items:
    frame_keys = (item.get("metadata") or {}).get("frame_storage_keys") or []
    for storage_key, ts in frame_keys:
        frame_captures.append({"storage_key": storage_key, "timestamp_sec": ts})

# Link frame captures to anchors where timestamp falls within anchor range
# Anchors with timestamp_range type have values like "00:01:30-00:01:35"
for capture in frame_captures:
    ts = capture["timestamp_sec"]
    for anchor_val, entry in anchor_map.items():
        if entry.anchor_type == "timestamp_range":
            # Simple check: if capture timestamp is within ±10s of anchor midpoint
            parts = anchor_val.replace("-", " ").split()
            if len(parts) >= 2:
                def _to_sec(t):
                    p = t.split(":")
                    try:
                        return sum(float(x) * (60 ** (len(p)-1-i)) for i, x in enumerate(p))
                    except (ValueError, TypeError):
                        return -1
                mid = (_to_sec(parts[0]) + _to_sec(parts[-1])) / 2
                if abs(ts - mid) <= 10:
                    capture.setdefault("linked_anchor_ids", []).append(entry.anchor_id)
```

Change the return dict:
```python
return {
    ...existing fields...,
    "frame_captures": frame_captures,           # replaces the hard-coded "pending" note
    "frame_captures_note": (
        "Frame captures embedded above."
        if frame_captures else
        "No frame captures available for this job."
    ),
    ...
}
```

Remove the old hard-coded `"frame_captures_note": "Frame captures are not embedded in this export (pending Azure Vision integration)."` line.

In `build_export_pdf` and `build_export_docx`: if `evidence_bundle.get("frame_captures")` is non-empty and storage is local (key starts with `/` or `./`), attempt to read and embed the image bytes. For blob keys, include a text reference line `Frame capture: {storage_key} @ {timestamp_sec}s` instead of embedding — do not attempt blob download at export time.

Specifically in PDF (using `fpdf2`): after the evidence section loop, if `frame_captures` is non-empty:
```python
for cap in evidence_bundle.get("frame_captures") or []:
    key = cap.get("storage_key", "")
    ts  = cap.get("timestamp_sec", 0)
    if key.startswith("/") or (key.startswith(".") and os.path.exists(key)):
        try:
            pdf.image(key, w=120)
            pdf.set_font("Helvetica", size=8)
            pdf.cell(0, 5, f"Frame @ {ts:.1f}s — {key}", ln=True)
        except Exception:
            pdf.set_font("Helvetica", size=8)
            pdf.cell(0, 5, f"Frame @ {ts:.1f}s (image unreadable)", ln=True)
    else:
        pdf.set_font("Helvetica", size=8)
        pdf.cell(0, 5, f"Frame @ {ts:.1f}s: {key}", ln=True)
```

In DOCX (using `python-docx`): same logic — `doc.add_picture(key)` for local paths, a plain paragraph for blob keys.

---

**4. `tests/unit/test_frame_persist.py` (new) — 4 tests**

- `test_upload_frame_local_fallback_writes_file` — monkeypatch env to clear AZURE_STORAGE_ACCOUNT_URL and AZURE_STORAGE_CONNECTION_STRING; call `upload_frame("job-1", 0, b"JPEG")` with `EXPORTS_BASE_PATH = tmp_path`; assert returned path exists and contains `b"JPEG"`.
- `test_upload_frame_returns_none_on_exception` — monkeypatch `open` to raise `OSError`; call `upload_frame(...)`; assert returns `None`.
- `test_video_adapter_sets_frame_storage_keys_in_metadata` — monkeypatch `is_ffmpeg_available → True`, `extract_keyframes → [("/tmp/f.jpg", 0.0)]`, `open` in video.py to return stub bytes, `upload_frame → "evidence/job/0.jpg"`, `analyze_frames → "desc"`; call `VideoAdapter().normalize(job)`; assert `ev.metadata["frame_storage_keys"] == [("evidence/job/0.jpg", 0.0)]`.
- `test_export_builder_includes_frame_captures_in_bundle` — build a minimal job dict with `extracted_evidence.evidence_items[0].metadata.frame_storage_keys = [("key", 1.5)]`; call `build_evidence_bundle(draft, job)`; assert `bundle["frame_captures"]` is a list with one entry whose `storage_key == "key"`.

**Do not change:** existing test files, `sipoc_validator.py`, `reviewing.py`, `processing.py`, `extraction.py`.

---

**New env var — document in `REFERENCE.md`:**
```
AZURE_STORAGE_CONTAINER_EVIDENCE=evidence   # blob container for frame captures and evidence assets
```

---

**Verification:**
```bash
cd backend && .venv/bin/pytest ../tests/unit/test_frame_persist.py -v
.venv/bin/pytest ../tests/ -q   # full suite green (270+ tests)
```

Commit as: `feat: persist frame captures to storage and surface in export bundle (PRD §8.10)`

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
