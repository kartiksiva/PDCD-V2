"""Anchor alignment engine: validates anchors and computes transcript/media consistency.

PRD §8.5 requires transcript/media consistency via "first N seconds overlap and
token/sequence similarity on normalized text."

Current behavior:
  - Anchor validation still runs against transcript cues/section labels and lowers
    evidence-item confidence when anchors are invalid.
  - The existing first-N-seconds anchor-validity proxy remains as a fallback score.
  - When both uploaded transcript text and a real video transcript are available,
    text similarity overrides the proxy and becomes the authoritative consistency
    signal written to transcript_media_consistency.
"""

from __future__ import annotations

import os
import re
from difflib import SequenceMatcher
from typing import Any

from app.agents.anchor_utils import classify_anchor

_VTT_CUE_RE = re.compile(
    r"(\d{2}:\d{2}:\d{2}[.,]\d+)\s*-->\s*(\d{2}:\d{2}:\d{2}[.,]\d+)"
)
_TS_RANGE_RE = re.compile(
    r"^(\d{2}:\d{2}:\d{2})(?:[.,]\d+)?(?:-(\d{2}:\d{2}:\d{2})(?:[.,]\d+)?)?$"
)
_SECTION_HEADING_RE = re.compile(
    r"^Section\s+\d+[:\.\s].+", re.MULTILINE
)
_SPEAKER_LABEL_RE = re.compile(
    r"^(?:\*{0,2})?(?:[A-Z][A-Za-z'`.\-]+(?:\s+[A-Z][A-Za-z'`.&()/:\-]+){0,5})"
    r"(?:\s*\([^)]+\))?\s*:\s*",
    re.MULTILINE,
)
_VTT_CUE_LINE_RE = re.compile(
    r"^(?:WEBVTT|\d+|\d{2,}:\d{2}(?::\d{2})?\.\d{3}\s+-->\s+.*)$",
    re.IGNORECASE | re.MULTILINE,
)
_TOLERANCE_SEC = 2.0
# PRD §8.5 "first N seconds" window for consistency scoring.
CONSISTENCY_WINDOW_SEC = 60.0
_CONSISTENCY_MATCH_THRESHOLD = float(os.environ.get("PFCD_CONSISTENCY_MATCH_THRESHOLD", "0.80"))
_CONSISTENCY_INCONCLUSIVE_THRESHOLD = float(
    os.environ.get("PFCD_CONSISTENCY_INCONCLUSIVE_THRESHOLD", "0.50")
)
_CONSISTENCY_MISMATCH_THRESHOLD = float(
    os.environ.get("PFCD_CONSISTENCY_MISMATCH_THRESHOLD", "0.30")
)


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


def _normalize_for_similarity(text: str, max_chars: int = 2000) -> str:
    """Strip VTT noise and speaker labels; lowercase; truncate."""
    cleaned = _VTT_CUE_LINE_RE.sub("", str(text or ""))
    cleaned = _SPEAKER_LABEL_RE.sub("", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip().lower()
    if len(cleaned) > max_chars:
        cleaned = cleaned[:max_chars].rsplit(" ", 1)[0].strip()
    return cleaned


def _tokenize(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text))


def _text_similarity_score(text_a: str, text_b: str) -> float:
    """Jaccard token overlap (0.4) + SequenceMatcher ratio (0.6). Returns 0.0-1.0."""
    a = _normalize_for_similarity(text_a)
    b = _normalize_for_similarity(text_b, max_chars=max(len(a), 1))
    if not a or not b:
        return 0.0
    tokens_a, tokens_b = _tokenize(a), _tokenize(b)
    if not tokens_a or not tokens_b:
        return 0.0
    jaccard = len(tokens_a & tokens_b) / max(len(tokens_a | tokens_b), 1)
    seq = SequenceMatcher(a=a, b=b).ratio()
    return round(jaccard * 0.4 + seq * 0.6, 3)


def normalize_timestamp_anchor(anchor: str) -> str | None:
    """Normalize HH:MM:SS[-HH:MM:SS] (with optional sub-second) to HH:MM:SS-HH:MM:SS.
    Returns None if the string cannot be parsed as a timestamp range.
    """
    match = _TS_RANGE_RE.match(anchor.strip())
    if not match:
        return None
    start = match.group(1)
    end = match.group(2) or start
    return f"{start}-{end}"


