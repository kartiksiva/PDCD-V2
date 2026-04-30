"""Unit tests for SIPOC schema validation (PRD §8.8 and §10)."""

from __future__ import annotations

import pathlib
import sys
from typing import Any, Dict, List

ROOT = pathlib.Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sipoc_row(
    *,
    step_anchor: List[str] = None,
    source_anchor: str = "00:00:00-00:01:00",
    supplier: str = "Supplier",
    input: str = "Input",
    process_step: str = "Process",
    output: str = "Output",
    customer: str = "Customer",
    anchor_missing_reason: str = None,
) -> Dict[str, Any]:
    return {
        "step_anchor": step_anchor if step_anchor is not None else ["step-01"],
        "source_anchor": source_anchor,
        "supplier": supplier,
        "input": input,
        "process_step": process_step,
        "output": output,
        "customer": customer,
        "anchor_missing_reason": anchor_missing_reason,
    }


def _pdd_steps(*step_ids: str) -> List[Dict[str, Any]]:
    return [{"id": sid, "summary": f"Step {sid}"} for sid in step_ids]


# ---------------------------------------------------------------------------
# Empty SIPOC
# ---------------------------------------------------------------------------

def test_empty_sipoc_fails_quality_gate():
    from app.agents.sipoc_validator import validate_sipoc

    result = validate_sipoc([], _pdd_steps("step-01"))

    assert result.quality_gate_pass is False
    flag_codes = [f["code"] for f in result.flags]
    assert "sipoc_empty" in flag_codes
    assert any(f["severity"] == "blocker" for f in result.flags)


# ---------------------------------------------------------------------------
# Quality gate — valid anchor presence
# ---------------------------------------------------------------------------

def test_single_fully_anchored_row_passes_quality_gate():
    from app.agents.sipoc_validator import validate_sipoc

    sipoc = [_sipoc_row(step_anchor=["step-01"], source_anchor="00:00:00-00:01:00")]
    result = validate_sipoc(sipoc, _pdd_steps("step-01"))

    assert result.quality_gate_pass is True
    assert result.valid_anchor_count == 1
    assert result.missing_anchor_count == 0
    flag_codes = [f["code"] for f in result.flags]
    assert "sipoc_no_anchor" not in flag_codes


def test_no_anchored_row_fails_quality_gate():
    from app.agents.sipoc_validator import validate_sipoc

    sipoc = [_sipoc_row(step_anchor=[], source_anchor="", anchor_missing_reason="no data")]
    result = validate_sipoc(sipoc, _pdd_steps("step-01"))

    assert result.quality_gate_pass is False
    flag_codes = [f["code"] for f in result.flags]
    assert "sipoc_no_anchor" in flag_codes
    assert any(f["severity"] == "blocker" for f in result.flags if f["code"] == "sipoc_no_anchor")


def test_mixed_rows_passes_when_at_least_one_anchored():
    from app.agents.sipoc_validator import validate_sipoc

    sipoc = [
        _sipoc_row(step_anchor=["step-01"], source_anchor="00:00:00-00:01:00"),
        _sipoc_row(step_anchor=[], source_anchor="", anchor_missing_reason="upstream data gap"),
    ]
    result = validate_sipoc(sipoc, _pdd_steps("step-01"))

    assert result.quality_gate_pass is True
    assert result.valid_anchor_count == 1
    assert result.missing_anchor_count == 1


# ---------------------------------------------------------------------------
# Required field checks
# ---------------------------------------------------------------------------

def test_missing_required_field_emits_sipoc_row_incomplete():
    from app.agents.sipoc_validator import validate_sipoc

    sipoc = [_sipoc_row(supplier="")]  # supplier missing
    result = validate_sipoc(sipoc, _pdd_steps("step-01"))

    flag_codes = [f["code"] for f in result.flags]
    assert "sipoc_row_incomplete" in flag_codes
    assert any(f["severity"] == "warning" for f in result.flags if f["code"] == "sipoc_row_incomplete")


