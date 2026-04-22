from __future__ import annotations

import importlib
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


def _reload_app(monkeypatch, tmp_path):
    db_path = tmp_path / "pfcd-draft-edit.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("AZURE_OPENAI_CHAT_DEPLOYMENT_NAME", "test-deployment")
    monkeypatch.delenv("PFCD_API_KEY", raising=False)

    import app.db as db_mod
    import app.repository as repo_mod
    import app.main as main_mod

    importlib.reload(db_mod)
    importlib.reload(repo_mod)
    importlib.reload(main_mod)
    main_mod.JOB_REPO.init_db()
    return main_mod


def _full_pdd(purpose: str = "Test Purpose") -> dict:
    return {
        "purpose": purpose,
        "scope": "In scope",
        "triggers": ["Submit request"],
        "preconditions": ["User authenticated"],
        "steps": [{"id": "step-01", "summary": "User submits request"}],
        "roles": ["Analyst"],
        "systems": ["Portal"],
        "business_rules": ["Approval required"],
        "exceptions": [],
        "outputs": ["Submitted request"],
        "metrics": {"coverage": "high", "confidence": 0.85},
        "risks": [],
    }


def _full_sipoc() -> list[dict]:
    return [
        {
            "supplier": "Customer",
            "input": "Request",
            "process_step": "Submit request",
            "output": "Submitted request",
            "customer": "Analyst",
            "step_anchor": ["step-01"],
            "source_anchor": "00:00:00-00:00:30",
            "anchor_missing_reason": None,
        }
    ]


def _create_and_simulate(client) -> str:
    create_resp = client.post(
        "/api/jobs",
        json={"input_files": [{"source_type": "transcript", "file_name": "t.vtt", "size_bytes": 512}]},
    )
    assert create_resp.status_code == 201
    job_id = create_resp.json()["job_id"]
    simulate_resp = client.post(f"/dev/jobs/{job_id}/simulate")
    assert simulate_resp.status_code == 200
    return job_id


def test_update_draft_response_includes_review_notes(monkeypatch, tmp_path):
    main_mod = _reload_app(monkeypatch, tmp_path)

    from starlette.testclient import TestClient

    with TestClient(main_mod.app, raise_server_exceptions=False) as client:
        job_id = _create_and_simulate(client)
        draft = client.get(f"/api/jobs/{job_id}/draft").json()["draft"]
        response = client.put(
            f"/api/jobs/{job_id}/draft",
            json={"draft_version": draft["version"], "pdd": _full_pdd(), "sipoc": _full_sipoc()},
        )

    assert response.status_code == 200
    body = response.json()
    assert "review_notes" in body
    assert "agent_review" in body


def test_update_draft_re_review_clears_pdd_blocker(monkeypatch, tmp_path):
    main_mod = _reload_app(monkeypatch, tmp_path)

    from starlette.testclient import TestClient

    with TestClient(main_mod.app, raise_server_exceptions=False) as client:
        job_id = _create_and_simulate(client)
        draft = client.get(f"/api/jobs/{job_id}/draft").json()["draft"]
        response = client.put(
            f"/api/jobs/{job_id}/draft",
            json={"draft_version": draft["version"], "pdd": _full_pdd("Test Purpose"), "sipoc": _full_sipoc()},
        )

    assert response.status_code == 200
    flag_codes = [flag["code"] for flag in response.json()["review_notes"]["flags"]]
    assert "pdd_incomplete" not in flag_codes


def test_update_draft_re_review_triggers_pdd_blocker(monkeypatch, tmp_path):
    main_mod = _reload_app(monkeypatch, tmp_path)

    from starlette.testclient import TestClient

    with TestClient(main_mod.app, raise_server_exceptions=False) as client:
        job_id = _create_and_simulate(client)
        draft = client.get(f"/api/jobs/{job_id}/draft").json()["draft"]
        first_save = client.put(
            f"/api/jobs/{job_id}/draft",
            json={"draft_version": draft["version"], "pdd": _full_pdd("Initial Purpose"), "sipoc": _full_sipoc()},
        )
        assert first_save.status_code == 200
        next_version = first_save.json()["draft"]["version"]
        response = client.put(
            f"/api/jobs/{job_id}/draft",
            json={"draft_version": next_version, "pdd": _full_pdd(""), "sipoc": _full_sipoc()},
        )

    assert response.status_code == 200
    pdd_flags = [flag for flag in response.json()["review_notes"]["flags"] if flag["code"] == "pdd_incomplete"]
    assert pdd_flags
    assert any(flag["severity"] == "blocker" for flag in pdd_flags)


def test_update_draft_clears_sla_unresolved_after_user_fixes_sla(monkeypatch, tmp_path):
    """SLA_UNRESOLVED flag must be cleared on re-review when the user fixes pdd.sla."""
    main_mod = _reload_app(monkeypatch, tmp_path)

    from starlette.testclient import TestClient

    with TestClient(main_mod.app, raise_server_exceptions=False) as client:
        job_id = _create_and_simulate(client)

        # Inject extracted_facts with an SLA fact and a stale SLA_UNRESOLVED warning flag.
        job = main_mod.JOB_REPO.get_job(job_id)
        job["extracted_facts"] = {
            "quantitative_facts": [{"fact_type": "sla", "value": "24h regulatory", "anchor": "00:10:00"}],
            "exception_patterns": [],
            "workaround_rationale": [],
            "roles_detected": [],
        }
        job["review_notes"]["flags"].append({
            "code": "SLA_UNRESOLVED",
            "severity": "warning",
            "message": "stale pre-fix flag",
        })
        main_mod.JOB_REPO.upsert_job(job_id, job)

        # Save draft with SLA now properly populated.
        draft = client.get(f"/api/jobs/{job_id}/draft").json()["draft"]
        pdd = _full_pdd()
        pdd["sla"] = "24h regulatory"
        response = client.put(
            f"/api/jobs/{job_id}/draft",
            json={"draft_version": draft["version"], "pdd": pdd, "sipoc": _full_sipoc()},
        )

    assert response.status_code == 200
    flag_codes = [f["code"] for f in response.json()["review_notes"]["flags"]]
    assert "SLA_UNRESOLVED" not in flag_codes
