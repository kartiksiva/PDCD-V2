"""VideoAdapter — normalizes video source metadata into canonical evidence.

When video-derived text is successfully generated, the raw VTT transcript is
stored in ``_video_transcript_inline`` and frame descriptions are stored in
``_frame_descriptions_inline`` for downstream extraction/alignment only. Both
fields are ephemeral and must be removed before persistence.
"""

from __future__ import annotations

import shutil
import tempfile
from typing import Any, Dict, List

from app.agents.adapters.base import (
    DetectionResult,
    EvidenceObject,
    FactItem,
    IProcessEvidenceAdapter,
)
from app.agents.alignment import parse_vtt_cues
from app.agents.media_preprocessor import extract_keyframes, is_ffmpeg_available
from app.agents.transcription import transcribe_audio_blob
from app.agents.vision import analyze_frames
from app.storage import upload_frame

_VIDEO_MIME_PREFIXES = ("video/",)


def _format_seconds(total_seconds: float) -> str:
    total = max(int(total_seconds), 0)
    hours = total // 3600
    minutes = (total % 3600) // 60
    seconds = total % 60
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


class VideoAdapter(IProcessEvidenceAdapter):
    """
    Adapter for video source types.

    Normalizes video manifest metadata into a canonical EvidenceObject.
    Actual frame-by-frame content analysis (Azure Vision / Azure Speech) is
    a future integration point — this adapter currently produces metadata-level
    evidence and honest confidence values based on audio availability.

    Audio detected  → confidence 0.75 (video is primary evidence source)
    No audio        → confidence 0.45 (frame-first extraction, reduced confidence)
    """

    def detect(self, manifest_entry: Dict[str, Any]) -> DetectionResult:
        """Validate that the manifest entry is a supported video source."""
        source_type = manifest_entry.get("source_type", "")
        mime = (manifest_entry.get("mime_type") or "").lower()

        if source_type != "video":
            return DetectionResult(
                source_type=source_type,
                document_type="unknown",
                valid=False,
                confidence=0.0,
                notes=["source_type is not 'video'"],
            )

        notes: List[str] = []
        has_audio = bool(manifest_entry.get("audio_detected") or manifest_entry.get("audio_declared"))

        if mime and any(mime.startswith(p) for p in _VIDEO_MIME_PREFIXES):
            notes.append(f"Video MIME type confirmed: {mime}")
        else:
            notes.append("Video source accepted; MIME type not validated.")

        if has_audio:
            notes.append("Audio track detected — video is primary evidence source.")
            confidence = 0.75
        else:
            notes.append(
                "No audio track detected — frame-first extraction mode will be used. "
                "Confidence is reduced."
            )
            confidence = 0.45

        return DetectionResult(
            source_type="video",
            document_type="video",
            valid=True,
            confidence=confidence,
            notes=notes,
        )

    def normalize(self, job: Dict[str, Any]) -> EvidenceObject:
        """
        Build a canonical EvidenceObject from video manifest metadata.

        The adapter combines transcript and frame-derived evidence when
        available. If neither can be produced, it falls back to metadata-only
        evidence suitable for graceful degradation.
        """
        manifest = job.get("input_manifest") or {}
        video_meta = manifest.get("video") or {}
        job_id = job.get("job_id", "unknown")
        has_audio = bool(video_meta.get("audio_detected") or video_meta.get("audio_declared"))
        frame_policy = video_meta.get("frame_extraction_policy") or {}

        storage_key = video_meta.get("storage_key")
        interval = frame_policy.get("sample_interval_sec", 5)
        transcript_text = ""

        if has_audio and storage_key:
            raw = transcribe_audio_blob(storage_key)
            if raw and not raw.startswith("[transcription"):
                transcript_text = raw
                job["_video_transcript_inline"] = raw

        frame_descriptions = ""
        frame_storage_keys: list[tuple[str, float]] = []
        if storage_key and is_ffmpeg_available():
            tmp_dir = tempfile.mkdtemp(prefix="pfcd_frames_")
            try:
                frames = extract_keyframes(storage_key, tmp_dir, interval)
                if frames:
                    for index, (frame_path, timestamp_sec) in enumerate(frames):
                        try:
                            with open(frame_path, "rb") as handle:
                                jpg_bytes = handle.read()
                        except OSError:
                            continue
                        persisted_key = upload_frame(job_id, index, jpg_bytes)
                        if persisted_key:
                            frame_storage_keys.append((persisted_key, timestamp_sec))
                    job.setdefault("agent_signals", {})["frame_storage_keys"] = frame_storage_keys
                    frame_descriptions = analyze_frames(frames, frame_policy)
                    if frame_descriptions:
                        job["_frame_descriptions_inline"] = frame_descriptions
            finally:
                shutil.rmtree(tmp_dir, ignore_errors=True)

        if transcript_text or frame_descriptions:
            anchors = (
                [
                    f"{_format_seconds(start)}-{_format_seconds(end)}"
                    for start, end in parse_vtt_cues(transcript_text)
                ]
                if transcript_text
                else []
            )
            confidence = 0.90 if (transcript_text and frame_descriptions) else 0.85
            if transcript_text and frame_descriptions:
                content_text = (
                    f"AUDIO TRANSCRIPT:\n{transcript_text}\n\n"
                    f"FRAME ANALYSIS:\n{frame_descriptions}"
                )
            elif transcript_text:
                content_text = transcript_text
            else:
                content_text = f"FRAME ANALYSIS:\n{frame_descriptions}"

            return EvidenceObject(
                source_type="video",
                document_type="video",
                content_text=content_text,
                anchors=anchors,
                confidence=confidence,
                metadata={
                    "has_audio": has_audio,
                    "frame_policy": frame_policy,
                    "duration_hint_sec": manifest.get("duration_hint_sec"),
                    "storage_key": storage_key,
                    "has_frame_analysis": bool(frame_descriptions),
                    "frame_storage_keys": frame_storage_keys,
                },
            )

        # Build policy description
        threshold = frame_policy.get("scene_change_threshold", 0.68)
        ocr_enabled = frame_policy.get("ocr_enabled", True)
        ocr_trigger = frame_policy.get("ocr_trigger", "scene_change_only")

        content_lines = [
            f"Source type: video (audio {'detected' if has_audio else 'not detected'})",
            f"Frame extraction policy: sample_interval={interval}s, "
            f"scene_change_threshold={threshold}, OCR={'enabled' if ocr_enabled else 'disabled'}, "
            f"OCR trigger={ocr_trigger}",
        ]

        duration = manifest.get("duration_hint_sec")
        if duration:
            content_lines.append(f"Estimated duration: {duration}s")

        if not has_audio:
            content_lines.append(
                "Note: No audio track available. Process sequence will be derived "
                "from frame evidence only. Confidence is reduced."
            )
        else:
            content_lines.append(
                "Note: Audio track available. Combined video+audio evidence supports "
                "high-confidence process extraction when paired with transcript."
            )

        content_lines.append(
            "Azure Vision / Speech integration is pending — frame-level content "
            "analysis is not yet available. Evidence below is metadata-level only."
        )

        confidence = 0.75 if has_audio else 0.45

        return EvidenceObject(
            source_type="video",
            document_type="video",
            content_text="\n".join(content_lines),
            anchors=[],  # populated by Azure Vision integration (future)
            confidence=confidence,
            metadata={
                "has_audio": has_audio,
                "frame_policy": frame_policy,
                "duration_hint_sec": duration,
                "has_frame_analysis": False,
                "frame_storage_keys": [],
            },
        )

    def extract_facts(self, job: Dict[str, Any]) -> List[FactItem]:
        """
        Return structured facts from video frames.

        Stub — will call Azure Vision API when integrated.
        Currently returns empty list; frame-level facts are not available.
        """
        return []

    def render_review_notes(self, evidence_obj: EvidenceObject) -> List[str]:
        """Return provenance notes for display in review UI."""
        has_audio = evidence_obj.metadata.get("has_audio", False)
        frame_policy = evidence_obj.metadata.get("frame_policy") or {}

        notes = [
            "Video source detected.",
            (
                "Audio track confirmed. Video is primary evidence source; "
                "transcript is used for alignment and text disambiguation."
                if has_audio
                else
                "No audio track. Frame-first extraction mode is active. "
                "Transcript or separate audio is required for high-confidence output."
            ),
        ]

        if frame_policy:
            notes.append(
                f"Frame policy: interval={frame_policy.get('sample_interval_sec', 5)}s, "
                f"OCR={'on' if frame_policy.get('ocr_enabled', True) else 'off'}."
            )

        if evidence_obj.metadata.get("has_frame_analysis"):
            notes.append("Frame-level visual analysis complete.")
        elif evidence_obj.metadata.get("storage_key"):
            notes.append("Audio transcription complete. Frame-level visual analysis pending.")
        else:
            notes.append(
                "Azure Vision / Speech integration pending — frame content is not "
                "yet analyzed. Evidence strength is limited to manifest metadata."
            )

        return notes
