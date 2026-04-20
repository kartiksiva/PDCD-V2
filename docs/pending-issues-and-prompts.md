# Pending Issues and Current Automation Prompts

Generated at: 2026-04-20 (local Docker runtime + repository HEAD)

## 1) Pending Issues (Repo + Runtime)

| ID | Category | Symptom | Root Cause | Impact | Status | Recommended Next Action |
|---|---|---|---|---|---|---|
| PI-001 | repo | Azure cost guardrails are not fully provisioned in bootstrap path | `infra/dev-bootstrap.sh` bootstrap still records budget creation as blocked by CLI preview mismatch (`IMPLEMENTATION_SUMMARY.md` Section 1 Known gaps) | No automatic budget cap/alerts from scripted setup | Open | Add a portal/manual runbook step in infra docs or update script when stable CLI path is available |
| PI-002 | repo | Video evidence extraction is still metadata/transcription-first for many flows | `VideoAdapter` still documents Azure Vision/Speech integration as pending | Lower quality for frame-derived step reconstruction when transcript/audio is weak | Open | Implement frame-level vision adapter path end-to-end and persist richer frame evidence |
| PI-003 | repo | Transcript-media consistency still uses proxy path in several cases | Full token/sequence similarity against audio-derived text remains blocked pending deeper media integration (`IMPLEMENTATION_SUMMARY.md` known limitation) | Mismatch verdict reliability is limited for some input combinations | Open | Finish Azure Speech-aligned comparison path and make it primary where media is present |
| PI-004 | repo | Worker runtime knobs are implemented but not fully surfaced in operator reference | Follow-up explicitly noted in `IMPLEMENTATION_SUMMARY.md` Section 67 open follow-up | Operators may miss tuning controls in production incidents | Open | Add receive/idle backoff env vars to `REFERENCE.md` env table |
| PI-005 | runtime | Failed jobs do not auto-resume after config fixes | Worker intentionally skips terminal statuses (`failed`, `deleted`, `completed`) | Users must create a new job or re-enqueue manually | Open (by design) | Add explicit UI/ops action for “clone+rerun failed job” to reduce manual handling |
| PI-006 | runtime | Latest model extraction can emit malformed JSON | LLM occasionally returns non-strict JSON even with JSON response format | Retry exhaustion can fail jobs; now mitigated by fallback extraction | Mitigated, still relevant | Keep fallback path and add telemetry/metrics for fallback rate to track quality drift |
| PI-007 | runtime | Latest model processing still hard-fails on invalid JSON | `processing.py` still uses direct `json.loads(raw)` without robust parse/fallback | Processing phase can still fail on malformed model output | Open | Implement the same robust parse + fallback strategy in processing as extraction |
| PI-008 | runtime | Local Docker may use stale key from shell despite `.env.docker.local` updates | Compose variable precedence allows shell-exported `OPENAI_API_KEY` to override env-file value | Misleading quota/auth errors and hard-to-debug runs | Open operational risk | Update local runbook to require `env -u OPENAI_API_KEY docker compose ...` or avoid exported key |
| PI-009 | runtime | Vision API helpers still send `max_tokens` not `max_completion_tokens` | `vision.py` request payload uses `max_tokens` | Potential incompatibility if switching vision path to stricter/newer models | Open | Add compatibility handling in vision request builder similar to chat agents |

## 2) Current Automation Prompts Used in Backend

### Prompt Inventory Summary

| Agent | Prompt Constant / Builder | Source | Invocation Path | Provider/Model Path |
|---|---|---|---|---|
| extraction | `_SYSTEM_PROMPT`, `_USER_PROMPT_TEMPLATE`, `_build_speaker_hint()` | `backend/app/agents/extraction.py` | `run_extraction()` -> `_call_extraction()` | `PFCD_PROVIDER` + profile model from `job_logic.profile_config()` |
| processing | `_SYSTEM_PROMPT`, `_USER_PROMPT_TEMPLATE`, `_PDD_SCHEMA`, `_SIPOC_SCHEMA` | `backend/app/agents/processing.py` | `run_processing()` -> `_call_processing()` | `PFCD_PROVIDER` + profile model from `job_logic.profile_config()` |
| vision | `_SYSTEM_PROMPT`, `_build_messages()` | `backend/app/agents/vision.py` | `analyze_frames()` -> `_call_vision_openai/_call_vision_azure` | OpenAI (`OPENAI_VISION_MODEL`) or Azure (`AZURE_OPENAI_VISION_DEPLOYMENT`) |

### 2.1 Extraction Agent Prompts

#### `_SYSTEM_PROMPT`

```text
You are a process documentation specialist. Extract structured evidence from this business process transcript. Return only valid JSON.
```

#### `_USER_PROMPT_TEMPLATE`

