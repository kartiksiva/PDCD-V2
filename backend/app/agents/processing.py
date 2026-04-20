"""Processing agent: evidence items → PDD + SIPOC draft."""

from __future__ import annotations

import asyncio
import json
import logging
import os
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

Profile: {profile}

Generate a complete PDD and SIPOC from the evidence above. Return a JSON object with this exact shape:
{{
  "pdd": {pdd_schema},
  "sipoc": {sipoc_schema},
  "assumptions": ["list of assumptions made"],
  "confidence_summary": {{
    "overall": 0.0,
    "source_quality": "high|medium|low",
    "evidence_strength": "high|medium|low"
  }},
  "generated_at": "ISO 8601 UTC timestamp",
  "version": 1
}}

Rules:
- Every evidence item must map to at least one PDD step
- Every PDD step must appear in at least one SIPOC row
- step_anchor MUST be a non-empty JSON array with at least one PDD step ID from the steps list above (e.g. ["step-01"]). Never leave step_anchor as [] or null.
- source_anchor MUST be a non-empty string copied verbatim from an evidence item anchor value above (timestamp range "HH:MM:SS-HH:MM:SS" or section label). Never leave source_anchor as "" or null.
- If the closest available anchor is approximate, still use it and explain in anchor_missing_reason. Do not leave source_anchor blank as a way of signalling uncertainty.
- anchor_missing_reason must be null when both anchors are present; a short explanation string when source_anchor is approximate or step_anchor coverage is partial.
- confidence values are floats between 0.0 and 1.0
"""


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
    raw = os.environ.get("PFCD_MAX_COMPLETION_TOKENS", "2048").strip()
    try:
        value = int(raw)
    except ValueError:
        return 2048
    return max(1, value)


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


def run_processing(job: Dict[str, Any], profile_conf: Dict[str, Any]) -> float:
    """Call Azure OpenAI to generate PDD + SIPOC from extracted evidence.

    Mutates *job* in-place; returns cost in USD.
    """
    evidence = job.get("extracted_evidence") or {}
    manifest = job.get("input_manifest") or {}
    profile = profile_conf.get("profile", "balanced")
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
        profile=profile,
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
    draft = json.loads(raw)

    # Ensure required top-level keys are present
    draft.setdefault("generated_at", _utc_now())
    draft.setdefault("version", 1)
    draft.setdefault("assumptions", [])
    draft.setdefault("confidence_summary", {
        "overall": 0.65,
        "source_quality": "medium",
        "evidence_strength": job.get("agent_signals", {}).get("evidence_strength"),  # overwritten by reviewer
    })

    job["draft"] = draft
    from app.job_logic import estimate_cost_usd
    return estimate_cost_usd(deployment, pt, ct)
