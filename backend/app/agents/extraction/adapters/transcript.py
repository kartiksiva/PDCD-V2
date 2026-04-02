"""TranscriptAdapter — parses .txt and .vtt transcript files into EvidenceObjects."""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

from app.agents.schemas import EvidenceObject, ReviewFlag
from app.agents.extraction.adapters.base import IProcessEvidenceAdapter

logger = logging.getLogger(__name__)

# VTT timestamp pattern: HH:MM:SS.mmm --> HH:MM:SS.mmm
_VTT_TIMESTAMP_RE = re.compile(
    r"(\d{2}:\d{2}:\d{2}\.\d{3})\s+-->\s+(\d{2}:\d{2}:\d{2}\.\d{3})"
)
# Speaker label pattern e.g. "John Smith: text" or "[John Smith] text"
_SPEAKER_RE = re.compile(r"^(?:\[([^\]]+)\]|([^:\n]{2,40}):\s)")


class TranscriptAdapter(IProcessEvidenceAdapter):
    """
    Processes standalone transcript files (.txt, .vtt).

    For VTT files, extracts timing anchors and speaker turns.
    For plain-text files, creates segment-level evidence objects with no timing.
    """

    source_type = "transcript"

    async def normalize(
        self,
        input_file: Dict[str, Any],
        blob_url: Optional[str] = None,
    ) -> List[EvidenceObject]:
        """
        Parse transcript content into EvidenceObjects.

        In production, `blob_url` is used to download the file from Azure Blob.
        In tests, `input_file` may contain an inline `content` key for convenience.
        """
        content: str = input_file.get("content", "")
        mime = input_file.get("mime_type", "")

        if blob_url and not content:
            content = await self._download_text(blob_url)

        if not content:
            logger.warning("TranscriptAdapter: no content for input %s", input_file.get("file_name"))
            return []

        if "webvtt" in content[:20].lower() or mime == "text/vtt":
            return self._parse_vtt(content)
        return self._parse_plain(content)

    # ------------------------------------------------------------------
    # Internal parsers
    # ------------------------------------------------------------------

    def _parse_vtt(self, content: str) -> List[EvidenceObject]:
        objects: List[EvidenceObject] = []
        lines = content.splitlines()
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            m = _VTT_TIMESTAMP_RE.match(line)
            if m:
                anchor = f"{m.group(1)}-{m.group(2)}"
                text_lines = []
                i += 1
                while i < len(lines) and lines[i].strip():
                    text_lines.append(lines[i].strip())
                    i += 1
                raw_text = " ".join(text_lines)
                actor, text = self._extract_speaker(raw_text)
                objects.append(
                    EvidenceObject(
                        source_type="transcript",
                        document_type="transcript",
                        anchor=anchor,
                        confidence=0.75,
                        actor=actor,
                        text_snippet=text,
                    )
                )
            else:
                i += 1
        logger.debug("TranscriptAdapter: parsed %d VTT cues", len(objects))
        return objects

    def _parse_plain(self, content: str) -> List[EvidenceObject]:
        objects: List[EvidenceObject] = []
        for idx, line in enumerate(content.splitlines()):
            line = line.strip()
            if not line:
                continue
            actor, text = self._extract_speaker(line)
            objects.append(
                EvidenceObject(
                    source_type="transcript",
                    document_type="transcript",
                    anchor=f"line-{idx + 1}",
                    confidence=0.6,
                    actor=actor,
                    text_snippet=text,
                )
            )
        logger.debug("TranscriptAdapter: parsed %d plain-text lines", len(objects))
        return objects

    @staticmethod
    def _extract_speaker(text: str):
        m = _SPEAKER_RE.match(text)
        if m:
            actor = (m.group(1) or m.group(2)).strip()
            remainder = text[m.end():].strip()
            return actor, remainder
        return "Unknown Speaker", text

    @staticmethod
    async def _download_text(url: str) -> str:
        """Download text content from a blob URL."""
        import aiohttp  # type: ignore[import]
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                resp.raise_for_status()
                return await resp.text()

    # ------------------------------------------------------------------
    # IProcessEvidenceAdapter
    # ------------------------------------------------------------------

    def extract_facts(self, evidence: List[EvidenceObject]) -> List[EvidenceObject]:
        """Remove cue-number-only lines and facilitator prompt noise."""
        cleaned = []
        for obj in evidence:
            snippet = obj.text_snippet or ""
            # Skip VTT cue numbers and empty cues
            if re.match(r"^\d+$", snippet.strip()):
                continue
            if len(snippet.strip()) < 3:
                continue
            cleaned.append(obj)
        return cleaned

    def render_review_notes(self, evidence: List[EvidenceObject]) -> List[ReviewFlag]:
        flags: List[ReviewFlag] = []
        no_timing = sum(1 for e in evidence if e.anchor.startswith("line-"))
        unknown_speakers = sum(1 for e in evidence if e.actor == "Unknown Speaker")

        if no_timing == len(evidence) and evidence:
            flags.append(ReviewFlag(
                code="transcript_no_timing",
                severity="warning",
                message="Transcript has no timing anchors; sequence may be unreliable.",
                requires_user_action=False,
            ))
        if unknown_speakers > len(evidence) * 0.5:
            flags.append(ReviewFlag(
                code="unknown_speakers",
                severity="warning",
                message=f"{unknown_speakers} of {len(evidence)} transcript segments have unresolved speakers.",
                requires_user_action=True,
            ))
        return flags
