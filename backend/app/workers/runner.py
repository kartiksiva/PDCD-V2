"""Service Bus worker runner."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from uuid import uuid4

from azure.servicebus import ServiceBusMessage

from app.job_logic import JobStatus, Profile, add_agent_run, build_draft, profile_config
from app.repository import JobRepository
from app.servicebus import ServiceBusOrchestrator, build_message, max_retries

logger = logging.getLogger(__name__)

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

MAX_MESSAGE_BODY_BYTES = 10 * 1024 * 1024  # 10 MB

_TERMINAL_STATUSES = {
    JobStatus.COMPLETED.value,
    JobStatus.FAILED.value,
    JobStatus.EXPIRED.value,
    JobStatus.DELETED.value,
}


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

    @staticmethod
    def _make_blob_client() -> Optional[Any]:
        """Return a BlobServiceClient if Azure Storage is configured, else None."""
        conn_str = os.environ.get("AZURE_STORAGE_CONNECTION_STRING", "")
        if conn_str:
            try:
                from azure.storage.blob import BlobServiceClient
                return BlobServiceClient.from_connection_string(conn_str)
            except Exception as exc:  # pragma: no cover
                logger.warning("Could not create BlobServiceClient: %s", exc)
        return None

    def _run_phase(self, job: Dict[str, Any], message: Dict[str, Any]) -> None:
        job_id = job["job_id"]

        # Guard: never re-process a job that has already reached a terminal state
        # or is currently being finalized.
        if job["status"] in _TERMINAL_STATUSES or job["status"] == JobStatus.FINALIZING.value:
            logger.warning(
                "Skipping phase %s for job %s: status is %s",
                self.phase, job_id, job["status"],
            )
            return

        profile = Profile(job["profile_requested"])
        profile_conf = profile_config(profile)
        agent_name = PHASE_TO_AGENT[self.phase]
        job["current_phase"] = self.phase
        previous_status = job["status"]
        if job["status"] in {JobStatus.QUEUED.value, JobStatus.NEEDS_REVIEW.value}:
            job["status"] = JobStatus.PROCESSING.value
        job["updated_at"] = _utc_now()
        add_agent_run(job, agent_name, profile_conf["profile"], "running", model=profile_conf["model"])
        self.repo.upsert_job(job_id, job)
        if previous_status != job["status"]:
            self._record_status_event(job_id, previous_status, job["status"], self.phase)
        logger.info("Started phase %s for job %s", self.phase, job_id)

        blob_client = self._make_blob_client()

        if self.phase == "extracting":
            from app.agents.extraction.agent import ExtractionAgent
            agent = ExtractionAgent(
                profile=job["profile_requested"],
                job=job,
                blob_client=blob_client,
            )
            evidence_graph = asyncio.run(agent.run(job["input_manifest"]))
            job["transcript_media_consistency"]["verdict"] = evidence_graph.alignment_verdict
            job["transcript_media_consistency"]["similarity_score"] = evidence_graph.similarity_score

        elif self.phase == "processing":
            from app.agents.processing.agent import ProcessingAgent
            agent = ProcessingAgent(
                profile=job["profile_requested"],
                job=job,
                blob_client=blob_client,
            )
            draft = asyncio.run(agent.run(job_id))
            job["draft"] = draft.model_dump()

        elif self.phase == "reviewing":
            from app.agents.reviewing.agent import ReviewingAgent
            agent = ReviewingAgent(
                profile=job["profile_requested"],
                job=job,
                blob_client=blob_client,
            )
            review = asyncio.run(agent.run(job_id))
            job["review_notes"]["flags"] = [f.model_dump() for f in review.flags]
            job["agent_review"]["decision"] = review.decision
            job["agent_signals"]["evidence_strength"] = review.evidence_strength
            build_draft(job)

            previous_review_status = job["status"]
            job["status"] = JobStatus.NEEDS_REVIEW.value
            job["agent_review"]["decision_at"] = _utc_now()
            if previous_review_status != job["status"]:
                self._record_status_event(job_id, previous_review_status, job["status"], self.phase)

        job["updated_at"] = _utc_now()
        job["last_completed_phase"] = self.phase
        job["payload_hash"] = message["payload_hash"]
        job["phase_attempt"] = message["attempt"]
        job["active_agent_run_id"] = None
        self.repo.upsert_job(job_id, job)
        logger.info("Completed phase %s for job %s", self.phase, job_id)

        next_phase = PHASE_NEXT[self.phase]
        if next_phase:
            next_msg = build_message(
                job_id=job_id,
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
            logger.warning("Received message with no job_id; discarding")
            return
        job = self.repo.get_job(job_id)
        if not job:
            logger.warning("Job %s not found; discarding message", job_id)
            return
        if job["status"] in {JobStatus.DELETED.value, JobStatus.FAILED.value}:
            logger.info("Job %s is %s; skipping", job_id, job["status"])
            return
        if self._should_skip(job, payload["payload_hash"], payload["phase"]):
            logger.info("Skipping duplicate message for job %s phase %s", job_id, payload["phase"])
            return

        try:
            self._run_phase(job, payload)
        except Exception as exc:
            logger.error("Phase %s failed for job %s: %s", self.phase, job_id, exc, exc_info=True)
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
                logger.error("Job %s permanently failed after %d attempts", job_id, attempt)
                return
            retry_payload = build_message(
                job_id=payload.get("job_id"),
                phase=payload.get("phase"),
                attempt=attempt,
                requested_by=payload.get("requested_by", f"worker:{self.phase}"),
                trace_id=payload.get("trace_id", str(uuid4())),
            )
            delay_seconds = min(60, 2 ** attempt)
            self.orchestrator.enqueue(self.phase, retry_payload, delay_seconds=delay_seconds)
            self.repo.append_job_event(
                job_id,
                "phase_retry",
                {"phase": self.phase, "attempt": attempt, "delay_seconds": delay_seconds},
            )
            logger.info("Scheduled retry for job %s attempt %d in %ds", job_id, attempt, delay_seconds)


def _resolve_phase() -> str:
    role = os.environ.get("PFCD_WORKER_ROLE", "").strip().lower()
    if role:
        return role
    return "extracting"


def run() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    phase = _resolve_phase()
    worker = Worker(phase)
    if not worker.orchestrator.enabled:
        raise RuntimeError("AZURE_SERVICE_BUS_CONNECTION_STRING is required for workers.")
    logger.info("Worker starting for phase %s", phase)
    with worker.orchestrator.receive(phase) as receiver:
        if receiver is None:
            raise RuntimeError("Service Bus receiver not initialized.")
        logger.info("Worker listening on phase %s", phase)
        while True:
            messages = receiver.receive_messages(max_message_count=1, max_wait_time=5)
            for message in messages:
                try:
                    chunks = []
                    total = 0
                    for chunk in message.body:
                        total += len(chunk)
                        if total > MAX_MESSAGE_BODY_BYTES:
                            raise ValueError(
                                f"Message body exceeds {MAX_MESSAGE_BODY_BYTES // (1024 * 1024)}MB limit"
                            )
                        chunks.append(chunk)
                    body = b"".join(chunks)
                    worker.handle_message(message, body)
                    receiver.complete_message(message)
                except json.JSONDecodeError as exc:
                    logger.error("Unparseable message body; dead-lettering: %s", exc)
                    receiver.dead_letter_message(message, reason="UnparseableBody")
                except Exception as exc:
                    logger.error("Unhandled error processing message; abandoning: %s", exc, exc_info=True)
                    receiver.abandon_message(message)
            time.sleep(0.5)


if __name__ == "__main__":
    run()
