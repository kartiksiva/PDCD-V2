from __future__ import annotations

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


def test_cors_origins_warns_for_http_in_non_production(monkeypatch, caplog):
    from app import main as main_mod

    monkeypatch.setenv("PFCD_ENV", "development")
    monkeypatch.setenv("PFCD_CORS_ORIGINS", "http://localhost:5173")

    with caplog.at_level("WARNING"):
        origins = main_mod._cors_origins()

    assert origins == ["http://localhost:5173"]
    assert "non-HTTPS" in caplog.text


def test_cors_origins_rejects_http_in_production(monkeypatch):
    from app import main as main_mod

    monkeypatch.setenv("PFCD_ENV", "production")
    monkeypatch.setenv("PFCD_CORS_ORIGINS", "http://example.com")

    with pytest.raises(RuntimeError, match="HTTPS"):
        main_mod._cors_origins()


def test_cors_origins_accepts_https_in_production(monkeypatch):
    from app import main as main_mod

    monkeypatch.setenv("PFCD_ENV", "production")
    monkeypatch.setenv("PFCD_CORS_ORIGINS", "https://example.com")

    assert main_mod._cors_origins() == ["https://example.com"]
