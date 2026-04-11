"""Integration tests: API key enforcement across all protected endpoints."""

from __future__ import annotations

from uuid import uuid4

import pytest

pytestmark = pytest.mark.integration

_AUTH_KEY = "integration-test-key"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _h(key: str) -> dict:
    return {"X-API-Key": key}


# ---------------------------------------------------------------------------
# Basic enforcement
# ---------------------------------------------------------------------------

def test_health_is_always_public(app_client_with_auth):
    ctx, _ = app_client_with_auth
    # /health must succeed with no key.
    resp = ctx.client.get("/health")
    assert resp.status_code not in (401, 403)


def test_missing_key_returns_401(app_client_with_auth):
    ctx, _ = app_client_with_auth
    resp = ctx.client.get(f"/api/jobs/{uuid4()}")
    assert resp.status_code == 401


def test_wrong_key_returns_403(app_client_with_auth):
    ctx, _ = app_client_with_auth
    resp = ctx.client.get(f"/api/jobs/{uuid4()}", headers=_h("wrong-key"))
    assert resp.status_code == 403


def test_correct_key_passes_through(app_client_with_auth):
    ctx, key = app_client_with_auth
    # A real job_id that doesn't exist returns 404 — which means auth passed.
    resp = ctx.client.get(f"/api/jobs/{uuid4()}", headers=_h(key))
    assert resp.status_code == 404


def test_auth_disabled_when_env_unset(app_client):
    # app_client has PFCD_API_KEY unset → auth disabled.
    resp = app_client.client.get(f"/api/jobs/{uuid4()}")
    assert resp.status_code not in (401, 403)


def test_dev_simulate_requires_auth_key(app_client_with_auth):
    ctx, _ = app_client_with_auth
    resp = ctx.client.post(f"/dev/jobs/{uuid4()}/simulate")
    assert resp.status_code == 401


def test_dev_simulate_with_auth_key_passes(app_client_with_auth):
    ctx, key = app_client_with_auth
    resp = ctx.client.post(f"/dev/jobs/{uuid4()}/simulate", headers=_h(key))
    assert resp.status_code == 404


@pytest.mark.parametrize("method,path_tpl,body", [
    ("POST", "/api/jobs", {"input_files": [{"source_type": "transcript", "size_bytes": 1}]}),
    ("GET", "/api/jobs/{uid}", None),
    ("GET", "/api/jobs/{uid}/draft", None),
    ("PUT", "/api/jobs/{uid}/draft", {"pdd": {}}),
    ("POST", "/api/jobs/{uid}/finalize", None),
    ("DELETE", "/api/jobs/{uid}", None),
])
def test_all_protected_endpoints_return_401_without_key(app_client_with_auth, method, path_tpl, body):
    ctx, _ = app_client_with_auth
    path = path_tpl.replace("{uid}", str(uuid4()))
    resp = ctx.client.request(method, path, json=body)
    assert resp.status_code == 401, (
        f"{method} {path} expected 401, got {resp.status_code}: {resp.text}"
    )
