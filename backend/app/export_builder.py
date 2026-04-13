"""Evidence-linked export builders for PDF, DOCX, and Markdown (PRD §8.10)."""

from __future__ import annotations

import io
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.agents.anchor_utils import classify_anchor


@dataclass
class _AnchorEntry:
    anchor_id: str
    anchor_type: str  # timestamp_range | frame_id | section_label | missing
    anchor_value: str
    confidence: float
    linked_step_ids: List[str] = field(default_factory=list)
    linked_sipoc_rows: List[int] = field(default_factory=list)
    ocr_snippet: Optional[str] = None


def _classify_anchor_type(anchor: str) -> str:
    """Classify anchor string into a type label."""
    return classify_anchor(anchor)


def _timestamp_to_seconds(value: str) -> float:
    parts = value.split(":")
    try:
        total = 0.0
        for index, part in enumerate(parts):
            total += float(part) * (60 ** (len(parts) - 1 - index))
        return total
    except (TypeError, ValueError):
        return -1.0


def build_evidence_bundle(finalized_draft: Dict[str, Any], job: Dict[str, Any]) -> Dict[str, Any]:
    """Build evidence bundle manifest from finalized draft and job signals.

    Per PRD §8.10:
    - Only anchors linked to at least one PDD step or SIPOC row are included.
    - OCR snippets attached when available from extracted_evidence.
    - Frame captures are noted as pending (VideoAdapter stub).
    """
    pdd_steps: List[Dict[str, Any]] = (finalized_draft.get("pdd") or {}).get("steps") or []
    sipoc_rows: List[Dict[str, Any]] = finalized_draft.get("sipoc") or []

    anchor_map: Dict[str, _AnchorEntry] = {}

    # Collect anchors from PDD steps (each step may have multiple source_anchors)
    for step in pdd_steps:
        step_id = step.get("id", "")
        for sa in step.get("source_anchors") or []:
            anchor_val = sa.get("anchor", "")
            if not anchor_val:
                continue
            if anchor_val not in anchor_map:
                anchor_map[anchor_val] = _AnchorEntry(
                    anchor_id=f"a-{len(anchor_map) + 1}",
                    anchor_type=_classify_anchor_type(anchor_val),
                    anchor_value=anchor_val,
                    confidence=float(sa.get("confidence") or 0.0),
                )
            entry = anchor_map[anchor_val]
            if step_id and step_id not in entry.linked_step_ids:
                entry.linked_step_ids.append(step_id)

    # Collect anchors from SIPOC rows
    for idx, row in enumerate(sipoc_rows):
        anchor_val = row.get("source_anchor", "")
        if not anchor_val:
            continue
        if anchor_val not in anchor_map:
            anchor_map[anchor_val] = _AnchorEntry(
                anchor_id=f"a-{len(anchor_map) + 1}",
                anchor_type=_classify_anchor_type(anchor_val),
                anchor_value=anchor_val,
                confidence=0.0,
            )
        entry = anchor_map[anchor_val]
        if idx not in entry.linked_sipoc_rows:
            entry.linked_sipoc_rows.append(idx)

    # Attach OCR snippets from extracted evidence when anchor values match
    evidence_items: List[Dict[str, Any]] = (
        (job.get("extracted_evidence") or {}).get("evidence_items") or []
    )
    for item in evidence_items:
        # Extraction schema uses "anchor"; "source_anchor" is kept as fallback.
        item_anchor = item.get("anchor") or item.get("source_anchor") or ""
        if item_anchor and item_anchor in anchor_map:
            anchor_map[item_anchor].ocr_snippet = (
                item.get("ocr_text") or item.get("content_snippet")
            )

    # Collect frame captures from evidence metadata or persisted agent signals.
    frame_captures: list[dict] = []
    for item in evidence_items:
        frame_keys = (item.get("metadata") or {}).get("frame_storage_keys") or []
        for storage_key, timestamp_sec in frame_keys:
            frame_captures.append({"storage_key": storage_key, "timestamp_sec": timestamp_sec})
    for storage_key, timestamp_sec in (job.get("agent_signals") or {}).get("frame_storage_keys") or []:
        if not any(
            existing["storage_key"] == storage_key and existing["timestamp_sec"] == timestamp_sec
            for existing in frame_captures
        ):
            frame_captures.append({"storage_key": storage_key, "timestamp_sec": timestamp_sec})

    # Link frame captures to timestamp anchors by midpoint proximity.
    for capture in frame_captures:
        timestamp_sec = capture["timestamp_sec"]
        for anchor_val, entry in anchor_map.items():
            if entry.anchor_type != "timestamp_range":
                continue
            parts = anchor_val.split("-")
            if len(parts) == 1:
                midpoint = _timestamp_to_seconds(parts[0])
            else:
                start = _timestamp_to_seconds(parts[0])
                end = _timestamp_to_seconds(parts[-1])
                if start < 0 or end < 0:
                    continue
                midpoint = (start + end) / 2
            if midpoint >= 0 and abs(timestamp_sec - midpoint) <= 10:
                capture.setdefault("linked_anchor_ids", []).append(entry.anchor_id)

    # PRD §8.10: only include anchors linked to at least one step or SIPOC row
    linked_anchors = [
        {
            "anchor_id": e.anchor_id,
            "anchor_type": e.anchor_type,
            "anchor_value": e.anchor_value,
            "confidence": e.confidence,
            "linked_step_ids": e.linked_step_ids,
            "linked_sipoc_rows": e.linked_sipoc_rows,
            "ocr_snippet": e.ocr_snippet,
        }
        for e in anchor_map.values()
        if e.linked_step_ids or e.linked_sipoc_rows
    ]

    return {
        "evidence_strength": (job.get("agent_signals") or {}).get("evidence_strength"),
        "frame_policy": (
            (job.get("input_manifest") or {}).get("video", {}).get("frame_extraction_policy")
        ),
        "linked_anchors": linked_anchors,
        "total_linked_anchors": len(linked_anchors),
        "frame_captures": frame_captures,
        "frame_captures_note": (
            "Frame captures embedded above."
            if frame_captures
            else "No frame captures available for this job."
        ),
        "unlinked_note": "Evidence not included in this export format",
    }


