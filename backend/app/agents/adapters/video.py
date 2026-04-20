"""VideoAdapter — normalizes video source metadata into canonical evidence.

When video-derived text is successfully generated, the raw VTT transcript is
stored in ``_video_transcript_inline`` and frame descriptions are stored in
``_frame_descriptions_inline`` for downstream extraction/alignment only. Both
fields are ephemeral and must be removed before persistence.
"""

from __future__ import annotations

import shutil
import tempfile
import re
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
_VTT_TIMESTAMP_RE = re.compile(
    r"^(\d{2}:\d{2}:\d{2})(?:\.\d+)?\s+-->\s+(\d{2}:\d{2}:\d{2})(?:\.\d+)?(?:\s.*)?$"
)
_SPEAKER_RE = re.compile(r"^\s*([^:]{2,80}):\s*(.+)\s*$")


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
        profile = job.get("profile_requested") or "balanced"
        transcript_text = ""

        if has_audio and storage_key:
            try:
                raw = transcribe_audio_blob(storage_key, profile=profile)
            except TypeError:
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
                    try:
                        frame_descriptions = analyze_frames(frames, frame_policy, profile=profile)
                    except TypeError:
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
        Return structured segment-level facts from available video metadata.

        Emits one fact per major segment when speaker turns are present in
        Teams recording markers. Falls back to VTT cue segmentation when a
        video transcript is available.
        """
        marker_facts = self._facts_from_recording_markers(job)
        if marker_facts:
            return marker_facts
        return self._facts_from_video_transcript(job)

    def _facts_from_recording_markers(self, job: Dict[str, Any]) -> List[FactItem]:
        teams = job.get("teams_metadata") or {}
        markers = teams.get("recording_markers") or []
        if not isinstance(markers, list):
            return []

        facts: List[FactItem] = []
        for marker in markers:
            if not isinstance(marker, dict):
                continue

            speaker = (
                marker.get("speaker")
                or marker.get("speaker_name")
                or marker.get("display_name")
            )
            if not speaker:
                continue

            start = self._to_anchor_component(
                marker.get("start")
                or marker.get("start_time")
                or marker.get("start_time_utc")
                or marker.get("timestamp")
            )
            end = self._to_anchor_component(
                marker.get("end")
                or marker.get("end_time")
                or marker.get("end_time_utc")
                or marker.get("timestamp")
            )
            if not start:
                continue
            anchor = f"{start}-{end or start}"

            content = (
                marker.get("text")
                or marker.get("utterance")
                or marker.get("summary")
                or marker.get("label")
                or f"{speaker} segment"
            )
            facts.append(
                FactItem(
                    anchor=anchor,
                    content=str(content).strip(),
                    speaker=str(speaker).strip(),
                    confidence=0.5,
                )
            )
        return facts

    def _facts_from_video_transcript(self, job: Dict[str, Any]) -> List[FactItem]:
        raw = str(job.get("_video_transcript_inline") or "").strip()
        if not raw:
            return []

        lines = raw.splitlines()
        current_anchor: str | None = None
        current_lines: list[str] = []
        facts: List[FactItem] = []

        for line in lines:
            stripped = line.strip()
            if not stripped:
                if current_anchor and current_lines:
                    fact = self._fact_from_cue(current_anchor, current_lines)
                    if fact is not None:
                        facts.append(fact)
                current_anchor = None
                current_lines = []
                continue

            if stripped == "WEBVTT" or stripped.startswith("NOTE"):
                continue

            match = _VTT_TIMESTAMP_RE.match(stripped)
            if match:
                if current_anchor and current_lines:
                    fact = self._fact_from_cue(current_anchor, current_lines)
                    if fact is not None:
                        facts.append(fact)
                current_anchor = f"{match.group(1)}-{match.group(2)}"
                current_lines = []
                continue

            if current_anchor is not None and not stripped.isdigit():
                current_lines.append(stripped)

        if current_anchor and current_lines:
            fact = self._fact_from_cue(current_anchor, current_lines)
            if fact is not None:
                facts.append(fact)

        return facts

    def _fact_from_cue(self, anchor: str, lines: List[str]) -> FactItem | None:
        content = " ".join(lines).strip()
        if not content:
            return None
        speaker = None
        summary = content
        match = _SPEAKER_RE.match(content)
        if match:
            speaker = match.group(1).strip()
            summary = match.group(2).strip()
        return FactItem(
            anchor=anchor,
            content=summary or content,
            speaker=speaker,
            confidence=0.5,
        )

    def _to_anchor_component(self, value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return _format_seconds(float(value))
        text = str(value).strip()
        ts_match = re.search(r"(\d{2}:\d{2}:\d{2})", text)
        if ts_match:
            return ts_match.group(1)
        try:
            return _format_seconds(float(text))
        except ValueError:
            return None

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
