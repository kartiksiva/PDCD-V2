"""Processing agent: evidence items → PDD + SIPOC draft."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from typing import Any, Dict

from app.job_logic import _utc_now

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You are a business process analyst. Convert extracted evidence into a complete "
    "Process Definition Document (PDD) and SIPOC map. Return only valid JSON matching "
    "the provided schema exactly."
)

_PDD_SCHEMA = """\
{
  "process_name": "string",
  "function": "string",
  "sub_function": "string",
  "process_overview": "string",
  "process_objective": "string",
  "frequency": "string",
  "sla": "string",
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
      "tools_systems": "string",
      "input": "string",
      "output": "string",
      "exception": "string or null",
      "source_anchors": [{"source": "transcript", "anchor": "HH:MM:SS-HH:MM:SS", "confidence": 0.0}]
    }
  ],
  "roles": ["list of all actor names"],
  "systems": ["list of all systems"],
  "business_rules": ["list of rules extracted from evidence"],
  "exceptions": [
    {
      "scenario": "string — description of the exception condition",
      "trigger": "string — what causes this exception",
      "action_required": "string — corrective or escalation action to take",
      "owner": "string — role responsible for handling this exception"
    }
  ],
  "process_controls": [
    {
      "control_id": "control-01",
      "process_step_id": "step-01",
      "control_description": "string",
      "manual_or_system": "manual|system",
      "preventive_or_detective": "preventive|detective"
    }
  ],
  "outputs": ["list of process outputs"],
  "metrics": {"coverage": "high|medium|low", "confidence": 0.0, "staffing_note": "string or null"},
  "risks": ["list of identified risks"]
}"""

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

_USER_PROMPT_TEMPLATE = """\
Evidence items:
{evidence_json}

Extracted facts:
{extracted_facts_json}

Input manifest:
{manifest_json}

Alignment verdict: {alignment_verdict}

Profile: {profile}

Profile guidance:
{profile_guidance}

Generate a complete PDD and SIPOC from the evidence above. Return a JSON object with this exact shape:
{{
  "pdd": {pdd_schema},
  "sipoc": {sipoc_schema},
  "assumptions": ["list of assumptions made"],
  "improvement_notes": ["list of improvement notes derived from workaround rationale"],
  "automation_opportunities": [
    {{
      "id": "auto-01",
      "description": "string",
      "quantification": "string",
      "automation_signal": "high|medium|low"
    }}
  ],
  "faqs": [
    {{"question": "string", "answer": "string"}}
  ],
  "approval_matrix": [
    {{"role": "string", "responsibility": "string"}}
  ],
  "confidence_summary": {{
    "overall": 0.0,
    "source_quality": "high|medium|low",
    "evidence_strength": "high|medium|low",
    "confidence_delta": 0.0
  }},
  "generated_at": "ISO 8601 UTC timestamp",
  "version": 1
}}

Rules:
- Evidence priority: video/audio/frame-derived items (source_type video|audio|frame)
  take precedence over transcript-derived items (source_type transcript) for step sequence.
- Quantitative population rule: if extracted_facts.quantitative_facts includes fact_type "sla",
  populate pdd.sla from that fact and do not emit "Needs Review" for SLA. If it includes
  fact_type "volume", populate pdd.frequency from that fact and do not emit "Needs Review"
  for frequency. If it includes fact_type "staffing", include the staffing context in pdd
  either in process_overview narrative or as staffing_note under pdd.metrics.
- Full lifecycle rule: if evidence includes a close/confirm/conclude action, include that as
  an explicit closing step. Do not end the process at "escalate" or "resolve" without a close step.
- Exception completeness rule: for each extracted_facts.exception_patterns entry, include a matching
  entry in pdd.exceptions. Do not collapse distinct exception scenarios into one generic exception.
- Exception population rule: for each entry in pdd.exceptions[], populate action_required and
  owner from exception trigger context and step ownership. owner must come from
  extracted_facts.roles_detected when available; otherwise use "Process Owner". Do not emit
  "Needs Review" for action_required or owner when exception context and roles are available.
- Approval matrix coverage rule: every role listed in extracted_facts.roles_detected must appear in
  approval_matrix with explicit responsibility value R/A/C/I.
- Control type definitions:
  - manual: human action or decision without system enforcement
  - system: enforced or logged by the software itself
  - preventive: stops an error before it occurs
  - detective: identifies an error after it occurs
- Automation opportunity completeness: create one automation_opportunities[] entry for each detected
  manual re-keying/copy-paste workaround, shadow spreadsheet/offline tracking tool, and
  knowledge-dependent decision that could be encoded as a rule engine.
- Workaround rationale rule: for each extracted_facts.workaround_rationale entry, surface the
  rationale reason in draft.risks[] or improvement_notes[].
- If alignment_verdict is "suspected_mismatch", downgrade confidence on transcript-only
  inferences and avoid using transcript-only claims as primary sequencing evidence.