def build_export_markdown(draft: Dict[str, Any], evidence_bundle: Dict[str, Any]) -> str:
    """Build evidence-linked Markdown export."""
    if not draft:
        return "No finalized draft available."

    pdd = draft.get("pdd") or {}
    parts = [
        "# Process Definition Document",
        "",
        f"**Purpose:** {pdd.get('purpose', '')}",
        f"**Scope:** {pdd.get('scope', '')}",
        "",
        "## Steps",
        "",
    ]
    for step in pdd.get("steps") or []:
        anchors = ", ".join(
            sa.get("anchor", "")
            for sa in (step.get("source_anchors") or [])
            if sa.get("anchor")
        )
        anchor_str = f" *(anchors: {anchors})*" if anchors else ""
        parts.append(f"- **{step.get('id')}**: {step.get('summary')}{anchor_str}")

    parts.extend(["", "## SIPOC", ""])
    for idx, row in enumerate(draft.get("sipoc") or [], start=1):
        step_refs = ", ".join(row.get("step_anchor") or [])
        step_ref_str = f" (steps: {step_refs})" if step_refs else ""
        parts.append(
            f"{idx}. **{row.get('process_step')}** — anchor: "
            f"`{row.get('source_anchor', 'N/A')}`{step_ref_str}"
        )

    # Evidence bundle section
    parts.extend(["", "## Evidence Bundle", ""])
    strength = evidence_bundle.get("evidence_strength") or "unknown"
    parts.append(f"**Evidence Strength:** {strength}")

    linked_anchors = evidence_bundle.get("linked_anchors") or []
    if linked_anchors:
        parts.extend([
            "",
            "| Anchor | Type | Confidence | Linked Steps | OCR Snippet |",
            "|--------|------|------------|-------------|-------------|",
        ])
        for a in linked_anchors:
            steps_str = ", ".join(a.get("linked_step_ids") or []) or "—"
            ocr = (a.get("ocr_snippet") or "—")[:80]
            conf = f"{a.get('confidence', 0.0):.2f}"
            parts.append(
                f"| `{a['anchor_value']}` | {a['anchor_type']} | {conf} | {steps_str} | {ocr} |"
            )
    else:
        parts.append("")
        parts.append("*No linked evidence anchors found.*")

    note = evidence_bundle.get("frame_captures_note", "")
    if note:
        parts.extend(["", f"> {note}"])
    frame_captures = evidence_bundle.get("frame_captures") or []
    parts.extend(["", "### Frame captures", ""])
    if frame_captures:
        for capture in frame_captures:
            anchor_ids = ", ".join(capture.get("linked_anchor_ids") or []) or "unlinked"
            parts.append(
                f"- `{capture.get('storage_key')}` @ {capture.get('timestamp_sec', 0):.1f}s "
                f"(anchors: {anchor_ids})"
            )
    else:
        parts.append("- No frame captures available.")

    return "\n".join(parts)