def validate_anchor(
    anchor: str,
    cues: list[tuple[float, float]],
    section_labels: list[str],
) -> dict[str, Any]:
    """Validate an anchor string against parsed transcript data.

    Returns a dict with keys:
      valid: bool
      anchor_type: "timestamp_range" | "section_label" | "frame_id" | "missing"
      normalized: str | None
      confidence_penalty: float  (0.0 when valid, 0.1–0.3 when invalid)
      reason: str | None
    """
    anchor = (anchor or "").strip()
    anchor_type = classify_anchor(anchor)

    if anchor_type == "missing":
        return {
            "valid": False,
            "anchor_type": "missing",
            "normalized": None,
            "confidence_penalty": 0.3,
            "reason": "Empty anchor string.",
        }

    if anchor_type == "frame_id":
        return {
            "valid": False,
            "anchor_type": "frame_id",
            "normalized": anchor,
            "confidence_penalty": 0.1,
            "reason": "Frame ID anchors cannot be validated against transcript cues.",
        }

    normalized = normalize_timestamp_anchor(anchor)

    if anchor_type == "timestamp_range" and normalized is not None:
        # Timestamp range anchor
        match = _TS_RANGE_RE.match(anchor)
        try:
            a_start = _ts_to_sec(match.group(1))
            a_end = _ts_to_sec(match.group(2) or match.group(1))
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
        "anchor_type": "section_label",
        "normalized": None,
        "confidence_penalty": 0.1,
        "reason": "No transcript structure available to validate anchor.",
    }


def _consistency_score_from_anchors(
    evidence_items: list[dict[str, Any]],
    window_sec: float,
) -> tuple[float | None, int, int]:
    """Compute a similarity_score proxy from timestamp-anchor validity.

    Considers only evidence items whose anchor start falls within [0, window_sec]
    (PRD §8.5 "first N seconds").  If none fall in the window, falls back to the
    full-corpus timestamp anchors.  Returns (score, valid_count, total_count).
    score is None when no timestamp anchors exist (section-label-only transcript).

    NOTE: This is an anchor-quality proxy.  Replace with audio-derived token
    similarity once Azure Speech / VideoAdapter integration is complete.
    """
    window_valid: list[bool] = []
    all_valid: list[bool] = []

    for item in evidence_items:
        anchor = (item.get("anchor") or "").strip()
        m = _TS_RANGE_RE.match(anchor)
        if not m:
            continue
        try:
            start = _ts_to_sec(m.group(1))
        except (ValueError, IndexError):
            continue
        is_valid = bool((item.get("anchor_alignment") or {}).get("valid", False))
        all_valid.append(is_valid)
        if start <= window_sec:
            window_valid.append(is_valid)

    candidates = window_valid if window_valid else all_valid
    if not candidates:
        return None, 0, 0
    valid_count = sum(candidates)
    return round(valid_count / len(candidates), 4), valid_count, len(candidates)


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
        # No transcript or no items to validate — leave verdict as "inconclusive".
        job["agent_signals"]["anchor_alignment_summary"] = {
            "validated": 0,
            "invalid": 0,
            "section_label": 0,
            "skipped": True,
            "verdict": "inconclusive",
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

    # PRD §8.5 fallback: derive verdict + similarity_score from the first-N-seconds
    # anchor-validity window when text similarity is unavailable.
    similarity_score, win_valid, win_total = _consistency_score_from_anchors(
        evidence_items, CONSISTENCY_WINDOW_SEC
    )
    consistency_method = "anchor_validity_proxy"

    if similarity_score is None:
        # No timestamp anchors — section-label-only transcript; can't score.
        verdict = "inconclusive"
    elif similarity_score >= _CONSISTENCY_MATCH_THRESHOLD:
        verdict = "match"
    elif similarity_score >= _CONSISTENCY_INCONCLUSIVE_THRESHOLD:
        verdict = "inconclusive"
    else:
        verdict = "suspected_mismatch"

    # PRD §8.5: consistency is only meaningful when both media and transcript exist.
    # For transcript-only jobs leave the seeded "inconclusive" intact.
    has_media = job.get("has_video") or job.get("has_audio")
    video_transcript: str = job.get("_video_transcript_inline") or ""
    uploaded_transcript: str = job.get("_transcript_text_inline") or transcript_text

    if has_media and video_transcript and uploaded_transcript:
        similarity_score = _text_similarity_score(video_transcript, uploaded_transcript)
        if similarity_score >= _CONSISTENCY_MATCH_THRESHOLD:
            verdict = "match"
        elif similarity_score <= _CONSISTENCY_MISMATCH_THRESHOLD:
            verdict = "suspected_mismatch"
        else:
            verdict = "inconclusive"
        consistency_method = "text_similarity"

    if has_media:
        job["transcript_media_consistency"]["verdict"] = verdict
        job["transcript_media_consistency"]["similarity_score"] = similarity_score

    job["agent_signals"]["anchor_alignment_summary"] = {
        "validated": validated,
        "invalid": invalid,
        "section_label": section_label_count,
        "skipped": False,
        "verdict": verdict if has_media else "inconclusive",
        "similarity_score": similarity_score if has_media else None,
        "window_sec": CONSISTENCY_WINDOW_SEC,
        "window_anchors_checked": win_total,
        "consistency_method": consistency_method,
    }
