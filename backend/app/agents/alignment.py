"""Anchor alignment engine: validates LLM-extracted anchor strings against transcript cues."""

from __future__ import annotations

import re
from typing import Any

_VTT_CUE_RE = re.compile(
    r"(\d{2}:\d{2}:\d{2}[.,]\d+)\s*-->\s*(\d{2}:\d{2}:\d{2}[.,]\d+)"
)
_TS_RANGE_RE = re.compile(
    r"^(\d{2}:\d{2}:\d{2})(?:[.,]\d+)?-(\d{2}:\d{2}:\d{2})(?:[.,]\d+)?$"
)
_SECTION_HEADING_RE = re.compile(
    r"^Section\s+\d+[:\.\s].+", re.MULTILINE
)
_TOLERANCE_SEC = 2.0


def _ts_to_sec(ts: str) -> float:
    """Convert HH:MM:SS or HH:MM:SS.mmm to total seconds."""
    ts = ts.replace(",", ".")
    parts = ts.split(":")
    h, m, s = int(parts[0]), int(parts[1]), float(parts[2])
    return h * 3600 + m * 60 + s


def parse_vtt_cues(transcript_text: str) -> list[tuple[float, float]]:
    """Return sorted list of (start_sec, end_sec) from VTT cue lines."""
    cues = []
    for match in _VTT_CUE_RE.finditer(transcript_text):
        try:
            start = _ts_to_sec(match.group(1))
            end = _ts_to_sec(match.group(2))
            cues.append((start, end))
        except (ValueError, IndexError):
            continue
    return sorted(cues)


def parse_section_labels(transcript_text: str) -> list[str]:
    """Return lowercased section heading strings from plain-text transcript."""
    return [
        match.group(0).strip().lower()
        for match in _SECTION_HEADING_RE.finditer(transcript_text)
    ]


def normalize_timestamp_anchor(anchor: str) -> str | None:
    """Normalize HH:MM:SS-HH:MM:SS (with optional sub-second) to HH:MM:SS-HH:MM:SS.
    Returns None if the string cannot be parsed as a timestamp range.
    """
    match = _TS_RANGE_RE.match(anchor.strip())
    if not match:
        return None
    return f"{match.group(1)}-{match.group(2)}"


def validate_anchor(
    anchor: str,
    cues: list[tuple[float, float]],
    section_labels: list[str],
) -> dict[str, Any]:
    """Validate an anchor string against parsed transcript data.

    Returns a dict with keys:
      valid: bool
      anchor_type: "timestamp_range" | "section_label" | "unknown"
      normalized: str | None
      confidence_penalty: float  (0.0 when valid, 0.1–0.3 when invalid)
      reason: str | None
    """
    anchor = (anchor or "").strip()

    if not anchor:
        return {
            "valid": False,
            "anchor_type": "unknown",
            "normalized": None,
            "confidence_penalty": 0.3,
            "reason": "Empty anchor string.",
        }

    normalized = normalize_timestamp_anchor(anchor)

    if normalized is not None:
        # Timestamp range anchor
        match = _TS_RANGE_RE.match(anchor)
        try:
            a_start = _ts_to_sec(match.group(1))
            a_end = _ts_to_sec(match.group(2))
        except (ValueError, AttributeError):
            return {
                "valid": False,
                "anchor_type": "timestamp_range",
                "normalized": None,
                "confidence_penalty": 0.2,
                "reason": "Anchor timestamp could not be parsed.",
            }

        if not cues:
            # Plain-text transcript — timestamps can't be validated against cues
            return {
                "valid": True,
                "anchor_type": "timestamp_range",
                "normalized": normalized,
                "confidence_penalty": 0.0,
                "reason": None,
            }

        # Check overlap with any cue within tolerance
        for c_start, c_end in cues:
            if a_start <= c_end + _TOLERANCE_SEC and a_end >= c_start - _TOLERANCE_SEC:
                return {
                    "valid": True,
                    "anchor_type": "timestamp_range",
                    "normalized": normalized,
                    "confidence_penalty": 0.0,
                    "reason": None,
                }

        return {
            "valid": False,
            "anchor_type": "timestamp_range",
            "normalized": normalized,
            "confidence_penalty": 0.2,
            "reason": "Anchor timestamp range does not overlap any transcript cue.",
        }

    # Section label anchor
    anchor_lower = anchor.lower()

    if section_labels:
        for label in section_labels:
            if anchor_lower in label or label in anchor_lower:
                return {
                    "valid": True,
                    "anchor_type": "section_label",
                    "normalized": anchor,
                    "confidence_penalty": 0.0,
                    "reason": None,
                }
        return {
            "valid": False,
            "anchor_type": "section_label",
            "normalized": anchor,
            "confidence_penalty": 0.1,
            "reason": "Anchor section label not found in transcript.",
        }

    return {
        "valid": False,
        "anchor_type": "unknown",
        "normalized": None,
        "confidence_penalty": 0.1,
        "reason": "No transcript structure available to validate anchor.",
    }


def run_anchor_alignment(job: dict[str, Any]) -> None:
    """Validate evidence item anchors against the in-memory transcript.

    Reads:  job["extracted_evidence"]["evidence_items"]
            job["_transcript_text_inline"]
    Writes: per-item "anchor_alignment" dicts (confidence may be lowered)
            job["agent_signals"]["anchor_alignment_summary"]
    """
    transcript_text: str = job.get("_transcript_text_inline") or ""
    evidence_items = (job.get("extracted_evidence") or {}).get("evidence_items") or []

    if not transcript_text or not evidence_items:
        job["agent_signals"]["anchor_alignment_summary"] = {
            "validated": 0,
            "invalid": 0,
            "section_label": 0,
            "skipped": True,
        }
        return

    is_vtt = "WEBVTT" in transcript_text[:200] or "-->" in transcript_text[:500]

    if is_vtt:
        cues = parse_vtt_cues(transcript_text)
        section_labels: list[str] = []
    else:
        cues = []
        section_labels = parse_section_labels(transcript_text)

    validated = 0
    invalid = 0
    section_label_count = 0

    for item in evidence_items:
        anchor = item.get("anchor") or ""
        result = validate_anchor(anchor, cues, section_labels)
        item["anchor_alignment"] = result

        if result["anchor_type"] == "section_label":
            section_label_count += 1

        if result["valid"]:
            validated += 1
        else:
            invalid += 1
            penalty = result["confidence_penalty"]
            if penalty > 0:
                current = float(item.get("confidence", 1.0))
                item["confidence"] = max(0.0, round(current - penalty, 4))

    job["agent_signals"]["anchor_alignment_summary"] = {
        "validated": validated,
        "invalid": invalid,
        "section_label": section_label_count,
        "skipped": False,
    }
