from __future__ import annotations

import importlib
import pathlib
import sys
from unittest.mock import MagicMock

ROOT = pathlib.Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


def test_app_shutdown_closes_orchestrator(monkeypatch, tmp_path):
    db_path = tmp_path / "pfcd-main.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("AZURE_OPENAI_CHAT_DEPLOYMENT_NAME", "test-deployment")

    import app.main as main_mod

    importlib.reload(main_mod)
    main_mod.ORCHESTRATOR = MagicMock()

    from starlette.testclient import TestClient

    with TestClient(main_mod.app, raise_server_exceptions=False) as client:
        client.get("/health")

    main_mod.ORCHESTRATOR.close.assert_called_once_with()
