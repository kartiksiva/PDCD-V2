"""Unit tests for agent layer: extraction, processing, reviewing."""

from __future__ import annotations

import json
import os
import pathlib
import sys
import importlib
from typing import Any, Dict
from types import SimpleNamespace
from unittest.mock import MagicMock, AsyncMock, patch
from uuid import uuid4

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
FIXTURES = ROOT / "tests" / "fixtures"
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("AZURE_OPENAI_CHAT_DEPLOYMENT_NAME", "test-deployment")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_fixture(scenario: str, filename: str) -> str:
    return (FIXTURES / scenario / filename).read_text(encoding="utf-8")


def _load_expected(scenario: str) -> Dict[str, Any]:
    return json.loads(_load_fixture(scenario, "expected_draft.json"))


def _make_job(
    *,
    has_video: bool = True,
    has_audio: bool = True,
    has_transcript: bool = True,
    consistency_verdict: str = "match",
) -> Dict[str, Any]:
    from app.job_logic import InputFile, JobCreateRequest, default_job_payload

    files = []
    if has_video:
        files.append(InputFile(source_type="video", size_bytes=100, audio_detected=has_audio))
    if has_transcript:
        files.append(InputFile(source_type="transcript", size_bytes=50))

    req = JobCreateRequest(profile="balanced", input_files=files)
    job = default_job_payload(req)
    job["job_id"] = str(uuid4())
    # Override booleans directly — default_job_payload derives has_audio from source_type=="audio"
    # but tests control audio via the video file's audio_detected flag.
    job["has_audio"] = has_audio
    job["transcript_media_consistency"]["verdict"] = consistency_verdict
    return job


def _balanced_profile() -> Dict[str, Any]:
    return {"profile": "balanced", "model": "gpt-4o-mini", "cost_cap_usd": 4.0}


def _async_sk_response(content: str, prompt_tokens: int = 100, completion_tokens: int = 200):
    """Return an async fake for _call_extraction / _call_processing."""
    async def _fake(*args, **kwargs):
        return content, prompt_tokens, completion_tokens
    return _fake


# ---------------------------------------------------------------------------
# Extraction agent tests
# ---------------------------------------------------------------------------

def test_extraction_agent_scenario_a(monkeypatch):
    """Extraction agent parses scenario A transcript into >= 8 evidence items with non-empty anchors."""
    from app.agents.extraction import run_extraction

    transcript = _load_fixture("scenario_a", "transcript.vtt")
    expected = _load_expected("scenario_a")
    mock_result = {"evidence_items": expected["extracted_evidence"]["evidence_items"],
                   "speakers_detected": ["Finance Analyst", "AP Manager"],
                   "process_domain": "Accounts Payable — Invoice Approval",
                   "transcript_quality": "high"}

    job = _make_job()
    job["_transcript_text_inline"] = transcript

    with patch("app.agents.extraction._call_extraction",
               side_effect=_async_sk_response(json.dumps(mock_result), 100, 200)):
        cost = run_extraction(job, _balanced_profile())

    evidence = job.get("extracted_evidence", {})
    items = evidence.get("evidence_items", [])
    assert len(items) >= 8, f"Expected >= 8 evidence items, got {len(items)}"
    for item in items:
        assert item.get("anchor"), f"Item {item.get('id')} has no anchor"
    assert job["agent_signals"]["transcript_parsed"] is True
    assert cost >= 0.0


def test_extraction_agent_no_transcript_graceful():
    """Extraction agent returns empty evidence and cost=0 when no supported content is available."""
    from app.agents.extraction import run_extraction

    job = _make_job(has_video=False, has_transcript=False)

    cost = run_extraction(job, _balanced_profile())

    assert cost == 0.0
    assert job["extracted_evidence"]["evidence_items"] == []
    assert job["agent_signals"]["transcript_parsed"] is False


