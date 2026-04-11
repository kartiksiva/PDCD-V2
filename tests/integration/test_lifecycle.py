"""Integration tests: full job lifecycle via the FastAPI layer (real SQLite)."""

from __future__ import annotations

import pytest
from uuid import uuid4

pytestmark = pytest.mark.integration


def test_health_returns_ok(app_client):
    resp = app_client.client.get("/health")
    # 200 (all env vars set) or 503 (degraded — expected in CI).
    assert resp.status_code in (200, 503)
    body = resp.json()
    assert "status" in body
    assert body["status"] in ("ok", "degraded")


def test_create_job_returns_queued(app_client):
    payload = {
        "input_files": [
            {"source_type": "transcript", "file_name": "t.vtt", "size_bytes": 512}
        ]
    }
    resp = app_client.client.post("/api/jobs", json=payload)
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "queued"
    # Must be a valid UUID.
    from uuid import UUID
    UUID(body["job_id"])


def test_create_job_requires_at_least_one_file(app_client):
    resp = app_client.client.post("/api/jobs", json={"input_files": []})
    assert resp.status_code == 400


def test_create_job_rejects_oversized_file(app_client):
    oversized = 600 * 1024 * 1024  # 600 MB
    payload = {
        "input_files": [
            {"source_type": "video", "file_name": "big.mp4", "size_bytes": oversized}
        ]
    }
    resp = app_client.client.post("/api/jobs", json=payload)
    assert resp.status_code == 413


def test_get_job_returns_queued_state(app_client):
    payload = {
        "input_files": [
            {"source_type": "transcript", "file_name": "t.vtt", "size_bytes": 512}
        ]
    }
    create_resp = app_client.client.post("/api/jobs", json=payload)
    job_id = create_resp.json()["job_id"]

    resp = app_client.client.get(f"/api/jobs/{job_id}")
    assert resp.status_code == 200
    assert resp.json()["status"] == "queued"


def test_get_missing_job_returns_404(app_client):
    resp = app_client.client.get(f"/api/jobs/{uuid4()}")
    assert resp.status_code == 404


def test_simulate_advances_to_needs_review(app_client):
    payload = {
        "input_files": [
            {"source_type": "transcript", "file_name": "t.vtt", "size_bytes": 512}
        ]
    }
    job_id = app_client.client.post("/api/jobs", json=payload).json()["job_id"]

    resp = app_client.client.post(f"/dev/jobs/{job_id}/simulate")
    assert resp.status_code == 200
    assert resp.json()["status"] == "needs_review"


def test_get_draft_returns_mock_draft(app_client):
    payload = {
        "input_files": [
            {"source_type": "transcript", "file_name": "t.vtt", "size_bytes": 512}
        ]
    }
    job_id = app_client.client.post("/api/jobs", json=payload).json()["job_id"]
    app_client.client.post(f"/dev/jobs/{job_id}/simulate")

    resp = app_client.client.get(f"/api/jobs/{job_id}/draft")
    assert resp.status_code == 200
    body = resp.json()
    assert "draft" in body
    assert body["draft"]["pdd"]["steps"]  # non-empty steps


def test_get_draft_before_simulate_returns_409(app_client):
    payload = {
        "input_files": [
            {"source_type": "transcript", "file_name": "t.vtt", "size_bytes": 512}
        ]
    }
    job_id = app_client.client.post("/api/jobs", json=payload).json()["job_id"]

    resp = app_client.client.get(f"/api/jobs/{job_id}/draft")
    assert resp.status_code == 409


def test_update_draft_saves_changes(app_client):
    payload = {
        "input_files": [
            {"source_type": "transcript", "file_name": "t.vtt", "size_bytes": 512}
        ]
    }
    job_id = app_client.client.post("/api/jobs", json=payload).json()["job_id"]
    app_client.client.post(f"/dev/jobs/{job_id}/simulate")

    updated_pdd = {"purpose": "Integration-test updated purpose", "steps": []}
    put_resp = app_client.client.put(
        f"/api/jobs/{job_id}/draft",
        json={"pdd": updated_pdd},
    )
    assert put_resp.status_code == 200
    assert put_resp.json()["user_saved_draft"] is True

    get_resp = app_client.client.get(f"/api/jobs/{job_id}/draft")
    assert get_resp.json()["draft"]["pdd"]["purpose"] == "Integration-test updated purpose"


def test_finalize_job_returns_completed(seeded_needs_review_job):
    job_id, ctx = seeded_needs_review_job
    save_resp = ctx.client.put(
        f"/api/jobs/{job_id}/draft",
        json={"assumptions": ["Saved before finalize"]},
    )
    assert save_resp.status_code == 200
    resp = ctx.client.post(f"/api/jobs/{job_id}/finalize")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "completed"
    assert "exports" in body


def test_finalize_idempotent(seeded_completed_job):
    job_id, ctx = seeded_completed_job
    resp = ctx.client.post(f"/api/jobs/{job_id}/finalize")
    assert resp.status_code == 200
    assert resp.json()["status"] == "completed"


def test_delete_job_transitions_to_deleted(app_client):
    payload = {
        "input_files": [
            {"source_type": "transcript", "file_name": "t.vtt", "size_bytes": 512}
        ]
    }
    job_id = app_client.client.post("/api/jobs", json=payload).json()["job_id"]

    resp = app_client.client.delete(f"/api/jobs/{job_id}")
    assert resp.status_code == 200
    assert resp.json()["status"] == "deleted"


def test_finalize_deleted_job_returns_410(app_client):
    payload = {
        "input_files": [
            {"source_type": "transcript", "file_name": "t.vtt", "size_bytes": 512}
        ]
    }
    job_id = app_client.client.post("/api/jobs", json=payload).json()["job_id"]
    app_client.client.delete(f"/api/jobs/{job_id}")

    resp = app_client.client.post(f"/api/jobs/{job_id}/finalize")
    assert resp.status_code == 410
