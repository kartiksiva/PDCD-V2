"""Unit tests for /health/readiness dependency checks."""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))


def _set_required_env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///./test.db")
    monkeypatch.setenv("AZURE_STORAGE_CONNECTION_STRING", "UseDevelopmentStorage=true")
    monkeypatch.setenv("AZURE_SERVICE_BUS_CONNECTION_STRING", "Endpoint=sb://test/;SharedAccessKeyName=x;SharedAccessKey=y")
    monkeypatch.setenv("AZURE_SERVICE_BUS_QUEUE_EXTRACTING", "extracting")
    monkeypatch.setenv("AZURE_SERVICE_BUS_QUEUE_PROCESSING", "processing")
    monkeypatch.setenv("AZURE_SERVICE_BUS_QUEUE_REVIEWING", "reviewing")


def test_readiness_returns_200_when_all_checks_ok(app_client, monkeypatch):
    ctx = app_client
    _set_required_env(monkeypatch)
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://example.openai.azure.com/")
    monkeypatch.setenv("AZURE_OPENAI_CHAT_DEPLOYMENT_NAME", "gpt-4o-mini")
    monkeypatch.setenv("AZURE_SPEECH_ACCOUNT_NAME", "pfcd-dev-speech")

    monkeypatch.setattr(ctx.module, "_check_database_readiness", lambda: {"status": "ok"})
    monkeypatch.setattr(ctx.module, "_check_storage_readiness", lambda: {"status": "ok"})
    monkeypatch.setattr(ctx.module, "_check_service_bus_readiness", lambda: {"status": "ok"})
    monkeypatch.setattr(ctx.module, "_check_openai_readiness", lambda: {"status": "ok"})
    monkeypatch.setattr(ctx.module, "_check_speech_readiness", lambda: {"status": "ok"})

    resp = ctx.client.get("/health/readiness")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["status"] == "ready"
    assert payload["missing_environment"] == []


def test_readiness_returns_503_when_database_check_fails(app_client, monkeypatch):
    ctx = app_client
    _set_required_env(monkeypatch)
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://example.openai.azure.com/")
    monkeypatch.setenv("AZURE_OPENAI_CHAT_DEPLOYMENT_NAME", "gpt-4o-mini")
    monkeypatch.setenv("AZURE_SPEECH_ACCOUNT_NAME", "pfcd-dev-speech")

    monkeypatch.setattr(ctx.module, "_check_database_readiness", lambda: {"status": "error", "error": "db down"})
    monkeypatch.setattr(ctx.module, "_check_storage_readiness", lambda: {"status": "ok"})
    monkeypatch.setattr(ctx.module, "_check_service_bus_readiness", lambda: {"status": "ok"})
    monkeypatch.setattr(ctx.module, "_check_openai_readiness", lambda: {"status": "ok"})
    monkeypatch.setattr(ctx.module, "_check_speech_readiness", lambda: {"status": "ok"})

    resp = ctx.client.get("/health/readiness")
    assert resp.status_code == 503
    payload = resp.json()
    assert payload["status"] == "not_ready"
    assert payload["checks"]["database"]["status"] == "error"


def test_readiness_returns_503_when_required_env_missing(app_client, monkeypatch):
    ctx = app_client
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("AZURE_STORAGE_CONNECTION_STRING", raising=False)
    monkeypatch.delenv("AZURE_SERVICE_BUS_CONNECTION_STRING", raising=False)
    monkeypatch.delenv("AZURE_SERVICE_BUS_QUEUE_EXTRACTING", raising=False)
    monkeypatch.delenv("AZURE_SERVICE_BUS_QUEUE_PROCESSING", raising=False)
    monkeypatch.delenv("AZURE_SERVICE_BUS_QUEUE_REVIEWING", raising=False)

    resp = ctx.client.get("/health/readiness")
    assert resp.status_code == 503
    payload = resp.json()
    assert payload["status"] == "not_ready"
    assert "DATABASE_URL" in payload["missing_environment"]
