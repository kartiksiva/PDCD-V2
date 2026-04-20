"""Adapter layer for IProcessEvidenceAdapter sources."""

from app.agents.adapters.base import (
    DetectionResult,
    DocumentTypeManifest,
    EvidenceObject,
    FactItem,
    IProcessEvidenceAdapter,
)
from app.agents.adapters.audio import AudioAdapter
from app.agents.adapters.document import DocumentAdapter
from app.agents.adapters.registry import AdapterRegistry
from app.agents.adapters.transcript import TranscriptAdapter
from app.agents.adapters.video import VideoAdapter

__all__ = [
    "IProcessEvidenceAdapter",
    "EvidenceObject",
    "DetectionResult",
    "FactItem",
    "DocumentTypeManifest",
    "AdapterRegistry",
    "AudioAdapter",
    "DocumentAdapter",
    "TranscriptAdapter",
    "VideoAdapter",
]
