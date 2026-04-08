"""Tests for profile deployment selection in job_logic."""

from __future__ import annotations

from app.job_logic import Profile, profile_config


def test_profile_config_prefers_azure_openai_deployment_name(monkeypatch):
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT_NAME", "gpt-4o-mini")
    monkeypatch.delenv("AZURE_OPENAI_DEPLOYMENT", raising=False)

    balanced = profile_config(Profile.BALANCED)
    quality = profile_config(Profile.QUALITY)

    assert balanced["model"] == "gpt-4o-mini"
    assert quality["model"] == "gpt-4o-mini"


def test_profile_config_falls_back_to_azure_openai_deployment(monkeypatch):
    monkeypatch.delenv("AZURE_OPENAI_DEPLOYMENT_NAME", raising=False)
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT", "my-fallback-deployment")

    cfg = profile_config(Profile.BALANCED)
    assert cfg["model"] == "my-fallback-deployment"
