import importlib
import pathlib
import sys
from uuid import uuid4

ROOT = pathlib.Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
sys.path.append(str(BACKEND))


def _reload_modules():
    import app.db as db
    import app.repository as repo

    importlib.reload(db)
    importlib.reload(repo)
    return db, repo


def test_job_roundtrip(tmp_path, monkeypatch):
    db_path = tmp_path / "pfcd-test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")

    _, repo = _reload_modules()
    from app.job_logic import InputFile, JobCreateRequest, default_job_payload

    repository = repo.JobRepository.from_env()
    repository.init_db()

    payload = default_job_payload(
        JobCreateRequest(
            profile="balanced",
            input_files=[InputFile(source_type="video", size_bytes=123)],
            teams_metadata={"meeting_id": "t-1"},
        )
    )
    job_id = str(uuid4())
    payload["job_id"] = job_id

    repository.upsert_job(job_id, payload)
    loaded = repository.get_job(job_id)

    assert loaded is not None
    assert loaded["job_id"] == job_id
    assert loaded["input_manifest"]["inputs"][0]["source_type"] == "video"
    assert loaded["teams_metadata"]["meeting_id"] == "t-1"


def test_job_events(tmp_path, monkeypatch):
    db_path = tmp_path / "pfcd-events.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")

    _, repo = _reload_modules()

    repository = repo.JobRepository.from_env()
    repository.init_db()

    job_id = str(uuid4())
    repository.append_job_event(job_id, "job_created", {"job_id": job_id})

    # Validate write by reading raw table
    from sqlalchemy import text
    from app.db import session_scope
    with session_scope() as session:
        result = session.execute(text("SELECT COUNT(1) FROM job_events WHERE job_id = :job_id"), {"job_id": job_id})
        count = result.scalar()

    assert count == 1
