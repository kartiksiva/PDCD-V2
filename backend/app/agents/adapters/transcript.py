"""TranscriptAdapter — normalizes VTT and plain-text transcript sources."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

from app.agents.adapters.base import (
    DetectionResult,
    EvidenceObject,
    FactItem,
    IProcessEvidenceAdapter,
)

# Matches VTT timestamp lines: 00:00:12.000 --> 00:00:28.000 [optional positional data]
_VTT_TIMESTAMP_RE = re.compile(
    r"^(\d{2}:\d{2}:\d{2})(?:\.\d+)?\s+-->\s+(\d{2}:\d{2}:\d{2})(?:\.\d+)?(?:\s.*)?$"
)
# Plain cue sequence numbers (VTT allows integer IDs before timestamp lines)
_CUE_ID_RE = re.compile(r"^\d+$")
# Section headings in plain-text transcripts
_SECTION_LABEL_RE = re.compile(
    r"^(section\s+\d+|#{1,3}\s+|\d+\.\d*\s+|\*{1,2}.+\*{1,2})", re.IGNORECASE
)

_VTT_MIME_TYPES = {"text/vtt", "text/webvtt"}
_TXT_MIME_TYPES = {"text/plain"}


def _parse_vtt(text: str) -> Tuple[str, List[str]]:
    """
    Parse a WEBVTT string into (clean_content, anchors).

    Clean content has inline anchor tags: "[HH:MM:SS-HH:MM:SS] <speaker>: <text>"
    Anchors is the ordered list of timestamp ranges found.
    """
    lines = text.splitlines()
    content_parts: List[str] = []
    anchors: List[str] = []

    current_ts: str | None = None
    current_lines: List[str] = []

    for line in lines:
        stripped = line.strip()

        if not stripped:
            # Blank line — flush current cue if any
            if current_ts and current_lines:
                content = " ".join(current_lines)
                content_parts.append(f"[{current_ts}] {content}")
                current_ts = None
                current_lines = []
            continue

        if stripped == "WEBVTT" or stripped.startswith("NOTE"):
            continue

        m = _VTT_TIMESTAMP_RE.match(stripped)
        if m:
            # New cue — flush previous
            if current_ts and current_lines:
                content = " ".join(current_lines)
                content_parts.append(f"[{current_ts}] {content}")
                current_lines = []
            current_ts = f"{m.group(1)}-{m.group(2)}"
            anchors.append(current_ts)
            continue

        if _CUE_ID_RE.match(stripped):
            # Cue sequence number — skip
            continue

        # Content line
        if current_ts is not None:
            current_lines.append(stripped)

    # Flush trailing cue
    if current_ts and current_lines:
        content = " ".join(current_lines)
        content_parts.append(f"[{current_ts}] {content}")

    return "\n".join(content_parts), anchors


def _parse_txt(text: str) -> Tuple[str, List[str]]:
    """
    Parse a plain-text transcript into (content, section_label_anchors).

    Content is returned as-is; section labels are extracted as anchors.
    """
    anchors: List[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped and _SECTION_LABEL_RE.match(stripped):
            anchors.append(stripped)
    return text, anchors


def _is_vtt(raw: str) -> bool:
    """Return True if the text looks like WEBVTT format."""
    first_nonempty = next((l.strip() for l in raw.splitlines() if l.strip()), "")
    return first_nonempty == "WEBVTT"


class TranscriptAdapter(IProcessEvidenceAdapter):
    """
    Adapter for transcript source types (.vtt, .txt).

    Normalizes raw VTT or plain-text transcripts into:
    - Clean content with inline timestamp anchors for LLM
    - Ordered list of timestamp-range or section-label anchors
    """

    def detect(self, manifest_entry: Dict[str, Any]) -> DetectionResult:
        """Validate that the manifest entry is a supported transcript source."""
        source_type = manifest_entry.get("source_type", "")
        mime = (manifest_entry.get("mime_type") or "").lower()
        file_name = (manifest_entry.get("file_name") or "").lower()

        if source_type != "transcript":
            return DetectionResult(
                source_type=source_type,
                document_type="unknown",
                valid=False,
                confidence=0.0,
                notes=["source_type is not 'transcript'"],
            )

        if mime in _VTT_MIME_TYPES or file_name.endswith(".vtt"):
            return DetectionResult(
                source_type="transcript",
                document_type="vtt",
                valid=True,
                confidence=0.90,
                notes=["VTT transcript detected by mime type or file extension."],
            )

        if mime in _TXT_MIME_TYPES or file_name.endswith(".txt"):
            return DetectionResult(
                source_type="transcript",
                document_type="txt",
                valid=True,
                confidence=0.80,
                notes=["Plain-text transcript detected."],
            )

        # Fallback: accept any transcript source without strict MIME check
        return DetectionResult(
            source_type="transcript",
            document_type="txt",
            valid=True,
            confidence=0.70,
            notes=["Transcript accepted without explicit format detection; treating as plain text."],
        )

    def normalize(self, job: Dict[str, Any]) -> EvidenceObject:
        """
        Read transcript text from job and return a canonical EvidenceObject.

        VTT transcripts are cleaned (WEBVTT headers and cue numbers stripped) and
        annotated with inline timestamp anchors. Plain text is returned as-is with
        section labels extracted as anchors.
        """
        raw_text: str = job.get("_transcript_text_inline") or ""

        if not raw_text.strip():
            return EvidenceObject(
                source_type="transcript",
                document_type="unknown",
                content_text="",
                anchors=[],
                confidence=0.0,
                metadata={"empty": True},
            )

        if _is_vtt(raw_text):
            content_text, anchors = _parse_vtt(raw_text)
            doc_type = "vtt"
            confidence = 0.90
        else:
            content_text, anchors = _parse_txt(raw_text)
            doc_type = "txt"
            confidence = 0.80

        return EvidenceObject(
            source_type="transcript",
            document_type=doc_type,
            content_text=content_text,
            anchors=anchors,
            confidence=confidence,
            metadata={
                "anchor_count": len(anchors),
                "raw_length_chars": len(raw_text),
            },
        )

    def extract_facts(self, job: Dict[str, Any]) -> List[FactItem]:
        """
        Return structured FactItems from the transcript.

        For VTT: one FactItem per cue with speaker and timestamp anchor.
        For plain text: one FactItem per non-empty line (no speaker).
        """
        raw_text: str = job.get("_transcript_text_inline") or ""
        if not raw_text.strip():
            return []

        if _is_vtt(raw_text):
            return self._facts_from_vtt(raw_text)
        return self._facts_from_txt(raw_text)

    def _facts_from_vtt(self, text: str) -> List[FactItem]:
        lines = text.splitlines()
        facts: List[FactItem] = []
        current_ts: str | None = None
        current_lines: List[str] = []

        for line in lines:
            stripped = line.strip()
            if not stripped:
                if current_ts and current_lines:
                    content = " ".join(current_lines)
                    speaker = _extract_speaker(content)
                    facts.append(FactItem(
                        anchor=current_ts,
                        content=content,
                        speaker=speaker,
                        confidence=0.85,
                    ))
                    current_ts = None
                    current_lines = []
                continue
            if stripped == "WEBVTT" or stripped.startswith("NOTE"):
                continue
            m = _VTT_TIMESTAMP_RE.match(stripped)
            if m:
                if current_ts and current_lines:
                    content = " ".join(current_lines)
                    speaker = _extract_speaker(content)
                    facts.append(FactItem(
                        anchor=current_ts,
                        content=content,
                        speaker=speaker,
                        confidence=0.85,
                    ))
                    current_lines = []
                current_ts = f"{m.group(1)}-{m.group(2)}"
                continue
            if _CUE_ID_RE.match(stripped):
                continue
            if current_ts is not None:
                current_lines.append(stripped)

        if current_ts and current_lines:
            content = " ".join(current_lines)
            facts.append(FactItem(
                anchor=current_ts,
                content=content,
                speaker=_extract_speaker(content),
                confidence=0.85,
            ))
        return facts

    def _facts_from_txt(self, text: str) -> List[FactItem]:
        facts: List[FactItem] = []
        for i, line in enumerate(text.splitlines()):
            stripped = line.strip()
            if stripped:
                facts.append(FactItem(
                    anchor=f"line-{i + 1}",
                    content=stripped,
                    speaker=None,
                    confidence=0.70,
                ))
        return facts

    def render_review_notes(self, evidence_obj: EvidenceObject) -> List[str]:
        """Return provenance notes for display in review UI."""
        if not evidence_obj.content_text:
            return ["Transcript source: empty or unavailable."]

        notes = [
            f"Transcript format: {evidence_obj.document_type.upper()}",
            f"Anchor count: {evidence_obj.metadata.get('anchor_count', len(evidence_obj.anchors))}",
            f"Source confidence: {evidence_obj.confidence:.0%}",
        ]
        if evidence_obj.document_type == "vtt":
            notes.append(
                "Timestamp anchors extracted from VTT cues. "
                "LLM receives cleaned content with inline [HH:MM:SS-HH:MM:SS] markers."
            )
        else:
            notes.append(
                "Plain-text transcript. Section labels used as anchors where available."
            )
        return notes


def _extract_speaker(content: str) -> str | None:
    """Extract speaker name from 'Speaker Name: content' pattern."""
    if ": " in content:
        candidate = content.split(": ", 1)[0].strip()
        # Heuristic: speaker names are short and don't look like process steps
        if 0 < len(candidate) <= 40 and "\n" not in candidate:
            return candidate
    return None