def test_extraction_cost_calculation(monkeypatch):
    """Cost should equal (prompt * 0.15 + completion * 0.60) / 1_000_000."""
    from app.agents.extraction import run_extraction

    mock_result = {"evidence_items": [], "speakers_detected": [], "process_domain": "test", "transcript_quality": "low"}

    job = _make_job()
    job["_transcript_text_inline"] = "some transcript text"

    with patch("app.agents.extraction._call_extraction",
               side_effect=_async_sk_response(json.dumps(mock_result), 1000, 500)):
        cost = run_extraction(job, _balanced_profile())

    expected_cost = (1000 * 0.15 + 500 * 0.60) / 1_000_000
    assert abs(cost - expected_cost) < 1e-9


def test_extraction_usage_tokens_supports_object_usage():
    from app.agents.extraction import _extract_usage_tokens

    prompt_tokens, completion_tokens = _extract_usage_tokens(
        {"usage": SimpleNamespace(prompt_tokens=123, completion_tokens=45)}
    )

    assert prompt_tokens == 123
    assert completion_tokens == 45


def test_extraction_times_out_long_llm_call(monkeypatch):
    import asyncio

    from app.agents.extraction import run_extraction

    job = _make_job()
    job["_transcript_text_inline"] = "some transcript text"

    async def _never_returns(*_args, **_kwargs):
        await asyncio.sleep(10)

    monkeypatch.setenv("PFCD_LLM_TIMEOUT_SECONDS", "0.01")

    with patch("app.agents.extraction._call_extraction", side_effect=_never_returns):
        with pytest.raises(RuntimeError, match="timed out"):
            run_extraction(job, _balanced_profile())


def test_processing_usage_tokens_supports_dict_usage():
    from app.agents.processing import _extract_usage_tokens

    prompt_tokens, completion_tokens = _extract_usage_tokens(
        {"usage": {"prompt_tokens": 10, "completion_tokens": 20}}
    )

    assert prompt_tokens == 10
    assert completion_tokens == 20


def test_processing_usage_tokens_defaults_to_zero_when_missing():
    from app.agents.processing import _extract_usage_tokens

    prompt_tokens, completion_tokens = _extract_usage_tokens({})

    assert prompt_tokens == 0
    assert completion_tokens == 0


def test_processing_times_out_long_llm_call(monkeypatch):
    import asyncio

    from app.agents.processing import run_processing

    job = _make_job()
    job["extracted_evidence"] = {
        "evidence_items": [],
        "speakers_detected": [],
        "process_domain": "test",
        "transcript_quality": "low",
    }

    async def _never_returns(*_args, **_kwargs):
        await asyncio.sleep(10)

    monkeypatch.setenv("PFCD_LLM_TIMEOUT_SECONDS", "0.01")

    with patch("app.agents.processing._call_processing", side_effect=_never_returns):
        with pytest.raises(RuntimeError, match="timed out"):
            run_processing(job, _balanced_profile())


# ---------------------------------------------------------------------------
# Processing agent tests
# ---------------------------------------------------------------------------

def test_processing_agent_populates_draft(monkeypatch):
    """Processing agent stores draft with required PDD and SIPOC keys."""
    from app.agents.processing import run_processing

    expected = _load_expected("scenario_a")
    mock_draft = expected["draft"]

    job = _make_job()
    job["extracted_evidence"] = expected["extracted_evidence"]

    with patch("app.agents.processing._call_processing",
               side_effect=_async_sk_response(json.dumps(mock_draft), 100, 200)):
        cost = run_processing(job, _balanced_profile())

    assert job.get("draft") is not None
    pdd = job["draft"].get("pdd", {})
    for key in ["purpose", "scope", "steps", "roles", "systems"]:
        assert key in pdd, f"PDD missing key: {key}"
    assert isinstance(job["draft"].get("sipoc"), list)
    assert cost >= 0.0


def test_processing_agent_sipoc_rows_have_anchors(monkeypatch):
    from app.agents.processing import run_processing

    expected = _load_expected("scenario_a")
    job = _make_job()
    job["extracted_evidence"] = expected["extracted_evidence"]

    with patch(
        "app.agents.processing._call_processing",
        side_effect=_async_sk_response(json.dumps(expected["draft"]), 100, 200),
    ):
        run_processing(job, _balanced_profile())

    for row in job["draft"]["sipoc"]:
        assert len(row["step_anchor"]) >= 1
        assert row["source_anchor"] != ""


