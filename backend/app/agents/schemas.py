"""Shared Pydantic schemas for agent inputs and outputs."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Evidence layer
# ---------------------------------------------------------------------------

class SourceAnchor(BaseModel):
    source: str  # "speech", "frame", "transcript", "ocr"
    anchor: str  # timestamp range e.g. "00:01:05-00:01:15" or frame id
    confidence: float = Field(ge=0.0, le=1.0)
    ocr_region: Optional[str] = None


class EvidenceObject(BaseModel):
    source_type: str          # "video", "audio", "transcript"
    document_type: str        # "video", "audio", "transcript", "ocr_frame"
    anchor: str               # primary timestamp range or frame id
    confidence: float = Field(ge=0.0, le=1.0)
    actor: Optional[str] = None
    text_snippet: Optional[str] = None
    frame_path: Optional[str] = None   # blob path to extracted frame image
    metadata: Dict[str, Any] = Field(default_factory=dict)


class EvidenceGraph(BaseModel):
    job_id: str
    evidence: List[EvidenceObject] = Field(default_factory=list)
    alignment_verdict: str = "inconclusive"   # "match" | "inconclusive" | "suspected_mismatch"
    similarity_score: Optional[float] = None
    source_quality: str = "medium"            # "high" | "medium" | "low" | "insufficient"
    audio_detected: bool = False
    transcript_detected: bool = False


# ---------------------------------------------------------------------------
# Draft layer
# ---------------------------------------------------------------------------

class PDDStep(BaseModel):
    id: str
    summary: str
    actor: str = "Unknown Speaker"
    system: Optional[str] = None
    input: Optional[str] = None
    output: Optional[str] = None
    exception: Optional[str] = None
    source_anchors: List[SourceAnchor] = Field(default_factory=list)


class PDDMetrics(BaseModel):
    coverage: str = "medium"
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


class PDDOutput(BaseModel):
    purpose: str
    scope: str
    triggers: List[str] = Field(default_factory=list)
    preconditions: List[str] = Field(default_factory=list)
    steps: List[PDDStep] = Field(default_factory=list)
    roles: List[str] = Field(default_factory=list)
    systems: List[str] = Field(default_factory=list)
    business_rules: List[str] = Field(default_factory=list)
    exceptions: List[str] = Field(default_factory=list)
    outputs: List[str] = Field(default_factory=list)
    metrics: PDDMetrics = Field(default_factory=PDDMetrics)
    risks: List[str] = Field(default_factory=list)


class SIPOCRow(BaseModel):
    supplier: str
    input: str
    process_step: str
    output: str
    customer: str
    step_anchor: List[str] = Field(default_factory=list)   # linked PDDStep ids
    source_anchor: Optional[str] = None                    # timestamp/frame
    anchor_missing_reason: Optional[str] = None


class ConfidenceSummary(BaseModel):
    overall: float = Field(ge=0.0, le=1.0)
    source_quality: str
    evidence_strength: str


class DraftOutput(BaseModel):
    pdd: PDDOutput
    sipoc: List[SIPOCRow] = Field(default_factory=list)
    assumptions: List[str] = Field(default_factory=list)
    confidence_summary: ConfidenceSummary
    generated_at: Optional[str] = None
    version: int = 1


# ---------------------------------------------------------------------------
# Review layer
# ---------------------------------------------------------------------------

class ReviewFlag(BaseModel):
    code: str
    severity: str   # "blocker" | "warning" | "info"
    message: str
    requires_user_action: bool = False


class ReviewOutput(BaseModel):
    decision: str   # "approve_for_draft" | "needs_review" | "blocked"
    flags: List[ReviewFlag] = Field(default_factory=list)
    alignment_verdict: str = "inconclusive"
    similarity_score: Optional[float] = None
    evidence_strength: str = "medium"
    confidence_score: float = Field(default=0.5, ge=0.0, le=1.0)
    reviewer_notes: Optional[str] = None
