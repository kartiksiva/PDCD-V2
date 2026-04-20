"""Whisper transcription helpers for local audio/video blobs.

The returned transcript text is kept in-memory only by callers such as
VideoAdapter and must not be persisted directly on the job payload.
"""

from __future__ import annotations

import logging
import os
import shutil

import httpx

from app.agents.media_preprocessor import (
    extract_audio_track,
    is_ffmpeg_available,
    merge_vtt_chunks,
    split_audio_chunks,
)
from app.job_logic import Profile, _provider_name, get_transcription_target

logger = logging.getLogger(__name__)

_DEFAULT_AZURE_OPENAI_API_VERSION = "2024-10-21"
_MAX_TRANSCRIPTION_BYTES = 24 * 1024 * 1024
_CHUNK_DURATION_SEC = 600


def _too_large_stub() -> str:
    return "[transcription_skipped:file_too_large — chunked transcription pending MediaPreprocessor]"


def _transcribe_with_azure(storage_key: str, *, deployment: str) -> str:
    from azure.identity import DefaultAzureCredential

    endpoint = os.environ["AZURE_OPENAI_ENDPOINT"].rstrip("/")
    api_version = os.environ.get("AZURE_OPENAI_API_VERSION", _DEFAULT_AZURE_OPENAI_API_VERSION)
    url = (
        f"{endpoint}/openai/deployments/{deployment}/audio/transcriptions"
        f"?api-version={api_version}"
    )

    credential = DefaultAzureCredential()
    token = credential.get_token("https://cognitiveservices.azure.com/.default")
    headers = {"Authorization": f"Bearer {token.token}"}

    with open(storage_key, "rb") as fh:
        files = {"file": (os.path.basename(storage_key), fh, "application/octet-stream")}
        data = {"response_format": "vtt"}
        response = httpx.post(url, headers=headers, files=files, data=data, timeout=120.0)
        response.raise_for_status()
        return response.text


def _transcribe_with_openai(storage_key: str, *, model: str) -> str:
    api_key = os.environ["OPENAI_API_KEY"]
    headers = {"Authorization": f"Bearer {api_key}"}

    with open(storage_key, "rb") as fh:
        files = {"file": (os.path.basename(storage_key), fh, "application/octet-stream")}
        data = {"model": model, "response_format": "vtt"}
        response = httpx.post(
            "https://api.openai.com/v1/audio/transcriptions",
            headers=headers,
            files=files,
            data=data,
            timeout=120.0,
        )
        response.raise_for_status()
        return response.text


def _resolve_profile(profile: str | None) -> Profile:
    if (profile or "").strip().lower() == Profile.QUALITY.value:
        return Profile.QUALITY
    return Profile.BALANCED


def _transcribe_single(path: str, profile: str | None = None) -> str:
    target = get_transcription_target(_resolve_profile(profile))
    if _provider_name() == "openai":
        return _transcribe_with_openai(path, model=target["model"])
    return _transcribe_with_azure(path, deployment=target["model"])


def transcribe_audio_blob(storage_key: str, *, profile: str | None = None) -> str:
    """Transcribe audio/video file at storage_key using Whisper. Returns VTT text."""
    tmp_dir: str | None = None
    try:
        size_bytes = os.path.getsize(storage_key)
        work_path = storage_key

        if size_bytes > _MAX_TRANSCRIPTION_BYTES:
            if not is_ffmpeg_available():
                logger.warning(
                    "File %s is %.1f MB and ffmpeg is not available; skipping transcription",
                    storage_key,
                    size_bytes / 1024 / 1024,
                )
                return _too_large_stub()

            import tempfile

            tmp_dir = tempfile.mkdtemp(prefix="pfcd_transcribe_")
            audio_path = extract_audio_track(storage_key, tmp_dir)
            if audio_path is None:
                logger.warning("Audio extraction failed for %s; skipping", storage_key)
                return _too_large_stub()

            work_path = audio_path
            # Future extension point: extract keyframes here once a multimodal
            # video-analysis target exists in the pipeline.

        audio_size = os.path.getsize(work_path)
        if audio_size > _MAX_TRANSCRIPTION_BYTES:
            chunk_pairs = split_audio_chunks(work_path, _CHUNK_DURATION_SEC)
        else:
            chunk_pairs = [(work_path, 0.0)]

        vtt_chunks: list[tuple[str, float]] = []
        for chunk_path, offset_sec in chunk_pairs:
            if profile is None:
                vtt = _transcribe_single(chunk_path)
            else:
                vtt = _transcribe_single(chunk_path, profile)
            if vtt.startswith("[transcription"):
                logger.warning("Chunk transcription failed at offset %.0fs: %s", offset_sec, vtt)
                continue
            vtt_chunks.append((vtt, offset_sec))

        if not vtt_chunks:
            return "[transcription_failed:all_chunks_failed]"

        return merge_vtt_chunks(vtt_chunks)
    except Exception as exc:  # pragma: no cover - exercised by higher-level tests
        logger.error("Transcription failed for %s: %s", storage_key, exc, exc_info=True)
        return f"[transcription_failed:{type(exc).__name__}]"
    finally:
        if tmp_dir:
            shutil.rmtree(tmp_dir, ignore_errors=True)
