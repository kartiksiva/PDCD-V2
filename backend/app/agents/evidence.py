"""Evidence strength computation: derives 'high'/'medium'/'low' from source presence + confidence."""

from __future__ import annotations

from typing import Any

_CONFIDENCE_LOW_THRESHOLD = 0.60


def _mean_confidence(items: list[dict[str, Any]]) -> float | None:
    """Return mean of item confidence values; None if list is empty or has no confidence fields."""
    values = [
        float(item["confidence"])
        for item in items
        if item.get("confidence") is not None
    ]
    if not values:
        return None
    return sum(values) / len(values)


def compute_evidence_strength(
    has_video: bool,
    has_audio: bool,
    has_transcript: bool,
    evidence_items: list[dict[str, Any]] | None = None,
) -> str:
    """Return 'high', 'medium', or 'low'.

    Structural rules (PRD §7 evidence hierarchy):
      video + audio (with or without transcript) -> high
      video + transcript, no audio              -> medium
      transcript only                           -> medium
      video only, or no sources                 -> low

    Confidence degradation (applied after structural rule):
      If evidence_items provided and mean confidence < LOW_THRESHOLD,
      degrade one tier: high -> medium, medium -> low.
    """
    if has_video and has_audio:
        strength = "high"
    elif has_video and has_transcript:
        strength = "medium"
    elif has_transcript:
        strength = "medium"
    else:
        strength = "low"

    if evidence_items and strength != "low":
        mean = _mean_confidence(evidence_items)
        if mean is not None and mean < _CONFIDENCE_LOW_THRESHOLD:
            strength = "medium" if strength == "high" else "low"

    return strength