def test_all_required_fields_present_no_incomplete_flag():
    from app.agents.sipoc_validator import validate_sipoc

    sipoc = [_sipoc_row()]  # all fields set by helper defaults
    result = validate_sipoc(sipoc, _pdd_steps("step-01"))

    flag_codes = [f["code"] for f in result.flags]
    assert "sipoc_row_incomplete" not in flag_codes


def test_multiple_missing_fields_reported():
    from app.agents.sipoc_validator import validate_sipoc

    sipoc = [_sipoc_row(supplier="", customer="")]
    result = validate_sipoc(sipoc, _pdd_steps("step-01"))

    incomplete_flags = [f for f in result.flags if f["code"] == "sipoc_row_incomplete"]
    assert len(incomplete_flags) == 1
    assert "supplier" in incomplete_flags[0]["message"]
    assert "customer" in incomplete_flags[0]["message"]


# ---------------------------------------------------------------------------
# step_anchor cross-reference
# ---------------------------------------------------------------------------

def test_invalid_step_ref_emits_warning():
    from app.agents.sipoc_validator import validate_sipoc

    sipoc = [_sipoc_row(step_anchor=["step-99"])]  # step-99 does not exist in PDD
    result = validate_sipoc(sipoc, _pdd_steps("step-01", "step-02"))

    flag_codes = [f["code"] for f in result.flags]
    assert "sipoc_invalid_step_ref" in flag_codes
    assert any(
        "step-99" in f["message"]
        for f in result.flags if f["code"] == "sipoc_invalid_step_ref"
    )


def test_valid_step_refs_no_warning():
    from app.agents.sipoc_validator import validate_sipoc

    sipoc = [_sipoc_row(step_anchor=["step-01", "step-02"])]
    result = validate_sipoc(sipoc, _pdd_steps("step-01", "step-02", "step-03"))

    flag_codes = [f["code"] for f in result.flags]
    assert "sipoc_invalid_step_ref" not in flag_codes


def test_empty_pdd_steps_skips_cross_reference():
    """When PDD steps list is empty, cross-reference is skipped (no false positives)."""
    from app.agents.sipoc_validator import validate_sipoc

    sipoc = [_sipoc_row(step_anchor=["step-01"])]
    result = validate_sipoc(sipoc, [])  # empty PDD steps

    flag_codes = [f["code"] for f in result.flags]
    assert "sipoc_invalid_step_ref" not in flag_codes


def test_multiple_step_anchors_partially_invalid():
    from app.agents.sipoc_validator import validate_sipoc

    sipoc = [_sipoc_row(step_anchor=["step-01", "step-99"])]
    result = validate_sipoc(sipoc, _pdd_steps("step-01", "step-02"))

    flag_codes = [f["code"] for f in result.flags]
    assert "sipoc_invalid_step_ref" in flag_codes
    # Any invalid step ref means the row cannot count toward the quality gate
    assert result.valid_anchor_count == 0


# ---------------------------------------------------------------------------
# source_anchor classification
# ---------------------------------------------------------------------------

def test_timestamp_range_anchor_is_classified_correctly():
    from app.agents.sipoc_validator import SIPOCRowResult, validate_sipoc

    sipoc = [_sipoc_row(source_anchor="00:01:30-00:02:45")]
    result = validate_sipoc(sipoc, _pdd_steps("step-01"))

    assert result.row_results[0].anchor_type == "timestamp_range"
    assert result.row_results[0].has_source_anchor is True


def test_section_label_anchor_is_classified_correctly():
    from app.agents.sipoc_validator import validate_sipoc

    sipoc = [_sipoc_row(source_anchor="Section 1: Invoice Receipt")]
    result = validate_sipoc(sipoc, _pdd_steps("step-01"))

    assert result.row_results[0].anchor_type == "section_label"
    assert result.row_results[0].has_source_anchor is True


