"""Unit tests for IProcessEvidenceAdapter implementations and AdapterRegistry."""

from __future__ import annotations

import json
import pathlib
import sys
from typing import Any, Dict
from unittest.mock import patch
from uuid import uuid4

ROOT = pathlib.Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
FIXTURES = ROOT / "tests" / "fixtures"
sys.path.insert(0, str(BACKEND))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_fixture(scenario: str, filename: str) -> str:
    return (FIXTURES / scenario / filename).read_text(encoding="utf-8")


def _make_job(
    *,
    has_video: bool = True,
    has_audio: bool = True,
    has_transcript: bool = True,
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
    job["has_audio"] = has_audio
    return job


# ---------------------------------------------------------------------------
# TranscriptAdapter — detect()
# ---------------------------------------------------------------------------

def test_transcript_adapter_detect_vtt_mime():
    from app.agents.adapters.transcript import TranscriptAdapter

    adapter = TranscriptAdapter()
    result = adapter.detect({"source_type": "transcript", "mime_type": "text/vtt", "file_name": "t.vtt"})
    assert result.valid is True
    assert result.document_type == "vtt"
    assert result.confidence >= 0.85


def test_transcript_adapter_detect_txt_extension():
    from app.agents.adapters.transcript import TranscriptAdapter

    adapter = TranscriptAdapter()
    result = adapter.detect({"source_type": "transcript", "mime_type": "text/plain", "file_name": "t.txt"})
    assert result.valid is True
    assert result.document_type == "txt"


def test_transcript_adapter_detect_rejects_non_transcript():
    from app.agents.adapters.transcript import TranscriptAdapter

    adapter = TranscriptAdapter()
    result = adapter.detect({"source_type": "video", "mime_type": "video/mp4", "file_name": "v.mp4"})
    assert result.valid is False


def test_transcript_adapter_detect_fallback_accepts_unknown_format():
    from app.agents.adapters.transcript import TranscriptAdapter

    adapter = TranscriptAdapter()
    result = adapter.detect({"source_type": "transcript"})
    assert result.valid is True
    assert result.confidence > 0.0


# ---------------------------------------------------------------------------
# TranscriptAdapter — normalize()
# ---------------------------------------------------------------------------

def test_transcript_adapter_normalize_vtt_strips_webvtt_header():
    from app.agents.adapters.transcript import TranscriptAdapter

    adapter = TranscriptAdapter()
    job = _make_job()
    job["_transcript_text_inline"] = _load_fixture("scenario_a", "transcript.vtt")

    ev = adapter.normalize(job)

    assert ev.source_type == "transcript"
    assert ev.document_type == "vtt"
    assert "WEBVTT" not in ev.content_text
    assert ev.content_text.strip() != ""


def test_transcript_adapter_normalize_vtt_produces_inline_anchors():
    from app.agents.adapters.transcript import TranscriptAdapter

    adapter = TranscriptAdapter()
    job = _make_job()
    job["_transcript_text_inline"] = _load_fixture("scenario_a", "transcript.vtt")

    ev = adapter.normalize(job)

    # Each cue should have [HH:MM:SS-HH:MM:SS] inline marker
    assert "[00:00:00-00:00:12]" in ev.content_text
    assert "[00:00:12-00:00:28]" in ev.content_text


def test_transcript_adapter_normalize_vtt_extracts_anchors_list():
    from app.agents.adapters.transcript import TranscriptAdapter

    adapter = TranscriptAdapter()
    job = _make_job()
    job["_transcript_text_inline"] = _load_fixture("scenario_a", "transcript.vtt")

    ev = adapter.normalize(job)

    # Scenario A has 15 VTT cues (more than the 12 extracted evidence items —
    # the LLM collapses some intro/transition cues during extraction)
    assert len(ev.anchors) == 15
    assert ev.anchors[0] == "00:00:00-00:00:12"
    assert ev.anchors[1] == "00:00:12-00:00:28"


def test_transcript_adapter_normalize_txt_returns_content_and_section_anchors():
    from app.agents.adapters.transcript import TranscriptAdapter

    adapter = TranscriptAdapter()
    job = _make_job()
    job["_transcript_text_inline"] = _load_fixture("scenario_d", "transcript.txt")

    ev = adapter.normalize(job)

    assert ev.document_type == "txt"
    assert ev.content_text.strip() != ""
    # Scenario D has section labels — at least one anchor expected
    assert len(ev.anchors) >= 1


def test_transcript_adapter_normalize_empty_returns_empty_evidence():
    from app.agents.adapters.transcript import TranscriptAdapter

    adapter = TranscriptAdapter()
    job = _make_job(has_transcript=False)
    # No _transcript_text_inline set

    ev = adapter.normalize(job)

    assert ev.content_text == ""
    assert ev.anchors == []
    assert ev.confidence == 0.0


def test_transcript_adapter_normalize_preserves_speaker_in_content():
    from app.agents.adapters.transcript import TranscriptAdapter

    adapter = TranscriptAdapter()
    job = _make_job()
    job["_transcript_text_inline"] = _load_fixture("scenario_a", "transcript.vtt")

    ev = adapter.normalize(job)

    # Speakers in scenario A — should be present in clean content
    assert "Finance Analyst" in ev.content_text
    assert "AP Manager" in ev.content_text


# ---------------------------------------------------------------------------
# TranscriptAdapter — extract_facts()
# ---------------------------------------------------------------------------

def test_transcript_adapter_extract_facts_returns_one_per_vtt_cue():
    from app.agents.adapters.transcript import TranscriptAdapter

    adapter = TranscriptAdapter()
    job = _make_job()
    job["_transcript_text_inline"] = _load_fixture("scenario_a", "transcript.vtt")

    facts = adapter.extract_facts(job)

    assert len(facts) == 15  # scenario_a has 15 VTT cues
    assert all(f.anchor for f in facts)
    assert all(f.content for f in facts)


def test_transcript_adapter_extract_facts_identifies_speakers():
    from app.agents.adapters.transcript import TranscriptAdapter

    adapter = TranscriptAdapter()
    job = _make_job()
    job["_transcript_text_inline"] = _load_fixture("scenario_a", "transcript.vtt")

    facts = adapter.extract_facts(job)

    speakers = {f.speaker for f in facts if f.speaker}
    assert "Finance Analyst" in speakers
    assert "AP Manager" in speakers


def test_extract_speaker_prefers_vtt_voice_tag():
    from app.agents.adapters.transcript import _extract_speaker

    assert _extract_speaker("<v Jane Doe>Welcome everyone") == "Jane Doe"


def test_extract_speaker_rejects_numeric_or_false_positive_prefixes():
    from app.agents.adapters.transcript import _extract_speaker

    assert _extract_speaker("3rd approver: Reviews ticket") is None
    assert _extract_speaker("Step 2: Validate invoice fields") is None
    assert _extract_speaker("Invoice approval: Manager approves request") is None


def test_transcript_adapter_extract_facts_returns_empty_on_no_content():
    from app.agents.adapters.transcript import TranscriptAdapter

    adapter = TranscriptAdapter()
    job = _make_job(has_transcript=False)

    facts = adapter.extract_facts(job)

    assert facts == []


# ---------------------------------------------------------------------------
# TranscriptAdapter — render_review_notes()
# ---------------------------------------------------------------------------

def test_transcript_adapter_render_review_notes_vtt():
    from app.agents.adapters.transcript import TranscriptAdapter

    adapter = TranscriptAdapter()
    job = _make_job()
    job["_transcript_text_inline"] = _load_fixture("scenario_a", "transcript.vtt")
    ev = adapter.normalize(job)

    notes = adapter.render_review_notes(ev)

    assert isinstance(notes, list)
    assert len(notes) > 0
    assert any("VTT" in n or "Anchor" in n or "anchor" in n for n in notes)


def test_transcript_adapter_render_review_notes_empty_reports_unavailable():
    from app.agents.adapters.transcript import TranscriptAdapter

    adapter = TranscriptAdapter()
    job = _make_job(has_transcript=False)
    ev = adapter.normalize(job)

    notes = adapter.render_review_notes(ev)

    assert any("unavailable" in n or "empty" in n for n in notes)


# ---------------------------------------------------------------------------
# VideoAdapter — detect()
# ---------------------------------------------------------------------------

def test_video_adapter_detect_video_with_audio():
    from app.agents.adapters.video import VideoAdapter

    adapter = VideoAdapter()
    result = adapter.detect({
        "source_type": "video",
        "mime_type": "video/mp4",
        "audio_detected": True,
    })
    assert result.valid is True
    assert result.document_type == "video"
    assert result.confidence == 0.75


def test_video_adapter_detect_video_without_audio_lower_confidence():
    from app.agents.adapters.video import VideoAdapter

    adapter = VideoAdapter()
    result = adapter.detect({
        "source_type": "video",
        "mime_type": "video/mp4",
        "audio_detected": False,
    })
    assert result.valid is True
    assert result.confidence == 0.45
    assert any("No audio" in n or "frame-first" in n for n in result.notes)


def test_video_adapter_detect_rejects_non_video():
    from app.agents.adapters.video import VideoAdapter

    adapter = VideoAdapter()
    result = adapter.detect({"source_type": "transcript", "mime_type": "text/plain"})
    assert result.valid is False


# ---------------------------------------------------------------------------
# VideoAdapter — normalize()
# ---------------------------------------------------------------------------

def test_video_adapter_normalize_returns_evidence_object():
    from app.agents.adapters.video import VideoAdapter

    adapter = VideoAdapter()
    job = _make_job(has_video=True, has_audio=True, has_transcript=False)

    ev = adapter.normalize(job)

    assert ev.source_type == "video"
    assert ev.document_type == "video"
    assert ev.content_text.strip() != ""
    assert ev.confidence == 0.75


def test_video_adapter_normalize_no_audio_lower_confidence():
    from app.agents.adapters.video import VideoAdapter

    adapter = VideoAdapter()
    job = _make_job(has_video=True, has_audio=False, has_transcript=False)
    # Patch has_audio in manifest
    job["input_manifest"]["video"]["audio_detected"] = False

    ev = adapter.normalize(job)

    assert ev.confidence == 0.45
    assert "No audio" in ev.content_text or "frame-first" in ev.content_text.lower() or "not detected" in ev.content_text


def test_video_adapter_normalize_empty_anchors_stub():
    """Frame anchors are empty pending Azure Vision integration."""
    from app.agents.adapters.video import VideoAdapter

    adapter = VideoAdapter()
    job = _make_job(has_video=True, has_audio=True, has_transcript=False)

    ev = adapter.normalize(job)

    assert ev.anchors == []


def test_video_adapter_normalize_metadata_includes_audio_flag():
    from app.agents.adapters.video import VideoAdapter

    adapter = VideoAdapter()
    job = _make_job(has_video=True, has_audio=True, has_transcript=False)

    ev = adapter.normalize(job)

    assert ev.metadata.get("has_audio") is True


def test_video_adapter_normalize_with_transcription(monkeypatch):
    from app.agents.adapters.video import VideoAdapter

    adapter = VideoAdapter()
    job = _make_job(has_video=True, has_audio=True, has_transcript=False)
    job["input_manifest"]["video"]["storage_key"] = "/tmp/demo.mp4"
    vtt_text = "WEBVTT\n\n00:00:00.000 --> 00:00:03.000\nFinance Analyst: Open SAP.\n"

    with patch("app.agents.adapters.video.transcribe_audio_blob", return_value=vtt_text):
        ev = adapter.normalize(job)

    assert ev.content_text == vtt_text
    assert ev.confidence == 0.85
    assert ev.anchors == ["00:00:00-00:00:03"]
    assert job["_video_transcript_inline"] == vtt_text


# ---------------------------------------------------------------------------
# VideoAdapter — render_review_notes()
# ---------------------------------------------------------------------------

def test_video_adapter_render_review_notes_with_audio():
    from app.agents.adapters.video import VideoAdapter

    adapter = VideoAdapter()
    job = _make_job(has_video=True, has_audio=True, has_transcript=False)
    ev = adapter.normalize(job)

    notes = adapter.render_review_notes(ev)

    assert isinstance(notes, list)
    assert any("Audio" in n or "audio" in n for n in notes)


def test_video_adapter_render_review_notes_without_audio():
    from app.agents.adapters.video import VideoAdapter

    adapter = VideoAdapter()
    job = _make_job(has_video=True, has_audio=False, has_transcript=False)
    job["input_manifest"]["video"]["audio_detected"] = False
    ev = adapter.normalize(job)

    notes = adapter.render_review_notes(ev)

    assert any("No audio" in n or "frame" in n.lower() for n in notes)


def test_video_adapter_render_review_notes_with_transcription_complete_note():
    from app.agents.adapters.video import VideoAdapter

    adapter = VideoAdapter()
    job = _make_job(has_video=True, has_audio=True, has_transcript=False)
    job["input_manifest"]["video"]["storage_key"] = "/tmp/demo.mp4"
    vtt_text = "WEBVTT\n\n00:00:00.000 --> 00:00:03.000\nFinance Analyst: Open SAP.\n"

    with patch("app.agents.adapters.video.transcribe_audio_blob", return_value=vtt_text):
        ev = adapter.normalize(job)

    notes = adapter.render_review_notes(ev)

    assert "Audio transcription complete. Frame-level visual analysis pending." in notes


# ---------------------------------------------------------------------------
# AdapterRegistry
# ---------------------------------------------------------------------------

def test_registry_returns_transcript_adapter_for_transcript():
    from app.agents.adapters.registry import AdapterRegistry
    from app.agents.adapters.transcript import TranscriptAdapter

    registry = AdapterRegistry()
    adapters = registry.get_adapters(["transcript"])

    assert len(adapters) == 1
    assert isinstance(adapters[0], TranscriptAdapter)


def test_registry_returns_video_adapter_for_video():
    from app.agents.adapters.registry import AdapterRegistry
    from app.agents.adapters.video import VideoAdapter

    registry = AdapterRegistry()
    adapters = registry.get_adapters(["video"])

    assert len(adapters) == 1
    assert isinstance(adapters[0], VideoAdapter)


def test_registry_returns_both_adapters_transcript_first():
    from app.agents.adapters.registry import AdapterRegistry
    from app.agents.adapters.transcript import TranscriptAdapter
    from app.agents.adapters.video import VideoAdapter

    registry = AdapterRegistry()
    # Deliberately pass video first to confirm transcript still comes first
    adapters = registry.get_adapters(["video", "transcript"])

    assert len(adapters) == 2
    assert isinstance(adapters[0], TranscriptAdapter)
    assert isinstance(adapters[1], VideoAdapter)


def test_registry_skips_unknown_source_types():
    from app.agents.adapters.registry import AdapterRegistry

    registry = AdapterRegistry()
    adapters = registry.get_adapters(["audio", "doc", "unknown"])

    assert adapters == []


def test_registry_get_adapter_returns_none_for_unknown():
    from app.agents.adapters.registry import AdapterRegistry

    registry = AdapterRegistry()
    assert registry.get_adapter("audio") is None


def test_registry_supported_types_contains_video_and_transcript():
    from app.agents.adapters.registry import AdapterRegistry

    registry = AdapterRegistry()
    supported = registry.supported_types

    assert "video" in supported
    assert "transcript" in supported


# ---------------------------------------------------------------------------
# Extraction agent — adapter integration
# ---------------------------------------------------------------------------

def test_extraction_uses_adapter_normalized_content(monkeypatch):
    """Extraction agent calls adapter normalization and passes clean content to SK."""
    from app.agents.extraction import run_extraction

    mock_result = {
        "evidence_items": [],
        "speakers_detected": [],
        "process_domain": "test",
        "transcript_quality": "low",
    }

    job = _make_job()
    job["_transcript_text_inline"] = _load_fixture("scenario_a", "transcript.vtt")

    captured_prompts = []

    async def _fake_call(deployment, system_prompt, user_content):
        captured_prompts.append(user_content)
        return json.dumps(mock_result), 100, 50

    with patch("app.agents.extraction._call_extraction", side_effect=_fake_call):
        run_extraction(job, {"profile": "balanced", "model": "gpt-4o-mini", "cost_cap_usd": 4.0})

    assert len(captured_prompts) == 1
    # Adapter should have stripped raw VTT header — WEBVTT should not appear in prompt
    assert "WEBVTT" not in captured_prompts[0]
    # Inline anchor markers should be present
    assert "[00:00:00-00:00:12]" in captured_prompts[0]


def test_extraction_stores_document_type_manifests(monkeypatch):
    """Extraction agent populates document_type_manifests on the job."""
    from app.agents.extraction import run_extraction

    mock_result = {
        "evidence_items": [],
        "speakers_detected": [],
        "process_domain": "test",
        "transcript_quality": "low",
    }

    job = _make_job()
    job["_transcript_text_inline"] = "Some plain transcript text"

    async def _fake_call(*args, **kwargs):
        return json.dumps(mock_result), 100, 50

    with patch("app.agents.extraction._call_extraction", side_effect=_fake_call):
        run_extraction(job, {"profile": "balanced", "model": "gpt-4o-mini", "cost_cap_usd": 4.0})

    manifests = job.get("document_type_manifests")
    assert isinstance(manifests, list)
    source_types = {m["source_type"] for m in manifests}
    assert "transcript" in source_types or "video" in source_types


def test_extraction_document_manifests_populated_on_graceful_degradation():
    """document_type_manifests is set even when no content is available."""
    from app.agents.extraction import run_extraction

    job = _make_job(has_video=False, has_transcript=False)

    run_extraction(job, {"profile": "balanced", "model": "gpt-4o-mini", "cost_cap_usd": 4.0})

    assert "document_type_manifests" in job
    assert isinstance(job["document_type_manifests"], list)
