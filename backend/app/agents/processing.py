"""Processing agent: evidence items → PDD + SIPOC draft."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict


_DEPLOYMENT = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini")
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
    "source_anchor": "HH:MM:SS-HH:MM:SS or section label",
    "supplier": "string",
    "input": "string",
    "process_step": "string",
    "output": "string",
    "customer": "string",
    "anchor_missing_reason": "string or null"
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
- source_anchor must reference timestamps from evidence; set anchor_missing_reason if unavailable
- confidence values are floats between 0.0 and 1.0
"""


def _cost_usd(prompt_tokens: int, completion_tokens: int) -> float:
    return (prompt_tokens * 0.15 + completion_tokens * 0.60) / 1_000_000


async def _call_processing(deployment: str, system_prompt: str, user_content: str):
    """Invoke Azure OpenAI via Semantic Kernel; returns (raw_json, prompt_tokens, completion_tokens)."""
    from semantic_kernel.connectors.ai.open_ai import AzureChatCompletion, AzureChatPromptExecutionSettings
    from semantic_kernel.contents import ChatHistory
    from app.agents.kernel_factory import get_kernel
    kernel = get_kernel(deployment)
    chat = ChatHistory()
    chat.add_system_message(system_prompt)
    chat.add_user_message(user_content)
    settings = AzureChatPromptExecutionSettings(
        response_format={"type": "json_object"}
    )
    svc = kernel.get_service(type=AzureChatCompletion)  # type: ignore[arg-type]
    result = await svc.get_chat_message_content(chat, settings, kernel=kernel)
    usage = result.metadata.get("usage", {})
    return (
        str(result),
        usage.get("prompt_tokens", 0),
        usage.get("completion_tokens", 0),
    )


def run_processing(job: Dict[str, Any], profile_conf: Dict[str, Any]) -> float:
    """Call Azure OpenAI to generate PDD + SIPOC from extracted evidence.

    Mutates *job* in-place; returns cost in USD.
    """
    evidence = job.get("extracted_evidence") or {}
    manifest = job.get("input_manifest") or {}
    profile = profile_conf.get("profile", "balanced")
    deployment = profile_conf.get("model", _DEPLOYMENT)
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

    raw, pt, ct = asyncio.run(_call_processing(deployment, _SYSTEM_PROMPT, user_prompt))
    draft = json.loads(raw)

    # Ensure required top-level keys are present
    draft.setdefault("generated_at", datetime.now(timezone.utc).isoformat())
    draft.setdefault("version", 1)
    draft.setdefault("assumptions", [])
    draft.setdefault("confidence_summary", {
        "overall": 0.65,
        "source_quality": "medium",
        "evidence_strength": job.get("agent_signals", {}).get("evidence_strength"),  # overwritten by reviewer
    })

    job["draft"] = draft
    return _cost_usd(pt, ct)
