"""Unit tests for Semantic Kernel factory configuration."""

from __future__ import annotations

from unittest.mock import patch

import app.agents.kernel_factory as kernel_factory


def test_get_kernel_uses_default_api_version(monkeypatch):
    endpoint = "https://example.openai.azure.com/"
    monkeypatch.delenv("PFCD_PROVIDER", raising=False)
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", endpoint)
    monkeypatch.delenv("AZURE_OPENAI_API_VERSION", raising=False)

    with patch("app.agents.kernel_factory._cached_kernel_azure", return_value="kernel") as cached:
        result = kernel_factory.get_kernel("my-deployment")

    assert result == "kernel"
    cached.assert_called_once_with(endpoint, "my-deployment", "2024-10-21")


def test_get_kernel_uses_env_api_version(monkeypatch):
    endpoint = "https://example.openai.azure.com/"
    monkeypatch.delenv("PFCD_PROVIDER", raising=False)
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", endpoint)
    monkeypatch.setenv("AZURE_OPENAI_API_VERSION", "2025-01-01-preview")

    with patch("app.agents.kernel_factory._cached_kernel_azure", return_value="kernel") as cached:
        result = kernel_factory.get_kernel("my-deployment")

    assert result == "kernel"
    cached.assert_called_once_with(endpoint, "my-deployment", "2025-01-01-preview")


def test_get_kernel_openai_provider_uses_openai_cache(monkeypatch):
    monkeypatch.setenv("PFCD_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    with patch("app.agents.kernel_factory._cached_kernel_openai", return_value="kernel") as cached:
        result = kernel_factory.get_kernel("gpt-4o-mini")

    assert result == "kernel"
    cached.assert_called_once_with("test-key", "gpt-4o-mini")


def test_get_chat_service_returns_openai_service(monkeypatch):
    monkeypatch.setenv("PFCD_PROVIDER", "openai")

    fake_service = object()

    class FakeKernel:
        def get_service(self, *, type):
            return fake_service

    with patch("app.agents.kernel_factory.get_kernel", return_value=FakeKernel()):
        result = kernel_factory.get_chat_service("gpt-4o-mini")

    assert result is fake_service
