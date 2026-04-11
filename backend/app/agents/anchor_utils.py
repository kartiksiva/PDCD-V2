"""Shared anchor classification utilities."""

from __future__ import annotations

import re

# HH:MM:SS(.mmm)? or HH:MM:SS(.mmm)?-HH:MM:SS(.mmm)?
_TIMESTAMP_RANGE_RE = re.compile(
    r"^\d{2}:\d{2}:\d{2}(?:[\.,]\d+)?(?:-\d{2}:\d{2}:\d{2}(?:[\.,]\d+)?)?$"
)
# frame-1, frame_1, frame1
_FRAME_ID_RE = re.compile(r"^frame[-_]?\d+", re.IGNORECASE)


def classify_anchor(anchor: str | None) -> str:
    """Return one of: timestamp_range, frame_id, section_label, missing."""
    if not anchor or not str(anchor).strip():
        return "missing"
    value = str(anchor).strip()
    if _TIMESTAMP_RANGE_RE.match(value):
        return "timestamp_range"
    if _FRAME_ID_RE.match(value):
        return "frame_id"
    return "section_label"
