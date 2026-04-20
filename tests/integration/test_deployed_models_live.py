"""Optional live test against deployed LLM models.

Run explicitly with:
  PFCD_RUN_DEPLOYED_MODEL_TESTS=1 PYTHONPATH=backend pytest -q tests/integration/test_deployed_models_live.py
"""

from __future__ import annotations

import os
from typing import Dict, Any
from uuid import uuid4

import pytest


def _provider() -> str:
    return (os.environ.get("PFCD_PROVIDER", "azure_openai").strip().lower() or "azure_openai")


def _live_env_ready() -> bool:
    provider = _provider()
    if provider == "openai":
        return bool(os.environ.get("OPENAI_API_KEY"))
    return bool(
        os.environ.get("AZURE_OPENAI_ENDPOINT")
        and (
            os.environ.get("AZURE_OPENAI_DEPLOYMENT_BALANCED")
            or os.environ.get("AZURE_OPENAI_CHAT_DEPLOYMENT_NAME")
        )
    )


def _make_live_job() -> Dict[str, Any]:
    from app.job_logic import InputFile, JobCreateRequest, default_job_payload

    req = JobCreateRequest(
        profile="balanced",
        input_files=[InputFile(source_type="transcript", size_bytes=100)],
    )
    job = default_job_payload(req)
    job["job_id"] = str(uuid4())
    job["_transcript_text_inline"] = (
        "[00:00:01-00:00:08] Analyst opens ticketing portal and reviews pending requests.\n"
        "[00:00:09-00:00:18] Analyst validates customer details and categorizes the issue.\n"
        "[00:00:19-00:00:31] Analyst updates status, assigns owner, and sends acknowledgement email."
    )
    return job


@pytest.mark.skipif(
    os.environ.get("PFCD_RUN_DEPLOYED_MODEL_TESTS") != "1",
    reason="Set PFCD_RUN_DEPLOYED_MODEL_TESTS=1 to run deployed-model live tests.",
)
def test_live_extraction_and_processing_on_deployed_models():
    if not _live_env_ready():
        pytest.skip("Live deployed-model test skipped: provider environment is not configured.")

    from app.agents.extraction import run_extraction
    from app.agents.processing import run_processing

    model = (
        os.environ.get("AZURE_OPENAI_DEPLOYMENT_BALANCED")
        or os.environ.get("AZURE_OPENAI_CHAT_DEPLOYMENT_NAME")
        or os.environ.get("OPENAI_CHAT_MODEL_BALANCED")
    )
    assert model, "No balanced deployment/model configured for live test."

    profile_conf = {"profile": "balanced", "model": model, "cost_cap_usd": 4.0}

    job = _make_live_job()
    extraction_cost = run_extraction(job, profile_conf)
    assert extraction_cost >= 0.0
    assert job.get("extracted_evidence", {}).get("evidence_items"), "No evidence extracted by deployed model."

    processing_cost = run_processing(job, profile_conf)
    assert processing_cost >= 0.0
    draft = job.get("draft") or {}
    assert "pdd" in draft
    assert isinstance(draft.get("sipoc"), list)
    assert "confidence_summary" in draft
