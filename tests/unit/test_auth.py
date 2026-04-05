"""HTTP-level auth tests for PFCD API key enforcement."""

from __future__ import annotations

import importlib
import pathlib
import sys
from uuid import uuid4

ROOT = pathlib.Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


def _get_client(monkeypatch, tmp_path, api_key="test-secret"):
    db_path = tmp_path / "pfcd-auth-test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    if api_key is not None:
        monkeypatch.setenv("PFCD_API_KEY", api_key)
    else:
        monkeypatch.delenv("PFCD_API_KEY", raising=False)
    import app.main as main_mod
    importlib.reload(main_mod)
    from starlette.testclient import TestClient
    return TestClient(main_mod.app, raise_server_exceptions=False)


def test_health_is_public(monkeypatch, tmp_path):
    client = _get_client(monkeypatch, tmp_path)
    resp = client.get("/health")
    assert resp.status_code not in (401, 403)


def test_missing_key_returns_401(monkeypatch, tmp_path):
    client = _get_client(monkeypatch, tmp_path)
    resp = client.get(f"/api/jobs/{uuid4()}")
    assert resp.status_code == 401


def test_wrong_key_returns_403(monkeypatch, tmp_path):
    client = _get_client(monkeypatch, tmp_path)
    resp = client.get(f"/api/jobs/{uuid4()}", headers={"X-API-Key": "wrong-key"})
    assert resp.status_code == 403


def test_correct_key_passes_through(monkeypatch, tmp_path):
    client = _get_client(monkeypatch, tmp_path)
    resp = client.get(f"/api/jobs/{uuid4()}", headers={"X-API-Key": "test-secret"})
    assert resp.status_code not in (401, 403)


def test_auth_disabled_when_env_unset(monkeypatch, tmp_path):
    client = _get_client(monkeypatch, tmp_path, api_key=None)
    resp = client.get(f"/api/jobs/{uuid4()}")
    assert resp.status_code not in (401, 403)


def test_all_write_methods_require_auth(monkeypatch, tmp_path):
    client = _get_client(monkeypatch, tmp_path)
    job_id = str(uuid4())
    cases = [
        ("POST", "/api/jobs", {}),
        ("PUT", f"/api/jobs/{job_id}/draft", {}),
        ("POST", f"/api/jobs/{job_id}/finalize", {}),
        ("DELETE", f"/api/jobs/{job_id}", {}),
    ]
    for method, path, body in cases:
        resp = client.request(method, path, json=body)
        assert resp.status_code == 401, f"{method} {path} expected 401, got {resp.status_code}"


def test_compare_digest_rejects_prefix(monkeypatch, tmp_path):
    client = _get_client(monkeypatch, tmp_path, api_key="correct-key")
    resp = client.get(f"/api/jobs/{uuid4()}", headers={"X-API-Key": "correct-ke"})
    assert resp.status_code == 403
