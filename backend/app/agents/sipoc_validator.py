"""SIPOC schema validation — PRD §8.8 and §10 quality gate."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List

# Timestamp range: HH:MM:SS[-HH:MM:SS] with optional fractional seconds
_TIMESTAMP_RANGE_RE = re.compile(
    r"^\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:-\d{2}:\d{2}:\d{2}(?:\.\d+)?)?$"
)
# Frame ID fallback anchor: frame-N, frame_N, frameN (case-insensitive)
_FRAME_ID_RE = re.compile(r"^frame[-_]?\d+", re.IGNORECASE)

_REQUIRED_FIELDS = ["supplier", "input", "process_step", "output", "customer"]


def _flag(
    code: str, severity: str, message: str, *, requires_user_action: bool = False
) -> Dict[str, Any]:
    return {
        "code": code,
        "severity": severity,
        "message": message,
        "requires_user_action": requires_user_action,
    }


def _classify_anchor(anchor: str) -> str:
    """
    Classify a source_anchor string.

    Returns one of: "timestamp_range", "section_label", "frame_id", "missing".
    """
    if not anchor or not anchor.strip():
        return "missing"
    a = anchor.strip()
    if _TIMESTAMP_RANGE_RE.match(a):
        return "timestamp_range"
    if _FRAME_ID_RE.match(a):
        return "frame_id"
    return "section_label"


@dataclass
class SIPOCRowResult:
    """Validation outcome for a single SIPOC row."""

    row_index: int
    valid: bool
    missing_fields: List[str]
    has_step_anchor: bool
    has_source_anchor: bool
    anchor_type: str           # "timestamp_range" | "section_label" | "frame_id" | "missing"
    has_missing_reason: bool
    invalid_step_refs: List[str]  # step IDs referenced but absent from PDD steps


@dataclass
class SIPOCValidationResult:
    """Aggregate result of validating an entire SIPOC list."""

    quality_gate_pass: bool
    row_results: List[SIPOCRowResult]
    flags: List[Dict[str, Any]]
    valid_anchor_count: int     # rows with both step_anchor and source_anchor
    missing_anchor_count: int   # rows missing one or both anchors
    frame_id_only_count: int    # rows using frame_id fallback anchor


def validate_sipoc(
    sipoc: List[Dict[str, Any]],
    pdd_steps: List[Dict[str, Any]],
) -> SIPOCValidationResult:
    """
    Validate a SIPOC list against PRD §8.8 and §10 rules.

    Rules enforced:
    - SIPOC must be non-empty.
    - Each row must have all 5 required fields: supplier, input, process_step, output, customer.
    - step_anchor must be a non-empty list of step IDs present in pdd_steps.
      If step_anchor is absent, anchor_missing_reason must be provided.
    - source_anchor must be a non-empty string.
      If absent, anchor_missing_reason must be provided.
    - frame_id anchors are allowed only as fallback — emits a warning.
    - Quality gate (PRD §10): at least one row must have both step_anchor and source_anchor.

    Args:
        sipoc: List of SIPOC row dicts from the draft.
        pdd_steps: List of PDD step dicts used for step_anchor cross-reference.

    Returns:
        SIPOCValidationResult with quality_gate_pass flag, per-row detail, and flags to emit.
    """
    flags: List[Dict[str, Any]] = []
    row_results: List[SIPOCRowResult] = []
    valid_anchor_count = 0
    missing_anchor_count = 0
    frame_id_only_count = 0

    # Build set of valid step IDs from PDD for cross-reference
    valid_step_ids = {s.get("id") for s in (pdd_steps or []) if s.get("id")}

    if not sipoc:
        flags.append(_flag(
            "sipoc_empty",
            "blocker",
            "SIPOC contains no rows. At least one valid row is required.",
            requires_user_action=True,
        ))
        return SIPOCValidationResult(
            quality_gate_pass=False,
            row_results=[],
            flags=flags,
            valid_anchor_count=0,
            missing_anchor_count=0,
            frame_id_only_count=0,
        )

    for idx, row in enumerate(sipoc):
        row_num = idx + 1  # 1-based for human-readable messages

        # 1. Required field check
        missing_fields = [
            f for f in _REQUIRED_FIELDS
            if not row.get(f) or not str(row.get(f, "")).strip()
        ]

        # 2. step_anchor — must be a non-empty list with at least one non-empty ID
        step_anchor_raw = row.get("step_anchor") or []
        step_anchor_ids = [s for s in step_anchor_raw if s and str(s).strip()]
        has_step_anchor = bool(step_anchor_ids)

        # Cross-reference step IDs against PDD steps (only when PDD steps are known)
        invalid_step_refs: List[str] = []
        if has_step_anchor and valid_step_ids:
            invalid_step_refs = [s for s in step_anchor_ids if s not in valid_step_ids]

        # 3. source_anchor — classify type
        source_anchor_raw = str(row.get("source_anchor") or "")
        anchor_type = _classify_anchor(source_anchor_raw)
        has_source_anchor = anchor_type != "missing"

        # 4. anchor_missing_reason — required when anchors are absent
        missing_reason_raw = row.get("anchor_missing_reason") or ""
        has_missing_reason = bool(str(missing_reason_raw).strip())

        # 5. Aggregate counts
        if has_step_anchor and has_source_anchor:
            valid_anchor_count += 1
        else:
            missing_anchor_count += 1

        if anchor_type == "frame_id":
            frame_id_only_count += 1

        row_result = SIPOCRowResult(
            row_index=idx,
            valid=not missing_fields and has_step_anchor and has_source_anchor,
            missing_fields=missing_fields,
            has_step_anchor=has_step_anchor,
            has_source_anchor=has_source_anchor,
            anchor_type=anchor_type,
            has_missing_reason=has_missing_reason,
            invalid_step_refs=invalid_step_refs,
        )
        row_results.append(row_result)

        # Emit per-row flags

        if missing_fields:
            flags.append(_flag(
                "sipoc_row_incomplete",
                "warning",
                f"SIPOC row {row_num} is missing required fields: {', '.join(missing_fields)}.",
            ))

        if not has_step_anchor and not has_missing_reason:
            flags.append(_flag(
                "sipoc_missing_reason_absent",
                "warning",
                f"SIPOC row {row_num} has no step_anchor and no anchor_missing_reason provided.",
            ))

        if not has_source_anchor and not has_missing_reason:
            # Only emit if not already covered by step_anchor missing-reason check above
            if has_step_anchor:
                flags.append(_flag(
                    "sipoc_missing_reason_absent",
                    "warning",
                    f"SIPOC row {row_num} has no source_anchor and no anchor_missing_reason provided.",
                ))

        if invalid_step_refs:
            flags.append(_flag(
                "sipoc_invalid_step_ref",
                "warning",
                f"SIPOC row {row_num} references unknown PDD step ID(s): "
                f"{', '.join(invalid_step_refs)}.",
            ))

        if anchor_type == "frame_id":
            flags.append(_flag(
                "sipoc_frame_id_only",
                "warning",
                f"SIPOC row {row_num} uses a frame_id anchor (fallback path — "
                "timestamp extraction was unavailable).",
            ))

    # Quality gate: PRD §10 requires at least one row with both anchors
    quality_gate_pass = valid_anchor_count >= 1
    if not quality_gate_pass:
        flags.append(_flag(
            "sipoc_no_anchor",
            "blocker",
            "SIPOC contains no rows with both step_anchor and source_anchor. "
            "Quality gate failed — at least one fully-anchored row is required.",
            requires_user_action=True,
        ))

    return SIPOCValidationResult(
        quality_gate_pass=quality_gate_pass,
        row_results=row_results,
        flags=flags,
        valid_anchor_count=valid_anchor_count,
        missing_anchor_count=missing_anchor_count,
        frame_id_only_count=frame_id_only_count,
    )
