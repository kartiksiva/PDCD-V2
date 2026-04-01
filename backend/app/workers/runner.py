"""Service Bus worker runner."""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict
from uuid import uuid4

from azure.servicebus import ServiceBusMessage

from app.job_logic import JobStatus, Profile, add_agent_run, build_draft, profile_config
from app.repository import JobRepository
from app.servicebus import ServiceBusOrchestrator, build_message, max_retries

PHASE_TO_AGENT = {
    "extracting": "extraction",
    "processing": "processing",
    "reviewing": "reviewing",
}

PHASE_NEXT = {
    "extracting": "processing",
    "processing": "reviewing",
    "reviewing": None,
}
PHASE_ORDER = ["extracting", "processing", "reviewing"]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_message(raw_body: Any) -> Dict[str, Any]:
    if isinstance(raw_body, (bytes, bytearray)):
        return json.loads(raw_body.decode("utf-8"))
    if isinstance(raw_body, str):
        return json.loads(raw_body)
    if isinstance(raw_body, dict):
        return raw_body
    return json.loads(bytes(raw_body).decode("utf-8"))


class Worker:
    def __init__(self, phase: str) -> None:
        self.phase = phase
        self.repo = JobRepository.from_env()
        self.orchestrator = ServiceBusOrchestrator()

    def _should_skip(self, job: Dict[str, Any], payload_hash: str, phase: str) -> bool:
        if job.get("last_completed_phase") == phase and job.get("payload_hash") == payload_hash:
            return True
        if job.get("last_completed_phase") in PHASE_ORDER and phase in PHASE_ORDER:
            if PHASE_ORDER.index(job["last_completed_phase"]) > PHASE_ORDER.index(phase):
                return True
        return False

    def _record_status_event(self, job_id: str, from_status: str, to_status: str, phase: str) -> None:
        self.repo.append_job_event(
            job_id,
            "status_transition",
            {
                "from": from_status,
                "to": to_status,
                "phase": phase,
                "at": _utc_now(),
            },
        )

    def _run_phase(self, job: Dict[str, Any], message: Dict[str, Any]) -> None:
        profile = Profile(job["profile_requested"])
        profile_conf = profile_config(profile)
        agent_name = PHASE_TO_AGENT[self.phase]
        job["current_phase"] = self.phase
        previous_status = job["status"]
        if job["status"] in {JobStatus.QUEUED.value, JobStatus.NEEDS_REVIEW.value}:
            job["status"] = JobStatus.PROCESSING.value
        job["updated_at"] = _utc_now()
        add_agent_run(job, agent_name, profile_conf["profile"], "running", model=profile_conf["model"])
        self.repo.upsert_job(job["job_id"], job)
        if previous_status != job["status"]:
            self._record_status_event(job["job_id"], previous_status, job["status"], self.phase)

        # Placeholder processing work
        time.sleep(0.1)

        if self.phase == "reviewing":
            build_draft(job)
            blocker = any(
                flag["severity"] == "blocker" for flag in job["review_notes"]["flags"]
            )
            previous_review_status = job["status"]
            job["status"] = JobStatus.NEEDS_REVIEW.value
            job["agent_review"]["decision"] = "blocked" if blocker else "needs_review"
            job["agent_review"]["decision_at"] = _utc_now()
            if previous_review_status != job["status"]:
                self._record_status_event(job["job_id"], previous_review_status, job["status"], self.phase)
        job["updated_at"] = _utc_now()
        add_agent_run(
            job,
            agent_name,
            profile_conf["profile"],
            "success",
            model=profile_conf["model"],
            duration_ms=120,
            cost=0.4,
        )
        job["last_completed_phase"] = self.phase
        job["payload_hash"] = message["payload_hash"]
        job["phase_attempt"] = message["attempt"]
        job["active_agent_run_id"] = None
        self.repo.upsert_job(job["job_id"], job)

        next_phase = PHASE_NEXT[self.phase]
        if next_phase:
            next_msg = build_message(
                job_id=job["job_id"],
                phase=next_phase,
                attempt=0,
                requested_by=f"worker:{self.phase}",
                trace_id=message["trace_id"],
            )
            self.orchestrator.enqueue(next_phase, next_msg)

    def handle_message(self, message: ServiceBusMessage, raw_body: Any) -> None:
        payload = _load_message(raw_body)
        job_id = payload.get("job_id")
        if not job_id:
            return
        job = self.repo.get_job(job_id)
        if not job:
            return
        if job["status"] in {JobStatus.DELETED.value, JobStatus.FAILED.value}:
            return
        if self._should_skip(job, payload["payload_hash"], payload["phase"]):
            return

        try:
            self._run_phase(job, payload)
        except Exception as exc:
            attempt = int(payload.get("attempt", 0)) + 1
            if attempt > max_retries():
                job["status"] = JobStatus.FAILED.value
                job["error"] = {"message": str(exc), "phase": self.phase}
                job["updated_at"] = _utc_now()
                self.repo.upsert_job(job_id, job)
                self.repo.append_job_event(
                    job_id,
                    "phase_failed",
                    {"phase": self.phase, "attempt": attempt, "message": str(exc)},
                )
                return
            payload = build_message(
                job_id=payload.get("job_id"),
                phase=payload.get("phase"),
                attempt=attempt,
                requested_by=payload.get("requested_by", f"worker:{self.phase}"),
                trace_id=payload.get("trace_id", str(uuid4())),
            )
            delay_seconds = min(60, 2 ** attempt)
            self.orchestrator.enqueue(self.phase, payload, delay_seconds=delay_seconds)
            self.repo.append_job_event(
                job_id,
                "phase_retry",
                {"phase": self.phase, "attempt": attempt, "delay_seconds": delay_seconds},
            )


def _resolve_phase() -> str:
    role = os.environ.get("PFCD_WORKER_ROLE", "").strip().lower()
    if role:
        return role
    return "extracting"


def run() -> None:
    phase = _resolve_phase()
    worker = Worker(phase)
    if not worker.orchestrator.enabled:
        raise RuntimeError("AZURE_SERVICE_BUS_CONNECTION_STRING is required for workers.")
    receiver = worker.orchestrator.receive(phase)
    if receiver is None:
        raise RuntimeError("Service Bus receiver not initialized.")
    with receiver:
        while True:
            messages = receiver.receive_messages(max_message_count=1, max_wait_time=5)
            for message in messages:
                try:
                    body = b"".join([b for b in message.body])
                    worker.handle_message(message, body)
                    receiver.complete_message(message)
                except Exception:
                    receiver.abandon_message(message)
            time.sleep(0.5)


if __name__ == "__main__":
    run()
