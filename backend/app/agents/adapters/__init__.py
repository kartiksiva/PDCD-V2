"""Adapter layer for IProcessEvidenceAdapter — video and transcript sources."""

from app.agents.adapters.base import (
    DetectionResult,
    DocumentTypeManifest,
    EvidenceObject,
    FactItem,
    IProcessEvidenceAdapter,
)
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
    "TranscriptAdapter",
    "VideoAdapter",
]