def test_processing_agent_sets_defaults_on_minimal_response(monkeypatch):
    """Processing agent fills in defaults when LLM returns minimal JSON."""
    from app.agents.processing import run_processing

    minimal_draft = {"pdd": {"purpose": "test"}, "sipoc": []}

    job = _make_job()
    job["extracted_evidence"] = {"evidence_items": [], "speakers_detected": [], "process_domain": "test", "transcript_quality": "low"}

    with patch("app.agents.processing._call_processing",
               side_effect=_async_sk_response(json.dumps(minimal_draft), 80, 40)):
        run_processing(job, _balanced_profile())

    assert job["draft"]["version"] == 1
    assert "generated_at" in job["draft"]
    assert "confidence_summary" in job["draft"]


# ---------------------------------------------------------------------------
# Reviewing agent tests
# ---------------------------------------------------------------------------

def _job_with_draft(draft: Dict[str, Any], **kwargs) -> Dict[str, Any]:
    job = _make_job(**kwargs)
    job["draft"] = draft
    job["extracted_evidence"] = {"evidence_items": [], "speakers_detected": [], "process_domain": "test", "transcript_quality": "medium"}
    return job


def _full_pdd() -> Dict[str, Any]:
    return {
        "purpose": "Test process",
        "scope": "In scope",
        "triggers": ["trigger"],
        "preconditions": ["precondition"],
        "steps": [{"id": "step-01"}],
        "roles": ["Actor"],
        "systems": ["System"],
        "business_rules": ["Rule"],
        "exceptions": [],
        "outputs": ["Output"],
        "metrics": {"coverage": "high", "confidence": 0.85},
        "risks": [],
    }


def _full_sipoc() -> list:
    return [{"step_anchor": ["step-01"], "source_anchor": "00:00:00-00:01:00", "supplier": "S", "input": "I", "process_step": "P", "output": "O", "customer": "C", "anchor_missing_reason": None}]


def test_reviewing_sets_approve_for_draft_on_high_evidence():
    """Reviewing agent approves draft when video + audio + transcript are all present and draft is complete."""
    from app.agents.reviewing import run_reviewing

    draft = {"pdd": _full_pdd(), "sipoc": _full_sipoc(), "confidence_summary": {"overall": 0.88, "source_quality": "high", "evidence_strength": "high"}}
    job = _job_with_draft(draft, has_video=True, has_audio=True, has_transcript=True, consistency_verdict="match")

    cost = run_reviewing(job, _balanced_profile())

    assert cost == 0.0
    assert job["agent_review"]["decision"] == "approve_for_draft"
    assert job["agent_signals"]["evidence_strength"] == "high"
    assert not any(f["severity"] == "blocker" for f in job["review_notes"]["flags"])


def test_reviewing_sets_transcript_mismatch_flag():
    """Reviewing agent adds transcript_mismatch WARNING when consistency verdict is suspected_mismatch."""
    from app.agents.reviewing import run_reviewing

    draft = {"pdd": _full_pdd(), "sipoc": _full_sipoc(), "confidence_summary": {"overall": 0.62, "source_quality": "medium", "evidence_strength": "high"}}
    job = _job_with_draft(draft, has_video=True, has_audio=True, has_transcript=True, consistency_verdict="suspected_mismatch")

    run_reviewing(job, _balanced_profile())

    flag_codes = [f["code"] for f in job["review_notes"]["flags"]]
    assert "transcript_mismatch" in flag_codes
    # mismatch alone is a warning, not a blocker → decision should be needs_review
    assert job["agent_review"]["decision"] == "needs_review"


