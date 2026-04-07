"""Integration tests: export format correctness and evidence bundle."""

from __future__ import annotations

import json
import pathlib

import pytest

pytestmark = pytest.mark.integration

FIXTURES = pathlib.Path(__file__).resolve().parents[2] / "tests" / "fixtures"


# ---------------------------------------------------------------------------
# Per-format content tests (all use seeded_completed_job)
# ---------------------------------------------------------------------------

def test_json_export_contains_required_fields(seeded_completed_job):
    job_id, ctx = seeded_completed_job
    resp = ctx.client.get(f"/api/jobs/{job_id}/exports/json")
    assert resp.status_code == 200
    body = resp.json()
    assert body["job_id"] == job_id
    assert body["status"] == "completed"
    assert "draft" in body
    assert "exports_manifest" in body
    assert "evidence_bundle" in body["exports_manifest"]


def test_markdown_export_is_text(seeded_completed_job):
    job_id, ctx = seeded_completed_job
    resp = ctx.client.get(f"/api/jobs/{job_id}/exports/markdown")
    assert resp.status_code == 200
    assert "markdown" in resp.headers.get("content-type", "").lower()
    assert "#" in resp.text  # has at least one Markdown heading


def test_pdf_export_is_binary(seeded_completed_job):
    job_id, ctx = seeded_completed_job
    resp = ctx.client.get(f"/api/jobs/{job_id}/exports/pdf")
    assert resp.status_code == 200
    assert resp.headers.get("content-type", "").startswith("application/pdf")
    assert resp.content[:4] == b"%PDF"
    assert f"pdd-{job_id}.pdf" in resp.headers.get("content-disposition", "")


def test_docx_export_is_valid_zip(seeded_completed_job):
    job_id, ctx = seeded_completed_job
    resp = ctx.client.get(f"/api/jobs/{job_id}/exports/docx")
    assert resp.status_code == 200
    ct = resp.headers.get("content-type", "")
    assert "openxmlformats" in ct or "officedocument" in ct
    # DOCX is a ZIP archive; magic bytes are PK (0x50 0x4B).
    assert resp.content[:2] == b"PK"


def test_all_four_formats_available(seeded_completed_job):
    job_id, ctx = seeded_completed_job
    for fmt in ("json", "markdown", "pdf", "docx"):
        resp = ctx.client.get(f"/api/jobs/{job_id}/exports/{fmt}")
        assert resp.status_code == 200, f"Format {fmt!r} returned {resp.status_code}"


# ---------------------------------------------------------------------------
# Evidence bundle assertions
# ---------------------------------------------------------------------------

def test_evidence_bundle_has_anchors(seeded_completed_job):
    job_id, ctx = seeded_completed_job
    resp = ctx.client.get(f"/api/jobs/{job_id}/exports/json")
    bundle = resp.json()["exports_manifest"]["evidence_bundle"]
    linked = bundle["linked_anchors"]
    assert isinstance(linked, list)
    assert len(linked) > 0, "Expected at least one linked anchor from SIPOC rows"
    for anchor in linked:
        assert "anchor_type" in anchor
        assert "confidence" in anchor
        assert "anchor_value" in anchor


# ---------------------------------------------------------------------------
# PRD §12 acceptance scenarios
# ---------------------------------------------------------------------------

def test_scenario_a_happy_path(app_client):
    """video + audio + transcript → finalize → evidence_bundle present."""
    payload = {
        "input_files": [
            {"source_type": "video", "file_name": "session.mp4", "size_bytes": 1024,
             "audio_detected": True},
            {"source_type": "audio", "file_name": "session.wav", "size_bytes": 512},
            {"source_type": "transcript", "file_name": "session.vtt", "size_bytes": 256},
        ]
    }
    job_id = app_client.client.post("/api/jobs", json=payload).json()["job_id"]
    app_client.client.post(f"/dev/jobs/{job_id}/simulate")

    fin = app_client.client.post(f"/api/jobs/{job_id}/finalize")
    assert fin.status_code == 200
    assert fin.json()["status"] == "completed"

    export_resp = app_client.client.get(f"/api/jobs/{job_id}/exports/json")
    assert export_resp.status_code == 200
    bundle = export_resp.json()["exports_manifest"]["evidence_bundle"]
    assert bundle is not None
    assert "linked_anchors" in bundle


def test_transcript_only_fallback(app_client):
    """transcript-only → draft generated, review_notes flags present."""
    payload = {
        "input_files": [
            {"source_type": "transcript", "file_name": "t.vtt", "size_bytes": 512}
        ]
    }
    job_id = app_client.client.post("/api/jobs", json=payload).json()["job_id"]
    app_client.client.post(f"/dev/jobs/{job_id}/simulate")

    draft_resp = app_client.client.get(f"/api/jobs/{job_id}/draft")
    assert draft_resp.status_code == 200
    body = draft_resp.json()
    assert body["draft"] is not None
    assert body["draft"]["pdd"]["steps"]
    # simulate always injects review flags (warning + info).
    assert len(body["review_notes"]["flags"]) > 0
