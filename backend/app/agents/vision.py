"""Frame-level visual analysis using a vision-capable LLM."""

from __future__ import annotations

import base64
import logging
import os
from typing import Any

import httpx

from app.job_logic import _provider_name

logger = logging.getLogger(__name__)

_MAX_FRAMES_PER_CALL = int(os.environ.get("PFCD_VISION_FRAMES_PER_CALL", "4"))
_MAX_FRAMES_TOTAL = int(os.environ.get("PFCD_VISION_MAX_FRAMES", "40"))
_OPENAI_VISION_MODEL = os.environ.get("OPENAI_VISION_MODEL", "gpt-4o-mini")
_AZURE_VISION_DEPLOYMENT = os.environ.get("AZURE_OPENAI_VISION_DEPLOYMENT", "")

_SYSTEM_PROMPT = """You are a process documentation assistant. For each video frame shown, describe:
1. What the user is doing (actions, clicks, navigation)
2. What application or screen is visible
3. Any visible text that identifies a process step, form field, or transaction

Be concise. Focus on process-relevant actions, not aesthetics.
Output one paragraph per frame, prefixed with the frame timestamp."""


def _max_completion_tokens() -> int:
    raw = os.environ.get("PFCD_MAX_COMPLETION_TOKENS", "2048").strip()
    try:
        value = int(raw)
    except ValueError:
        return 2048
    return max(1, value)


def _encode_image(path: str) -> str:
    with open(path, "rb") as fh:
        return base64.b64encode(fh.read()).decode("ascii")


def _build_messages(batch: list[tuple[str, float]], policy: dict[str, Any]) -> list[dict[str, Any]]:
    start_ts = batch[0][1]
    end_ts = batch[-1][1]
    content: list[dict[str, Any]] = [
        {
            "type": "text",
            "text": (
                f"Analyze frames from {start_ts:.1f}s to {end_ts:.1f}s. "
                f"Frame policy: {policy or {}}."
            ),
        }
    ]
    for frame_path, timestamp_sec in batch:
        content.append({"type": "text", "text": f"Frame timestamp: {timestamp_sec:.1f}s"})
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{_encode_image(frame_path)}"},
            }
        )

    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": content},
    ]


def _call_vision_openai(messages: list[dict]) -> str:
    """POST to OpenAI chat completions with vision content."""
    api_key = os.environ["OPENAI_API_KEY"]
    response = httpx.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": _OPENAI_VISION_MODEL,
            "messages": messages,
            "max_completion_tokens": _max_completion_tokens(),
        },
        timeout=60.0,
    )
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]


def _call_vision_azure(messages: list[dict]) -> str:
    """POST to Azure OpenAI chat completions with vision content."""
    from azure.identity import DefaultAzureCredential

    if not _AZURE_VISION_DEPLOYMENT:
        raise ValueError("AZURE_OPENAI_VISION_DEPLOYMENT is not set")

    endpoint = os.environ["AZURE_OPENAI_ENDPOINT"].rstrip("/")
    api_version = os.environ.get("AZURE_OPENAI_API_VERSION", "2024-10-21")
    url = (
        f"{endpoint}/openai/deployments/{_AZURE_VISION_DEPLOYMENT}"
        f"/chat/completions?api-version={api_version}"
    )
    credential = DefaultAzureCredential()
    token = credential.get_token("https://cognitiveservices.azure.com/.default")
    response = httpx.post(
        url,
        headers={"Authorization": f"Bearer {token.token}"},
        json={"messages": messages, "max_completion_tokens": _max_completion_tokens()},
        timeout=60.0,
    )
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]


def analyze_frames(frames: list[tuple[str, float]], policy: dict) -> str:
    if not frames:
        return ""

    try:
        capped_frames = frames[:_MAX_FRAMES_TOTAL]
        responses: list[str] = []
        batch_size = max(_MAX_FRAMES_PER_CALL, 1)

        for index in range(0, len(capped_frames), batch_size):
            batch = capped_frames[index:index + batch_size]
            messages = _build_messages(batch, policy)
            if _provider_name() == "openai":
                responses.append(_call_vision_openai(messages))
            else:
                responses.append(_call_vision_azure(messages))

        return "\n\n".join(text for text in responses if text)
    except Exception as exc:  # pragma: no cover - exercised by unit tests
        logger.warning("Frame analysis failed: %s", exc)
        return ""
