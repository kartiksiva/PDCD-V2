"""Extraction agent: transcript text → structured evidence items."""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any, Dict, List, Tuple

from app.agents.adapters.registry import AdapterRegistry

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


def _build_speaker_hint(job: Dict[str, Any]) -> str:
    """Return a speaker-hint block from teams_metadata.transcript_speaker_map, or ''."""
    teams = job.get("teams_metadata") or {}
    speaker_map = teams.get("transcript_speaker_map") or {}
    if not speaker_map:
        return ""
    lines = "\n".join(f"  - {speaker_id}: {name}" for speaker_id, name in speaker_map.items())
    return f"\nKnown speaker identities (use these for actor assignment):\n{lines}\n"


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _extract_usage_tokens(metadata: Dict[str, Any]) -> Tuple[int, int]:
    usage = metadata.get("usage")
    if usage is None:
        return 0, 0
    if isinstance(usage, dict):
        return _safe_int(usage.get("prompt_tokens")), _safe_int(usage.get("completion_tokens"))
    return _safe_int(getattr(usage, "prompt_tokens", 0)), _safe_int(
        getattr(usage, "completion_tokens", 0)
    )


async def _call_extraction(deployment: str, system_prompt: str, user_content: str):
    """Invoke chat completion via Semantic Kernel; returns (raw_json, prompt_tokens, completion_tokens)."""
    from semantic_kernel.connectors.ai.open_ai import OpenAIChatPromptExecutionSettings
    from semantic_kernel.contents import ChatHistory
    from app.agents.kernel_factory import get_chat_service, get_kernel

    kernel = get_kernel(deployment)
    chat = ChatHistory()
    chat.add_system_message(system_prompt)
    chat.add_user_message(user_content)
    settings = OpenAIChatPromptExecutionSettings(
        response_format={"type": "json_object"}
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
    transcript_content = ""
    video_content = ""
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
        if ev.source_type == "transcript" and ev.content_text:
            transcript_content = ev.content_text
        elif ev.source_type == "video" and ev.content_text and not ev.content_text.startswith("["):
            video_content = ev.content_text

    # Build content for LLM: prefer uploaded transcript; supplement with video transcription.
    if transcript_content and video_content:
        content_text = (
            f"VIDEO TRANSCRIPT:\n{video_content}\n\n"
            f"UPLOADED TRANSCRIPT:\n{transcript_content}"
        )
    elif transcript_content:
        content_text = transcript_content
    elif video_content:
        content_text = video_content

    # Final fallback: raw inline text (used when source_types is empty or unknown).
    # NOTE: _transcript_text_inline is intentionally ephemeral (set by the worker
    # during extracting and removed before persistence).
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

    deployment = profile_conf.get("model")
    if not deployment:
        raise RuntimeError("profile_conf.model is required for extraction.")
    timeout_seconds = _llm_timeout_seconds()
    try:
        raw, pt, ct = asyncio.run(
            asyncio.wait_for(
                _call_extraction(
                    deployment,
                    _SYSTEM_PROMPT,
                    _USER_PROMPT_TEMPLATE.format(transcript_text=content_text) + _build_speaker_hint(job),
                ),
                timeout=timeout_seconds,
            )
        )
    except asyncio.TimeoutError as exc:
        raise RuntimeError(f"Extraction LLM call timed out after {timeout_seconds:.0f}s") from exc

    extracted = json.loads(raw)
    job["extracted_evidence"] = extracted
    job["agent_signals"]["transcript_parsed"] = True
    job["agent_signals"]["speakers_detected"] = extracted.get("speakers_detected") or []
    from app.job_logic import estimate_cost_usd
    return estimate_cost_usd(deployment, pt, ct)
