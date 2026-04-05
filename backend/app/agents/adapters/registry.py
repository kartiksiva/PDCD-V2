"""AdapterRegistry — maps source_type strings to IProcessEvidenceAdapter instances."""

from __future__ import annotations

from typing import Dict, List, Optional

from app.agents.adapters.base import IProcessEvidenceAdapter
from app.agents.adapters.transcript import TranscriptAdapter
from app.agents.adapters.video import VideoAdapter

# Ordered list of source types for deterministic adapter resolution.
# Transcript takes extraction precedence over video (richer text content for LLM).
_SOURCE_TYPE_ORDER = ["transcript", "video"]

_REGISTRY: Dict[str, IProcessEvidenceAdapter] = {
    "transcript": TranscriptAdapter(),
    "video": VideoAdapter(),
}


class AdapterRegistry:
    """
    Registry that maps source_type strings to adapter instances.

    Usage:
        registry = AdapterRegistry()
        adapters = registry.get_adapters(["video", "transcript"])
        # Returns [TranscriptAdapter, VideoAdapter] — transcript first by precedence
    """

    def get_adapter(self, source_type: str) -> Optional[IProcessEvidenceAdapter]:
        """Return the adapter for a single source type, or None if unsupported."""
        return _REGISTRY.get(source_type)

    def get_adapters(self, source_types: List[str]) -> List[IProcessEvidenceAdapter]:
        """
        Return all applicable adapters for the given source types.

        Adapters are returned in extraction-precedence order (transcript first,
        then video) regardless of the order in source_types.
        Unknown source types are silently skipped.
        """
        ordered = [st for st in _SOURCE_TYPE_ORDER if st in source_types]
        # Include any source types not in the precedence list, appended at end
        extras = [st for st in source_types if st not in _SOURCE_TYPE_ORDER]
        result: List[IProcessEvidenceAdapter] = []
        for st in ordered + extras:
            adapter = _REGISTRY.get(st)
            if adapter is not None:
                result.append(adapter)
        return result

    @property
    def supported_types(self) -> List[str]:
        """Return the list of source types with registered adapters."""
        return list(_REGISTRY.keys())