def test_frame_id_anchor_emits_warning_and_is_counted():
    from app.agents.sipoc_validator import validate_sipoc

    sipoc = [_sipoc_row(source_anchor="frame-042")]
    result = validate_sipoc(sipoc, _pdd_steps("step-01"))

    assert result.row_results[0].anchor_type == "frame_id"
    assert result.frame_id_only_count == 1
    flag_codes = [f["code"] for f in result.flags]
    assert "sipoc_frame_id_only" in flag_codes
    assert any(f["severity"] == "warning" for f in result.flags if f["code"] == "sipoc_frame_id_only")


def test_frame_id_underscore_variant_detected():
    from app.agents.sipoc_validator import validate_sipoc

    sipoc = [_sipoc_row(source_anchor="frame_007")]
    result = validate_sipoc(sipoc, _pdd_steps("step-01"))

    assert result.row_results[0].anchor_type == "frame_id"


def test_empty_source_anchor_classified_as_missing():
    from app.agents.sipoc_validator import validate_sipoc

    sipoc = [_sipoc_row(source_anchor="", anchor_missing_reason="not captured")]
    result = validate_sipoc(sipoc, _pdd_steps("step-01"))

    assert result.row_results[0].anchor_type == "missing"
    assert result.row_results[0].has_source_anchor is False


# ---------------------------------------------------------------------------
# anchor_missing_reason requirements
# ---------------------------------------------------------------------------

def test_no_step_anchor_without_reason_emits_warning():
    from app.agents.sipoc_validator import validate_sipoc

    sipoc = [_sipoc_row(step_anchor=[], anchor_missing_reason=None)]
    result = validate_sipoc(sipoc, _pdd_steps("step-01"))

    flag_codes = [f["code"] for f in result.flags]
    assert "sipoc_missing_reason_absent" in flag_codes


def test_no_step_anchor_with_reason_suppresses_warning():
    from app.agents.sipoc_validator import validate_sipoc

    sipoc = [_sipoc_row(step_anchor=[], anchor_missing_reason="Legacy row without step mapping")]
    result = validate_sipoc(sipoc, _pdd_steps("step-01"))

    flag_codes = [f["code"] for f in result.flags]
    assert "sipoc_missing_reason_absent" not in flag_codes


def test_no_source_anchor_without_reason_emits_warning():
    from app.agents.sipoc_validator import validate_sipoc

    sipoc = [_sipoc_row(
        step_anchor=["step-01"],
        source_anchor="",
        anchor_missing_reason=None,
    )]
    result = validate_sipoc(sipoc, _pdd_steps("step-01"))

    flag_codes = [f["code"] for f in result.flags]
    assert "sipoc_missing_reason_absent" in flag_codes


# ---------------------------------------------------------------------------
# Per-row result structure
# ---------------------------------------------------------------------------

def test_row_results_count_matches_sipoc_length():
    from app.agents.sipoc_validator import validate_sipoc

    sipoc = [_sipoc_row(), _sipoc_row(step_anchor=["step-02"])]
    result = validate_sipoc(sipoc, _pdd_steps("step-01", "step-02"))

    assert len(result.row_results) == 2


def test_fully_valid_row_is_marked_valid():
    from app.agents.sipoc_validator import validate_sipoc

    sipoc = [_sipoc_row(step_anchor=["step-01"], source_anchor="00:00:00-00:01:00")]
    result = validate_sipoc(sipoc, _pdd_steps("step-01"))

    assert result.row_results[0].valid is True
    assert result.row_results[0].missing_fields == []
    assert result.row_results[0].invalid_step_refs == []


def test_row_with_missing_fields_is_marked_invalid():
    from app.agents.sipoc_validator import validate_sipoc

    sipoc = [_sipoc_row(supplier="")]
    result = validate_sipoc(sipoc, _pdd_steps("step-01"))

    assert result.row_results[0].valid is False
    assert "supplier" in result.row_results[0].missing_fields


