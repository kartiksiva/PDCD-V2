from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_backend_health_check_does_not_treat_503_as_success():
    workflow = _read(".github/workflows/deploy-backend.yml")

    assert '|| [ "$status_code" = "503" ]' not in workflow
    assert 'if [ "$status_code" = "503" ]; then' in workflow


def test_worker_deploy_verifies_revision_and_replica_health():
    workflow = _read(".github/workflows/deploy-workers.yml")

    assert "az containerapp revision show" in workflow
    assert "az containerapp replica list" in workflow


def test_backend_workflow_supports_queue_override_values():
    workflow = _read(".github/workflows/deploy-backend.yml")

    assert "SERVICE_BUS_QUEUE_EXTRACTING" in workflow
    assert "SERVICE_BUS_QUEUE_PROCESSING" in workflow
    assert "SERVICE_BUS_QUEUE_REVIEWING" in workflow
    assert 'value: "extracting"' not in workflow
    assert 'value: "processing"' not in workflow
    assert 'value: "reviewing"' not in workflow


def test_worker_workflow_uses_override_queue_values_in_env_and_scaler():
    workflow = _read(".github/workflows/deploy-workers.yml")

    assert "SERVICE_BUS_QUEUE_EXTRACTING" in workflow
    assert "SERVICE_BUS_QUEUE_PROCESSING" in workflow
    assert "SERVICE_BUS_QUEUE_REVIEWING" in workflow
    assert 'echo "WORKER_QUEUE_NAME=${{ matrix.role }}"' not in workflow
    assert 'value: "extracting"' not in workflow
    assert 'value: "processing"' not in workflow
    assert 'value: "reviewing"' not in workflow
