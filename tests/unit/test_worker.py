"""Tests for worker phase handling and export functions."""

from __future__ import annotations

import importlib
import json
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


# ---------------------------------------------------------------------------
# Worker phase tests
# ---------------------------------------------------------------------------

def _make_job(*, status="queued", has_video=True, has_audio=True, has_transcript=False) -> Dict[str, Any]:
    from app.job_logic import InputFile, JobCreateRequest, default_job_payload

    files = [InputFile(source_type="video", size_bytes=100, audio_detected=has_audio)]
    if has_transcript:
        files.append(InputFile(source_type="transcript", size_bytes=50))
    req = JobCreateRequest(profile="balanced", input_files=files)
    payload = default_job_payload(req)
    payload["job_id"] = str(uuid4())
    payload["status"] = status
    return payload


def _make_message(job_id: str, phase: str, attempt: int = 0) -> Dict[str, Any]:
    from app.servicebus import build_message

    return build_message(
        job_id=job_id,
        phase=phase,
        attempt=attempt,
        requested_by="test",
        trace_id=str(uuid4()),
    )


def test_worker_extracting_phase(tmp_path, monkeypatch):
    """Worker in extracting phase transitions job to PROCESSING and enqueues next phase."""
    db_path = tmp_path / "worker-extract.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")

    _, repo_mod = _reload_modules()
    from app.workers.runner import Worker

    repository = repo_mod.JobRepository.from_env()
    repository.init_db()

    job = _make_job()
    job_id = job["job_id"]
    repository.upsert_job(job_id, job)

    enqueued = []
    worker = Worker("extracting")
    worker.repo = repository
    worker.orchestrator = MagicMock()
    worker.orchestrator.enqueue.side_effect = lambda phase, msg, **kw: enqueued.append((phase, msg))

    message = _make_message(job_id, "extracting")
    worker._run_phase(job, message)

    updated = repository.get_job(job_id)
    assert updated["last_completed_phase"] == "extracting"
    # After extracting, next phase (processing) is enqueued
    assert len(enqueued) == 1
    assert enqueued[0][0] == "processing"


def test_worker_reviewing_phase_builds_draft(tmp_path, monkeypatch):
    """Reviewing phase calls build_draft and sets status to NEEDS_REVIEW."""
    db_path = tmp_path / "worker-review.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")

    _, repo_mod = _reload_modules()
    from app.workers.runner import Worker

    repository = repo_mod.JobRepository.from_env()
    repository.init_db()

    job = _make_job(status="processing")
    job_id = job["job_id"]
    repository.upsert_job(job_id, job)

    worker = Worker("reviewing")
    worker.repo = repository
    worker.orchestrator = MagicMock()

    message = _make_message(job_id, "reviewing")
    worker._run_phase(job, message)

    updated = repository.get_job(job_id)
    assert updated["status"] == "needs_review"
    assert updated["draft"] is not None
    assert "pdd" in updated["draft"]
    assert updated["last_completed_phase"] == "reviewing"


def test_worker_skips_completed_job(tmp_path, monkeypatch):
    """Worker must not re-process a job that is already COMPLETED."""
    db_path = tmp_path / "worker-skip-completed.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")

    _, repo_mod = _reload_modules()
    from app.workers.runner import Worker

    repository = repo_mod.JobRepository.from_env()
    repository.init_db()

    job = _make_job(status="completed")
    job_id = job["job_id"]
    repository.upsert_job(job_id, job)

    worker = Worker("extracting")
    worker.repo = repository
    worker.orchestrator = MagicMock()

    message = _make_message(job_id, "extracting")
    # Should return without raising and without modifying the job
    worker._run_phase(job, message)

    updated = repository.get_job(job_id)
    assert updated["status"] == "completed"
    worker.orchestrator.enqueue.assert_not_called()


def test_worker_skips_failed_job(tmp_path, monkeypatch):
    """Worker must not re-process a job that is FAILED."""
    db_path = tmp_path / "worker-skip-failed.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")

    _, repo_mod = _reload_modules()
    from app.workers.runner import Worker

    repository = repo_mod.JobRepository.from_env()
    repository.init_db()

    job = _make_job(status="failed")
    job_id = job["job_id"]
    repository.upsert_job(job_id, job)

    worker = Worker("extracting")
    worker.repo = repository
    worker.orchestrator = MagicMock()

    message = _make_message(job_id, "extracting")
    worker._run_phase(job, message)

    updated = repository.get_job(job_id)
    assert updated["status"] == "failed"
    worker.orchestrator.enqueue.assert_not_called()


def test_worker_marks_failed_after_max_retries(tmp_path, monkeypatch):
    """handle_message marks job FAILED when retry count exceeds max_retries."""
    db_path = tmp_path / "worker-max-retries.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")

    _, repo_mod = _reload_modules()
    from app.workers.runner import Worker

    repository = repo_mod.JobRepository.from_env()
    repository.init_db()

    job = _make_job()
    job_id = job["job_id"]
    repository.upsert_job(job_id, job)

    worker = Worker("extracting")
    worker.repo = repository
    worker.orchestrator = MagicMock()

    message = _make_message(job_id, "extracting", attempt=99)

    with patch.object(worker, "_run_phase", side_effect=RuntimeError("boom")):
        worker.handle_message(MagicMock(), message)

    updated = repository.get_job(job_id)
    assert updated["status"] == "failed"
    assert updated["error"]["message"] == "boom"


