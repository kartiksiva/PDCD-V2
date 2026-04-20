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
- If alignment_verdict is "suspected_mismatch", downgrade confidence on transcript-only
  inferences and avoid using transcript-only claims as primary sequencing evidence.
- Use conservative language: do not invent roles, systems, or business rules not supported by evidence.
- If evidence is sparse or transcript-only, still produce best-effort structure and list explicit
  assumptions in assumptions[] instead of fabricating detail.
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
            "- Be thorough. Include observable sub-steps, exceptions, and system interactions.\n"
            "- Capture nuance when evidence supports it, while preserving schema precision."
        )
    return (
        "- Be concise. Prefer fewer, higher-confidence steps.\n"
        "- Avoid speculative detail when evidence is ambiguous."
    )


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
    # ceiling than extraction (default 8192 vs extraction's 4096).
    raw = (
        os.environ.get("PFCD_MAX_PROCESSING_TOKENS")
        or os.environ.get("PFCD_MAX_COMPLETION_TOKENS")
        or "8192"
    ).strip()
    try:
        value = int(raw)
    except ValueError:
        return 8192
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

    # Ensure required top-level keys are present
    draft.setdefault("generated_at", _utc_now())
    draft.setdefault("version", 1)
    draft.setdefault("assumptions", [])
    draft.setdefault("confidence_summary", {
        "overall": 0.65,
        "source_quality": "medium",
        "evidence_strength": job.get("agent_signals", {}).get("evidence_strength"),  # overwritten by reviewer
        "confidence_delta": 0.0,
    })
    draft["confidence_summary"].setdefault("confidence_delta", 0.0)

    job["draft"] = draft
    from app.job_logic import estimate_cost_usd
    return estimate_cost_usd(deployment, pt, ct)