```text
Transcript:
{transcript_text}

Extract all distinct process steps from this transcript. Return a JSON object with this exact shape:
{
  "evidence_items": [
    {
      "id": "ev-01",
      "summary": "Actor performs action on system",
      "actor": "string",
      "system": "string",
      "input_artifact": "string",
      "output_artifact": "string",
      "anchor": "HH:MM:SS-HH:MM:SS or section label",
      "confidence": 0.0
    }
  ],
  "speakers_detected": ["name or Unknown"],
  "process_domain": "string",
  "transcript_quality": "high|medium|low"
}

Rules:
- id must be sequential: ev-01, ev-02, …
- anchor must reference a timestamp range or section label from the transcript
- confidence is a float between 0.0 and 1.0
- speakers_detected must list all unique speakers; use "Unknown" if unidentifiable
```

#### Speaker hint injection

`_build_speaker_hint(job)` appends this dynamic block to the user prompt when `teams_metadata.transcript_speaker_map` is present:

```text
Known speaker identities (use these for actor assignment):
  - <speaker_id>: <display_name>
```

### 2.2 Processing Agent Prompts

#### `_SYSTEM_PROMPT`

```text
You are a business process analyst. Convert extracted evidence into a complete Process Definition Document (PDD) and SIPOC map. Return only valid JSON matching the provided schema exactly.
```

#### `_USER_PROMPT_TEMPLATE`

```text
Evidence items:
{evidence_json}

Input manifest:
{manifest_json}

Profile: {profile}

Generate a complete PDD and SIPOC from the evidence above. Return a JSON object with this exact shape:
{
  "pdd": {pdd_schema},
  "sipoc": {sipoc_schema},
  "assumptions": ["list of assumptions made"],
  "confidence_summary": {
    "overall": 0.0,
    "source_quality": "high|medium|low",
    "evidence_strength": "high|medium|low"
  },
  "generated_at": "ISO 8601 UTC timestamp",
  "version": 1
}

Rules:
- Every evidence item must map to at least one PDD step
- Every PDD step must appear in at least one SIPOC row
- step_anchor MUST be a non-empty JSON array with at least one PDD step ID from the steps list above (e.g. ["step-01"]). Never leave step_anchor as [] or null.
- source_anchor MUST be a non-empty string copied verbatim from an evidence item anchor value above (timestamp range "HH:MM:SS-HH:MM:SS" or section label). Never leave source_anchor as "" or null.
- If the closest available anchor is approximate, still use it and explain in anchor_missing_reason. Do not leave source_anchor blank as a way of signalling uncertainty.
- anchor_missing_reason must be null when both anchors are present; a short explanation string when source_anchor is approximate or step_anchor coverage is partial.
- confidence values are floats between 0.0 and 1.0
```

#### `_PDD_SCHEMA` (embedded in user prompt)

```json
{
  "purpose": "string — one-sentence purpose of the process",
  "scope": "string — in/out of scope boundaries",
  "triggers": ["list of events that start the process"],
  "preconditions": ["list of conditions that must be true before start"],
  "steps": [
    {
      "id": "step-01",
      "summary": "string",
      "actor": "string",
      "system": "string",
      "input": "string",
      "output": "string",
      "exception": "string or null",
      "source_anchors": [{"source": "transcript", "anchor": "HH:MM:SS-HH:MM:SS", "confidence": 0.0}]
    }
  ],
  "roles": ["list of all actor names"],
  "systems": ["list of all systems"],
  "business_rules": ["list of rules extracted from evidence"],
  "exceptions": ["list of exception conditions"],
  "outputs": ["list of process outputs"],
  "metrics": {"coverage": "high|medium|low", "confidence": 0.0},
  "risks": ["list of identified risks"]
}
```

#### `_SIPOC_SCHEMA` (embedded in user prompt)

```json
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
]
```

### 2.3 Vision Agent Prompts

#### `_SYSTEM_PROMPT`

```text
You are a process documentation assistant. For each video frame shown, describe:
1. What the user is doing (actions, clicks, navigation)
2. What application or screen is visible
3. Any visible text that identifies a process step, form field, or transaction

Be concise. Focus on process-relevant actions, not aesthetics.
Output one paragraph per frame, prefixed with the frame timestamp.
```

#### User message built by `_build_messages(batch, policy)`

User message content always starts with:

```text
Analyze frames from <start_ts>s to <end_ts>s. Frame policy: <policy>.
```

Then for each frame in batch:

```text
Frame timestamp: <timestamp>s
```

plus an inline image payload:

```json
{"type":"image_url","image_url":{"url":"data:image/jpeg;base64,<...>"}}
```

## 3) Evidence Sources Used for Runtime Portion

- `GET /api/jobs/<job_id>` snapshots from running local stack
- Worker logs from `worker-extracting`, `worker-processing`, `worker-reviewing`
- Live env precedence checks in running containers (`OPENAI_API_KEY`, provider/model vars)