def test_reviewing_blocks_on_insufficient_evidence():
    """Reviewing agent sets decision=blocked when video only (no audio, no transcript)."""
    from app.agents.reviewing import run_reviewing

    draft = {"pdd": _full_pdd(), "sipoc": _full_sipoc(), "confidence_summary": {"overall": 0.40, "source_quality": "low", "evidence_strength": "low"}}
    job = _job_with_draft(draft, has_video=True, has_audio=False, has_transcript=False, consistency_verdict="inconclusive")

    run_reviewing(job, _balanced_profile())

    flag_codes = [f["code"] for f in job["review_notes"]["flags"]]
    assert "insufficient_evidence" in flag_codes
    assert job["agent_review"]["decision"] == "blocked"
    assert job["agent_signals"]["evidence_strength"] == "low"


def test_reviewing_sets_frame_first_evidence_flag():
    """Reviewing agent adds frame_first_evidence WARNING for video+transcript without audio."""
    from app.agents.reviewing import run_reviewing

    draft = {"pdd": _full_pdd(), "sipoc": _full_sipoc(), "confidence_summary": {"overall": 0.68, "source_quality": "medium", "evidence_strength": "medium"}}
    job = _job_with_draft(draft, has_video=True, has_audio=False, has_transcript=True, consistency_verdict="match")

    run_reviewing(job, _balanced_profile())

    flag_codes = [f["code"] for f in job["review_notes"]["flags"]]
    assert "frame_first_evidence" in flag_codes
    assert job["agent_signals"]["evidence_strength"] == "medium"
    assert job["agent_review"]["decision"] == "needs_review"


def test_reviewing_sets_transcript_fallback_flag():
    """Reviewing agent adds transcript_fallback WARNING when transcript only (no video/audio)."""
    from app.agents.reviewing import run_reviewing

    draft = {"pdd": _full_pdd(), "sipoc": _full_sipoc(), "confidence_summary": {"overall": 0.65, "source_quality": "medium", "evidence_strength": "medium"}}
    job = _job_with_draft(draft, has_video=False, has_audio=False, has_transcript=True, consistency_verdict="inconclusive")

    run_reviewing(job, _balanced_profile())

    flag_codes = [f["code"] for f in job["review_notes"]["flags"]]
    assert "transcript_fallback" in flag_codes
    assert job["agent_review"]["decision"] == "needs_review"


def test_reviewing_blocks_stub_draft_source():
    from app.agents.reviewing import run_reviewing

    draft = {
        "draft_source": "stub",
        "pdd": _full_pdd(),
        "sipoc": _full_sipoc(),
        "confidence_summary": {"overall": 0.65, "source_quality": "medium", "evidence_strength": "medium"},
    }
    job = _job_with_draft(draft, has_video=True, has_audio=True, has_transcript=True, consistency_verdict="match")

    run_reviewing(job, _balanced_profile())

    by_code = {f["code"]: f for f in job["review_notes"]["flags"]}
    assert "stub_draft_detected" in by_code
    assert by_code["stub_draft_detected"]["severity"] == "blocker"
    assert job["agent_review"]["decision"] == "blocked"


def test_reviewing_blocks_on_incomplete_pdd():
    """Reviewing agent sets decision=blocked when PDD is missing required keys."""
    from app.agents.reviewing import run_reviewing

    incomplete_pdd = {"purpose": "Test"}  # missing most required fields
    draft = {"pdd": incomplete_pdd, "sipoc": _full_sipoc(), "confidence_summary": {"overall": 0.5, "source_quality": "medium", "evidence_strength": "medium"}}
    job = _job_with_draft(draft, has_video=True, has_audio=True, has_transcript=True)

    run_reviewing(job, _balanced_profile())

    flag_codes = [f["code"] for f in job["review_notes"]["flags"]]
    assert "pdd_incomplete" in flag_codes
    assert job["agent_review"]["decision"] == "blocked"


def test_reviewing_blocks_on_sipoc_no_anchor():
    """Reviewing agent sets decision=blocked when no SIPOC row has both anchors."""
    from app.agents.reviewing import run_reviewing

    no_anchor_sipoc = [{"step_anchor": [], "source_anchor": "", "supplier": "S", "input": "I", "process_step": "P", "output": "O", "customer": "C", "anchor_missing_reason": "no data"}]
    draft = {"pdd": _full_pdd(), "sipoc": no_anchor_sipoc, "confidence_summary": {"overall": 0.5, "source_quality": "medium", "evidence_strength": "medium"}}
    job = _job_with_draft(draft, has_video=True, has_audio=True, has_transcript=True)

    run_reviewing(job, _balanced_profile())

    flag_codes = [f["code"] for f in job["review_notes"]["flags"]]
    assert "sipoc_no_anchor" in flag_codes
    assert job["agent_review"]["decision"] == "blocked"


