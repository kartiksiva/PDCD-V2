"""AudioAdapter — normalizes audio source metadata into canonical evidence."""

from __future__ import annotations

from typing import Any, Dict, List

from app.agents.adapters.base import (
    DetectionResult,
    EvidenceObject,
    FactItem,
    IProcessEvidenceAdapter,
)
from app.agents.alignment import parse_vtt_cues
from app.agents.transcription import transcribe_audio_blob

_AUDIO_MIME_PREFIXES = ("audio/",)


def _format_seconds(total_seconds: float) -> str:
    total = max(int(total_seconds), 0)
    hours = total // 3600
    minutes = (total % 3600) // 60
    seconds = total % 60
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


class AudioAdapter(IProcessEvidenceAdapter):
    """Adapter for audio-only source inputs."""

    def detect(self, manifest_entry: Dict[str, Any]) -> DetectionResult:
        source_type = manifest_entry.get("source_type", "")
        mime = (manifest_entry.get("mime_type") or "").lower()
        if source_type != "audio":
            return DetectionResult(
                source_type=source_type,
                document_type="unknown",
                valid=False,
                confidence=0.0,
                notes=["source_type is not 'audio'"],
            )

        notes: List[str] = []
        if mime and any(mime.startswith(prefix) for prefix in _AUDIO_MIME_PREFIXES):
            notes.append(f"Audio MIME type confirmed: {mime}")
        else:
            notes.append("Audio source accepted; MIME type not strictly validated.")
        return DetectionResult(
            source_type="audio",
            document_type="audio",
            valid=True,
            confidence=0.70,
            notes=notes,
        )

    def normalize(self, job: Dict[str, Any]) -> EvidenceObject:
        manifest = job.get("input_manifest") or {}
        source_inputs = manifest.get("inputs") or []
        audio_input = next((inp for inp in source_inputs if inp.get("source_type") == "audio"), {})
        storage_key = audio_input.get("storage_key")
        profile = job.get("profile_requested") or "balanced"

        transcript_text = ""
        if storage_key:
            try:
                raw = transcribe_audio_blob(storage_key, profile=profile)
            except TypeError:
                raw = transcribe_audio_blob(storage_key)
            if raw and not raw.startswith("[transcription"):
                transcript_text = raw
                job["_audio_transcript_inline"] = raw

        if transcript_text:
            anchors = [
                f"{_format_seconds(start)}-{_format_seconds(end)}"
                for start, end in parse_vtt_cues(transcript_text)
            ]
            return EvidenceObject(
                source_type="audio",
                document_type="audio",
                content_text=transcript_text,
                anchors=anchors,
                confidence=0.70,
                metadata={
                    "storage_key": storage_key,
                    "transcribed": True,
                    "duration_hint_sec": manifest.get("duration_hint_sec"),
                },
            )

        size_bytes = audio_input.get("size_bytes") or 0
        file_name = audio_input.get("file_name") or "audio-input"
        content = (
            f"Source type: audio\n"
            f"File name: {file_name}\n"
            f"Approx size bytes: {size_bytes}\n"
            "Audio transcription is unavailable; extraction uses metadata-only context."
        )
        return EvidenceObject(
            source_type="audio",
            document_type="audio",
            content_text=content,
            anchors=[],
            confidence=0.55,
            metadata={
                "storage_key": storage_key,
                "transcribed": False,
                "duration_hint_sec": manifest.get("duration_hint_sec"),
            },
        )

    def extract_facts(self, job: Dict[str, Any]) -> List[FactItem]:
        raw = str(job.get("_audio_transcript_inline") or "").strip()
        if not raw:
            return []
        cues = parse_vtt_cues(raw)
        facts: List[FactItem] = []
        for index, (start, end) in enumerate(cues):
            facts.append(
                FactItem(
                    anchor=f"{_format_seconds(start)}-{_format_seconds(end)}",
                    content=f"Audio segment {index + 1}",
                    speaker=None,
                    confidence=0.55,
                )
            )
        return facts

    def render_review_notes(self, evidence_obj: EvidenceObject) -> List[str]:
        if evidence_obj.metadata.get("transcribed"):
            return [
                "Audio source detected.",
                "Audio transcription complete.",
                "Audio-derived sequence is used for extraction.",
            ]
        return [
            "Audio source detected.",
            "Audio transcription unavailable; metadata-only fallback was used.",
            "Review extracted steps carefully before finalize.",
        ]
