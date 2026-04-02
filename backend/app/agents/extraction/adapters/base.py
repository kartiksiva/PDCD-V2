"""IProcessEvidenceAdapter — abstract base class for all evidence adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from app.agents.schemas import EvidenceObject, ReviewFlag


class IProcessEvidenceAdapter(ABC):
    """
    Plugin contract for processing a single evidence source type.

    Implementations must handle one source_type (video, audio, transcript).
    Each adapter is responsible for:
      - Detecting whether it handles a given input file
      - Normalising the raw input into canonical EvidenceObjects
      - Extracting structured facts from those objects
      - Generating provenance / confidence review notes
    """

    # Subclasses declare which source_type they handle.
    source_type: str = ""

    def detect(self, input_file: Dict[str, Any]) -> bool:
        """Return True if this adapter handles the given input file dict."""
        return input_file.get("source_type") == self.source_type

    @abstractmethod
    async def normalize(
        self,
        input_file: Dict[str, Any],
        blob_url: Optional[str] = None,
    ) -> List[EvidenceObject]:
        """
        Download/read the input and return a list of canonical EvidenceObjects.

        Args:
            input_file: dict from input_manifest["inputs"]
            blob_url:   pre-signed Azure Blob URL for the raw media file (may be None in tests)
        """

    @abstractmethod
    def extract_facts(
        self,
        evidence: List[EvidenceObject],
    ) -> List[EvidenceObject]:
        """
        Post-process a list of EvidenceObjects to enrich or deduplicate facts.
        Returns the updated list (may be the same objects mutated in place).
        """

    @abstractmethod
    def render_review_notes(
        self,
        evidence: List[EvidenceObject],
    ) -> List[ReviewFlag]:
        """
        Inspect the evidence list and return any review flags
        (e.g. low-confidence, missing audio, fragmented transcript).
        """
