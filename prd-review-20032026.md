# PRD Review: PFCD Video-First v1 (Update 1)
**Date:** March 20, 2026
**Project:** PFCD-V2 (Video-First Process Discovery)

## 1. Executive Summary
The PRD has been refined to address several critical functional gaps identified in the initial review, particularly around speaker resolution, export richness, and upload policies. These additions significantly strengthen the "Review/Edit" and "Finalize" phases of the workflow.

## 2. Key Updates & Improvements

### Speaker Resolution (Section 8.1)
- **Improvement:** The addition of manual resolution for `Unknown Speaker` is a vital usability fix. Allowing users to map these to existing participants and persisting them as `speaker_resolutions` ensures the final PDD is accurate and professional.
- **Note:** This will require the Review UI to fetch and display the `transcript_speaker_map` and `participants` from the `teams_metadata`.

### Evidence Richness in Exports (Section 8.10)
- **Improvement:** Explicitly including frame captures and OCR snippets in PDF/DOCX exports transforms the PDD from a simple text document into a verifiable audit trail.
- **Verification:** The "Evidence bundle manifest" is a great addition for traceability. 
- **Recommendation:** Ensure the export service can handle high-resolution image embedding without creating excessively large files (potential for image compression/downsampling).

### Upload Size & Cost Governance (Section 8.13)
- **Improvement:** Defining a clear 413 error and suggesting remediation for large files prevents "silent failures" or infinite hangs. 
- **Strategic Note:** The "estimate warning" for Quality profiles is a proactive way to manage user expectations regarding processing time and Azure consumption.

## 3. Remaining Observations

### Technical Risks (Refined)
- **Export Complexity:** Generating PDFs with embedded, context-aware images (linked to specific steps) adds significant complexity to the `finalizing` phase. This may require a dedicated worker or a specialized library (e.g., Playwright or a robust PDF engine) within the Azure Container App.
- **Speaker Mapping Persistence:** Ensure the `speaker_resolutions` are handled idempotently if a user re-edits a draft multiple times.

### Functional Gaps (Remaining)
- **Chunked Uploads:** While the 500MB limit is now handled with a 413, the PRD suggests segmented uploads for a "future release." For long Teams recordings (1hr+ at 1080p), 500MB might still be tight. A note on recommended bitrates/resolutions in the UI could help.

## 4. Architectural Recommendations (Updated)
- **Image Proxy/Optimization:** Consider an internal Azure Function or service that optimizes/crops frames *specifically* for the export format to keep the final PDD/DOCX size manageable.
- **Draft Versioning:** Since users can now resolve speakers and edit evidence links, consider a simple "last saved" timestamp in the draft metadata to prevent overwriting edits if multiple users (Manager/SME) review the same job.

## 5. Conclusion
The updates directly address the "Human-in-the-loop" requirements for speaker mapping and provide a more "enterprise-ready" export format. The project is well-positioned for the technical design of the Extraction and Processing agents.

**Status:** Updated & Approved for Technical Design Phase.