def test_reviewing_flags_unknown_speaker():
    """Reviewing agent adds unknown_speaker WARNING when speakers list contains 'Unknown'."""
    from app.agents.reviewing import run_reviewing

    draft = {"pdd": _full_pdd(), "sipoc": _full_sipoc(), "confidence_summary": {"overall": 0.85, "source_quality": "high", "evidence_strength": "high"}}
    job = _job_with_draft(draft, has_video=True, has_audio=True, has_transcript=True)
    job["extracted_evidence"]["speakers_detected"] = ["Finance Analyst", "Unknown"]

    run_reviewing(job, _balanced_profile())

    flag_codes = [f["code"] for f in job["review_notes"]["flags"]]
    assert "unknown_speaker" in flag_codes


# ---------------------------------------------------------------------------
# load_transcript_text helper tests
# ---------------------------------------------------------------------------

def test_load_transcript_text_inline_fallback():
    """load_transcript_text returns inline text when _transcript_text_inline is set."""
    from app.job_logic import load_transcript_text

    job = _make_job()
    job["_transcript_text_inline"] = "Hello world transcript"
    # Remove any file-based inputs to ensure fallback is used
    job["input_manifest"]["inputs"] = []

    result = load_transcript_text(job, storage=MagicMock())
    assert result == "Hello world transcript"


def test_load_transcript_text_from_storage(tmp_path):
    """load_transcript_text reads transcript bytes from storage when file is configured."""
    from app.job_logic import load_transcript_text

    job = _make_job()
    job["input_manifest"]["inputs"] = [
        {"source_type": "transcript", "file_name": "transcript.vtt", "size_bytes": 100}
    ]

    mock_storage = MagicMock()
    mock_storage.load_bytes.return_value = b"Stored transcript content"

    result = load_transcript_text(job, storage=mock_storage)
    assert result == "Stored transcript content"
    mock_storage.load_bytes.assert_called_once()


def test_load_transcript_text_returns_none_on_storage_error():
    """load_transcript_text returns None if storage raises an exception."""
    from app.job_logic import load_transcript_text

    job = _make_job()
    job["input_manifest"]["inputs"] = [
        {"source_type": "transcript", "file_name": "transcript.vtt", "size_bytes": 100}
    ]

    mock_storage = MagicMock()
    mock_storage.load_bytes.side_effect = FileNotFoundError("blob not found")

    result = load_transcript_text(job, storage=mock_storage)
    assert result is None


def test_load_transcript_text_returns_none_when_no_transcript():
    """load_transcript_text returns None when no transcript input is present."""
    from app.job_logic import load_transcript_text

    job = _make_job(has_transcript=False)
    job["input_manifest"]["inputs"] = [
        {"source_type": "video", "file_name": "recording.mp4", "size_bytes": 5000}
    ]

    result = load_transcript_text(job, storage=MagicMock())
    assert result is None


def test_normalize_input_video_only(monkeypatch):
    from app.agents.extraction import _normalize_input

    job = _make_job(has_video=True, has_audio=True, has_transcript=False)
    job["input_manifest"]["video"]["storage_key"] = "/tmp/demo.mp4"

    with patch(
        "app.agents.adapters.video.transcribe_audio_blob",
        return_value=(
            "WEBVTT\n\n00:00:00.000 --> 00:00:03.000\nFinance Analyst: Open SAP.\n"
        ),
    ):
        content_text, manifests = _normalize_input(job)

    assert content_text.startswith("WEBVTT")
    assert any(m["source_type"] == "video" for m in manifests)