- Use conservative language: do not invent roles, systems, or business rules not supported by evidence.
- If evidence is sparse or transcript-only, still produce best-effort structure and list explicit
  assumptions in assumptions[] instead of fabricating detail.
- PDD steps[] must include only current as-is executable actions.
- Future-state proposals, recommendations, target-state workflows, and consultant suggestions must NOT
  appear in pdd.steps[]; place them in automation_opportunities[] or assumptions[] instead.
- Populate steps[].tools_systems from evidence; use "Needs Review" when the system/tool cannot
  be determined from evidence.
- Populate automation_opportunities[] from repetitive/rule-based/manual effort patterns in evidence.
  Include quantification where possible (volume, time, rework, touchpoints); otherwise "Needs Review".
- Prefer concrete figures (percentages, counts, durations, frequencies, and error rates) from evidence
  over generic descriptions. If evidence includes a specific number (e.g. "20% reassignment rate",
  "200 complaints/day", "1-2 day delay"), include it verbatim in quantification.
- Every evidence item must map to at least one PDD step
- Every PDD step must appear in at least one SIPOC row
- step_anchor MUST be a non-empty JSON array with at least one PDD step ID from the steps list above (e.g. ["step-01"]). Never leave step_anchor as [] or null.
- source_anchor MUST be a non-empty string copied verbatim from an evidence item anchor value above (timestamp range "HH:MM:SS-HH:MM:SS" or section label). Never leave source_anchor as "" or null.
- If the closest available anchor is approximate, still use it and explain in anchor_missing_reason. Do not leave source_anchor blank as a way of signalling uncertainty.
- anchor_missing_reason must be null when both anchors are present; a short explanation string when source_anchor is approximate or step_anchor coverage is partial.
- confidence values are floats between 0.0 and 1.0
- confidence_delta is the change from baseline confidence (negative: reduced confidence,
  positive: corroborating evidence increased confidence).
