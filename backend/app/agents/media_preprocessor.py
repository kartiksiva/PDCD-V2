"""Media preprocessing helpers for large audio/video transcription inputs."""

from __future__ import annotations

import glob
import logging
import os
import re
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

_MAX_TRANSCRIPTION_BYTES = 24 * 1024 * 1024
_TIMESTAMP_RE = re.compile(
    r"^(?P<start>\d{2}:\d{2}:\d{2}[.,]\d{3})\s+-->\s+"
    r"(?P<end>\d{2}:\d{2}:\d{2}[.,]\d{3})(?P<rest>.*)$"
)


def is_ffmpeg_available() -> bool:
    """Return True if ffmpeg is on PATH and executable."""
    try:
        result = subprocess.run(
            ["ffmpeg", "-version"],
            capture_output=True,
            check=False,
        )
    except FileNotFoundError:
        return False
    return result.returncode == 0


def extract_audio_track(video_path: str, output_dir: str) -> str | None:
    """Extract audio-only track from video_path into output_dir as MP3."""
    try:
        os.makedirs(output_dir, exist_ok=True)
        output_path = str(Path(output_dir) / f"{Path(video_path).stem}_audio.mp3")
        result = subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                video_path,
                "-vn",
                "-acodec",
                "mp3",
                "-ab",
                "64k",
                output_path,
            ],
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            logger.warning("ffmpeg audio extraction failed for %s", video_path)
            return None
        return output_path
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.warning("Audio extraction failed for %s: %s", video_path, exc)
        return None


def split_audio_chunks(
    audio_path: str,
    chunk_sec: int = 600,
) -> list[tuple[str, float]]:
    """Split audio_path into <=chunk_sec chunks using ffmpeg segment muxer."""
    try:
        if os.path.getsize(audio_path) <= _MAX_TRANSCRIPTION_BYTES:
            return [(audio_path, 0.0)]

        source = Path(audio_path)
        output_pattern = str(source.with_name(f"{source.stem}_chunk_%03d{source.suffix}"))
        result = subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                audio_path,
                "-f",
                "segment",
                "-segment_time",
                str(chunk_sec),
                "-c",
                "copy",
                output_pattern,
            ],
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            logger.warning("ffmpeg chunking failed for %s", audio_path)
            return [(audio_path, 0.0)]

        chunk_glob = str(source.with_name(f"{source.stem}_chunk_*{source.suffix}"))
        chunk_files = sorted(glob.glob(chunk_glob))
        if not chunk_files:
            return [(audio_path, 0.0)]
        return [(chunk_file, float(index * chunk_sec)) for index, chunk_file in enumerate(chunk_files)]
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.warning("Audio chunking failed for %s: %s", audio_path, exc)
        return [(audio_path, 0.0)]


def extract_keyframes(
    video_path: str,
    output_dir: str,
    sample_interval_sec: int = 5,
    max_frames: int = 40,
) -> list[tuple[str, float]]:
    """Extract keyframes from video_path at sample_interval_sec intervals."""
    try:
        os.makedirs(output_dir, exist_ok=True)
        output_pattern = str(Path(output_dir) / "frame_%04d.jpg")
        result = subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                video_path,
                "-vf",
                f"fps=1/{sample_interval_sec}",
                "-q:v",
                "3",
                "-frames:v",
                str(max_frames),
                output_pattern,
            ],
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            logger.warning("ffmpeg keyframe extraction failed for %s", video_path)
            return []

        frame_files = sorted(glob.glob(str(Path(output_dir) / "frame_*.jpg")))
        return [
            (frame_file, float(index * sample_interval_sec))
            for index, frame_file in enumerate(frame_files)
        ]
    except FileNotFoundError:
        return []
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.warning("Keyframe extraction failed for %s: %s", video_path, exc)
        return []


def _shift_ts(ts: str, offset_sec: float) -> str:
    """Shift a VTT timestamp string (HH:MM:SS.mmm) by offset_sec."""
    normalized = ts.replace(",", ".")
    hours, minutes, seconds = normalized.split(":")
    sec_part, millis = seconds.split(".")
    total_ms = (
        int(hours) * 3600 * 1000
        + int(minutes) * 60 * 1000
        + int(sec_part) * 1000
        + int(millis)
    )
    shifted_ms = max(int(round(total_ms + (offset_sec * 1000))), 0)
    out_hours = shifted_ms // 3_600_000
    remainder = shifted_ms % 3_600_000
    out_minutes = remainder // 60_000
    remainder %= 60_000
    out_seconds = remainder // 1_000
    out_millis = remainder % 1_000
    return f"{out_hours:02d}:{out_minutes:02d}:{out_seconds:02d}.{out_millis:03d}"


def merge_vtt_chunks(chunks: list[tuple[str, float]]) -> str:
    """Merge a list of (vtt_text, offset_sec) into a single VTT document."""
    merged: list[str] = ["WEBVTT", ""]

    for vtt_text, offset_sec in chunks:
        cue_body: list[str] = []
        in_cue = False

        for raw_line in vtt_text.splitlines():
            line = raw_line.rstrip("\n")
            stripped = line.strip()

            if not stripped:
                if in_cue and cue_body:
                    merged.extend(cue_body)
                    merged.append("")
                    cue_body = []
                    in_cue = False
                continue

            if stripped == "WEBVTT":
                continue

            match = _TIMESTAMP_RE.match(stripped)
            if match:
                if in_cue and cue_body:
                    merged.extend(cue_body)
                    merged.append("")
                    cue_body = []
                start = _shift_ts(match.group("start"), offset_sec)
                end = _shift_ts(match.group("end"), offset_sec)
                merged.append(f"{start} --> {end}{match.group('rest')}")
                in_cue = True
                continue

            if in_cue:
                cue_body.append(stripped)

        if in_cue and cue_body:
            merged.extend(cue_body)
            merged.append("")

    while len(merged) > 2 and merged[-1] == "":
        merged.pop()
    return "\n".join(merged) + "\n"
