"""Extraction agent: transcript text → structured evidence items."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from typing import Any, Dict, List, Tuple

from app.agents.adapters.registry import AdapterRegistry

_adapter_registry = AdapterRegistry()
logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You are a process documentation specialist. Extract structured process evidence from "
    "business process recordings. Video and audio are the primary sources; transcript is "
    "a supporting signal. Return only valid JSON."
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
      "source_type": "video|audio|transcript|frame",
      "anchor": "HH:MM:SS-HH:MM:SS or section label",
      "confidence": 0.0
    }}
  ],
  "speakers_detected": ["name or Unknown Speaker"],
  "process_domain": "string",
  "transcript_quality": "high|medium|low"
}}

Rules:
- id must be sequential: ev-01, ev-02, …
- each evidence item must represent a distinct process action, not a transcript fragment
- remove transcript artifacts: VTT cue numbers, timestamps-only lines, facilitator questions,
  filler phrases, and non-process chitchat
- collapse adjacent steps with the same actor and substantially the same action into one item
- anchor must reference a timestamp range or section label from the transcript
- source_type must be one of video|audio|transcript|frame based on the evidence source
- confidence is a float between 0.0 and 1.0
- speakers_detected must list all unique speakers; use "Unknown Speaker" if unidentifiable
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


def _max_completion_tokens() -> int:
    raw = os.environ.get("PFCD_MAX_COMPLETION_TOKENS", "2048").strip()
    try:
        value = int(raw)
    except ValueError:
        return 2048
    return max(1, value)


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


def _parse_extraction_json(raw: str) -> Dict[str, Any]:
    candidates: List[str] = [raw.strip()]
    fenced = re.findall(r"```(?:json)?\s*(.*?)```", raw, flags=re.IGNORECASE | re.DOTALL)
    candidates.extend(chunk.strip() for chunk in fenced if chunk.strip())
    balanced = _extract_balanced_json_object(raw)
    if balanced:
        candidates.append(balanced.strip())

    last_error: json.JSONDecodeError | None = None
    for candidate in candidates:
        if not candidate:
            continue
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError as exc:
            last_error = exc
    if last_error is not None:
        raise last_error
    raise json.JSONDecodeError("No valid JSON object found", raw, 0)


def _fallback_extraction_from_text(content_text: str, parse_error: str) -> Dict[str, Any]:
    items: List[Dict[str, Any]] = []
    timestamp_re = re.compile(r"^\[(\d{2}:\d{2}:\d{2}(?:-\d{2}:\d{2}:\d{2})?)\]\s*(.+)$")
    lines = [line.strip() for line in content_text.splitlines() if line.strip()]
    for line in lines:
        match = timestamp_re.match(line)
        if not match:
            continue
        anchor, summary = match.group(1), match.group(2)
        items.append(
            {
                "id": f"ev-{len(items)+1:02d}",
                "summary": summary[:240],
                "actor": "Unknown",
                "system": "Unknown",
                "input_artifact": "",
                "output_artifact": "",
                "anchor": anchor,
                "source_type": "transcript",
                "confidence": 0.35,
            }
        )

    if not items:
        for line in lines[:8]:
            items.append(
                {
                    "id": f"ev-{len(items)+1:02d}",
                    "summary": line[:240],
                    "actor": "Unknown",
                    "system": "Unknown",
                    "input_artifact": "",
                    "output_artifact": "",
                    "anchor": "section:fallback",
                    "source_type": "transcript",
                    "confidence": 0.25,
                }
            )

    return {
        "evidence_items": items,
        "speakers_detected": ["Unknown"] if items else [],
        "process_domain": "unknown",
        "transcript_quality": "low",
        "fallback_reason": "llm_invalid_json",
        "fallback_parse_error": parse_error[:512],
    }


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


def _fact_items_to_evidence_items(
    facts: List[Any], *, source_type: str
) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for idx, fact in enumerate(facts, start=1):
        summary = (getattr(fact, "content", "") or "").strip()
        anchor = (getattr(fact, "anchor", "") or "").strip()
        if not summary or not anchor:
            continue
        speaker = (getattr(fact, "speaker", None) or "Unknown").strip()
        confidence = float(getattr(fact, "confidence", 0.5) or 0.5)
        items.append(
            {
                "id": f"ev-{idx:02d}",
                "summary": summary[:240],
                "actor": speaker,
                "system": "Unknown",
                "input_artifact": "",
                "output_artifact": "",
                "source_type": source_type,
                "anchor": anchor,
                "confidence": max(0.0, min(confidence, 1.0)),
            }
        )
    return items


def _apply_source_type_defaults(extracted: Dict[str, Any], primary_source_type: str) -> None:
    items = extracted.get("evidence_items")
    if not isinstance(items, list):
        return
    if primary_source_type == "video":
        resolved = "video"
    elif primary_source_type == "audio":
        resolved = "audio"
    else:
        # Keep transcript as the conservative fallback for unsupported/mixed
        # sources such as generic documents.
        resolved = "transcript"
    for item in items:
        if isinstance(item, dict):
            item["source_type"] = resolved


def _normalize_input(job: Dict[str, Any]) -> Tuple[str, List[Dict[str, Any]], Dict[str, Any]]:
    """
    Use registered adapters to normalize job input into extraction content.

    Returns (content_text, manifests, input_context) where:
    - content_text is the cleaned, LLM-ready string (video preferred when both exist)
    - manifests is a list of DocumentTypeManifest dicts to store on the job
    - input_context contains primary source selection and deterministic fact hints

    Falls back to raw _transcript_text_inline if no adapter matches.
    """
    source_types: List[str] = (
        job.get("input_manifest", {}).get("source_types") or []
    )
    adapters = _adapter_registry.get_adapters(source_types)

    content_text = ""
    source_content: Dict[str, str] = {}
    source_fact_hints: Dict[str, List[Dict[str, Any]]] = {}
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
        if ev.content_text:
            source_content[ev.source_type] = ev.content_text
        source_fact_hints[ev.source_type] = _fact_items_to_evidence_items(
            adapter.extract_facts(job), source_type=ev.source_type
        )

    primary_source_type = "transcript"
    fact_hints: List[Dict[str, Any]] = []
    for source_type in ("video", "transcript", "audio", "document"):
        if source_content.get(source_type):
            content_text = source_content[source_type]
            primary_source_type = source_type
            fact_hints = source_fact_hints.get(source_type, [])
            break

    # Video-first precedence: when both are available, transcript stays as
    # alignment context and video drives extraction content.
    if primary_source_type == "video" and source_content.get("transcript"):
        job["_transcript_text_inline"] = source_content["transcript"]

    # Final fallback: raw inline text (used when source_types is empty or unknown).
    # NOTE: _transcript_text_inline is intentionally ephemeral (set by the worker
    # during extracting and removed before persistence).
    if not content_text:
        content_text = (
            job.get("_transcript_text_inline")
            or job.get("_audio_transcript_inline")
            or ""
        )

    if not content_text:
        for source_type in ("video", "transcript", "audio", "document"):
            hints = source_fact_hints.get(source_type) or []
            if hints:
                primary_source_type = source_type
                fact_hints = hints
                break

    return content_text, manifests, {
        "primary_source_type": primary_source_type,
        "fact_hints": fact_hints,
    }


def run_extraction(job: Dict[str, Any], profile_conf: Dict[str, Any]) -> float:
    """Call Azure OpenAI to extract evidence items from the job's transcript.

    Mutates *job* in-place; returns cost in USD.
    """
    content_text, manifests, input_context = _normalize_input(job)
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

    try:
        extracted = _parse_extraction_json(raw)
    except json.JSONDecodeError as exc:
        logger.warning(
            "Extraction response JSON parse failed for job %s; using deterministic fallback: %s",
            job.get("job_id"),
            exc,
        )
        extracted = _fallback_extraction_from_text(content_text, str(exc))
        job["agent_signals"]["extraction_fallback"] = {
            "used": True,
            "reason": "llm_invalid_json",
            "error": str(exc)[:512],
        }

    primary_source_type = input_context.get("primary_source_type") or "transcript"
    if not extracted.get("evidence_items"):
        fact_hints = input_context.get("fact_hints") or []
        if fact_hints:
            extracted["evidence_items"] = fact_hints
            extracted.setdefault("fallback_reason", "adapter_fact_hints")

    _apply_source_type_defaults(extracted, primary_source_type)

    job["extracted_evidence"] = extracted
    job["agent_signals"]["transcript_parsed"] = True
    job["agent_signals"]["speakers_detected"] = extracted.get("speakers_detected") or []
    from app.job_logic import estimate_cost_usd
    return estimate_cost_usd(deployment, pt, ct)
