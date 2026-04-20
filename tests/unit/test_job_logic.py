"""Tests for profile deployment selection in job_logic."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.job_logic import (
    InputFile,
    JobCreateRequest,
    Profile,
    apply_cost_tracking_and_cap_warning,
    default_job_payload,
    get_transcription_target,
    get_vision_model,
    profile_config,
)


def test_profile_config_prefers_azure_openai_deployment_name(monkeypatch):
    monkeypatch.delenv("PFCD_PROVIDER", raising=False)
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
    monkeypatch.delenv("PFCD_PROVIDER", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_DEPLOYMENT_BALANCED", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_DEPLOYMENT_QUALITY", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_CHAT_DEPLOYMENT_NAME", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_DEPLOYMENT_NAME", raising=False)
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT", "my-fallback-deployment")

    cfg = profile_config(Profile.BALANCED)
    assert cfg["model"] == "my-fallback-deployment"


def test_profile_config_falls_back_to_deployment_name_alias(monkeypatch):
    monkeypatch.delenv("PFCD_PROVIDER", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_DEPLOYMENT_BALANCED", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_DEPLOYMENT_QUALITY", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_CHAT_DEPLOYMENT_NAME", raising=False)
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT_NAME", "legacy-name-deployment")
    monkeypatch.delenv("AZURE_OPENAI_DEPLOYMENT", raising=False)

    cfg = profile_config(Profile.BALANCED)
    assert cfg["model"] == "legacy-name-deployment"


def test_profile_config_prefers_profile_specific_env(monkeypatch):
    monkeypatch.delenv("PFCD_PROVIDER", raising=False)
    monkeypatch.setenv("AZURE_OPENAI_CHAT_DEPLOYMENT_NAME", "generic-deployment")
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT_BALANCED", "balanced-deployment")
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT_QUALITY", "quality-deployment")

    balanced = profile_config(Profile.BALANCED)
    quality = profile_config(Profile.QUALITY)

    assert balanced["model"] == "balanced-deployment"
    assert quality["model"] == "quality-deployment"


def test_profile_config_raises_when_deployment_not_configured(monkeypatch):
    monkeypatch.delenv("PFCD_PROVIDER", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_DEPLOYMENT_BALANCED", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_DEPLOYMENT_QUALITY", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_CHAT_DEPLOYMENT_NAME", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_DEPLOYMENT_NAME", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_DEPLOYMENT", raising=False)

    with pytest.raises(RuntimeError, match="AZURE_OPENAI_CHAT_DEPLOYMENT_NAME"):
        profile_config(Profile.BALANCED)


def test_profile_config_openai_provider_uses_openai_chat_models(monkeypatch):
    monkeypatch.setenv("PFCD_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_CHAT_MODEL_BALANCED", "gpt-4o-mini")
    monkeypatch.setenv("OPENAI_CHAT_MODEL_QUALITY", "gpt-4o")

    balanced = profile_config(Profile.BALANCED)
    quality = profile_config(Profile.QUALITY)

    assert balanced["provider"] == "openai"
    assert balanced["model"] == "gpt-4o-mini"
    assert quality["provider"] == "openai"
    assert quality["model"] == "gpt-4o"


def test_default_job_payload_uses_provider_effective_from_profile(monkeypatch):
    monkeypatch.setenv("PFCD_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_CHAT_MODEL_BALANCED", "gpt-4o-mini")

    job = default_job_payload(
        JobCreateRequest(
            profile=Profile.BALANCED,
            input_files=[InputFile(source_type="video", size_bytes=100)],
        )
    )

    assert job["provider_effective"]["provider"] == "openai"
    assert job["provider_effective"]["deployment"] == "gpt-4o-mini"
    assert job["provider_effective"]["chat_model"] == "gpt-4o-mini"
    assert job["provider_effective"]["transcription"]["service"] == "openai_whisper"


@pytest.mark.parametrize(
    ("provider", "profile", "balanced_key", "quality_key", "fallback_key", "expected"),
    [
        (
            "openai",
            Profile.BALANCED,
            "OPENAI_VISION_MODEL_BALANCED",
            "OPENAI_VISION_MODEL_QUALITY",
            "OPENAI_VISION_MODEL",
            "gpt-4o-mini",
        ),
        (
            "openai",
            Profile.QUALITY,
            "OPENAI_VISION_MODEL_BALANCED",
            "OPENAI_VISION_MODEL_QUALITY",
            "OPENAI_VISION_MODEL",
            "gpt-4o",
        ),
        (
            "azure_openai",
            Profile.BALANCED,
            "AZURE_OPENAI_VISION_DEPLOYMENT_BALANCED",
            "AZURE_OPENAI_VISION_DEPLOYMENT_QUALITY",
            "AZURE_OPENAI_VISION_DEPLOYMENT",
            "azure-vision-balanced",
        ),
        (
            "azure_openai",
            Profile.QUALITY,
            "AZURE_OPENAI_VISION_DEPLOYMENT_BALANCED",
            "AZURE_OPENAI_VISION_DEPLOYMENT_QUALITY",
            "AZURE_OPENAI_VISION_DEPLOYMENT",
            "azure-vision-quality",
        ),
    ],
)
def test_get_vision_model_profile_matrix(
    monkeypatch,
    provider,
    profile,
    balanced_key,
    quality_key,
    fallback_key,
    expected,
):
    monkeypatch.setenv("PFCD_PROVIDER", provider)
    monkeypatch.setenv(balanced_key, "gpt-4o-mini" if provider == "openai" else "azure-vision-balanced")
    monkeypatch.setenv(quality_key, "gpt-4o" if provider == "openai" else "azure-vision-quality")
    monkeypatch.delenv(fallback_key, raising=False)

    assert get_vision_model(profile) == expected


def test_get_vision_model_falls_back_to_single_var(monkeypatch):
    monkeypatch.setenv("PFCD_PROVIDER", "openai")
    monkeypatch.delenv("OPENAI_VISION_MODEL_BALANCED", raising=False)
    monkeypatch.delenv("OPENAI_VISION_MODEL_QUALITY", raising=False)
    monkeypatch.setenv("OPENAI_VISION_MODEL", "gpt-4.1-mini")
    assert get_vision_model(Profile.BALANCED) == "gpt-4.1-mini"
    assert get_vision_model(Profile.QUALITY) == "gpt-4.1-mini"


def test_get_transcription_target_provider_matrix(monkeypatch):
    monkeypatch.setenv("PFCD_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_TRANSCRIPTION_MODEL", "whisper-1")
    openai_target = get_transcription_target(Profile.BALANCED)
    assert openai_target["service"] == "openai_whisper"
    assert openai_target["model"] == "whisper-1"

    monkeypatch.setenv("PFCD_PROVIDER", "azure_openai")
    monkeypatch.setenv("AZURE_OPENAI_WHISPER_DEPLOYMENT", "whisper-prod")
    azure_target = get_transcription_target(Profile.QUALITY)
    assert azure_target["service"] == "azure_openai_whisper"
    assert azure_target["model"] == "whisper-prod"


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


def test_default_job_payload_uses_ttl_env_override(monkeypatch):
    monkeypatch.setenv("AZURE_OPENAI_CHAT_DEPLOYMENT_NAME", "test-deployment")
    monkeypatch.setenv("PFCD_JOB_TTL_DAYS", "14")

    job = default_job_payload(
        JobCreateRequest(
            profile=Profile.BALANCED,
            input_files=[InputFile(source_type="video", size_bytes=100)],
        )
    )

    ttl_dt = datetime.fromisoformat(job["ttl_expires_at"])
    delta_days = (ttl_dt - datetime.now(timezone.utc)).total_seconds() / 86400

    assert 13.9 <= delta_days <= 14.1
