"""Unit tests for media preprocessing helpers and large-file transcription flow."""

from __future__ import annotations

import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))


def test_is_ffmpeg_available_returns_bool(monkeypatch):
    from app.agents.media_preprocessor import is_ffmpeg_available

    def _ok(*args, **kwargs):
        return subprocess.CompletedProcess(args[0], 0)

    def _bad(*args, **kwargs):
        return subprocess.CompletedProcess(args[0], 1)

    monkeypatch.setattr("app.agents.media_preprocessor.subprocess.run", _ok)
    assert isinstance(is_ffmpeg_available(), bool)
    assert is_ffmpeg_available() is True

    monkeypatch.setattr("app.agents.media_preprocessor.subprocess.run", _bad)
    assert isinstance(is_ffmpeg_available(), bool)
    assert is_ffmpeg_available() is False


def test_merge_vtt_chunks_single_chunk_no_offset():
    from app.agents.media_preprocessor import merge_vtt_chunks

    vtt_text = "WEBVTT\n\n00:00:00.000 --> 00:00:03.000\nOpen SAP.\n"

    merged = merge_vtt_chunks([(vtt_text, 0.0)])

    assert merged.startswith("WEBVTT")
    assert "00:00:00.000 --> 00:00:03.000" in merged


def test_merge_vtt_chunks_two_chunks_offsets_applied():
    from app.agents.media_preprocessor import merge_vtt_chunks

    first = "WEBVTT\n\n00:00:00.000 --> 00:00:03.000\nOpen SAP.\n"
    second = "WEBVTT\n\n00:00:00.000 --> 00:00:05.000\nApprove invoice.\n"

    merged = merge_vtt_chunks([(first, 0.0), (second, 600.0)])

    assert "00:00:00.000 --> 00:00:03.000" in merged
    assert "00:10:00.000 --> 00:10:05.000" in merged


def test_merge_vtt_chunks_handles_comma_separator():
    from app.agents.media_preprocessor import merge_vtt_chunks

    vtt_text = "WEBVTT\n\n00:00:00,100 --> 00:00:03,200\nOpen SAP.\n"

    merged = merge_vtt_chunks([(vtt_text, 0.0)])

    assert "00:00:00.100 --> 00:00:03.200" in merged


def test_split_audio_chunks_returns_single_if_small(monkeypatch):
    from app.agents.media_preprocessor import split_audio_chunks

    monkeypatch.setattr("app.agents.media_preprocessor.os.path.getsize", lambda _path: 1024)

    assert split_audio_chunks("/tmp/demo.mp3") == [("/tmp/demo.mp3", 0.0)]


def test_extract_keyframes_returns_empty_when_ffmpeg_unavailable(monkeypatch):
    from app.agents.media_preprocessor import extract_keyframes

    def _missing(*args, **kwargs):
        raise FileNotFoundError

    monkeypatch.setattr("app.agents.media_preprocessor.subprocess.run", _missing)

    assert extract_keyframes("/tmp/demo.mp4", "/tmp/frames") == []


def test_extract_keyframes_returns_list_of_tuples(monkeypatch):
    from app.agents.media_preprocessor import extract_keyframes

    monkeypatch.setattr(
        "app.agents.media_preprocessor.subprocess.run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0),
    )
    monkeypatch.setattr(
        "app.agents.media_preprocessor.glob.glob",
        lambda _pattern: ["frame_0001.jpg", "frame_0002.jpg"],
    )

    assert extract_keyframes("/tmp/demo.mp4", "/tmp/frames") == [
        ("frame_0001.jpg", 0.0),
        ("frame_0002.jpg", 5.0),
    ]


def test_transcribe_audio_blob_uses_preprocessor_for_large_file(monkeypatch, tmp_path):
    from app.agents.transcription import transcribe_audio_blob

    source_path = str(tmp_path / "meeting.mp4")
    extracted_path = str(tmp_path / "meeting_audio.mp3")
    vtt_text = "WEBVTT\n\n00:00:00.000 --> 00:00:03.000\nFinance Analyst: Open SAP.\n"

    def _fake_getsize(path: str) -> int:
        if path == source_path:
            return 50 * 1024 * 1024
        if path == extracted_path:
            return 50 * 1024 * 1024
        raise AssertionError(f"unexpected path: {path}")

    monkeypatch.setattr("app.agents.transcription.os.path.getsize", _fake_getsize)
    monkeypatch.setattr("app.agents.transcription.is_ffmpeg_available", lambda: True)
    monkeypatch.setattr("app.agents.transcription.extract_audio_track", lambda _src, _out: extracted_path)
    monkeypatch.setattr(
        "app.agents.transcription.split_audio_chunks",
        lambda _path, _chunk_sec: [(extracted_path, 0.0)],
    )
    monkeypatch.setattr("app.agents.transcription._transcribe_single", lambda _path: vtt_text)
    monkeypatch.setattr(tempfile, "mkdtemp", lambda prefix="": str(tmp_path / "work"))

    result = transcribe_audio_blob(source_path)

    assert result.startswith("WEBVTT")
    assert "00:00:00.000 --> 00:00:03.000" in result


def test_transcribe_audio_blob_falls_back_when_ffmpeg_unavailable(monkeypatch, tmp_path):
    from app.agents.transcription import _too_large_stub, transcribe_audio_blob

    source_path = str(tmp_path / "meeting.mp4")

    monkeypatch.setattr(
        "app.agents.transcription.os.path.getsize",
        lambda _path: 50 * 1024 * 1024,
    )
    monkeypatch.setattr("app.agents.transcription.is_ffmpeg_available", lambda: False)

    assert transcribe_audio_blob(source_path) == _too_large_stub()
