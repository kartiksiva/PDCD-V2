from __future__ import annotations

import importlib
import os
import pathlib
import sys
from unittest.mock import MagicMock

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

ROOT = pathlib.Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


def _postgres_smoke_url() -> str:
    database_url = os.environ.get("PFCD_POSTGRES_SMOKE_DATABASE_URL")
    if not database_url:
        pytest.skip("PFCD_POSTGRES_SMOKE_DATABASE_URL is not configured")
    return database_url


def _reset_public_schema(database_url: str) -> None:
    engine = create_engine(database_url, future=True, isolation_level="AUTOCOMMIT")
    with engine.connect() as connection:
        connection.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))
    engine.dispose()


def _upgrade_with_alembic(database_url: str) -> None:
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")


def _build_client(monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path, database_url: str):
    exports_path = tmp_path / "exports"
    exports_path.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("EXPORTS_BASE_PATH", str(exports_path))
    monkeypatch.setenv("AZURE_OPENAI_CHAT_DEPLOYMENT_NAME", "test-deployment")
    monkeypatch.setenv("AZURE_OPENAI_API_VERSION", "2024-10-21")
    monkeypatch.delenv("AZURE_SERVICE_BUS_CONNECTION_STRING", raising=False)
    monkeypatch.delenv("AZURE_STORAGE_CONNECTION_STRING", raising=False)
    monkeypatch.delenv("PFCD_API_KEY", raising=False)

    import app.db as db_mod
    import app.repository as repo_mod
    import app.main as main_mod

    importlib.reload(db_mod)
    importlib.reload(repo_mod)
    importlib.reload(main_mod)

    main_mod.ORCHESTRATOR = MagicMock()

    from starlette.testclient import TestClient

    return TestClient(main_mod.app, raise_server_exceptions=False)


@pytest.mark.integration
@pytest.mark.postgres
def test_postgres_alembic_and_api_lifecycle_smoke(monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path) -> None:
    database_url = _postgres_smoke_url()
    monkeypatch.setenv("DATABASE_URL", database_url)
    _reset_public_schema(database_url)
    _upgrade_with_alembic(database_url)

    client = _build_client(monkeypatch, tmp_path, database_url)

    create_response = client.post(
        "/api/jobs",
        json={
            "input_files": [
                {"source_type": "transcript", "file_name": "smoke.vtt", "size_bytes": 1024}
            ]
        },
    )
    assert create_response.status_code == 201, create_response.text
    job_id = create_response.json()["job_id"]

    simulate_response = client.post(f"/dev/jobs/{job_id}/simulate")
    assert simulate_response.status_code == 200, simulate_response.text

    draft_response = client.get(f"/api/jobs/{job_id}/draft")
    assert draft_response.status_code == 200, draft_response.text
    save_response = client.put(
        f"/api/jobs/{job_id}/draft",
        json={
            "draft_version": draft_response.json()["draft"]["version"],
            "assumptions": ["Validated against PostgreSQL smoke DB"],
        },
    )
    assert save_response.status_code == 200, save_response.text

    finalize_response = client.post(f"/api/jobs/{job_id}/finalize")
    assert finalize_response.status_code == 200, finalize_response.text

    export_response = client.get(f"/api/jobs/{job_id}/exports/markdown")
    assert export_response.status_code == 200, export_response.text
    assert "# Process Definition Document" in export_response.text
