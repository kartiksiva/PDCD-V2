"""Whisper transcription helpers for local audio/video blobs.

The returned transcript text is kept in-memory only by callers such as
VideoAdapter and must not be persisted directly on the job payload.
"""

from __future__ import annotations

import logging
import os

import httpx

from app.job_logic import _provider_name

logger = logging.getLogger(__name__)

_DEFAULT_AZURE_OPENAI_API_VERSION = "2024-10-21"
_MAX_TRANSCRIPTION_BYTES = 24 * 1024 * 1024


def _too_large_stub() -> str:
    return "[transcription_skipped:file_too_large — chunked transcription pending MediaPreprocessor]"


def _transcribe_with_azure(storage_key: str) -> str:
    from azure.identity import DefaultAzureCredential

    endpoint = os.environ["AZURE_OPENAI_ENDPOINT"].rstrip("/")
    deployment = os.environ.get("AZURE_OPENAI_WHISPER_DEPLOYMENT", "whisper")
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


def _transcribe_with_openai(storage_key: str) -> str:
    api_key = os.environ["OPENAI_API_KEY"]
    model = os.environ.get("OPENAI_TRANSCRIPTION_MODEL", "whisper-1")
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


def transcribe_audio_blob(storage_key: str) -> str:
    """Transcribe audio/video file at storage_key using Whisper. Returns VTT text."""
    try:
        size_bytes = os.path.getsize(storage_key)
        if size_bytes > _MAX_TRANSCRIPTION_BYTES:
            logger.warning(
                "Skipping transcription for %s: file too large (%d bytes)",
                storage_key,
                size_bytes,
            )
            return _too_large_stub()

        if _provider_name() == "openai":
            return _transcribe_with_openai(storage_key)
        return _transcribe_with_azure(storage_key)
    except Exception as exc:  # pragma: no cover - exercised by higher-level tests
        logger.error("Transcription failed for %s: %s", storage_key, exc, exc_info=True)
        return f"[transcription_failed:{type(exc).__name__}]"