def test_normalize_input_video_and_transcript(monkeypatch):
    from app.agents.extraction import _normalize_input

    transcript = _load_fixture("scenario_a", "transcript.vtt")
    job = _make_job(has_video=True, has_audio=True, has_transcript=True)
    job["_transcript_text_inline"] = transcript
    job["input_manifest"]["video"]["storage_key"] = "/tmp/demo.mp4"

    with patch(
        "app.agents.adapters.video.transcribe_audio_blob",
        return_value=(
            "WEBVTT\n\n00:00:00.000 --> 00:00:03.000\nFinance Analyst: Open SAP.\n"
        ),
    ):
        content_text, manifests = _normalize_input(job)

    assert content_text.startswith("VIDEO TRANSCRIPT:\nWEBVTT")
    assert "\n\nUPLOADED TRANSCRIPT:\n" in content_text
    assert any(m["source_type"] == "transcript" for m in manifests)
    assert any(m["source_type"] == "video" for m in manifests)


# ---------------------------------------------------------------------------
# Anchor alignment tests
# ---------------------------------------------------------------------------

def test_alignment_valid_vtt_timestamp_anchor():
    """Anchor matching a VTT cue range is validated and typed as timestamp_range."""
    from app.agents.alignment import run_anchor_alignment

    transcript = _load_fixture("scenario_a", "transcript.vtt")
    job = _make_job()
    job["_transcript_text_inline"] = transcript
    job["extracted_evidence"] = {
        "evidence_items": [
            {"id": "ev-01", "summary": "test", "anchor": "00:00:12-00:00:28", "confidence": 0.9}
        ],
        "speakers_detected": [],
        "process_domain": "test",
        "transcript_quality": "high",
    }

    run_anchor_alignment(job)

    item = job["extracted_evidence"]["evidence_items"][0]
    assert item["anchor_alignment"]["valid"] is True
    assert item["anchor_alignment"]["anchor_type"] == "timestamp_range"
    assert item["anchor_alignment"]["confidence_penalty"] == 0.0
    summary = job["agent_signals"]["anchor_alignment_summary"]
    assert summary["validated"] == 1
    assert summary["invalid"] == 0
    assert summary["skipped"] is False


def test_alignment_section_label_anchor():
    """Anchor matching a section heading in a plain-text transcript is validated."""
    from app.agents.alignment import run_anchor_alignment

    transcript = _load_fixture("scenario_d", "transcript.txt")
    job = _make_job()
    job["_transcript_text_inline"] = transcript
    job["extracted_evidence"] = {
        "evidence_items": [
            {"id": "ev-01", "summary": "test", "anchor": "Section 1: Invoice Receipt and Initial Review", "confidence": 0.8}
        ],
        "speakers_detected": [],
        "process_domain": "test",
        "transcript_quality": "high",
    }

    run_anchor_alignment(job)

    item = job["extracted_evidence"]["evidence_items"][0]
    assert item["anchor_alignment"]["valid"] is True
    assert item["anchor_alignment"]["anchor_type"] == "section_label"
    assert item["anchor_alignment"]["confidence_penalty"] == 0.0


def test_alignment_out_of_range_anchor_applies_penalty():
    """An anchor timestamp outside all VTT cues is invalid and reduces item confidence."""
    from app.agents.alignment import run_anchor_alignment

    transcript = _load_fixture("scenario_a", "transcript.vtt")
    job = _make_job()
    job["_transcript_text_inline"] = transcript
    job["extracted_evidence"] = {
        "evidence_items": [
            {"id": "ev-01", "summary": "test", "anchor": "09:00:00-09:01:00", "confidence": 0.8}
        ],
        "speakers_detected": [],
        "process_domain": "test",
        "transcript_quality": "high",
    }

    run_anchor_alignment(job)

    item = job["extracted_evidence"]["evidence_items"][0]
    assert item["anchor_alignment"]["valid"] is False
    assert item["anchor_alignment"]["confidence_penalty"] > 0.0
    assert item["confidence"] < 0.8
    assert job["agent_signals"]["anchor_alignment_summary"]["invalid"] == 1