def build_export_pdf(draft: Dict[str, Any], evidence_bundle: Dict[str, Any]) -> bytes:
    """Build evidence-linked PDF export."""
    from fpdf import FPDF
    from fpdf.enums import XPos, YPos

    pdf = FPDF()
    pdf.add_page()
    page_width = pdf.w - pdf.l_margin - pdf.r_margin

    def _heading(text: str, size: int = 12, bold: bool = False) -> None:
        pdf.set_x(pdf.l_margin)
        style = "B" if bold else ""
        pdf.set_font("Helvetica", style=style, size=size)
        pdf.cell(page_width, 10, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_font("Helvetica", size=11)

    def _row(text: str) -> None:
        pdf.set_x(pdf.l_margin)
        pdf.multi_cell(page_width, 7, text)

    pdf.set_font("Helvetica", size=11)
    pdd = draft.get("pdd") or {}

    _heading("Process Definition Document", size=14, bold=True)
    pdf.ln(2)
    _row(f"Purpose: {pdd.get('purpose', '')}")
    _row(f"Scope: {pdd.get('scope', '')}")

    pdf.ln(3)
    _heading("Steps", bold=True)
    for step in pdd.get("steps") or []:
        anchors = ", ".join(
            sa.get("anchor", "")
            for sa in (step.get("source_anchors") or [])
            if sa.get("anchor")
        )
        anchor_part = f" [anchors: {anchors}]" if anchors else ""
        _row(f"  {step.get('id')}: {step.get('summary')}{anchor_part}")

    pdf.ln(3)
    _heading("SIPOC", bold=True)
    for idx, row in enumerate(draft.get("sipoc") or [], start=1):
        step_refs = ", ".join(row.get("step_anchor") or [])
        step_ref_part = f" [steps: {step_refs}]" if step_refs else ""
        _row(
            f"  {idx}. {row.get('process_step')} "
            f"[anchor: {row.get('source_anchor', 'N/A')}]{step_ref_part}"
        )

    # Evidence bundle section
    pdf.ln(4)
    _heading("Evidence Bundle", bold=True)
    strength = evidence_bundle.get("evidence_strength") or "unknown"
    _row(f"Evidence Strength: {strength}")

    linked_anchors = evidence_bundle.get("linked_anchors") or []
    if linked_anchors:
        pdf.ln(2)
        _row(f"Total linked anchors: {len(linked_anchors)}")
        pdf.ln(1)
        for a in linked_anchors:
            steps_str = ", ".join(a.get("linked_step_ids") or []) or "none"
            conf = f"{a.get('confidence', 0.0):.2f}"
            _row(
                f"  [{a['anchor_type']}] {a['anchor_value']}  "
                f"confidence: {conf}  steps: {steps_str}"
            )
            if a.get("ocr_snippet"):
                snippet = a["ocr_snippet"][:120]
                _row(f"    OCR: {snippet}")
    else:
        _row("No linked evidence anchors found.")

    note = evidence_bundle.get("frame_captures_note", "")
    if note:
        pdf.ln(2)
        _row(f"Note: {note}")

    frame_captures = evidence_bundle.get("frame_captures") or []
    if frame_captures:
        pdf.ln(3)
        _heading("Frame Captures", bold=True)
        for capture in frame_captures:
            key = capture.get("storage_key", "")
            timestamp_sec = capture.get("timestamp_sec", 0.0)
            if key.startswith("/") or (key.startswith(".") and os.path.exists(key)):
                try:
                    pdf.image(key, w=120)
                    pdf.set_font("Helvetica", size=8)
                    pdf.cell(0, 5, f"Frame @ {timestamp_sec:.1f}s — {key}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
                    pdf.set_font("Helvetica", size=11)
                except Exception:
                    pdf.set_font("Helvetica", size=8)
                    pdf.cell(0, 5, f"Frame @ {timestamp_sec:.1f}s (image unreadable)", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
                    pdf.set_font("Helvetica", size=11)
            else:
                pdf.set_font("Helvetica", size=8)
                pdf.cell(0, 5, f"Frame @ {timestamp_sec:.1f}s: {key}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
                pdf.set_font("Helvetica", size=11)

    return bytes(pdf.output())


def build_export_docx(
    draft: Dict[str, Any], evidence_bundle: Dict[str, Any], job_id: str
) -> bytes:
    """Build evidence-linked DOCX export using python-docx."""
    from docx import Document  # type: ignore[import-untyped]

    doc = Document()
    doc.add_heading("Process Definition Document", level=0)

    pdd = draft.get("pdd") or {}
    doc.add_paragraph(f"Purpose: {pdd.get('purpose', '')}")
    doc.add_paragraph(f"Scope: {pdd.get('scope', '')}")

    doc.add_heading("Steps", level=1)
    for step in pdd.get("steps") or []:
        anchors = ", ".join(
            sa.get("anchor", "")
            for sa in (step.get("source_anchors") or [])
            if sa.get("anchor")
        )
        text = f"{step.get('id')}: {step.get('summary')}"
        if anchors:
            text += f" [anchors: {anchors}]"
        doc.add_paragraph(text, style="List Bullet")

    doc.add_heading("SIPOC", level=1)
    sipoc = draft.get("sipoc") or []
    if sipoc:
        table = doc.add_table(rows=1, cols=6)
        table.style = "Table Grid"
        hdr_cells = table.rows[0].cells
        for i, h in enumerate(["#", "Supplier", "Input", "Process Step", "Output", "Customer"]):
            hdr_cells[i].text = h
        for idx, row in enumerate(sipoc, start=1):
            cells = table.add_row().cells
            cells[0].text = str(idx)
            cells[1].text = row.get("supplier", "")
            cells[2].text = row.get("input", "")
            cells[3].text = row.get("process_step", "")
            cells[4].text = row.get("output", "")
            cells[5].text = row.get("customer", "")
    else:
        doc.add_paragraph("No SIPOC rows available.")

    # Evidence bundle section
    doc.add_heading("Evidence Bundle", level=1)
    strength = evidence_bundle.get("evidence_strength") or "unknown"
    doc.add_paragraph(f"Evidence Strength: {strength}")

    linked_anchors = evidence_bundle.get("linked_anchors") or []
    if linked_anchors:
        table = doc.add_table(rows=1, cols=5)
        table.style = "Table Grid"
        hdr_cells = table.rows[0].cells
        for i, h in enumerate(["Anchor", "Type", "Confidence", "Linked Steps", "OCR Snippet"]):
            hdr_cells[i].text = h
        for a in linked_anchors:
            cells = table.add_row().cells
            cells[0].text = a["anchor_value"]
            cells[1].text = a["anchor_type"]
            cells[2].text = f"{a.get('confidence', 0.0):.2f}"
            cells[3].text = ", ".join(a.get("linked_step_ids") or []) or "—"
            cells[4].text = (a.get("ocr_snippet") or "—")[:120]
    else:
        doc.add_paragraph("No linked evidence anchors found.")

    note = evidence_bundle.get("frame_captures_note", "")
    if note:
        doc.add_paragraph(note)

    frame_captures = evidence_bundle.get("frame_captures") or []
    if frame_captures:
        doc.add_heading("Frame Captures", level=1)
        for capture in frame_captures:
            key = capture.get("storage_key", "")
            timestamp_sec = capture.get("timestamp_sec", 0.0)
            if os.path.isabs(key) or (key.startswith(".") and os.path.exists(key)):
                try:
                    doc.add_picture(key)
                    doc.add_paragraph(f"Frame @ {timestamp_sec:.1f}s — {key}")
                except Exception:
                    doc.add_paragraph(f"Frame @ {timestamp_sec:.1f}s (image unreadable)")
            else:
                doc.add_paragraph(f"Frame capture: {key} @ {timestamp_sec:.1f}s")

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
