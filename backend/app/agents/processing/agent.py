"""ProcessingAgent — loads the evidence graph and produces a draft candidate."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.agents.base import BaseAgent
from app.agents.schemas import (
    ConfidenceSummary,
    DraftOutput,
    EvidenceGraph,
    PDDOutput,
    PDDStep,
    SIPOCRow,
)
from app.agents.processing.plugin import ProcessingPlugin

logger = logging.getLogger(__name__)

_QUALITY_CONFIDENCE = {"high": 0.82, "medium": 0.65, "low": 0.48, "insufficient": 0.2}


class ProcessingAgent(BaseAgent):
    """
    Processing Agent.

    1. Loads evidence_graph.json from blob (or local fallback)
    2. Runs three SK functions: extract_steps → generate_pdd → generate_sipoc
    3. Assembles a DraftOutput and persists draft_candidate.json
    4. Returns the DraftOutput
    """

    AGENT_NAME = "processing"

    def __init__(
        self,
        profile: str,
        job: Dict[str, Any],
        blob_client=None,
    ) -> None:
        super().__init__(self.AGENT_NAME, profile, job)
        self.blob_client = blob_client
        self._plugin = ProcessingPlugin(self.kernel, self.deployment)
        self.kernel.add_plugin(self._plugin, plugin_name="Processing")

    async def run(self, job_id: str) -> DraftOutput:
        self._start_timer()
        logger.info("ProcessingAgent starting for job %s", job_id)
        self.record_run("running")

        graph = await self._load_evidence_graph(job_id)
        evidence_json = json.dumps([e.model_dump() for e in graph.evidence], ensure_ascii=True)
        context_json = json.dumps({
            "source_quality": graph.source_quality,
            "profile": self.profile,
            "has_video": any(e.source_type == "video" for e in graph.evidence),
            "has_audio": graph.audio_detected,
            "has_transcript": graph.transcript_detected,
            "alignment_verdict": graph.alignment_verdict,
        }, ensure_ascii=True)

        # --- Step 1: extract steps ---
        steps_raw = await self._plugin.extract_steps(evidence_json)
        steps: List[PDDStep] = self._plugin.parse_steps(steps_raw)
        if not steps:
            logger.warning("ProcessingAgent: no steps extracted; using fallback for job %s", job_id)
            steps = self._fallback_steps()
        steps_json = json.dumps([s.model_dump() for s in steps], ensure_ascii=True)

        # --- Step 2: generate PDD ---
        pdd_raw = await self._plugin.generate_pdd(steps_json, context_json)
        pdd: PDDOutput = self._plugin.parse_pdd(pdd_raw, steps)

        # --- Step 3: generate SIPOC ---
        sipoc_raw = await self._plugin.generate_sipoc(steps_json, evidence_json)
        sipoc: List[SIPOCRow] = self._plugin.parse_sipoc(sipoc_raw)
        if not sipoc:
            sipoc = self._fallback_sipoc(steps)

        confidence = _QUALITY_CONFIDENCE.get(graph.source_quality, 0.5)
        draft = DraftOutput(
            pdd=pdd,
            sipoc=sipoc,
            assumptions=self._build_assumptions(graph),
            confidence_summary=ConfidenceSummary(
                overall=confidence,
                source_quality=graph.source_quality,
                evidence_strength=graph.source_quality,
            ),
            generated_at=datetime.now(timezone.utc).isoformat(),
            version=1,
        )

        await self._persist_draft(job_id, draft)

        # Rough token estimate: ~4 chars per token for inputs + outputs
        total_chars = len(evidence_json) + len(steps_json) + len(pdd_raw) + len(sipoc_raw)
        total_tokens = total_chars // 4
        self.record_run("success", token_count=total_tokens, confidence_delta=confidence - 0.5)

        logger.info(
            "ProcessingAgent completed: job=%s steps=%d sipoc=%d quality=%s",
            job_id, len(steps), len(sipoc), graph.source_quality,
        )
        return draft

    # ------------------------------------------------------------------
    # Evidence graph loading
    # ------------------------------------------------------------------

    async def _load_evidence_graph(self, job_id: str) -> EvidenceGraph:
        data = await self._read_artifact(job_id, "evidence_graph.json")
        if data:
            try:
                return EvidenceGraph.model_validate_json(data)
            except Exception as exc:
                logger.error("ProcessingAgent: failed to parse evidence_graph: %s", exc)
        logger.warning("ProcessingAgent: evidence_graph not found; using empty graph for job %s", job_id)
        return EvidenceGraph(job_id=job_id, source_quality="insufficient")

    async def _read_artifact(self, job_id: str, filename: str) -> Optional[bytes]:
        container = os.environ.get("AZURE_STORAGE_CONTAINER_EVIDENCE", "evidence")
        blob_name = f"{job_id}/{filename}"

        if self.blob_client:
            try:
                blob = self.blob_client.get_blob_client(container=container, blob=blob_name)
                return blob.download_blob().readall()
            except Exception as exc:
                logger.warning("ProcessingAgent: blob read failed (%s); trying local: %s", filename, exc)

        local_path = os.path.join("./storage/evidence", job_id, filename)
        if os.path.exists(local_path):
            with open(local_path, "rb") as f:
                return f.read()
        return None

    async def _persist_draft(self, job_id: str, draft: DraftOutput) -> None:
        data = draft.model_dump_json(indent=None).encode("utf-8")
        container = os.environ.get("AZURE_STORAGE_CONTAINER_EVIDENCE", "evidence")
        blob_name = f"{job_id}/draft_candidate.json"

        if self.blob_client:
            try:
                blob = self.blob_client.get_blob_client(container=container, blob=blob_name)
                blob.upload_blob(data, overwrite=True)
                return
            except Exception as exc:
                logger.warning("ProcessingAgent: blob write failed; using local: %s", exc)

        local_dir = os.path.join("./storage/evidence", job_id)
        os.makedirs(local_dir, exist_ok=True)
        with open(os.path.join(local_dir, "draft_candidate.json"), "wb") as f:
            f.write(data)

    # ------------------------------------------------------------------
    # Fallbacks (used when LLM is unavailable or returns empty)
    # ------------------------------------------------------------------

    @staticmethod
    def _fallback_steps() -> List[PDDStep]:
        from app.agents.schemas import SourceAnchor
        return [
            PDDStep(
                id="step-01",
                summary="Process starts with first verifiable operator action.",
                actor="Unknown Speaker",
                source_anchors=[
                    SourceAnchor(source="frame", anchor="00:00:00-00:00:10", confidence=0.3)
                ],
            )
        ]

    @staticmethod
    def _fallback_sipoc(steps: List[PDDStep]) -> List[SIPOCRow]:
        return [
            SIPOCRow(
                supplier="Operator",
                input="Task request",
                process_step=steps[0].summary if steps else "Unknown step",
                output="Process step list",
                customer="Operations lead",
                step_anchor=[steps[0].id] if steps else [],
                source_anchor=None,
                anchor_missing_reason="LLM output unavailable; fallback row generated",
            )
        ]

    @staticmethod
    def _build_assumptions(graph: EvidenceGraph) -> List[str]:
        assumptions = ["Evidence confidence is bounded by source availability."]
        if graph.alignment_verdict == "suspected_mismatch":
            assumptions.append("Transcript and video evidence were misaligned; video sequence takes precedence.")
        if graph.source_quality in ("low", "insufficient"):
            assumptions.append("Limited evidence sources; step sequence may be incomplete.")
        return assumptions
