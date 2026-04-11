"""Unit tests for Semantic Kernel factory configuration."""

from __future__ import annotations

from unittest.mock import patch

from app.agents.kernel_factory import get_kernel


def test_get_kernel_uses_default_api_version(monkeypatch):
    endpoint = "https://example.openai.azure.com/"
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", endpoint)
    monkeypatch.delenv("AZURE_OPENAI_API_VERSION", raising=False)

    with patch("app.agents.kernel_factory._cached_kernel", return_value="kernel") as cached:
        result = get_kernel("my-deployment")

    assert result == "kernel"
    cached.assert_called_once_with(endpoint, "my-deployment", "2024-10-21")


def test_get_kernel_uses_env_api_version(monkeypatch):
    endpoint = "https://example.openai.azure.com/"
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", endpoint)
    monkeypatch.setenv("AZURE_OPENAI_API_VERSION", "2025-01-01-preview")

    with patch("app.agents.kernel_factory._cached_kernel", return_value="kernel") as cached:
        result = get_kernel("my-deployment")

    assert result == "kernel"
    cached.assert_called_once_with(endpoint, "my-deployment", "2025-01-01-preview")