# ---------------------------------------------------------------------------
# Integration with reviewing agent
# ---------------------------------------------------------------------------

def test_reviewing_agent_uses_sipoc_validator_for_frame_id_warning():
    """Reviewing agent emits sipoc_frame_id_only warning via SIPOCValidator."""
    import pathlib
    import sys
    from uuid import uuid4

    from app.agents.reviewing import run_reviewing
    from app.job_logic import InputFile, JobCreateRequest, default_job_payload

    files = [
        InputFile(source_type="video", size_bytes=100, audio_detected=True),
        InputFile(source_type="transcript", size_bytes=50),
    ]
    req = JobCreateRequest(profile="balanced", input_files=files)
    job = default_job_payload(req)
    job["job_id"] = str(uuid4())
    job["has_audio"] = True

    pdd = {
        "purpose": "Test", "scope": "In scope", "triggers": ["t"],
        "preconditions": ["p"], "steps": [{"id": "step-01", "summary": "s"}],
        "roles": ["Actor"], "systems": ["Sys"], "business_rules": ["r"],
        "exceptions": [], "outputs": ["o"],
        "metrics": {"coverage": "high", "confidence": 0.85}, "risks": [],
    }
    sipoc = [{
        "step_anchor": ["step-01"],
        "source_anchor": "frame-007",
        "supplier": "S", "input": "I", "process_step": "P",
        "output": "O", "customer": "C", "anchor_missing_reason": None,
    }]
    job["draft"] = {
        "pdd": pdd, "sipoc": sipoc,
        "confidence_summary": {"overall": 0.80, "source_quality": "high", "evidence_strength": "high"},
    }
    job["extracted_evidence"] = {
        "evidence_items": [], "speakers_detected": [],
        "process_domain": "test", "transcript_quality": "medium",
    }

    run_reviewing(job, {"profile": "balanced", "model": "gpt-4o-mini", "cost_cap_usd": 4.0})

    flag_codes = [f["code"] for f in job["review_notes"]["flags"]]
    assert "sipoc_frame_id_only" in flag_codes


def test_reviewing_agent_emits_sipoc_invalid_step_ref():
    """Reviewing agent flags SIPOC rows referencing non-existent PDD steps."""
    from uuid import uuid4

    from app.agents.reviewing import run_reviewing
    from app.job_logic import InputFile, JobCreateRequest, default_job_payload

    files = [
        InputFile(source_type="video", size_bytes=100, audio_detected=True),
        InputFile(source_type="transcript", size_bytes=50),
    ]
    req = JobCreateRequest(profile="balanced", input_files=files)
    job = default_job_payload(req)
    job["job_id"] = str(uuid4())
    job["has_audio"] = True

    pdd = {
        "purpose": "Test", "scope": "In scope", "triggers": ["t"],
        "preconditions": ["p"], "steps": [{"id": "step-01"}],
        "roles": ["Actor"], "systems": ["Sys"], "business_rules": ["r"],
        "exceptions": [], "outputs": ["o"],
        "metrics": {"coverage": "high", "confidence": 0.85}, "risks": [],
    }
    sipoc = [{
        "step_anchor": ["step-99"],  # does not exist
        "source_anchor": "00:00:00-00:01:00",
        "supplier": "S", "input": "I", "process_step": "P",
        "output": "O", "customer": "C", "anchor_missing_reason": None,
    }]
    job["draft"] = {
        "pdd": pdd, "sipoc": sipoc,
        "confidence_summary": {"overall": 0.80, "source_quality": "high", "evidence_strength": "high"},
    }
    job["extracted_evidence"] = {
        "evidence_items": [], "speakers_detected": [],
        "process_domain": "test", "transcript_quality": "medium",
    }

    run_reviewing(job, {"profile": "balanced", "model": "gpt-4o-mini", "cost_cap_usd": 4.0})

    flag_codes = [f["code"] for f in job["review_notes"]["flags"]]
    assert "sipoc_invalid_step_ref" in flag_codes