"""


def _profile_guidance(profile: str) -> str:
    if profile == "quality":
        return (
            "Target 10-18 steps. Preserve distinct steps even if adjacent. "
            "Capture all named roles, all SLA figures, all named exceptions."
        )
    return "Target 8-14 steps. Merge sub-steps. Omit future-state or aspirational content. Capture only as-is evidence."


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _extract_usage_tokens(metadata: Dict[str, Any]) -> tuple[int, int]:
    usage = metadata.get("usage")
    if usage is None:
        return 0, 0
    if isinstance(usage, dict):
        return _safe_int(usage.get("prompt_tokens")), _safe_int(usage.get("completion_tokens"))
    return _safe_int(getattr(usage, "prompt_tokens", 0)), _safe_int(
        getattr(usage, "completion_tokens", 0)
    )


def _max_completion_tokens() -> int:
    # PFCD_MAX_PROCESSING_TOKENS takes precedence; falls back to PFCD_MAX_COMPLETION_TOKENS.
    # Processing generates PDD+SIPOC JSON from all evidence items, so it needs a higher
    # ceiling than extraction (default 16384 vs extraction's 4096).
    raw = (
        os.environ.get("PFCD_MAX_PROCESSING_TOKENS")
        or os.environ.get("PFCD_MAX_COMPLETION_TOKENS")
        or "16384"
    ).strip()
    try:
        value = int(raw)
    except ValueError:
        return 16384
    return max(512, value)


async def _call_processing(deployment: str, system_prompt: str, user_content: str):
    """Invoke chat completion via Semantic Kernel; returns (raw_json, prompt_tokens, completion_tokens)."""
    from semantic_kernel.connectors.ai.open_ai import OpenAIChatPromptExecutionSettings
    from semantic_kernel.contents import ChatHistory
    from app.agents.kernel_factory import get_chat_service, get_kernel

    kernel = get_kernel(deployment)
    chat = ChatHistory()
    chat.add_system_message(system_prompt)
    chat.add_user_message(user_content)
    settings = OpenAIChatPromptExecutionSettings(
        response_format={"type": "json_object"},
        max_completion_tokens=_max_completion_tokens(),
    )
    svc = get_chat_service(deployment)
    result = await svc.get_chat_message_content(chat, settings, kernel=kernel)
    prompt_tokens, completion_tokens = _extract_usage_tokens(result.metadata)
    return (
        str(result),
        prompt_tokens,
        completion_tokens,
    )


def _llm_timeout_seconds() -> float:
    raw = os.environ.get("PFCD_LLM_TIMEOUT_SECONDS", "120").strip()
    try:
        value = float(raw)
    except ValueError:
        return 120.0
    return max(1.0, value)


def _extract_balanced_json_object(text: str) -> str | None:
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_string = False
    escaped = False
    for idx in range(start, len(text)):
        ch = text[idx]
        if escaped:
            escaped = False
            continue
        if ch == "\\":
            escaped = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : idx + 1]
    return None


def _parse_processing_json(raw: str) -> tuple[Dict[str, Any], bool]:
    candidates: list[tuple[str, bool]] = [(raw.strip(), False)]
    fenced = re.findall(r"```(?:json)?\s*(.*?)```", raw, flags=re.IGNORECASE | re.DOTALL)
    candidates.extend((chunk.strip(), True) for chunk in fenced if chunk.strip())
    balanced = _extract_balanced_json_object(raw)
    if balanced:
        candidates.append((balanced.strip(), True))

    last_error: json.JSONDecodeError | None = None
    for candidate, fallback_used in candidates:
        if not candidate:
            continue
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed, fallback_used
        except json.JSONDecodeError as exc:
            last_error = exc

    if last_error is not None:
        raise last_error
    raise json.JSONDecodeError("No valid JSON object found", raw, 0)


def run_processing(job: Dict[str, Any], profile_conf: Dict[str, Any]) -> float:
    """Call Azure OpenAI to generate PDD + SIPOC from extracted evidence.

    Mutates *job* in-place; returns cost in USD.
    """
    evidence = job.get("extracted_evidence") or {}
    manifest = job.get("input_manifest") or {}
    profile = profile_conf.get("profile", "balanced")
    alignment_verdict = (
        job.get("transcript_media_consistency", {}).get("verdict") or "inconclusive"
    )
    deployment = profile_conf.get("model")
    if not deployment:
        raise RuntimeError("profile_conf.model is required for processing.")
    logger.info(
        "Processing model resolved for job %s: profile=%s deployment=%s",
        job.get("job_id"),
        profile,
        deployment,
    )

    user_prompt = _USER_PROMPT_TEMPLATE.format(
        evidence_json=json.dumps(evidence, ensure_ascii=True, separators=(",", ":")),
        extracted_facts_json=json.dumps(
            job.get("extracted_facts") or {},
            ensure_ascii=True,
            separators=(",", ":"),
        ),
        manifest_json=json.dumps(manifest, ensure_ascii=True, separators=(",", ":")),
        alignment_verdict=alignment_verdict,
        profile=profile,
        profile_guidance=_profile_guidance(profile),
        pdd_schema=_PDD_SCHEMA,
        sipoc_schema=_SIPOC_SCHEMA,
    )

    timeout_seconds = _llm_timeout_seconds()
    try:
        raw, pt, ct = asyncio.run(
            asyncio.wait_for(
                _call_processing(deployment, _SYSTEM_PROMPT, user_prompt),
                timeout=timeout_seconds,
            )
        )
    except asyncio.TimeoutError as exc:
        raise RuntimeError(f"Processing LLM call timed out after {timeout_seconds:.0f}s") from exc
    draft, processing_fallback_used = _parse_processing_json(raw)
    if processing_fallback_used:
        job.setdefault("agent_signals", {})["processing_fallback"] = True

    # Guard: if the LLM returned a JSON object that is missing both pdd and sipoc,
    # the response likely has a different shape (e.g., wrapped in a "result" key).
    # Surface this as a clear runtime error rather than masking it with sipoc_empty.
    if not isinstance(draft.get("pdd"), dict) and not isinstance(draft.get("sipoc"), list):
        raise RuntimeError(
            f"Processing LLM response is missing required 'pdd' and 'sipoc' keys; "
            f"top-level keys present: {list(draft.keys())!r}"
        )

    # Ensure required top-level keys are present
    draft.setdefault("generated_at", _utc_now())
    draft.setdefault("version", 1)
    draft.setdefault("assumptions", [])
    draft.setdefault("improvement_notes", [])
    draft.setdefault("automation_opportunities", [])
    draft.setdefault("faqs", [])
    draft.setdefault("approval_matrix", [])
    draft.setdefault("confidence_summary", {
        "overall": 0.65,
        "source_quality": "medium",
        "evidence_strength": job.get("agent_signals", {}).get("evidence_strength"),  # overwritten by reviewer
        "confidence_delta": 0.0,
    })
    draft["confidence_summary"].setdefault("confidence_delta", 0.0)
    pdd = draft.setdefault("pdd", {})
    pdd.setdefault("process_name", "Needs Review")
    pdd.setdefault("function", "Needs Review")
    pdd.setdefault("sub_function", "Needs Review")
    pdd.setdefault("process_overview", pdd.get("purpose", "Needs Review"))
    pdd.setdefault("process_objective", pdd.get("purpose", "Needs Review"))
    # Use `or` rather than setdefault so empty strings are also replaced.
    pdd["frequency"] = pdd.get("frequency") or "Needs Review"
    pdd["sla"] = pdd.get("sla") or "Needs Review"
    pdd.setdefault("process_controls", [])
    for step in pdd.get("steps") or []:
        if isinstance(step, dict):
            step.setdefault("tools_systems", step.get("system") or "Needs Review")

    job["draft"] = draft
    from app.job_logic import estimate_cost_usd
    return estimate_cost_usd(deployment, pt, ct)
