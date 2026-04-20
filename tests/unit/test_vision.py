"""Unit tests for frame-level vision analysis helpers."""

from __future__ import annotations

import pathlib
import sys
from unittest.mock import patch

import httpx

ROOT = pathlib.Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))


def test_analyze_frames_returns_empty_on_empty_input():
    from app.agents.vision import analyze_frames

    assert analyze_frames([], {}) == ""


def test_analyze_frames_calls_openai_provider(monkeypatch):
    from app.agents.vision import analyze_frames

    frames = [("/tmp/f1.jpg", 0.0)]

    monkeypatch.setattr("app.agents.vision._provider_name", lambda: "openai")
    monkeypatch.setattr("app.agents.vision._build_messages", lambda _frames, _policy: [{"role": "user"}])
    monkeypatch.setattr(
        "app.agents.vision._call_vision_openai",
        lambda _messages: "Frame 1: User opens SAP.",
    )

    result = analyze_frames(frames, {})

    assert "Frame 1: User opens SAP." in result


def test_analyze_frames_returns_empty_on_exception(monkeypatch):
    from app.agents.vision import analyze_frames

    frames = [("/tmp/f1.jpg", 0.0)]

    monkeypatch.setattr("app.agents.vision._provider_name", lambda: "openai")
    monkeypatch.setattr("app.agents.vision._build_messages", lambda _frames, _policy: [{"role": "user"}])

    def _raise(_messages):
        raise httpx.HTTPError("boom")

    monkeypatch.setattr("app.agents.vision._call_vision_openai", _raise)

    assert analyze_frames(frames, {}) == ""


def test_analyze_frames_batches_frames(monkeypatch):
    from app.agents.vision import analyze_frames

    frames = [
        ("/tmp/f1.jpg", 0.0),
        ("/tmp/f2.jpg", 5.0),
        ("/tmp/f3.jpg", 10.0),
        ("/tmp/f4.jpg", 15.0),
        ("/tmp/f5.jpg", 20.0),
    ]

    monkeypatch.setattr("app.agents.vision._provider_name", lambda: "openai")
    monkeypatch.setattr("app.agents.vision._build_messages", lambda _frames, _policy: [{"role": "user"}])
    monkeypatch.setattr("app.agents.vision._MAX_FRAMES_PER_CALL", 2)

    with patch("app.agents.vision._call_vision_openai", return_value="ok") as mock_call:
        result = analyze_frames(frames, {})

    assert result == "ok\n\nok\n\nok"
    assert mock_call.call_count == 3


def test_call_vision_openai_uses_max_completion_tokens(monkeypatch):
    from app.agents.vision import _call_vision_openai

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("PFCD_MAX_COMPLETION_TOKENS", "333")

    captured: dict = {}

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": "ok"}}]}

    def _fake_post(_url, headers, json, timeout):
        captured["headers"] = headers
        captured["json"] = json
        captured["timeout"] = timeout
        return _Resp()

    monkeypatch.setattr("app.agents.vision.httpx.post", _fake_post)

    result = _call_vision_openai([{"role": "user", "content": "x"}])

    assert result == "ok"
    assert captured["json"]["max_completion_tokens"] == 333
    assert "max_tokens" not in captured["json"]


def test_call_vision_azure_uses_max_completion_tokens(monkeypatch):
    from app.agents import vision

    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://example.openai.azure.com")
    monkeypatch.setenv("AZURE_OPENAI_API_VERSION", "2024-10-21")
    monkeypatch.setenv("PFCD_MAX_COMPLETION_TOKENS", "444")
    monkeypatch.setattr("app.agents.vision._AZURE_VISION_DEPLOYMENT", "vision-deployment")

    captured: dict = {}

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": "ok"}}]}

    class _Credential:
        def get_token(self, _scope):
            class _Token:
                token = "fake-token"

            return _Token()

    def _fake_post(_url, headers, json, timeout):
        captured["headers"] = headers
        captured["json"] = json
        captured["timeout"] = timeout
        return _Resp()

    monkeypatch.setattr("app.agents.vision.httpx.post", _fake_post)
    monkeypatch.setattr("azure.identity.DefaultAzureCredential", lambda: _Credential())

    result = vision._call_vision_azure([{"role": "user", "content": "x"}])

    assert result == "ok"
    assert captured["json"]["max_completion_tokens"] == 444
    assert "max_tokens" not in captured["json"]
