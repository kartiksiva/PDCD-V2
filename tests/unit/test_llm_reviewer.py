"""Unit tests for advisory LLM semantic reviewer."""

from __future__ import annotations

import importlib
import os
import pathlib
import sys
from typing import Any, Dict
from unittest.mock import MagicMock, patch
from uuid import uuid4

ROOT = pathlib.Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))


def _reload_modules():
    import app.db as db
    import app.repository as repo

    importlib.reload(db)
    importlib.reload(repo)
    return db, repo


def _make_job() -> Dict[str, Any]:
    from app.job_logic import InputFile, JobCreateRequest, default_job_payload

    req = JobCreateRequest(
        profile="balanced",
        input_files=[InputFile(source_type="transcript", size_bytes=128)],
    )
    job = default_job_payload(req)
    job["job_id"] = str(uuid4())
    job["draft"] = {
        "pdd": {
            "steps": [
                {
                    "id": "step-01",
                    "summary": "Capture request",
                    "source_anchors": [{"anchor": "00:00:01-00:00:05", "confidence": 0.9}],
                }
            ]
        },
        "sipoc": [],
    }
    job["extracted_evidence"] = {
        "evidence_items": [
            {
                "id": "ev-01",
                "summary": "Capture request in system",
                "anchor": "00:00:01-00:00:05",
                "confidence": 0.9,
            }
        ]
    }
    job["_transcript_text_inline"] = (
        "WEBVTT\n\n"
        "00:00:01.000 --> 00:00:05.000\n"
        "Analyst: Capture request in system\n"
    )
    job["agent_review"]["decision"] = "needs_review"
    return job


def _balanced_profile() -> Dict[str, Any]:
    return {"profile": "balanced", "model": "gpt-4o-mini", "cost_cap_usd": 4.0}


def test_uncited_flags_are_dropped():
    from app.agents.llm_reviewer import _drop_uncited_flags

    raw_flags = [
        {"code": "ok", "evidence_id": "ev-01", "anchor": "00:00:01-00:00:05", "message": "valid"},
        {"code": "missing_anchor", "evidence_id": "ev-02", "anchor": "", "message": "drop"},
        {"code": "missing_evidence", "anchor": "00:00:10-00:00:12", "message": "drop"},
    ]

    kept = _drop_uncited_flags(raw_flags)
    assert len(kept) == 1
    assert kept[0]["code"] == "ok"
    assert kept[0]["evidence_id"] == "ev-01"


def test_coverage_flag_for_unmapped_evidence(monkeypatch):
    from app.agents.llm_reviewer import run_llm_semantic_review

    monkeypatch.setenv("PFCD_REVIEW_LLM_ENABLED", "true")
    job = _make_job()
    job["extracted_evidence"]["evidence_items"].append(
        {
            "id": "ev-03",
            "summary": "Reconcile ERP billing",
            "anchor": "00:00:20-00:00:30",
            "confidence": 0.8,
        }
    )
    job["_transcript_text_inline"] += (
        "\n00:00:20.000 --> 00:00:30.000\nAnalyst: Reconcile ERP billing\n"
    )

    async def _fake_call(*_args, **_kwargs):
        return '{"coverage_flags":[],"consistency_flags":[]}', 10, 10

    with patch("app.agents.llm_reviewer._call_llm_review", side_effect=_fake_call):
        run_llm_semantic_review(job, _balanced_profile(), MagicMock())

    flags = job["review_notes"]["llm_semantic_flags"]
    assert any(flag["evidence_id"] == "ev-03" and flag["code"] == "coverage_gap" for flag in flags)


def test_no_flags_when_all_evidence_mapped(monkeypatch):
    from app.agents.llm_reviewer import run_llm_semantic_review

    monkeypatch.setenv("PFCD_REVIEW_LLM_ENABLED", "true")
    job = _make_job()

    async def _fake_call(*_args, **_kwargs):
        return '{"coverage_flags":[],"consistency_flags":[]}', 10, 10

    with patch("app.agents.llm_reviewer._call_llm_review", side_effect=_fake_call):
        run_llm_semantic_review(job, _balanced_profile(), MagicMock())

    assert job["review_notes"]["llm_semantic_flags"] == []


def test_llm_review_disabled_by_default(monkeypatch):
    from app.agents.llm_reviewer import run_llm_semantic_review

    monkeypatch.delenv("PFCD_REVIEW_LLM_ENABLED", raising=False)
    job = _make_job()

    with patch("app.agents.llm_reviewer._call_llm_review") as call_mock:
        run_llm_semantic_review(job, _balanced_profile(), MagicMock())

    call_mock.assert_not_called()
    assert job["review_notes"]["llm_semantic_flags"] == []


def test_skipped_when_decision_is_blocked(tmp_path, monkeypatch):
    db_path = tmp_path / "llm-reviewer-blocked.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("PFCD_REVIEW_LLM_ENABLED", "true")

    _, repo_mod = _reload_modules()
    from app.servicebus import build_message
    from app.workers.runner import Worker

    repository = repo_mod.JobRepository.from_env()
    repository.init_db()

    job = _make_job()
    job["status"] = "processing"
    job_id = job["job_id"]
    repository.upsert_job(job_id, job)

    worker = Worker("reviewing")
    worker.repo = repository
    worker.orchestrator = MagicMock()

    message = build_message(
        job_id=job_id,
        phase="reviewing",
        attempt=0,
        requested_by="test",
        trace_id=str(uuid4()),
    )

    def _fake_run_reviewing(job_payload: Dict[str, Any], _profile_conf: Dict[str, Any]) -> float:
        job_payload["agent_review"]["decision"] = "blocked"
        return 0.0

    with patch("app.workers.runner.run_reviewing", side_effect=_fake_run_reviewing):
        with patch("app.workers.runner.run_llm_semantic_review") as llm_mock:
            worker._run_phase(job, message)

    llm_mock.assert_not_called()

