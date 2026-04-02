"""AudioAdapter — transcribes audio files via Azure AI Speech."""

from __future__ import annotations

import logging
import os
import tempfile
from typing import Any, Dict, List, Optional

from app.agents.schemas import EvidenceObject, ReviewFlag
from app.agents.extraction.adapters.base import IProcessEvidenceAdapter

logger = logging.getLogger(__name__)


class AudioAdapter(IProcessEvidenceAdapter):
    """
    Processes standalone audio files (wav, mp3, m4a).

    Uses Azure AI Speech for transcription with diarisation.
    Falls back to a low-confidence stub when Azure Speech is not configured.
    """

    source_type = "audio"

    def __init__(self) -> None:
        self._speech_key = os.environ.get("AZURE_SPEECH_KEY", "")
        self._speech_region = os.environ.get("AZURE_SPEECH_REGION", "")
        self._speech_endpoint = os.environ.get("AZURE_SPEECH_ENDPOINT", "")

    @property
    def _speech_configured(self) -> bool:
        return bool(self._speech_region or self._speech_endpoint)

    async def normalize(
        self,
        input_file: Dict[str, Any],
        blob_url: Optional[str] = None,
    ) -> List[EvidenceObject]:
        if not self._speech_configured:
            logger.warning(
                "AudioAdapter: Azure Speech not configured; returning stub evidence. "
                "Set AZURE_SPEECH_REGION and AZURE_SPEECH_KEY."
            )
            return self._stub_evidence(input_file)

        audio_path = input_file.get("local_path") or await self._download_audio(blob_url)
        if not audio_path:
            logger.error("AudioAdapter: no audio path available for %s", input_file.get("file_name"))
            return []

        return await self._transcribe(audio_path)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _transcribe(self, audio_path: str) -> List[EvidenceObject]:
        """Call Azure Speech SDK for continuous recognition with diarisation."""
        import azure.cognitiveservices.speech as speechsdk  # type: ignore[import]

        speech_config = speechsdk.SpeechConfig(
            subscription=self._speech_key,
            region=self._speech_region,
        )
        speech_config.speech_recognition_language = "en-US"
        speech_config.set_property(
            speechsdk.PropertyId.SpeechServiceResponse_DiarizeIntermediateResults,
            "true",
        )

        audio_config = speechsdk.AudioConfig(filename=audio_path)
        recognizer = speechsdk.SpeechRecognizer(
            speech_config=speech_config,
            audio_config=audio_config,
        )

        results: List[EvidenceObject] = []
        done = False

        def _on_result(evt):
            r = evt.result
            if r.reason == speechsdk.ResultReason.RecognizedSpeech:
                offset_sec = r.offset / 1e7
                duration_sec = r.duration / 1e7
                start = _fmt_ts(offset_sec)
                end = _fmt_ts(offset_sec + duration_sec)
                speaker = getattr(r, "speaker_id", "Unknown Speaker") or "Unknown Speaker"
                results.append(
                    EvidenceObject(
                        source_type="audio",
                        document_type="audio",
                        anchor=f"{start}-{end}",
                        confidence=0.85,
                        actor=speaker,
                        text_snippet=r.text,
                    )
                )

        def _on_canceled(evt):
            nonlocal done
            done = True

        def _on_stopped(evt):
            nonlocal done
            done = True

        recognizer.recognized.connect(_on_result)
        recognizer.canceled.connect(_on_canceled)
        recognizer.session_stopped.connect(_on_stopped)
        recognizer.start_continuous_recognition()

        import asyncio
        while not done:
            await asyncio.sleep(0.1)
        recognizer.stop_continuous_recognition()

        logger.info("AudioAdapter: transcribed %d segments", len(results))
        return results

    @staticmethod
    async def _download_audio(url: Optional[str]) -> Optional[str]:
        if not url:
            return None
        import aiohttp  # type: ignore[import]
        suffix = ".wav"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as f:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as resp:
                    resp.raise_for_status()
                    f.write(await resp.read())
            return f.name

    @staticmethod
    def _stub_evidence(input_file: Dict[str, Any]) -> List[EvidenceObject]:
        return [
            EvidenceObject(
                source_type="audio",
                document_type="audio",
                anchor="00:00:00-00:00:10",
                confidence=0.3,
                actor="Unknown Speaker",
                text_snippet="[Audio transcription unavailable — Azure Speech not configured]",
                metadata={"stub": True, "file_name": input_file.get("file_name")},
            )
        ]

    # ------------------------------------------------------------------
    # IProcessEvidenceAdapter
    # ------------------------------------------------------------------

    def extract_facts(self, evidence: List[EvidenceObject]) -> List[EvidenceObject]:
        """Remove very short or empty segments."""
        return [e for e in evidence if len(e.text_snippet or "") > 2]

    def render_review_notes(self, evidence: List[EvidenceObject]) -> List[ReviewFlag]:
        flags: List[ReviewFlag] = []
        stubs = [e for e in evidence if e.metadata.get("stub")]
        if stubs:
            flags.append(ReviewFlag(
                code="audio_transcription_unavailable",
                severity="warning",
                message="Audio transcription was not performed; Azure Speech is not configured.",
                requires_user_action=False,
            ))
        low_conf = [e for e in evidence if e.confidence < 0.5]
        if low_conf:
            flags.append(ReviewFlag(
                code="audio_low_confidence",
                severity="info",
                message=f"{len(low_conf)} audio segments have confidence < 0.5.",
                requires_user_action=False,
            ))
        return flags


def _fmt_ts(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"