def test_alignment_no_transcript_is_noop():
    """run_anchor_alignment skips gracefully when no transcript or evidence items exist."""
    from app.agents.alignment import run_anchor_alignment

    job = _make_job()
    # No transcript, no evidence items
    job["extracted_evidence"] = {"evidence_items": [], "speakers_detected": [], "process_domain": "test", "transcript_quality": "low"}

    run_anchor_alignment(job)

    summary = job["agent_signals"]["anchor_alignment_summary"]
    assert summary["skipped"] is True
    assert summary["validated"] == 0


def test_alignment_unknown_anchor_type_is_penalized():
    """An anchor that is neither a timestamp nor a known section label gets a penalty."""
    from app.agents.alignment import run_anchor_alignment

    transcript = _load_fixture("scenario_a", "transcript.vtt")
    job = _make_job()
    job["_transcript_text_inline"] = transcript
    job["extracted_evidence"] = {
        "evidence_items": [
            {"id": "ev-01", "summary": "test", "anchor": "N/A", "confidence": 0.7}
        ],
        "speakers_detected": [],
        "process_domain": "test",
        "transcript_quality": "medium",
    }

    run_anchor_alignment(job)

    item = job["extracted_evidence"]["evidence_items"][0]
    assert item["anchor_alignment"]["valid"] is False
    assert item["anchor_alignment"]["confidence_penalty"] > 0.0


def test_alignment_within_tolerance_is_valid():
    """Anchor slightly outside cue boundary but within 2s tolerance is accepted."""
    from app.agents.alignment import run_anchor_alignment

    transcript = _load_fixture("scenario_a", "transcript.vtt")
    # VTT cue: 00:00:12.000 --> 00:00:28.000
    # Anchor shifted by ~1 second on each side, still within tolerance
    job = _make_job()
    job["_transcript_text_inline"] = transcript
    job["extracted_evidence"] = {
        "evidence_items": [
            {"id": "ev-01", "summary": "test", "anchor": "00:00:11-00:00:29", "confidence": 0.85}
        ],
        "speakers_detected": [],
        "process_domain": "test",
        "transcript_quality": "high",
    }

    run_anchor_alignment(job)

    item = job["extracted_evidence"]["evidence_items"][0]
    assert item["anchor_alignment"]["valid"] is True
    assert item["confidence"] == 0.85  # no penalty applied


# ---------------------------------------------------------------------------
# Evidence strength computation tests
# ---------------------------------------------------------------------------

def test_evidence_strength_high_all_sources():
    from app.agents.evidence import compute_evidence_strength
    assert compute_evidence_strength(True, True, True) == "high"


def test_evidence_strength_high_video_audio_no_transcript():
    from app.agents.evidence import compute_evidence_strength
    assert compute_evidence_strength(True, True, False) == "high"


def test_evidence_strength_medium_video_transcript_no_audio():
    from app.agents.evidence import compute_evidence_strength
    assert compute_evidence_strength(True, False, True) == "medium"


def test_evidence_strength_medium_transcript_only():
    from app.agents.evidence import compute_evidence_strength
    assert compute_evidence_strength(False, False, True) == "medium"


def test_evidence_strength_low_video_only():
    from app.agents.evidence import compute_evidence_strength
    assert compute_evidence_strength(True, False, False) == "low"


def test_evidence_strength_low_no_sources():
    from app.agents.evidence import compute_evidence_strength
    assert compute_evidence_strength(False, False, False) == "low"


def test_evidence_strength_degrades_on_low_confidence():
    """Low mean confidence demotes high -> medium."""
    from app.agents.evidence import compute_evidence_strength
    items = [{"confidence": 0.40}, {"confidence": 0.35}]
    assert compute_evidence_strength(True, True, True, evidence_items=items) == "medium"


def test_text_similarity_score_identical():
    from app.agents.alignment import _text_similarity_score

    score = _text_similarity_score("Approve invoice in SAP", "Approve invoice in SAP")

    assert score == 1.0


def test_text_similarity_score_match():
    from app.agents.alignment import _text_similarity_score

    score = _text_similarity_score(
        "Finance Analyst opens SAP and routes invoice for approval",
        "The finance analyst opens sap then routes the invoice for approval",
    )

    assert score >= 0.65


