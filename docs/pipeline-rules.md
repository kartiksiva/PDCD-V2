# Pipeline Rules Reference

All rules applied across the three pipeline phases: **Extraction → Processing → Reviewing**.

---

## Phase 1 — Extraction (`agents/extraction.py`)

Rules applied by the LLM during evidence extraction from transcript/video input.

> **System prompt source priority** (applies before all rules): when video or audio is present they are the primary evidence source; transcript is a supporting signal. When transcript is the only source, it is treated as primary and all described process steps must be extracted in full detail.

| # | Rule | Source |
|---|------|--------|
| E-01 | Evidence item IDs must be sequential: `ev-01`, `ev-02`, … | `_USER_PROMPT_TEMPLATE` |
| E-02 | `subject_process` is the operational process being documented — not the discovery meeting itself | `_USER_PROMPT_TEMPLATE` |
| E-03 | Each evidence item represents one step of the subject process — not a meeting action or session summary | `_USER_PROMPT_TEMPLATE` |
| E-04 | If the transcript is a discovery session, extract process steps from Q&A content (participants' answers) | `_USER_PROMPT_TEMPLATE` |
| E-05 | Set `evidence_type` to `"as_is"` for currently executed process actions and current pain points | `_USER_PROMPT_TEMPLATE` |
| E-06 | Set `evidence_type` to `"future_state"` for proposed improvements, recommendations, target-state design, or consultant suggestions; do not mix into as-is evidence items | `_USER_PROMPT_TEMPLATE` |
| E-07 | Remove only genuine non-process content: greetings, audio-check talk, scheduling coordination, and filler phrases | `_USER_PROMPT_TEMPLATE` |
| E-08 | Collapse adjacent steps with the same actor and substantially the same action into one item | `_USER_PROMPT_TEMPLATE` |
| E-09 | `anchor` must reference a timestamp range or section label from the transcript — do NOT invent timestamps | `_USER_PROMPT_TEMPLATE` |
| E-10 | `source_type` must be one of `video \| audio \| transcript \| frame` based on the evidence source | `_USER_PROMPT_TEMPLATE` |
| E-11 | `confidence`: 0.7–0.9 for explicitly stated steps; 0.4–0.6 for inferred; 0.2–0.4 for ambiguous | `_USER_PROMPT_TEMPLATE` |
| E-12 | `speakers_detected` must list all unique speakers; use `"Unknown Speaker"` if unidentifiable | `_USER_PROMPT_TEMPLATE` |
| E-13 | `quantitative_facts` must capture stated metrics and timings with anchors: volume, sla, effort, staffing, error_rate | `_USER_PROMPT_TEMPLATE` |
| E-14 | `exception_patterns` must capture distinct exception scenarios and their triggers | `_USER_PROMPT_TEMPLATE` |
| E-15 | `workaround_rationale` must capture workaround + underlying reason pairs, with anchors | `_USER_PROMPT_TEMPLATE` |
| E-16 | `roles_detected` must list all named operational roles discovered in the process content | `_USER_PROMPT_TEMPLATE` |
| E-17 | Aim for complete extraction: a 60-minute discovery session should yield 15–30 evidence items | `_USER_PROMPT_TEMPLATE` |
| E-18 | `transcript_quality`: `high` if cues clearly describe process steps; `medium` if some steps are implicit; `low` if content is mostly chitchat | `_USER_PROMPT_TEMPLATE` |

---

## Phase 2 — Processing (`agents/processing.py`)

Rules applied by the LLM when generating the PDD + SIPOC draft from extracted evidence.

### Evidence & sequencing

| # | Rule | Source |
|---|------|--------|
| P-01 | Video/audio/frame-derived evidence (`source_type: video \| audio \| frame`) takes precedence over transcript-derived evidence for step sequence | `_USER_PROMPT_TEMPLATE` |
| P-02 | Every evidence item must map to at least one PDD step | `_USER_PROMPT_TEMPLATE` |
| P-03 | Every PDD step must appear in at least one SIPOC row | `_USER_PROMPT_TEMPLATE` |
| P-04 | If `alignment_verdict` is `"suspected_mismatch"`, downgrade confidence on transcript-only inferences and avoid using them as primary sequencing evidence | `_USER_PROMPT_TEMPLATE` |

### Content completeness

| # | Rule | Source |
|---|------|--------|
| P-05 | **Quantitative population rule**: if `extracted_facts.quantitative_facts` includes `fact_type "sla"`, populate `pdd.sla` — do not emit `"Needs Review"` when an SLA fact is present. Same for `fact_type "volume"` → `pdd.frequency`. For `fact_type "staffing"`, surface staffing context in `pdd.process_overview` or `pdd.metrics.staffing_note` | `_USER_PROMPT_TEMPLATE` |
| P-06 | **Full lifecycle rule**: if evidence includes a close/confirm/conclude action, include it as an explicit closing step. Do not end the process at "escalate" or "resolve" without a close step | `_USER_PROMPT_TEMPLATE` |
| P-07 | **Exception completeness rule**: for each `extracted_facts.exception_patterns` entry, include a matching entry in `pdd.exceptions`. Do not collapse distinct exception scenarios | `_USER_PROMPT_TEMPLATE` |
| P-08 | **Exception population rule**: for each `pdd.exceptions[]` entry, populate `action_required` and `owner` from exception trigger context and step ownership. `owner` must come from `extracted_facts.roles_detected` when available; otherwise use `"Process Owner"`. Do not emit `"Needs Review"` for either field when context is available | `_USER_PROMPT_TEMPLATE` |
| P-09 | **Approval matrix coverage rule**: every role in `extracted_facts.roles_detected` must appear in `approval_matrix` with an explicit R/A/C/I value | `_USER_PROMPT_TEMPLATE` |
| P-10 | **Automation opportunity completeness**: create one `automation_opportunities[]` entry for each detected manual re-keying/copy-paste workaround, shadow spreadsheet/offline tracking tool, and knowledge-dependent decision that could be a rule engine | `_USER_PROMPT_TEMPLATE` |
| P-10b | **Automation quantification**: populate `automation_opportunities[].quantification` from volume/time/rework/touchpoint figures in evidence; use `"Needs Review"` only when no quantification is available in the evidence | `_USER_PROMPT_TEMPLATE` |
| P-11 | **Workaround rationale rule**: for each `extracted_facts.workaround_rationale` entry, surface the reason in `draft.risks[]` or `improvement_notes[]` | `_USER_PROMPT_TEMPLATE` |
| P-12 | PDD `steps[]` must include only current as-is executable actions. Future-state proposals, recommendations, and target-state workflows must NOT appear in `pdd.steps[]` — place them in `automation_opportunities[]` or `assumptions[]` | `_USER_PROMPT_TEMPLATE` |
| P-13 | Populate `steps[].tools_systems` from evidence; use `"Needs Review"` only when the system/tool cannot be determined from evidence | `_USER_PROMPT_TEMPLATE` |
| P-14 | Prefer concrete figures (percentages, counts, durations, frequencies, error rates) from evidence over generic descriptions. If evidence includes a specific number (e.g. `"20% reassignment rate"`, `"200 complaints/day"`, `"1-2 day delay"`), include it verbatim in `quantification` | `_USER_PROMPT_TEMPLATE` |

### Controls & language

| # | Rule | Source |
|---|------|--------|
| P-15 | **Control type definitions**: `manual` = human action or decision without system enforcement; `system` = enforced or logged by the software; `preventive` = stops an error before it occurs; `detective` = identifies an error after it occurs | `_USER_PROMPT_TEMPLATE` |
| P-16 | Use conservative language: do not invent roles, systems, or business rules not supported by evidence | `_USER_PROMPT_TEMPLATE` |
| P-17 | If evidence is sparse or transcript-only, still produce best-effort structure and list explicit assumptions in `assumptions[]` instead of fabricating detail | `_USER_PROMPT_TEMPLATE` |

### SIPOC anchors

| # | Rule | Source |
|---|------|--------|
| P-18 | `step_anchor` must be a non-empty JSON array with at least one PDD step ID (e.g., `["step-01"]`). Never leave it as `[]` or null | `_USER_PROMPT_TEMPLATE` |
| P-19 | `source_anchor` must be a non-empty string copied verbatim from an evidence item anchor (timestamp range `HH:MM:SS-HH:MM:SS` or section label). Never leave it blank | `_USER_PROMPT_TEMPLATE` |
| P-20 | If the closest available anchor is approximate, still use it and explain in `anchor_missing_reason`. Do not leave `source_anchor` blank as a way of signalling uncertainty | `_USER_PROMPT_TEMPLATE` |
| P-21 | `anchor_missing_reason` must be `null` when both anchors are present; a short explanation string when `source_anchor` is approximate or `step_anchor` coverage is partial | `_USER_PROMPT_TEMPLATE` |
| P-22 | Confidence values are floats between 0.0 and 1.0 | `_USER_PROMPT_TEMPLATE` |
| P-23 | `confidence_delta` is the change from baseline confidence (negative = reduced; positive = corroborating evidence) | `_USER_PROMPT_TEMPLATE` |

### Profile guidance

| Profile | Guidance |
|---------|----------|
| `balanced` | Target 8–14 steps. Merge sub-steps. Omit future-state or aspirational content. Capture only as-is evidence. |
| `quality` | Target 10–18 steps. Preserve distinct steps even if adjacent. Capture all named roles, all SLA figures, all named exceptions. |

---

## Phase 3 — Reviewing (`agents/reviewing.py` + `agents/sipoc_validator.py` + `agents/evidence.py`)

Pure-Python deterministic checks applied to the draft. No LLM call.

### Draft quality flags

| # | Flag Code | Severity | Trigger | Source |
|---|-----------|----------|---------|--------|
| R-01 | `stub_draft_detected` | **blocker** | `draft.draft_source == "stub"` — fallback stub must be replaced before finalize | `reviewing.py` |
| R-02 | `pdd_incomplete` | **blocker** | Any required PDD key (`purpose`, `scope`, `triggers`, `preconditions`, `steps`, `roles`, `systems`, `business_rules`, `exceptions`, `outputs`, `metrics`, `risks`) is missing or blank | `reviewing.py` |
| R-03 | `frame_first_evidence` | warning | Video present, transcript present, but no audio — sequence derived from frames | `reviewing.py` |
| R-04 | `transcript_fallback` | warning | Transcript-only input — validate actor and action assignments before finalize | `reviewing.py` |
| R-05 | `insufficient_evidence` | **blocker** | Video has no audio and no transcript — cannot extract process steps reliably | `reviewing.py` |
| R-06 | `transcript_mismatch` | warning | Both media and transcript present, and `alignment_verdict == "suspected_mismatch"` | `reviewing.py` |
| R-07 | `unknown_speaker` | warning | `"Unknown"` appears in `speakers_detected` | `reviewing.py` |
| R-08 | `SLA_UNRESOLVED` | warning | `pdd.sla == "Needs Review"` but `extracted_facts` contains a `fact_type: "sla"` entry | `reviewing.py` |
| R-09 | `FREQUENCY_UNRESOLVED` | warning | `pdd.frequency == "Needs Review"` but `extracted_facts` contains a `fact_type: "volume"` entry | `reviewing.py` |
| R-10 | `EXCEPTIONS_SUPPRESSED` | warning | `extracted_facts.exception_patterns` is non-empty but `pdd.exceptions` is empty | `reviewing.py` |

### SIPOC validation flags (`sipoc_validator.py`)

| # | Flag Code | Severity | Trigger |
|---|-----------|----------|---------|
| S-01 | `sipoc_empty` | **blocker** | SIPOC list contains no rows |
| S-02 | `sipoc_row_incomplete` | warning | A row is missing one or more of: `supplier`, `input`, `process_step`, `output`, `customer` |
| S-03 | `sipoc_missing_reason_absent` | warning | `step_anchor` or `source_anchor` is absent and no `anchor_missing_reason` is provided |
| S-04 | `sipoc_invalid_step_ref` | warning | A `step_anchor` ID does not exist in `pdd.steps` |
| S-05 | `sipoc_frame_id_only` | warning | Row uses a `frame_id` anchor (fallback — timestamp extraction unavailable) |
| S-06 | `sipoc_no_anchor` | **blocker** | No SIPOC row has both `step_anchor` and `source_anchor` (PRD §10 quality gate) |

### Evidence strength computation (`evidence.py`, PRD §7)

| Source combination | Structural strength | Confidence degradation |
|--------------------|--------------------|-----------------------|
| Video + Audio (± transcript) | **high** | If mean item confidence < 0.60 → degrade to **medium** |
| Video + Transcript, no audio | **medium** | If mean item confidence < 0.60 → degrade to **low** |
| Transcript only | **medium** | If mean item confidence < 0.60 → degrade to **low** |
| Video only, audio only, or no sources | **low** | No further degradation |

---

## Summary counts

| Phase | LLM rules | Deterministic checks / flags |
|-------|-----------|------------------------------|
| Extraction | 18 | — |
| Processing | 24 (P-01 – P-23 + P-10b) + profile guidance | — |
| Reviewing | — | 10 draft flags + 6 SIPOC flags + 4 evidence strength tiers |
