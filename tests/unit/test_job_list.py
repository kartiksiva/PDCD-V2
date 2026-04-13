from __future__ import annotations

import importlib
import pathlib
import sys
from datetime import datetime, timedelta, timezone
from uuid import uuid4

ROOT = pathlib.Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


def _reload_repository():
    import app.db as db_mod
    import app.repository as repo_mod

    importlib.reload(db_mod)
    importlib.reload(repo_mod)
    return repo_mod


def _reload_main(monkeypatch, tmp_path):
    db_path = tmp_path / "pfcd-job-list-api.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("AZURE_OPENAI_CHAT_DEPLOYMENT_NAME", "test-deployment")
    monkeypatch.delenv("PFCD_API_KEY", raising=False)

    import app.db as db_mod
    import app.repository as repo_mod
    import app.main as main_mod

    importlib.reload(db_mod)
    importlib.reload(repo_mod)
    importlib.reload(main_mod)
    return main_mod


def _base_payload():
    from app.job_logic import InputFile, JobCreateRequest, default_job_payload

    return default_job_payload(
        JobCreateRequest(
            profile="balanced",
            input_files=[InputFile(source_type="video", size_bytes=123)],
        )
    )


def test_list_jobs_empty(tmp_path, monkeypatch):
    db_path = tmp_path / "pfcd-list-empty.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("AZURE_OPENAI_CHAT_DEPLOYMENT_NAME", "test-deployment")

    repo_mod = _reload_repository()
    repository = repo_mod.JobRepository.from_env()
    repository.init_db()

    assert repository.list_jobs() == []


def test_list_jobs_returns_rows_most_recent_first(tmp_path, monkeypatch):
    db_path = tmp_path / "pfcd-list-order.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("AZURE_OPENAI_CHAT_DEPLOYMENT_NAME", "test-deployment")

    repo_mod = _reload_repository()
    repository = repo_mod.JobRepository.from_env()
    repository.init_db()

    earlier = datetime(2026, 4, 13, 9, 0, tzinfo=timezone.utc)
    later = earlier + timedelta(hours=1)

    first_id = str(uuid4())
    first_payload = _base_payload()
    first_payload["job_id"] = first_id
    first_payload["created_at"] = earlier.isoformat()
    first_payload["updated_at"] = earlier.isoformat()
    repository.upsert_job(first_id, first_payload)

    second_id = str(uuid4())
    second_payload = _base_payload()
    second_payload["job_id"] = second_id
    second_payload["created_at"] = later.isoformat()
    second_payload["updated_at"] = later.isoformat()
    repository.upsert_job(second_id, second_payload)

    jobs = repository.list_jobs()

    assert [job["job_id"] for job in jobs] == [second_id, first_id]


def test_list_jobs_excludes_deleted(tmp_path, monkeypatch):
    db_path = tmp_path / "pfcd-list-deleted.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("AZURE_OPENAI_CHAT_DEPLOYMENT_NAME", "test-deployment")

    repo_mod = _reload_repository()
    repository = repo_mod.JobRepository.from_env()
    repository.init_db()

    payload = _base_payload()
    job_id = str(uuid4())
    payload["job_id"] = job_id
    payload["deleted_at"] = datetime(2026, 4, 13, 10, 0, tzinfo=timezone.utc).isoformat()
    repository.upsert_job(job_id, payload)

    assert repository.list_jobs() == []


def test_list_jobs_endpoint_returns_200(monkeypatch, tmp_path):
    main_mod = _reload_main(monkeypatch, tmp_path)

    from starlette.testclient import TestClient

    with TestClient(main_mod.app, raise_server_exceptions=False) as client:
        response = client.get("/api/jobs")

    assert response.status_code == 200
    assert isinstance(response.json(), list)