def test_text_similarity_score_mismatch():
    from app.agents.alignment import _text_similarity_score

    score = _text_similarity_score(
        "Approve vendor invoice in SAP and schedule payment",
        "Troubleshoot warehouse barcode scanner and reset mobile device",
    )

    assert score <= 0.3


def test_run_anchor_alignment_uses_text_similarity_when_video_transcript_present():
    from app.agents.alignment import run_anchor_alignment

    transcript = _load_fixture("scenario_a", "transcript.vtt")
    job = _make_job()
    job["_transcript_text_inline"] = transcript
    job["_video_transcript_inline"] = transcript
    job["extracted_evidence"] = {
        "evidence_items": [
            {"id": "ev-01", "summary": "test", "anchor": "00:00:12-00:00:28", "confidence": 0.9}
        ],
        "speakers_detected": [],
        "process_domain": "test",
        "transcript_quality": "high",
    }

    run_anchor_alignment(job)

    summary = job["agent_signals"]["anchor_alignment_summary"]
    assert summary["consistency_method"] == "text_similarity"
    assert summary["similarity_score"] >= 0.99


def test_anchor_alignment_fallback_uses_configurable_inconclusive_threshold(monkeypatch):
    import app.agents.alignment as alignment

    monkeypatch.setenv("PFCD_CONSISTENCY_INCONCLUSIVE_THRESHOLD", "0.60")
    alignment = importlib.reload(alignment)
    try:
        transcript = _load_fixture("scenario_a", "transcript.vtt")
        job = _make_job()
        job["_transcript_text_inline"] = transcript
        job["extracted_evidence"] = {
            "evidence_items": [
                {"id": "ev-01", "summary": "test", "anchor": "00:00:12-00:00:28", "confidence": 0.9},
            ],
            "speakers_detected": [],
            "process_domain": "test",
            "transcript_quality": "high",
        }
        monkeypatch.setattr(
            alignment,
            "_consistency_score_from_anchors",
            lambda evidence_items, window_sec: (0.5, 1, 2),
        )

        alignment.run_anchor_alignment(job)

        summary = job["agent_signals"]["anchor_alignment_summary"]
        assert summary["consistency_method"] == "anchor_validity_proxy"
        assert summary["similarity_score"] == 0.5
        assert summary["verdict"] == "suspected_mismatch"
    finally:
        monkeypatch.delenv("PFCD_CONSISTENCY_INCONCLUSIVE_THRESHOLD", raising=False)
        importlib.reload(alignment)


def test_evidence_strength_medium_degrades_on_low_confidence():
    """Low mean confidence demotes medium -> low."""
    from app.agents.evidence import compute_evidence_strength
    items = [{"confidence": 0.30}]
    assert compute_evidence_strength(False, False, True, evidence_items=items) == "low"


def test_evidence_strength_preserved_on_high_confidence():
    """High mean confidence does not promote beyond structural cap."""
    from app.agents.evidence import compute_evidence_strength
    items = [{"confidence": 0.95}]
    # Transcript-only structural cap is medium; high confidence cannot make it high
    assert compute_evidence_strength(False, False, True, evidence_items=items) == "medium"


def test_reviewing_uses_computed_evidence_strength():
    """Reviewing agent reflects confidence-degraded evidence_strength, not hardcoded value."""
    from app.agents.reviewing import run_reviewing

    draft = {"pdd": _full_pdd(), "sipoc": _full_sipoc(), "confidence_summary": {"overall": 0.88, "source_quality": "high", "evidence_strength": "high"}}
    job = _job_with_draft(draft, has_video=True, has_audio=True, has_transcript=True)
    # Inject low-confidence evidence items so structural "high" degrades to "medium"
    job["extracted_evidence"]["evidence_items"] = [
        {"id": "ev-01", "confidence": 0.35},
        {"id": "ev-02", "confidence": 0.40},
    ]

    run_reviewing(job, _balanced_profile())

    assert job["agent_signals"]["evidence_strength"] == "medium"
    # Degraded to medium means decision is needs_review, not approve_for_draft
    assert job["agent_review"]["decision"] == "needs_review"
