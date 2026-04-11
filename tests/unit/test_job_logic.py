"""Tests for profile deployment selection in job_logic."""

from __future__ import annotations

import pytest

from app.job_logic import (
    InputFile,
    JobCreateRequest,
    Profile,
    apply_cost_tracking_and_cap_warning,
    default_job_payload,
    profile_config,
)


def test_profile_config_prefers_azure_openai_deployment_name(monkeypatch):
    monkeypatch.setenv("AZURE_OPENAI_CHAT_DEPLOYMENT_NAME", "gpt-4.1")
    monkeypatch.delenv("AZURE_OPENAI_DEPLOYMENT_BALANCED", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_DEPLOYMENT_QUALITY", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_DEPLOYMENT_NAME", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_DEPLOYMENT", raising=False)

    balanced = profile_config(Profile.BALANCED)
    quality = profile_config(Profile.QUALITY)

    assert balanced["model"] == "gpt-4.1"
    assert quality["model"] == "gpt-4.1"


def test_profile_config_falls_back_to_azure_openai_deployment(monkeypatch):
    monkeypatch.delenv("AZURE_OPENAI_DEPLOYMENT_BALANCED", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_DEPLOYMENT_QUALITY", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_CHAT_DEPLOYMENT_NAME", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_DEPLOYMENT_NAME", raising=False)
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT", "my-fallback-deployment")

    cfg = profile_config(Profile.BALANCED)
    assert cfg["model"] == "my-fallback-deployment"


def test_profile_config_falls_back_to_deployment_name_alias(monkeypatch):
    monkeypatch.delenv("AZURE_OPENAI_DEPLOYMENT_BALANCED", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_DEPLOYMENT_QUALITY", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_CHAT_DEPLOYMENT_NAME", raising=False)
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT_NAME", "legacy-name-deployment")
    monkeypatch.delenv("AZURE_OPENAI_DEPLOYMENT", raising=False)

    cfg = profile_config(Profile.BALANCED)
    assert cfg["model"] == "legacy-name-deployment"


def test_profile_config_prefers_profile_specific_env(monkeypatch):
    monkeypatch.setenv("AZURE_OPENAI_CHAT_DEPLOYMENT_NAME", "generic-deployment")
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT_BALANCED", "balanced-deployment")
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT_QUALITY", "quality-deployment")

    balanced = profile_config(Profile.BALANCED)
    quality = profile_config(Profile.QUALITY)

    assert balanced["model"] == "balanced-deployment"
    assert quality["model"] == "quality-deployment"


def test_profile_config_raises_when_deployment_not_configured(monkeypatch):
    monkeypatch.delenv("AZURE_OPENAI_DEPLOYMENT_BALANCED", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_DEPLOYMENT_QUALITY", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_CHAT_DEPLOYMENT_NAME", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_DEPLOYMENT_NAME", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_DEPLOYMENT", raising=False)

    with pytest.raises(RuntimeError, match="AZURE_OPENAI_CHAT_DEPLOYMENT_NAME"):
        profile_config(Profile.BALANCED)


def test_cost_cap_warn_only_adds_warning_flag(monkeypatch):
    monkeypatch.setenv("AZURE_OPENAI_CHAT_DEPLOYMENT_NAME", "test-deployment")
    job = default_job_payload(
        JobCreateRequest(
            profile=Profile.BALANCED,
            input_files=[InputFile(source_type="video", size_bytes=100)],
        )
    )

    apply_cost_tracking_and_cap_warning(job, phase="processing", cost=4.5, cap_usd=4.0)

    warnings = [f for f in job["review_notes"]["flags"] if f.get("code") == "cost_cap_exceeded"]
    assert len(warnings) == 1
    assert warnings[0]["severity"] == "warning"
    assert warnings[0]["requires_user_action"] is False
    assert job["agent_signals"]["cost_tracking"]["total_estimated_usd"] == pytest.approx(4.5)


def test_cost_cap_warning_is_not_duplicated(monkeypatch):
    monkeypatch.setenv("AZURE_OPENAI_CHAT_DEPLOYMENT_NAME", "test-deployment")
    job = default_job_payload(
        JobCreateRequest(
            profile=Profile.BALANCED,
            input_files=[InputFile(source_type="video", size_bytes=100)],
        )
    )

    apply_cost_tracking_and_cap_warning(job, phase="extracting", cost=3.0, cap_usd=4.0)
    apply_cost_tracking_and_cap_warning(job, phase="processing", cost=2.0, cap_usd=4.0)
    apply_cost_tracking_and_cap_warning(job, phase="reviewing", cost=1.0, cap_usd=4.0)

    warnings = [f for f in job["review_notes"]["flags"] if f.get("code") == "cost_cap_exceeded"]
    assert len(warnings) == 1
    assert job["agent_signals"]["cost_tracking"]["total_estimated_usd"] == pytest.approx(6.0)
