"""ExtractionAgent — orchestrates adapters and produces an EvidenceGraph."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.agents.base import BaseAgent
from app.agents.schemas import EvidenceGraph, EvidenceObject, ReviewFlag
from app.agents.extraction.adapters.base import IProcessEvidenceAdapter
from app.agents.extraction.adapters.audio import AudioAdapter
from app.agents.extraction.adapters.transcript import TranscriptAdapter
from app.agents.extraction.adapters.video import VideoAdapter

logger = logging.getLogger(__name__)

_ADAPTERS: List[IProcessEvidenceAdapter] = [
    VideoAdapter(),
    AudioAdapter(),
    TranscriptAdapter(),
]


def _compute_similarity(a_snippets: List[str], b_snippets: List[str]) -> float:
    """
    Compute a simple token-overlap similarity between two lists of text snippets.
    Used to compare first-N-seconds of transcript evidence vs audio/speech evidence.
    """
    if not a_snippets or not b_snippets:
        return 0.0
    a_tokens = set(" ".join(a_snippets[:10]).lower().split())
    b_tokens = set(" ".join(b_snippets[:10]).lower().split())
    if not a_tokens or not b_tokens:
        return 0.0
    intersection = a_tokens & b_tokens
    union = a_tokens | b_tokens
    return len(intersection) / len(union)


def _alignment_verdict(score: float) -> str:
    if score >= 0.6:
        return "match"
    if score >= 0.3:
        return "inconclusive"
    return "suspected_mismatch"


def _source_quality(evidence: List[EvidenceObject]) -> str:
    types = {e.source_type for e in evidence}
    doc_types = {e.document_type for e in evidence}
    has_video = "video" in types
    has_audio = "audio" in types or "audio" in doc_types
    has_transcript = "transcript" in types
    if has_video and (has_audio or has_transcript):
        return "high"
    if has_video or has_audio:
        return "medium"
    if has_transcript:
        return "low"
    return "insufficient"


class ExtractionAgent(BaseAgent):
    """
    Data Extraction Agent.

    1. Routes each input file to the appropriate IProcessEvidenceAdapter
    2. Normalises and extracts facts from all evidence
    3. Computes transcript/video alignment score if both are present
    4. Persists evidence_graph.json to blob storage (or local fallback)
    5. Returns an EvidenceGraph and updates the job payload
    """

    AGENT_NAME = "extraction"

    def __init__(
        self,
        profile: str,
        job: Dict[str, Any],
        blob_client=None,   # BlobServiceClient or None (local fallback)
    ) -> None:
        super().__init__(self.AGENT_NAME, profile, job)
        self.blob_client = blob_client

    async def run(self, input_manifest: Dict[str, Any]) -> EvidenceGraph:
        self._start_timer()
        job_id = self.job["job_id"]
        logger.info("ExtractionAgent starting for job %s", job_id)

        self.record_run("running")

        all_evidence: List[EvidenceObject] = []
        all_flags: List[ReviewFlag] = []

        inputs = input_manifest.get("inputs", [])
        if not inputs:
            logger.warning("ExtractionAgent: no inputs in manifest for job %s", job_id)

        for input_file in inputs:
            adapter = self._resolve_adapter(input_file)
            if adapter is None:
                logger.warning(
                    "ExtractionAgent: no adapter for source_type=%s",
                    input_file.get("source_type"),
                )
                continue

            blob_url = self._resolve_blob_url(input_file)
            evidence = await adapter.normalize(input_file, blob_url=blob_url)
            evidence = adapter.extract_facts(evidence)
            flags = adapter.render_review_notes(evidence)
            all_evidence.extend(evidence)
            all_flags.extend(flags)

        # Alignment check
        similarity_score: Optional[float] = None
        alignment_verdict = "inconclusive"
        speech_snippets = [
            e.text_snippet or ""
            for e in all_evidence
            if e.document_type in ("audio",) and e.text_snippet
        ]
        transcript_snippets = [
            e.text_snippet or ""
            for e in all_evidence
            if e.source_type == "transcript" and e.text_snippet
        ]
        if speech_snippets and transcript_snippets:
            similarity_score = _compute_similarity(speech_snippets, transcript_snippets)
            alignment_verdict = _alignment_verdict(similarity_score)
            logger.info(
                "ExtractionAgent: alignment verdict=%s score=%.3f",
                alignment_verdict, similarity_score,
            )

        source_quality = _source_quality(all_evidence)
        audio_detected = any(
            e.document_type == "audio" for e in all_evidence
        )

        graph = EvidenceGraph(
            job_id=job_id,
            evidence=all_evidence,
            alignment_verdict=alignment_verdict,
            similarity_score=similarity_score,
            source_quality=source_quality,
            audio_detected=audio_detected,
            transcript_detected=bool(transcript_snippets),
        )

        # Persist evidence graph
        await self._persist_graph(graph)

        # Update review_notes in job payload
        existing_flags = self.job.get("review_notes", {}).get("flags", [])
        self.job["review_notes"]["flags"] = existing_flags + [f.model_dump() for f in all_flags]

        total_tokens = len(all_evidence) * 10  # rough proxy for cost tracking
        self.record_run("success", token_count=total_tokens, confidence_delta=0.0)

        logger.info(
            "ExtractionAgent completed: job=%s evidence=%d quality=%s alignment=%s",
            job_id, len(all_evidence), source_quality, alignment_verdict,
        )
        return graph

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_adapter(input_file: Dict[str, Any]) -> Optional[IProcessEvidenceAdapter]:
        for adapter in _ADAPTERS:
            if adapter.detect(input_file):
                return adapter
        return None

    def _resolve_blob_url(self, input_file: Dict[str, Any]) -> Optional[str]:
        """Return a SAS/download URL for the input file if blob storage is configured."""
        if not self.blob_client:
            return None
        container = os.environ.get("AZURE_STORAGE_CONTAINER_UPLOADS", "uploads")
        blob_name = input_file.get("blob_path") or input_file.get("file_name")
        if not blob_name:
            return None
        try:
            blob = self.blob_client.get_blob_client(container=container, blob=blob_name)
            return blob.url
        except Exception as exc:
            logger.warning("ExtractionAgent: could not resolve blob URL: %s", exc)
            return None

    async def _persist_graph(self, graph: EvidenceGraph) -> None:
        """Write evidence_graph.json to blob storage or local filesystem."""
        job_id = graph.job_id
        data = graph.model_dump_json(indent=None).encode("utf-8")
        container = os.environ.get("AZURE_STORAGE_CONTAINER_EVIDENCE", "evidence")

        if self.blob_client:
            try:
                blob_name = f"{job_id}/evidence_graph.json"
                blob = self.blob_client.get_blob_client(container=container, blob=blob_name)
                blob.upload_blob(data, overwrite=True)
                logger.debug("ExtractionAgent: evidence_graph persisted to blob %s", blob_name)
                return
            except Exception as exc:
                logger.warning("ExtractionAgent: blob persistence failed; using local: %s", exc)

        # Local fallback
        local_dir = os.path.join("./storage/evidence", job_id)
        os.makedirs(local_dir, exist_ok=True)
        path = os.path.join(local_dir, "evidence_graph.json")
        with open(path, "wb") as f:
            f.write(data)
        logger.debug("ExtractionAgent: evidence_graph persisted locally at %s", path)
