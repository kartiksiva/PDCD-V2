"""Unit tests for TTL cleanup worker."""

import importlib
import pathlib
import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock
from uuid import uuid4

ROOT = pathlib.Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
sys.path.append(str(BACKEND))


def _utc_iso(delta_days: int = 0) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=delta_days)).isoformat()


def _reload_modules():
    import app.db as db
    import app.repository as repo

    importlib.reload(db)
    importlib.reload(repo)
    return db, repo


def _make_repo(tmp_path, monkeypatch):
    db_path = tmp_path / "pfcd-cleanup-test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    _, repo_mod = _reload_modules()
    repository = repo_mod.JobRepository.from_env()
    repository.init_db()
    return repository


def _create_job(repository, job_id=None, ttl_expires_at=None, cleanup_pending=False, status="queued"):
    from app.job_logic import InputFile, JobCreateRequest, default_job_payload

    if job_id is None:
        job_id = str(uuid4())
    payload = default_job_payload(
        JobCreateRequest(
            profile="balanced",
            input_files=[InputFile(source_type="video", size_bytes=100)],
        )
    )
    payload["job_id"] = job_id
    payload["status"] = status
    payload["ttl_expires_at"] = ttl_expires_at
    payload["cleanup_pending"] = cleanup_pending
    repository.upsert_job(job_id, payload)
    return job_id


def test_find_expired_jobs(tmp_path, monkeypatch):
    repository = _make_repo(tmp_path, monkeypatch)

    past_id = _create_job(repository, ttl_expires_at=_utc_iso(-1))
    future_id = _create_job(repository, ttl_expires_at=_utc_iso(1))
    no_ttl_id = _create_job(repository, ttl_expires_at=None)

    now = _utc_iso()
    expired = repository.find_expired_jobs(now)

    assert past_id in expired
    assert future_id not in expired
    assert no_ttl_id not in expired


def test_find_expired_jobs_skips_terminal_statuses(tmp_path, monkeypatch):
    repository = _make_repo(tmp_path, monkeypatch)

    already_expired = _create_job(repository, ttl_expires_at=_utc_iso(-1), status="expired")
    already_completed = _create_job(repository, ttl_expires_at=_utc_iso(-1), status="completed")
    active = _create_job(repository, ttl_expires_at=_utc_iso(-1), status="queued")

    now = _utc_iso()
    expired = repository.find_expired_jobs(now)

    assert already_expired not in expired
    assert already_completed not in expired
    assert active in expired


def test_find_cleanup_pending(tmp_path, monkeypatch):
    repository = _make_repo(tmp_path, monkeypatch)

    pending_id = _create_job(repository, cleanup_pending=True)
    clean_id = _create_job(repository, cleanup_pending=False)

    pending = repository.find_cleanup_pending_jobs()

    assert pending_id in pending
    assert clean_id not in pending


def test_purge_job_data(tmp_path, monkeypatch):
    repository = _make_repo(tmp_path, monkeypatch)

    job_id = _create_job(repository, cleanup_pending=True)
    repository.append_job_event(job_id, "test_event", {"x": 1})

    repository.purge_job_data(job_id)

    from sqlalchemy import text
    from app.db import session_scope

    with session_scope() as session:
        event_count = session.execute(
            text("SELECT COUNT(1) FROM job_events WHERE job_id = :job_id"), {"job_id": job_id}
        ).scalar()
        agent_run_count = session.execute(
            text("SELECT COUNT(1) FROM agent_runs WHERE job_id = :job_id"), {"job_id": job_id}
        ).scalar()
        draft_count = session.execute(
            text("SELECT COUNT(1) FROM drafts WHERE job_id = :job_id"), {"job_id": job_id}
        ).scalar()
        job_row = session.execute(
            text("SELECT cleanup_pending FROM jobs WHERE job_id = :job_id"), {"job_id": job_id}
        ).fetchone()

    assert event_count == 0
    assert agent_run_count == 0
    assert draft_count == 0
    assert job_row is not None, "Job row should still exist after purge"
    assert job_row[0] == 0  # cleanup_pending=False


def test_full_cleanup_cycle(tmp_path, monkeypatch):
    repository = _make_repo(tmp_path, monkeypatch)

    # Import cleanup worker after modules are reloaded
    import importlib
    import app.workers.cleanup as cleanup_mod
    importlib.reload(cleanup_mod)

    mock_storage = MagicMock()
    worker = cleanup_mod.CleanupWorker(repo=repository, storage=mock_storage)

    # Create a job with TTL in the past
    job_id = _create_job(repository, ttl_expires_at=_utc_iso(-1), status="queued")

    # Phase A: expire
    worker.expire_ttl_jobs()

    job = repository.get_job(job_id)
    assert job["status"] == "expired"
    assert job["cleanup_pending"] is True

    # Phase B: purge
    worker.purge_pending_jobs()

    mock_storage.delete_job_exports.assert_called_once_with(job_id)

    job_after = repository.get_job(job_id)
    assert job_after["cleanup_pending"] is False

    from sqlalchemy import text
    from app.db import session_scope

    with session_scope() as session:
        # purge_job_data deletes all events, then cleanup_completed is appended
        rows = session.execute(
            text("SELECT event_type FROM job_events WHERE job_id = :job_id"), {"job_id": job_id}
        ).fetchall()
    event_types = [r[0] for r in rows]
    assert event_types == ["cleanup_completed"]
