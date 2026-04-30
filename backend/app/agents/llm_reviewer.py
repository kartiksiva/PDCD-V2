"""LLM semantic reviewer: grounded advisory checks after deterministic review.

This module adds warning/info-only semantic flags. It never blocks finalize.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from typing import Any, Dict, List

from app.agents.alignment import parse_vtt_cues
from app.job_logic import estimate_cost_usd, load_transcript_text

_SYSTEM_PROMPT = (
    "You are a strict process-documentation QA reviewer. "
    "You verify a draft against supplied evidence items and transcript snippets. "
    "Return JSON only. Do not invent facts. Use warning/info severities only."
)

_USER_PROMPT_TEMPLATE = """\
Check two things only:
1) Coverage gap: evidence items not represented in any PDD step.
2) Factual consistency: mapped PDD step mismatches actor/system/action in evidence.

Draft PDD steps:
{steps_json}

Unmapped evidence candidates:
{unmapped_json}

Top mapped evidence candidates:
{mapped_json}

Return JSON with exact shape:
{{
  "coverage_flags": [
    {{
      "code": "coverage_gap",
      "severity": "warning",
      "message": "string",
      "evidence_id": "ev-01",
      "anchor": "00:00:10-00:00:20",
      "step_id": "",
      "snippet": "string"
    }}
  ],
  "consistency_flags": [
    {{
      "code": "factual_drift",
      "severity": "warning",
      "message": "string",
      "evidence_id": "ev-02",
      "anchor": "00:00:30-00:00:35",
      "step_id": "step-04",
      "snippet": "string"
    }}
  ]
}}
"""

_TS_RANGE_RE = re.compile(
    r"^(\d{2}:\d{2}:\d{2})(?:[.,]\d+)?(?:-(\d{2}:\d{2}:\d{2})(?:[.,]\d+)?)?$"
)
_VTT_LINE_RE = re.compile(
    r"(?m)^(\d{2}:\d{2}:\d{2}[.,]\d+)\s*-->\s*(\d{2}:\d{2}:\d{2}[.,]\d+)\s*$"
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
    raw = os.environ.get("PFCD_MAX_COMPLETION_TOKENS", "2048").strip()
    try:
        value = int(raw)
    except ValueError:
        return 2048
    return max(256, value)


def _llm_timeout_seconds() -> float:
    raw = os.environ.get("PFCD_LLM_TIMEOUT_SECONDS", "120").strip()
    try:
        value = float(raw)
    except ValueError:
        return 120.0
    return max(1.0, value)


def _ts_to_sec(ts: str) -> float:
    parts = ts.replace(",", ".").split(":")
    h, m, s = int(parts[0]), int(parts[1]), float(parts[2])
    return h * 3600 + m * 60 + s


def _anchor_bounds(anchor: str) -> tuple[float, float] | None:
    match = _TS_RANGE_RE.match((anchor or "").strip())
    if not match:
        return None
    start = _ts_to_sec(match.group(1))
    end = _ts_to_sec(match.group(2) or match.group(1))
    return (start, end)


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


def _parse_llm_json(raw: str) -> Dict[str, Any]:
    candidates: List[str] = [raw.strip()]
    fenced = re.findall(r"```(?:json)?\s*(.*?)```", raw, flags=re.IGNORECASE | re.DOTALL)
    candidates.extend(chunk.strip() for chunk in fenced if chunk.strip())
    balanced = _extract_balanced_json_object(raw)
    if balanced:
        candidates.append(balanced.strip())
    for candidate in candidates:
        if not candidate:
            continue
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            continue
    return {}


def _llm_review_enabled(profile_conf: Dict[str, Any]) -> bool:
    raw = os.environ.get("PFCD_REVIEW_LLM_ENABLED", "false").strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    return str(profile_conf.get("profile", "")).strip().lower() == "quality"


def _step_anchor_map(draft: Dict[str, Any]) -> Dict[str, List[str]]:
    mapping: Dict[str, List[str]] = {}
    steps = (draft.get("pdd") or {}).get("steps") or []
    for step in steps:
        step_id = str((step or {}).get("id") or "").strip()
        for source_anchor in (step.get("source_anchors") or []):
            anchor = str((source_anchor or {}).get("anchor") or "").strip()
            if not anchor:
                continue
            mapping.setdefault(anchor, [])
            if step_id and step_id not in mapping[anchor]:
                mapping[anchor].append(step_id)
    return mapping


def _vtt_blocks(transcript_text: str) -> List[Dict[str, Any]]:
    lines = transcript_text.splitlines()
    blocks: List[Dict[str, Any]] = []
    idx = 0
    while idx < len(lines):
        line = lines[idx].strip()
        match = _VTT_LINE_RE.match(line)
        if not match:
            idx += 1
            continue
        start = _ts_to_sec(match.group(1))
        end = _ts_to_sec(match.group(2))
        text_lines: List[str] = []
        idx += 1
        while idx < len(lines) and lines[idx].strip():
            value = lines[idx].strip()
            if not value.isdigit():
                text_lines.append(value)
            idx += 1
        blocks.append({"start": start, "end": end, "text": " ".join(text_lines).strip()})
        idx += 1
    return blocks


def _build_anchor_slices(evidence_items: List[Dict[str, Any]], transcript_text: str) -> Dict[str, str]:
    """Build short evidence snippets keyed by anchor."""
    slices: Dict[str, str] = {}
    if not transcript_text:
        return slices

    # Keep this call to reuse alignment parsing behavior and VTT detection path.
    cues = parse_vtt_cues(transcript_text)
    blocks = _vtt_blocks(transcript_text) if cues else []
    lower_text = transcript_text.lower()

    for item in evidence_items:
        anchor = str(item.get("anchor") or "").strip()
        if not anchor or anchor in slices:
            continue

        bounds = _anchor_bounds(anchor)
        if bounds and blocks:
            start, end = bounds
            matched = [
                b["text"]
                for b in blocks
                if start <= b["end"] + 2.0 and end >= b["start"] - 2.0 and b["text"]
            ]
            if matched:
                slices[anchor] = " ".join(matched)[:280]
                continue

        key = anchor.lower()
        pos = lower_text.find(key)
        if pos >= 0:
            left = max(0, pos - 120)
            right = min(len(transcript_text), pos + len(anchor) + 120)
            slices[anchor] = transcript_text[left:right].replace("\n", " ").strip()[:280]
            continue

        slices[anchor] = str(item.get("summary") or "").strip()[:280]

    return slices


def _drop_uncited_flags(flags: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    kept: List[Dict[str, Any]] = []
    for flag in flags:
        evidence_id = str(flag.get("evidence_id") or "").strip()
        anchor = str(flag.get("anchor") or "").strip()
        if not evidence_id or not anchor:
            continue
        kept.append(
            {
                "code": str(flag.get("code") or "llm_semantic_flag").strip(),
                "severity": str(flag.get("severity") or "warning").strip().lower(),
                "message": str(flag.get("message") or "").strip(),
                "evidence_id": evidence_id,
                "anchor": anchor,
                "step_id": str(flag.get("step_id") or "").strip(),
                "snippet": str(flag.get("snippet") or "").strip(),
            }
        )
    return kept


async def _call_llm_review(deployment: str, system_prompt: str, user_content: str):
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
    return str(result), prompt_tokens, completion_tokens


def _deterministic_coverage_flags(
    unmapped_items: List[Dict[str, Any]],
    slices: Dict[str, str],
) -> List[Dict[str, Any]]:
    flags: List[Dict[str, Any]] = []
    for item in unmapped_items:
        evidence_id = str(item.get("id") or "").strip()
        anchor = str(item.get("anchor") or "").strip()
        if not evidence_id or not anchor:
            continue
        flags.append(
            {
                "code": "coverage_gap",
                "severity": "warning",
                "message": f"Evidence {evidence_id} is not mapped to any PDD step.",
                "evidence_id": evidence_id,
                "anchor": anchor,
                "step_id": "",
                "snippet": slices.get(anchor, ""),
            }
        )
    return flags


def run_llm_semantic_review(job: Dict[str, Any], profile_conf: Dict[str, Any], storage: Any) -> float:
    """Run advisory semantic checks and persist `review_notes.llm_semantic_flags`.

    Returns LLM cost in USD.
    """
    review_notes = job.setdefault("review_notes", {})
    review_notes.setdefault("llm_semantic_flags", [])
    stats = job.setdefault("agent_signals", {}).setdefault(
        "llm_review_stats",
        {"total_flags": 0, "accepted_by_human": 0},
    )

    if not _llm_review_enabled(profile_conf):
        review_notes["llm_semantic_flags"] = []
        return 0.0

    if str((job.get("agent_review") or {}).get("decision") or "").strip().lower() == "blocked":
        review_notes["llm_semantic_flags"] = []
        return 0.0

    draft = job.get("draft") or {}
    evidence_items: List[Dict[str, Any]] = (
        (job.get("extracted_evidence") or {}).get("evidence_items") or []
    )
    if not draft or not evidence_items:
        review_notes["llm_semantic_flags"] = []
        return 0.0

    step_anchor_map = _step_anchor_map(draft)
    step_index = {
        str((step or {}).get("id") or "").strip(): step
        for step in ((draft.get("pdd") or {}).get("steps") or [])
    }

    unmapped_items: List[Dict[str, Any]] = []
    mapped_candidates: List[Dict[str, Any]] = []
    for item in evidence_items:
        anchor = str(item.get("anchor") or "").strip()
        mapped_step_ids = step_anchor_map.get(anchor, [])
        confidence = float(item.get("confidence") or 0.0)
        if mapped_step_ids:
            mapped_candidates.append(
                {
                    "evidence_id": item.get("id"),
                    "anchor": anchor,
                    "summary": item.get("summary"),
                    "confidence": confidence,
                    "step_id": mapped_step_ids[0],
                    "step_summary": (step_index.get(mapped_step_ids[0]) or {}).get("summary"),
                }
            )
        else:
            unmapped_items.append(item)

    transcript_text = load_transcript_text(job, storage) or job.get("_transcript_text_inline") or ""
    slices = _build_anchor_slices(evidence_items, transcript_text)
    top_mapped = sorted(
        mapped_candidates,
        key=lambda c: float(c.get("confidence") or 0.0),
        reverse=True,
    )[:5]
    for candidate in top_mapped:
        candidate["snippet"] = slices.get(str(candidate.get("anchor") or ""), "")

    llm_flags: List[Dict[str, Any]] = []
    deployment = profile_conf.get("model")
    if deployment and (unmapped_items or top_mapped):
        user_prompt = _USER_PROMPT_TEMPLATE.format(
            steps_json=json.dumps(
                (draft.get("pdd") or {}).get("steps") or [],
                ensure_ascii=True,
                separators=(",", ":"),
            ),
            unmapped_json=json.dumps(
                [
                    {
                        "evidence_id": item.get("id"),
                        "anchor": item.get("anchor"),
                        "summary": item.get("summary"),
                        "snippet": slices.get(str(item.get("anchor") or ""), ""),
                    }
                    for item in unmapped_items
                ],
                ensure_ascii=True,
                separators=(",", ":"),
            ),
            mapped_json=json.dumps(top_mapped, ensure_ascii=True, separators=(",", ":")),
        )
        timeout_seconds = _llm_timeout_seconds()
        try:
            raw, prompt_tokens, completion_tokens = asyncio.run(
                asyncio.wait_for(
                    _call_llm_review(deployment, _SYSTEM_PROMPT, user_prompt),
                    timeout=timeout_seconds,
                )
            )
            parsed = _parse_llm_json(raw)
            llm_flags.extend(parsed.get("coverage_flags") or [])
            llm_flags.extend(parsed.get("consistency_flags") or [])
            cost = estimate_cost_usd(deployment, prompt_tokens, completion_tokens)
        except Exception:
            cost = 0.0
    else:
        cost = 0.0

    # Always include deterministic coverage gap flags when items are unmapped.
    llm_flags.extend(_deterministic_coverage_flags(unmapped_items, slices))
    llm_flags = _drop_uncited_flags(llm_flags)

    deduped: List[Dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for flag in llm_flags:
        key = (
            flag.get("code", ""),
            flag.get("evidence_id", ""),
            flag.get("anchor", ""),
            flag.get("step_id", ""),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(flag)

    review_notes["llm_semantic_flags"] = deduped
    stats["total_flags"] = int(stats.get("total_flags") or 0) + len(deduped)
    stats.setdefault("accepted_by_human", 0)
    return cost

