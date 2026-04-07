"""Shared fixtures for PFCD integration tests."""

from __future__ import annotations

import importlib
import pathlib
import sys
from typing import NamedTuple
from unittest.mock import MagicMock

import pytest

# Ensure backend package is importable regardless of how pytest is invoked.
ROOT = pathlib.Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


class AppContext(NamedTuple):
    client: object   # starlette.testclient.TestClient
    repo: object     # app.repository.JobRepository
    module: object   # app.main module


def _reload_app(monkeypatch, tmp_path, *, api_key: str | None = None):
    """Reload app modules with a fresh SQLite DB in tmp_path.

    Returns (AppContext, api_key_value) where api_key_value is None when auth
    is disabled.
    """
    db_path = tmp_path / "test.db"
    exports_path = tmp_path / "exports"
    exports_path.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("EXPORTS_BASE_PATH", str(exports_path))
    monkeypatch.delenv("AZURE_SERVICE_BUS_CONNECTION_STRING", raising=False)
    monkeypatch.delenv("AZURE_STORAGE_CONNECTION_STRING", raising=False)

    if api_key is not None:
        monkeypatch.setenv("PFCD_API_KEY", api_key)
    else:
        monkeypatch.delenv("PFCD_API_KEY", raising=False)

    import app.db as db_mod
    import app.repository as repo_mod
    import app.main as main_mod

    importlib.reload(db_mod)
    importlib.reload(repo_mod)
    importlib.reload(main_mod)

    # Replace ORCHESTRATOR so enqueue() is never attempted against Azure.
    main_mod.ORCHESTRATOR = MagicMock()
    # Initialise schema in the fresh SQLite file.
    main_mod.JOB_REPO.init_db()

    from starlette.testclient import TestClient

    client = TestClient(main_mod.app, raise_server_exceptions=False)
    return AppContext(client=client, repo=main_mod.JOB_REPO, module=main_mod)


@pytest.fixture
def app_client(monkeypatch, tmp_path):
    """AppContext with auth disabled and a fresh SQLite DB."""
    return _reload_app(monkeypatch, tmp_path)


@pytest.fixture
def app_client_with_auth(monkeypatch, tmp_path):
    """(AppContext, api_key) tuple with auth enabled."""
    key = "integration-test-key"
    ctx = _reload_app(monkeypatch, tmp_path, api_key=key)
    return ctx, key


# ---------------------------------------------------------------------------
# Higher-level seeded fixtures
# ---------------------------------------------------------------------------

def _post_create_job(client, source_type: str = "transcript", size_bytes: int = 1024):
    payload = {
        "input_files": [
            {"source_type": source_type, "file_name": "test.vtt", "size_bytes": size_bytes}
        ]
    }
    resp = client.post("/api/jobs", json=payload)
    assert resp.status_code == 201, f"create_job failed: {resp.text}"
    return resp.json()["job_id"]


def _post_simulate(client, job_id: str):
    resp = client.post(f"/dev/jobs/{job_id}/simulate")
    assert resp.status_code == 200, f"simulate failed: {resp.text}"
    return resp.json()


@pytest.fixture
def seeded_needs_review_job(app_client):
    """(job_id, AppContext) with the job advanced to needs_review via simulate."""
    ctx = app_client
    job_id = _post_create_job(ctx.client)
    _post_simulate(ctx.client, job_id)
    return job_id, ctx


@pytest.fixture
def seeded_completed_job(seeded_needs_review_job):
    """(job_id, AppContext) with the job fully finalized (status=completed)."""
    job_id, ctx = seeded_needs_review_job
    resp = ctx.client.post(f"/api/jobs/{job_id}/finalize")
    assert resp.status_code == 200, f"finalize failed: {resp.text}"
    return job_id, ctx
