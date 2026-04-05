"""Extraction agent: transcript text → structured evidence items."""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any, Dict, List, Tuple

from semantic_kernel.connectors.ai.open_ai import AzureChatCompletion, AzureChatPromptExecutionSettings
from semantic_kernel.contents import ChatHistory

from app.agents.adapters.registry import AdapterRegistry
from app.agents.kernel_factory import get_kernel

_DEPLOYMENT = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini")
_adapter_registry = AdapterRegistry()

_SYSTEM_PROMPT = (
    "You are a process documentation specialist. Extract structured evidence from this "
    "business process transcript. Return only valid JSON."
)

_USER_PROMPT_TEMPLATE = """\
Transcript:
{transcript_text}

Extract all distinct process steps from this transcript. Return a JSON object with this exact shape:
{{
  "evidence_items": [
    {{
      "id": "ev-01",
      "summary": "Actor performs action on system",
      "actor": "string",
      "system": "string",
      "input_artifact": "string",
      "output_artifact": "string",
      "anchor": "HH:MM:SS-HH:MM:SS or section label",
      "confidence": 0.0
    }}
  ],
  "speakers_detected": ["name or Unknown"],
  "process_domain": "string",
  "transcript_quality": "high|medium|low"
}}

Rules:
- id must be sequential: ev-01, ev-02, …
- anchor must reference a timestamp range or section label from the transcript
- confidence is a float between 0.0 and 1.0
- speakers_detected must list all unique speakers; use "Unknown" if unidentifiable
"""


def _cost_usd(prompt_tokens: int, completion_tokens: int) -> float:
    # gpt-4o-mini pricing: $0.15/1M input, $0.60/1M output
    return (prompt_tokens * 0.15 + completion_tokens * 0.60) / 1_000_000


async def _call_extraction(deployment: str, system_prompt: str, user_content: str):
    """Invoke Azure OpenAI via Semantic Kernel; returns (raw_json, prompt_tokens, completion_tokens)."""
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


def _normalize_input(job: Dict[str, Any]) -> Tuple[str, List[Dict[str, Any]]]:
    """
    Use registered adapters to normalize job input into extraction content.

    Returns (content_text, manifests) where:
    - content_text is the cleaned, LLM-ready string (transcript preferred over video metadata)
    - manifests is a list of DocumentTypeManifest dicts to store on the job

    Falls back to raw _transcript_text_inline if no adapter matches.
    """
    source_types: List[str] = (
        job.get("input_manifest", {}).get("source_types") or []
    )
    adapters = _adapter_registry.get_adapters(source_types)

    content_text = ""
    manifests: List[Dict[str, Any]] = []

    for adapter in adapters:
        ev = adapter.normalize(job)
        notes = adapter.render_review_notes(ev)
        manifests.append({
            "source_type": ev.source_type,
            "document_type": ev.document_type,
            "confidence": ev.confidence,
            "anchor_count": len(ev.anchors),
            "provenance_notes": notes,
        })
        # Only transcript drives LLM extraction content.
        # Video adapter contributes manifests/provenance only — actual
        # frame/audio extraction requires Azure Vision/Speech (pending).
        if ev.source_type == "transcript" and ev.content_text:
            content_text = ev.content_text

    # Final fallback: raw inline text (used when source_types is empty or unknown)
    if not content_text:
        content_text = job.get("_transcript_text_inline") or ""

    return content_text, manifests


def run_extraction(job: Dict[str, Any], profile_conf: Dict[str, Any]) -> float:
    """Call Azure OpenAI to extract evidence items from the job's transcript.

    Mutates *job* in-place; returns cost in USD.
    """
    content_text, manifests = _normalize_input(job)
    job["document_type_manifests"] = manifests

    if not content_text:
        # Graceful degradation: no transcript available yet
        job["extracted_evidence"] = {
            "evidence_items": [],
            "speakers_detected": [],
            "process_domain": "unknown",
            "transcript_quality": "low",
        }
        job["agent_signals"]["transcript_parsed"] = False
        return 0.0

    deployment = profile_conf.get("model", _DEPLOYMENT)
    raw, pt, ct = asyncio.run(
        _call_extraction(
            deployment,
            _SYSTEM_PROMPT,
            _USER_PROMPT_TEMPLATE.format(transcript_text=content_text),
        )
    )

    extracted = json.loads(raw)
    job["extracted_evidence"] = extracted
    job["agent_signals"]["transcript_parsed"] = True
    return _cost_usd(pt, ct)