def test_worker_duplicate_message_skipped(tmp_path, monkeypatch):
    """Messages already processed (same phase + hash) are skipped."""
    db_path = tmp_path / "worker-dedup.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")

    _, repo_mod = _reload_modules()
    from app.workers.runner import Worker

    repository = repo_mod.JobRepository.from_env()
    repository.init_db()

    job = _make_job()
    job_id = job["job_id"]
    message = _make_message(job_id, "extracting")
    job["last_completed_phase"] = "extracting"
    job["payload_hash"] = message["payload_hash"]
    repository.upsert_job(job_id, job)

    worker = Worker("extracting")
    worker.repo = repository
    worker.orchestrator = MagicMock()

    run_phase_called = []
    with patch.object(worker, "_run_phase", side_effect=lambda *a: run_phase_called.append(True)):
        worker.handle_message(MagicMock(), message)

    assert not run_phase_called, "Duplicate message should have been skipped"


# ---------------------------------------------------------------------------
# Export function tests
# ---------------------------------------------------------------------------

def test_build_export_markdown_empty_draft():
    from app.export_builder import build_evidence_bundle, build_export_markdown

    result = build_export_markdown({}, build_evidence_bundle({}, {}))
    assert "No finalized draft" in result


def test_build_export_markdown_with_draft():
    from app.export_builder import build_evidence_bundle, build_export_markdown

    draft = {
        "pdd": {
            "purpose": "Test purpose",
            "scope": "Test scope",
            "steps": [{"id": "step-01", "summary": "Do something"}],
        },
        "sipoc": [{"process_step": "Step A", "source_anchor": "00:00:00"}],
    }
    result = build_export_markdown(draft, build_evidence_bundle(draft, {}))
    assert "Test purpose" in result
    assert "step-01" in result
    assert "Step A" in result


def test_build_export_markdown_special_characters():
    """Markdown export should handle special characters without error."""
    from app.export_builder import build_evidence_bundle, build_export_markdown

    draft = {
        "pdd": {
            "purpose": "Purpose with <special> & 'chars' \"quoted\"",
            "scope": "Scope\nwith\nnewlines",
            "steps": [{"id": "step-01", "summary": "Summary & more"}],
        },
        "sipoc": [],
    }
    result = build_export_markdown(draft, build_evidence_bundle(draft, {}))
    assert "<special>" in result


def test_build_export_pdf_returns_bytes():
    """PDF export should return non-empty bytes."""
    from app.export_builder import build_evidence_bundle, build_export_pdf

    draft = {
        "pdd": {
            "purpose": "Test purpose",
            "scope": "Test scope",
            "steps": [{"id": "step-01", "summary": "Do something"}],
        },
        "sipoc": [{"process_step": "Step A", "source_anchor": "00:00:00"}],
    }
    result = build_export_pdf(draft, build_evidence_bundle(draft, {}))
    assert isinstance(result, bytes)
    assert len(result) > 0
    # PDF files start with %PDF
    assert result[:4] == b"%PDF"


def test_build_export_pdf_empty_draft():
    """PDF export should handle an empty draft without raising."""
    from app.export_builder import build_evidence_bundle, build_export_pdf

    result = build_export_pdf({}, build_evidence_bundle({}, {}))
    assert isinstance(result, bytes)
    assert len(result) > 0


# ---------------------------------------------------------------------------
# Storage path traversal tests
# ---------------------------------------------------------------------------

def test_storage_rejects_path_traversal_job_id(tmp_path):
    """save_bytes must reject job_id containing path traversal sequences."""
    from app.storage import ExportStorage

    store = ExportStorage(base_path=str(tmp_path), connection_string=None, container="exports")
    try:
        store.save_bytes("../../etc/passwd", "json", b"data", "application/json")
        assert False, "Expected ValueError"
    except ValueError as exc:
        assert "job_id" in str(exc)


def test_storage_rejects_invalid_format(tmp_path):
    """save_bytes must reject non-alphanumeric format strings."""
    from app.storage import ExportStorage

    store = ExportStorage(base_path=str(tmp_path), connection_string=None, container="exports")
    try:
        store.save_bytes(str(uuid4()), "../evil", b"data", "application/json")
        assert False, "Expected ValueError"
    except ValueError as exc:
        assert "format" in str(exc)


def test_storage_valid_save_and_load(tmp_path):
    """save_bytes followed by load_bytes should return the same content."""
    from app.storage import ExportStorage

    store = ExportStorage(base_path=str(tmp_path), connection_string=None, container="exports")
    job_id = str(uuid4()).replace("-", "")
    content = b"hello world"
    meta = store.save_bytes(job_id, "json", content, "application/json")
    loaded = store.load_bytes(meta.__dict__)
    assert loaded == content
