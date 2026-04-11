"""Integration tests: error paths and guard conditions."""

from __future__ import annotations

from uuid import uuid4

import pytest

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_queued(client):
    payload = {
        "input_files": [
            {"source_type": "transcript", "file_name": "t.vtt", "size_bytes": 512}
        ]
    }
    resp = client.post("/api/jobs", json=payload)
    assert resp.status_code == 201
    return resp.json()["job_id"]


def _simulate(client, job_id):
    resp = client.post(f"/dev/jobs/{job_id}/simulate")
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Draft endpoints guard conditions
# ---------------------------------------------------------------------------

def test_get_draft_on_queued_job_returns_409(app_client):
    job_id = _create_queued(app_client.client)
    resp = app_client.client.get(f"/api/jobs/{job_id}/draft")
    assert resp.status_code == 409


def test_put_draft_on_queued_job_returns_409(app_client):
    job_id = _create_queued(app_client.client)
    resp = app_client.client.put(f"/api/jobs/{job_id}/draft", json={"pdd": {}})
    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# Finalize guard conditions
# ---------------------------------------------------------------------------

def test_finalize_without_user_saved_draft_returns_409(app_client):
    job_id = _create_queued(app_client.client)
    _simulate(app_client.client, job_id)

    resp = app_client.client.post(f"/api/jobs/{job_id}/finalize")
    assert resp.status_code == 409
    assert "saved" in resp.json()["detail"].lower()


def test_simulate_then_finalize_without_save_returns_409(app_client):
    job_id = _create_queued(app_client.client)
    _simulate(app_client.client, job_id)

    resp = app_client.client.post(f"/api/jobs/{job_id}/finalize")
    assert resp.status_code == 409


def test_finalize_blocked_by_blocker_flag_returns_409(app_client):
    job_id = _create_queued(app_client.client)
    _simulate(app_client.client, job_id)
    save_resp = app_client.client.put(
        f"/api/jobs/{job_id}/draft",
        json={"assumptions": ["Saved before blocker check"]},
    )
    assert save_resp.status_code == 200

    # Inject a BLOCKER flag via repo.
    job = app_client.repo.get_job(job_id)
    job["review_notes"]["flags"].append({
        "severity": "blocker",
        "code": "test_blocker",
        "message": "Synthetic blocker for integration test",
        "field": None,
    })
    app_client.repo.upsert_job(job_id, job)

    resp = app_client.client.post(f"/api/jobs/{job_id}/finalize")
    assert resp.status_code == 409
    assert "blocker" in resp.json()["detail"].lower()


def test_finalize_on_missing_job_returns_404(app_client):
    resp = app_client.client.post(f"/api/jobs/{uuid4()}/finalize")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Export guard conditions
# ---------------------------------------------------------------------------

def test_export_before_finalize_returns_409(app_client):
    job_id = _create_queued(app_client.client)
    _simulate(app_client.client, job_id)

    resp = app_client.client.get(f"/api/jobs/{job_id}/exports/json")
    assert resp.status_code == 409


def test_export_invalid_format_returns_400(seeded_completed_job):
    job_id, ctx = seeded_completed_job
    resp = ctx.client.get(f"/api/jobs/{job_id}/exports/xlsx")
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Simulate guard conditions
# ---------------------------------------------------------------------------

def test_simulate_missing_job_returns_404(app_client):
    resp = app_client.client.post(f"/dev/jobs/{uuid4()}/simulate")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Upload size enforcement
# ---------------------------------------------------------------------------

def test_upload_oversize_file_returns_413(app_client):
    # Temporarily lower the size limit so we don't send 500 MB in tests.
    app_client.module.MAX_UPLOAD_BYTES = 10

    resp = app_client.client.post(
        "/api/upload",
        files={"file": ("big.txt", b"x" * 11, "text/plain")},
    )
    assert resp.status_code == 413
