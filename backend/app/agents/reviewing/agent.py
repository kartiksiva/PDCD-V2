"""ReviewingAgent — runs quality gates and produces a ReviewOutput."""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional

from app.agents.base import BaseAgent
from app.agents.schemas import (
    DraftOutput,
    EvidenceGraph,
    ReviewFlag,
    ReviewOutput,
)
from app.agents.reviewing.plugin import ReviewingPlugin

logger = logging.getLogger(__name__)

# Required PDD keys per PRD §8.7
_REQUIRED_PDD_KEYS = {
    "purpose", "scope", "triggers", "preconditions", "steps",
    "roles", "systems", "business_rules", "exceptions", "outputs", "metrics", "risks",
}


class ReviewingAgent(BaseAgent):
    """
    Reviewing Agent.

    1. Loads draft_candidate.json and evidence_graph.json from blob/local
    2. Runs rule-based quality gates (schema, SIPOC anchors, evidence strength)
    3. Runs SK review_draft function for semantic confidence scoring
    4. Assembles ReviewOutput and persists review_snapshot.json
    5. Returns ReviewOutput
    """

    AGENT_NAME = "reviewing"

    def __init__(
        self,
        profile: str,
        job: Dict[str, Any],
        blob_client=None,
    ) -> None:
        super().__init__(self.AGENT_NAME, profile, job)
        self.blob_client = blob_client
        self._plugin = ReviewingPlugin(self.kernel, self.deployment)
        self.kernel.add_plugin(self._plugin, plugin_name="Reviewing")

    async def run(self, job_id: str) -> ReviewOutput:
        self._start_timer()
        logger.info("ReviewingAgent starting for job %s", job_id)
        self.record_run("running")

        draft = await self._load_draft(job_id)
        graph = await self._load_evidence_graph(job_id)

        # --- Rule-based quality gates (no LLM needed) ---
        rule_flags: List[ReviewFlag] = self._run_quality_gates(draft, graph)
        has_blocker = any(f.severity == "blocker" for f in rule_flags)

        # --- LLM-based review (skip if already blocked by rules) ---
        llm_review: Optional[ReviewOutput] = None
        if not has_blocker and self._llm_available():
            try:
                draft_json = json.dumps(draft.model_dump() if draft else {}, ensure_ascii=True)
                graph_json = json.dumps(graph.model_dump(), ensure_ascii=True)
                raw = await self._plugin.review_draft(draft_json, graph_json)
                llm_review = self._plugin.parse_review(raw)
            except Exception as exc:
                logger.error("ReviewingAgent: LLM review failed; using rule-based only: %s", exc)
                rule_flags.append(ReviewFlag(
                    code="llm_review_failed",
                    severity="warning",
                    message=f"LLM review could not be completed: {exc}",
                    requires_user_action=False,
                ))

        review = self._merge_review(rule_flags, llm_review, graph, draft)

        await self._persist_snapshot(job_id, review)

        total_tokens = (len(json.dumps(draft.model_dump() if draft else {})) +
                        len(json.dumps(graph.model_dump()))) // 4
        self.record_run(
            "success",
            token_count=total_tokens if not has_blocker else 0,
            confidence_delta=review.confidence_score - 0.5,
        )

        logger.info(
            "ReviewingAgent completed: job=%s decision=%s flags=%d evidence_strength=%s",
            job_id, review.decision, len(review.flags), review.evidence_strength,
        )
        return review

    # ------------------------------------------------------------------
    # Rule-based quality gates
    # ------------------------------------------------------------------

    def _run_quality_gates(
        self,
        draft: Optional[DraftOutput],
        graph: EvidenceGraph,
    ) -> List[ReviewFlag]:
        flags: List[ReviewFlag] = []

        if draft is None:
            flags.append(ReviewFlag(
                code="no_draft_candidate",
                severity="blocker",
                message="No draft candidate was produced by the Processing Agent.",
                requires_user_action=True,
            ))
            return flags

        # 1. PDD required keys
        pdd_dict = draft.pdd.model_dump()
        missing_keys = _REQUIRED_PDD_KEYS - set(pdd_dict.keys())
        if missing_keys:
            flags.append(ReviewFlag(
                code="pdd_missing_keys",
                severity="blocker",
                message=f"PDD is missing required fields: {', '.join(sorted(missing_keys))}",
                requires_user_action=True,
            ))

        # 2. SIPOC must have at least one row with valid step_anchor AND source_anchor
        valid_sipoc_rows = [
            r for r in draft.sipoc
            if r.step_anchor and r.source_anchor
        ]
        if not valid_sipoc_rows:
            flags.append(ReviewFlag(
                code="sipoc_no_anchored_row",
                severity="blocker",
                message="SIPOC has no rows with both a step_anchor and source_anchor.",
                requires_user_action=True,
            ))

        # 3. Evidence strength check
        if graph.source_quality == "insufficient":
            flags.append(ReviewFlag(
                code="insufficient_evidence",
                severity="blocker",
                message="Evidence strength is insufficient; no usable inputs were found.",
                requires_user_action=True,
            ))

        # 4. Alignment warning
        if graph.alignment_verdict == "suspected_mismatch":
            flags.append(ReviewFlag(
                code="transcript_video_mismatch",
                severity="warning",
                message="Transcript and video evidence are suspected to be misaligned. Verify step sequence.",
                requires_user_action=False,
            ))

        # 5. Unknown speaker warning
        unknown_steps = [s for s in draft.pdd.steps if s.actor == "Unknown Speaker"]
        if unknown_steps:
            flags.append(ReviewFlag(
                code="unknown_speakers",
                severity="warning",
                message=f"{len(unknown_steps)} step(s) have unresolved 'Unknown Speaker' actors.",
                requires_user_action=True,
            ))

        return flags

    # ------------------------------------------------------------------
    # Merging rule-based and LLM review results
    # ------------------------------------------------------------------

    def _merge_review(
        self,
        rule_flags: List[ReviewFlag],
        llm_review: Optional[ReviewOutput],
        graph: EvidenceGraph,
        draft: Optional[DraftOutput],
    ) -> ReviewOutput:
        all_flags = list(rule_flags)
        has_blocker = any(f.severity == "blocker" for f in all_flags)

        if llm_review:
            # Merge LLM flags, avoiding duplicates by code
            existing_codes = {f.code for f in all_flags}
            for flag in llm_review.flags:
                if flag.code not in existing_codes:
                    all_flags.append(flag)
            alignment = llm_review.alignment_verdict
            similarity = llm_review.similarity_score
            evidence_strength = llm_review.evidence_strength
            confidence = llm_review.confidence_score
            notes = llm_review.reviewer_notes
        else:
            alignment = graph.alignment_verdict
            similarity = graph.similarity_score
            evidence_strength = graph.source_quality
            # Rough confidence: penalise for each blocker/warning
            blockers = sum(1 for f in all_flags if f.severity == "blocker")
            warnings = sum(1 for f in all_flags if f.severity == "warning")
            base_conf = {"high": 0.82, "medium": 0.65, "low": 0.48, "insufficient": 0.2}
            confidence = max(0.1, base_conf.get(graph.source_quality, 0.5) - blockers * 0.3 - warnings * 0.05)
            notes = None

        if has_blocker:
            decision = "blocked"
        elif any(f.severity == "warning" for f in all_flags):
            decision = "needs_review"
        else:
            decision = "approve_for_draft"

        return ReviewOutput(
            decision=decision,
            flags=all_flags,
            alignment_verdict=alignment,
            similarity_score=similarity,
            evidence_strength=evidence_strength,
            confidence_score=round(confidence, 3),
            reviewer_notes=notes,
        )

    # ------------------------------------------------------------------
    # Artifact I/O
    # ------------------------------------------------------------------

    def _llm_available(self) -> bool:
        return bool(os.environ.get("AZURE_OPENAI_ENDPOINT", ""))

    async def _load_draft(self, job_id: str) -> Optional[DraftOutput]:
        data = await self._read_artifact(job_id, "draft_candidate.json")
        if data:
            try:
                return DraftOutput.model_validate_json(data)
            except Exception as exc:
                logger.error("ReviewingAgent: failed to parse draft_candidate: %s", exc)
        return None

    async def _load_evidence_graph(self, job_id: str) -> EvidenceGraph:
        data = await self._read_artifact(job_id, "evidence_graph.json")
        if data:
            try:
                return EvidenceGraph.model_validate_json(data)
            except Exception as exc:
                logger.error("ReviewingAgent: failed to parse evidence_graph: %s", exc)
        return EvidenceGraph(job_id=job_id, source_quality="insufficient")

    async def _read_artifact(self, job_id: str, filename: str) -> Optional[bytes]:
        container = os.environ.get("AZURE_STORAGE_CONTAINER_EVIDENCE", "evidence")
        blob_name = f"{job_id}/{filename}"
        if self.blob_client:
            try:
                blob = self.blob_client.get_blob_client(container=container, blob=blob_name)
                return blob.download_blob().readall()
            except Exception as exc:
                logger.warning("ReviewingAgent: blob read failed (%s): %s", filename, exc)
        local_path = os.path.join("./storage/evidence", job_id, filename)
        if os.path.exists(local_path):
            with open(local_path, "rb") as f:
                return f.read()
        return None

    async def _persist_snapshot(self, job_id: str, review: ReviewOutput) -> None:
        data = review.model_dump_json(indent=None).encode("utf-8")
        container = os.environ.get("AZURE_STORAGE_CONTAINER_EVIDENCE", "evidence")
        blob_name = f"{job_id}/review_snapshot.json"
        if self.blob_client:
            try:
                blob = self.blob_client.get_blob_client(container=container, blob=blob_name)
                blob.upload_blob(data, overwrite=True)
                return
            except Exception as exc:
                logger.warning("ReviewingAgent: blob write failed; using local: %s", exc)
        local_dir = os.path.join("./storage/evidence", job_id)
        os.makedirs(local_dir, exist_ok=True)
        with open(os.path.join(local_dir, "review_snapshot.json"), "wb") as f:
            f.write(data)
