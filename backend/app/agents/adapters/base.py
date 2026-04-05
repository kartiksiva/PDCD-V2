"""Adapter base classes and canonical data types for IProcessEvidenceAdapter."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class EvidenceObject:
    """Canonical evidence produced by normalizing a single source input."""

    source_type: str          # "video" | "transcript"
    document_type: str        # "video" | "vtt" | "txt"
    content_text: str         # Cleaned text ready for the extraction LLM
    anchors: List[str]        # Timestamp ranges or section labels extracted from content
    confidence: float         # Source-level confidence 0.0–1.0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class DetectionResult:
    """Result of detect() — tells caller whether this adapter can handle the input."""

    source_type: str
    document_type: str
    valid: bool
    confidence: float
    notes: List[str]


@dataclass
class FactItem:
    """A single structured fact extracted from a source (for extract_facts)."""

    anchor: str
    content: str
    speaker: Optional[str]
    confidence: float


@dataclass
class DocumentTypeManifest:
    """Per-source provenance manifest persisted to job payload."""

    source_type: str
    document_type: str
    confidence: float
    detection_notes: List[str]
    provenance_notes: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_type": self.source_type,
            "document_type": self.document_type,
            "confidence": self.confidence,
            "detection_notes": self.detection_notes,
            "provenance_notes": self.provenance_notes,
        }


class IProcessEvidenceAdapter(ABC):
    """
    Plugin contract for processing evidence from a single source type.

    Implementing a new adapter must not change any public API contracts.
    The adapter must emit a document_type_manifest and confidence score.
    """

    @abstractmethod
    def detect(self, manifest_entry: Dict[str, Any]) -> DetectionResult:
        """
        Inspect a single input_manifest entry and validate the source.

        Args:
            manifest_entry: One dict from input_manifest.inputs (source_type, mime_type, etc.)

        Returns:
            DetectionResult with valid=True if this adapter can handle the entry.
        """

    @abstractmethod
    def normalize(self, job: Dict[str, Any]) -> EvidenceObject:
        """
        Convert job payload data into a canonical EvidenceObject.

        Reads from job fields (e.g. _transcript_text_inline, input_manifest).
        Does not mutate the job — callers decide what to store.

        Returns:
            EvidenceObject with cleaned content_text and extracted anchors.
        """

    @abstractmethod
    def extract_facts(self, job: Dict[str, Any]) -> List[FactItem]:
        """
        Return structured evidence snippets from the source.

        Optional — may return empty list for adapters that rely on LLM extraction.
        """

    @abstractmethod
    def render_review_notes(self, evidence_obj: EvidenceObject) -> List[str]:
        """
        Return human-readable provenance and confidence notes for review UI.

        Args:
            evidence_obj: The EvidenceObject produced by normalize().
        """
