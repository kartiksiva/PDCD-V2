"""Service Bus worker runner."""

from __future__ import annotations

import json
import logging
import os
import random
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Dict
from uuid import uuid4

from azure.servicebus import ServiceBusMessage
from azure.servicebus.exceptions import ServiceBusConnectionError as SBConnectionError

from app.agents.alignment import run_anchor_alignment
from app.agents.extraction import run_extraction
from app.agents.processing import run_processing
from app.agents.reviewing import run_reviewing
from app.job_logic import (
    JobStatus,
    Profile,
    add_agent_run,
    apply_cost_tracking_and_cap_warning,
    build_draft,
    load_transcript_text,
    profile_config,
    update_agent_run,
    _utc_now,
)
from app.repository import JobRepository
from app.servicebus import ServiceBusOrchestrator, build_message, max_retries
from app.storage import ExportStorage

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
        self.storage = ExportStorage.from_env()
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
        run_id = add_agent_run(job, agent_name, profile_conf["profile"], "running", model=profile_conf["model"])
        self.repo.upsert_job(job_id, job)
        if previous_status != job["status"]:
            self._record_status_event(job_id, previous_status, job["status"], self.phase)
        logger.info("Started phase %s for job %s", self.phase, job_id)

        start = time.monotonic()
        if self.phase == "extracting":
            # NOTE: _transcript_text_inline is an in-memory working field used by
            # extraction/alignment in this phase only. It is intentionally not
            # persisted in the DB payload contract.
            transcript_text = load_transcript_text(job, self.storage)
            if transcript_text:
                job["_transcript_text_inline"] = transcript_text
            cost = run_extraction(job, profile_conf)
            run_anchor_alignment(job)
        elif self.phase == "processing":
            logger.info(
                "Processing phase runtime pair for job %s: endpoint=%s deployment=%s",
                job_id,
                os.environ.get("AZURE_OPENAI_ENDPOINT"),
                profile_conf.get("model"),
            )
            cost = run_processing(job, profile_conf)
        elif self.phase == "reviewing":
            # Ensure draft exists (fallback stub if processing was skipped)
            if not job.get("draft"):
                build_draft(job)
            cost = run_reviewing(job, profile_conf)
            job["agent_review"]["decision_at"] = _utc_now()
            # All reviewing outcomes transition to NEEDS_REVIEW so a human can
            # inspect before finalizing.  The agent's decision is recorded in
            # job["agent_review"]["decision"] ("approve_for_draft", "needs_review",
            # or "blocked") — the UI uses that field to control which actions
            # are available (e.g. show finalize button only for approve_for_draft).
            previous_review_status = job["status"]
            job["status"] = JobStatus.NEEDS_REVIEW.value
            if previous_review_status != job["status"]:
                self._record_status_event(job_id, previous_review_status, job["status"], self.phase)
        else:
            cost = 0.0
        duration_ms = int((time.monotonic() - start) * 1000)
        job["updated_at"] = _utc_now()
        update_agent_run(
            job,
            run_id,
            status="success",
            duration_ms=duration_ms,
            cost=cost,
        )
        apply_cost_tracking_and_cap_warning(
            job,
            phase=self.phase,
            cost=cost,
            cap_usd=float(profile_conf["cost_cap_usd"]),
        )
        job["last_completed_phase"] = self.phase
        job["payload_hash"] = message["payload_hash"]
        job["phase_attempt"] = message["attempt"]
        job["active_agent_run_id"] = None
        if self.phase == "extracting":
            # Keep the persisted payload deterministic: drop ephemeral working data.
            job.pop("_transcript_text_inline", None)
            job.pop("_video_transcript_inline", None)
            job.pop("_frame_descriptions_inline", None)
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
            update_agent_run(
                job,
                job.get("active_agent_run_id"),
                status="failed",
                duration_ms=0,
                cost=0.0,
                message=str(exc),
            )
            job["active_agent_run_id"] = None
            if attempt > max_retries():
                job["status"] = JobStatus.FAILED.value
                job["error"] = {"message": str(exc), "phase": self.phase}
                job["updated_at"] = _utc_now()
                if self.phase == "extracting":
                    job.pop("_transcript_text_inline", None)
                    job.pop("_video_transcript_inline", None)
                    job.pop("_frame_descriptions_inline", None)
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


def _start_health_server(port: int) -> HTTPServer:
    """Expose a minimal HTTP endpoint for legacy App Service warmup checks."""

    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, *args: object) -> None:
            pass

    server = HTTPServer(("0.0.0.0", port), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    logger.info("Legacy warmup listener active on port %d", server.server_port)
    return server


def _maybe_start_health_server() -> HTTPServer | None:
    port = os.environ.get("WEBSITES_PORT", "").strip()
    if not port:
        return None
    try:
        return _start_health_server(int(port))
    except ValueError:
        logger.warning("Skipping legacy warmup listener: invalid WEBSITES_PORT=%r", port)
        return None


def _connection_backoff_seconds(consecutive_errors: int) -> float:
    """Return bounded exponential backoff with small jitter for reconnect attempts."""
    exponent = min(max(1, consecutive_errors), 6)
    base = min(60.0, float(2 ** exponent))
    return base + random.uniform(0.0, 1.0)


def run() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    _health_server = _maybe_start_health_server()
    phase = _resolve_phase()
    logger.info(
        "Worker runtime OpenAI config: role=%s endpoint=%s chat_deployment=%s api_version=%s",
        phase,
        os.environ.get("AZURE_OPENAI_ENDPOINT"),
        os.environ.get("AZURE_OPENAI_CHAT_DEPLOYMENT_NAME"),
        os.environ.get("AZURE_OPENAI_API_VERSION"),
    )
    worker = Worker(phase)
    if not worker.orchestrator.enabled:
        raise RuntimeError("AZURE_SERVICE_BUS_CONNECTION_STRING is required for workers.")
    logger.info("Worker starting for phase %s", phase)
    consecutive_connection_errors = 0
    while True:
        try:
            with worker.orchestrator.receive(phase) as receiver:
                if receiver is None:
                    raise RuntimeError("Service Bus receiver not initialized.")
                if consecutive_connection_errors > 0:
                    logger.info(
                        "Service Bus receiver reconnected for phase %s after %d errors",
                        phase,
                        consecutive_connection_errors,
                    )
                consecutive_connection_errors = 0
                logger.info("Worker listening on phase %s", phase)
                while True:
                    try:
                        messages = receiver.receive_messages(max_message_count=1, max_wait_time=5)
                    except SBConnectionError as exc:
                        consecutive_connection_errors += 1
                        delay = _connection_backoff_seconds(consecutive_connection_errors)
                        logger.warning(
                            "Service Bus receive error on phase %s (consecutive=%d); "
                            "recreating receiver in %.1fs: %s",
                            phase,
                            consecutive_connection_errors,
                            delay,
                            exc,
                        )
                        time.sleep(delay)
                        break
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
        except SBConnectionError as exc:
            consecutive_connection_errors += 1
            delay = _connection_backoff_seconds(consecutive_connection_errors)
            logger.warning(
                "Service Bus receiver setup error on phase %s (consecutive=%d); retrying in %.1fs: %s",
                phase,
                consecutive_connection_errors,
                delay,
                exc,
            )
            time.sleep(delay)


if __name__ == "__main__":
    run()
