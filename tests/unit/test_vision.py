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
