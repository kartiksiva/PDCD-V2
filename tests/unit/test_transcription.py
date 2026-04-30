"""Unit tests for transcription HTTP retry and quota handling."""

from __future__ import annotations

import pathlib
import sys

import httpx
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))


class _Resp:
    def __init__(self, status_code: int, text: str = "") -> None:
        self.status_code = status_code
        self.text = text

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            request = httpx.Request("POST", "https://example.com")
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError("boom", request=request, response=response)


def test_transcribe_with_openai_retries_429_and_5xx_then_succeeds(monkeypatch, tmp_path):
    from app.agents import transcription

    sample = tmp_path / "sample.wav"
    sample.write_bytes(b"audio")

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    sleeps = []
    monkeypatch.setattr(transcription.time, "sleep", lambda seconds: sleeps.append(seconds))

    statuses = iter([429, 503, 200])

    def _fake_post(*args, **kwargs):
        status = next(statuses)
        if status == 200:
            return _Resp(200, "WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nok\n")
        return _Resp(status)

    monkeypatch.setattr(transcription.httpx, "post", _fake_post)

    result = transcription._transcribe_with_openai(str(sample), model="gpt-4o-mini")

    assert result.startswith("WEBVTT")
    assert sleeps == [1.0, 2.0]


def test_transcribe_with_openai_raises_quota_after_bounded_retries(monkeypatch, tmp_path):
    from app.agents import transcription

    sample = tmp_path / "sample.wav"
    sample.write_bytes(b"audio")

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    sleeps = []
    monkeypatch.setattr(transcription.time, "sleep", lambda seconds: sleeps.append(seconds))
    monkeypatch.setattr(transcription.httpx, "post", lambda *args, **kwargs: _Resp(429))

    with pytest.raises(transcription.TranscriptionQuotaError):
        transcription._transcribe_with_openai(str(sample), model="gpt-4o-mini")

    assert sleeps == [1.0, 2.0, 4.0]


def test_transcribe_audio_blob_surfaces_quota_distinct_error(monkeypatch):
    from app.agents import transcription

    monkeypatch.setattr(transcription.os.path, "getsize", lambda _path: 1024)
    monkeypatch.setattr(
        transcription,
        "_transcribe_single",
        lambda _path, _profile=None: (_ for _ in ()).throw(
            transcription.TranscriptionQuotaError("rate limited")
        ),
    )

    result = transcription.transcribe_audio_blob("/tmp/audio.mp3")

    assert result == "[transcription_failed:TranscriptionQuotaError]"
