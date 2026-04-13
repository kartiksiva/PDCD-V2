"""Local end-to-end pipeline smoke test.

Exercises extraction -> alignment -> processing -> reviewing against a real LLM.
Requires PFCD_PROVIDER=openai and OPENAI_API_KEY to be set.

Usage:
    cd backend
    PFCD_PROVIDER=openai OPENAI_API_KEY=sk-... python ../scripts/test_e2e_pipeline.py

Pass/fail is printed to stdout. Exit code 0 = pass, 1 = fail.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.agents.alignment import run_anchor_alignment
from app.agents.extraction import run_extraction
from app.agents.processing import run_processing
from app.agents.reviewing import run_reviewing
from app.job_logic import InputFile, JobCreateRequest, Profile, default_job_payload, profile_config


TRANSCRIPT_TEXT = """WEBVTT

00:00:10.000 --> 00:00:20.000
Analyst receives the intake request from the client via email.

00:00:21.000 --> 00:00:35.000
Reviewer validates completeness and logs it in the document store.

00:00:36.000 --> 00:00:50.000
Approver signs off and closes the ticket in CRM.

00:00:51.000 --> 00:01:05.000
Manager is notified and archives the approved record.
"""


def _require_env() -> tuple[bool, str | None]:
    provider = os.environ.get("PFCD_PROVIDER", "").strip().lower()
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if provider != "openai":
        return False, "PFCD_PROVIDER=openai is required."
    if not api_key:
        return False, "OPENAI_API_KEY is required."
    return True, None


def _build_job() -> tuple[dict, dict]:
    request = JobCreateRequest(
        profile=Profile.BALANCED,
        input_files=[
            InputFile(
                source_type="transcript",
                document_type="transcript",
                file_name="inline.vtt",
                size_bytes=len(TRANSCRIPT_TEXT.encode("utf-8")),
                mime_type="text/vtt",
            )
        ],
    )
    job = default_job_payload(request)
    job["job_id"] = "local-e2e-pipeline-smoke"
    job["_transcript_text_inline"] = TRANSCRIPT_TEXT
    job["has_transcript"] = True
    return job, profile_config(Profile.BALANCED)


def _count_sipoc_step_anchors(sipoc_rows: list[dict]) -> int:
    return sum(1 for row in sipoc_rows if len(row.get("step_anchor") or []) >= 1)


def _count_sipoc_source_anchors(sipoc_rows: list[dict]) -> int:
    return sum(1 for row in sipoc_rows if bool((row.get("source_anchor") or "").strip()))


def _print_summary(job: dict) -> None:
    evidence_items = (job.get("extracted_evidence") or {}).get("evidence_items") or []
    sipoc_rows = (job.get("draft") or {}).get("sipoc") or []
    flags = (job.get("review_notes") or {}).get("flags") or []
    flag_codes = [flag.get("code", "") for flag in flags]
    blocker_codes = [
        flag.get("code", "")
        for flag in flags
        if flag.get("severity") == "blocker"
    ]
    blockers_text = blocker_codes or ["NONE"]

    print("=== E2E Pipeline Smoke Test ===")
    print(f"Extraction evidence items  : {len(evidence_items)}")
    print(f"Alignment verdict          : {job.get('transcript_media_consistency', {}).get('verdict')}")
    print(f"SIPOC rows generated       : {len(sipoc_rows)}")
    print(f"SIPOC rows with step_anchor: {_count_sipoc_step_anchors(sipoc_rows)}")
    print(f"SIPOC rows with source_anchor: {_count_sipoc_source_anchors(sipoc_rows)}")
    print(f"Review flags               : {flag_codes}")
    print(f"Blockers                   : {blockers_text}")


def main() -> int:
    ok, error = _require_env()
    if not ok:
        print(f"Result: FAIL - {error}")
        return 1

    job, profile_conf = _build_job()

    try:
        run_extraction(job, profile_conf)
        run_anchor_alignment(job)
        run_processing(job, profile_conf)
        run_reviewing(job, profile_conf)
    except Exception as exc:
        print("=== E2E Pipeline Smoke Test ===")
        print(f"Result: FAIL - {type(exc).__name__}: {exc}")
        return 1

    _print_summary(job)

    blocker_codes = [
        flag.get("code", "")
        for flag in (job.get("review_notes") or {}).get("flags") or []
        if flag.get("severity") == "blocker"
    ]
    if "sipoc_no_anchor" in blocker_codes:
        print("Result: FAIL - sipoc_no_anchor blocker present")
        return 1

    print("Result: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
