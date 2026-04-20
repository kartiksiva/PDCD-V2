"""DocumentAdapter — minimal deterministic adapter for document inputs."""

from __future__ import annotations

from typing import Any, Dict, List

from app.agents.adapters.base import (
    DetectionResult,
    EvidenceObject,
    FactItem,
    IProcessEvidenceAdapter,
)

_TEXT_LIKE_EXTENSIONS = (".txt", ".md", ".csv", ".log", ".json")


class DocumentAdapter(IProcessEvidenceAdapter):
    """Adapter for uploaded supporting documents."""

    def detect(self, manifest_entry: Dict[str, Any]) -> DetectionResult:
        source_type = manifest_entry.get("source_type", "")
        if source_type != "document":
            return DetectionResult(
                source_type=source_type,
                document_type="unknown",
                valid=False,
                confidence=0.0,
                notes=["source_type is not 'document'"],
            )
        file_name = (manifest_entry.get("file_name") or "").lower()
        mime = (manifest_entry.get("mime_type") or "").lower()
        notes = [
            f"Document input detected (mime={mime or 'unknown'}, file={file_name or 'unknown'})."
        ]
        return DetectionResult(
            source_type="document",
            document_type="document",
            valid=True,
            confidence=0.50,
            notes=notes,
        )

    def normalize(self, job: Dict[str, Any]) -> EvidenceObject:
        source_inputs = (job.get("input_manifest") or {}).get("inputs") or []
        document_input = next(
            (inp for inp in source_inputs if inp.get("source_type") == "document"),
            {},
        )
        file_name = (document_input.get("file_name") or "document").strip()
        mime = (document_input.get("mime_type") or "").strip()
        storage_key = document_input.get("storage_key")
        size_bytes = document_input.get("size_bytes") or 0

        preview_text = self._load_preview_text(file_name, storage_key)
        if preview_text:
            content_text = (
                f"Document context from {file_name}:\n"
                f"{preview_text}"
            )
            confidence = 0.50
        else:
            content_text = (
                f"Source type: document\n"
                f"File name: {file_name}\n"
                f"MIME type: {mime or 'unknown'}\n"
                f"Approx size bytes: {size_bytes}\n"
                "Document text extraction is unavailable; this input is used as contextual metadata."
            )
            confidence = 0.40

        return EvidenceObject(
            source_type="document",
            document_type="document",
            content_text=content_text,
            anchors=[],
            confidence=confidence,
            metadata={
                "file_name": file_name,
                "mime_type": mime,
                "storage_key": storage_key,
                "preview_loaded": bool(preview_text),
            },
        )

    def extract_facts(self, job: Dict[str, Any]) -> List[FactItem]:
        source_inputs = (job.get("input_manifest") or {}).get("inputs") or []
        document_input = next(
            (inp for inp in source_inputs if inp.get("source_type") == "document"),
            {},
        )
        file_name = (document_input.get("file_name") or "document").strip()
        if not file_name:
            return []
        return [
            FactItem(
                anchor=f"document:{file_name}",
                content=f"Document provided: {file_name}",
                speaker=None,
                confidence=0.40,
            )
        ]

    def render_review_notes(self, evidence_obj: EvidenceObject) -> List[str]:
        preview_loaded = evidence_obj.metadata.get("preview_loaded", False)
        if preview_loaded:
            return [
                "Document source detected.",
                "Text preview loaded for contextual extraction support.",
                "Document evidence remains secondary to media sequence evidence.",
            ]
        return [
            "Document source detected.",
            "Document parsed as metadata-only context (no text preview).",
            "Review document-linked assumptions before finalize.",
        ]

    def _load_preview_text(self, file_name: str, storage_key: Any) -> str:
        if not storage_key or not isinstance(storage_key, str):
            return ""
        if not file_name.lower().endswith(_TEXT_LIKE_EXTENSIONS):
            return ""
        try:
            with open(storage_key, "rb") as handle:
                raw = handle.read().decode("utf-8", errors="ignore")
        except OSError:
            return ""
        lines = [line.strip() for line in raw.splitlines() if line.strip()]
        if not lines:
            return ""
        return "\n".join(lines[:20])[:2000]
