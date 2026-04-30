"""TTL expiry and data purge cleanup worker."""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timedelta, timezone

from app.job_logic import JobStatus
from app.repository import JobRepository
from app.servicebus import ServiceBusOrchestrator, build_message
from app.storage import ExportStorage

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = int(os.environ.get("PFCD_CLEANUP_INTERVAL_SECONDS", "300"))
STALE_PHASE_WINDOW_SECONDS = int(os.environ.get("PFCD_STALE_PHASE_WINDOW_SECONDS", "120"))


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class CleanupWorker:
    def __init__(self, repo: JobRepository, storage: ExportStorage, orchestrator: ServiceBusOrchestrator | None = None) -> None:
        self.repo = repo
        self.storage = storage
        self.orchestrator = orchestrator

    def reenqueue_stale_phases(self) -> None:
        """Re-enqueue jobs whose enqueue call was lost before Service Bus send completed."""
        if not self.orchestrator or not self.orchestrator.enabled:
            return
        stale_before = datetime.now(timezone.utc) - timedelta(seconds=STALE_PHASE_WINDOW_SECONDS)
        job_ids = self.repo.find_pending_next_phase_jobs(stale_before)
        for job_id in job_ids:
            try:
                job = self.repo.get_job(job_id)
                if not job:
                    continue
                next_phase = job.get("pending_next_phase")
                if not next_phase:
                    continue
                from uuid import uuid4
                retry_msg = build_message(
                    job_id=job_id,
                    phase=next_phase,
                    attempt=0,
                    requested_by="cleanup:stale_phase_sweeper",
                    trace_id=str(uuid4()),
                )
                self.orchestrator.enqueue(next_phase, retry_msg)
                job["pending_next_phase"] = None
                job["updated_at"] = _utc_now()
                self.repo.upsert_job(job_id, job)
                logger.info("Re-enqueued stale phase %s for job %s", next_phase, job_id)
            except Exception as exc:
                logger.error("Failed to re-enqueue stale phase for job %s: %s", job_id, exc, exc_info=True)

    def expire_ttl_jobs(self) -> None:
        """Phase A: mark TTL-exceeded jobs as EXPIRED and set cleanup_pending=True."""
        now = datetime.now(timezone.utc)
        job_ids = self.repo.find_expired_jobs(now)
        for job_id in job_ids:
            try:
                job = self.repo.get_job(job_id)
                if not job:
                    continue
                previous_status = job["status"]
                job["status"] = JobStatus.EXPIRED.value
                job["cleanup_pending"] = True
                job["updated_at"] = _utc_now()
                self.repo.upsert_job(job_id, job)
                self.repo.append_job_event(
                    job_id,
                    "status_transition",
                    {"from": previous_status, "to": JobStatus.EXPIRED.value, "reason": "ttl_expired", "at": _utc_now()},
                )
                logger.info("Expired job %s (was %s)", job_id, previous_status)
            except Exception as exc:
                logger.error("Failed to expire job %s: %s", job_id, exc, exc_info=True)
                self.repo.append_job_event(job_id, "cleanup_failed", {"phase": "expire", "message": str(exc)})

    def purge_pending_jobs(self) -> None:
        """Phase B: delete export files and purge DB rows for cleanup_pending jobs."""
        job_ids = self.repo.find_cleanup_pending_jobs()
        for job_id in job_ids:
            try:
                self.storage.delete_job_exports(job_id)
                self.repo.purge_job_data(job_id)
                self.repo.append_job_event(job_id, "cleanup_completed", {"at": _utc_now()})
                logger.info("Purged data for job %s", job_id)
            except Exception as exc:
                logger.error("Failed to purge job %s: %s", job_id, exc, exc_info=True)
                # Keep cleanup_pending=True so the next cleanup pass can retry the purge.
                try:
                    self.repo.append_job_event(job_id, "cleanup_failed", {"phase": "purge", "message": str(exc)})
                except Exception:
                    pass


def run() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    repo = JobRepository.from_env()
    repo.init_db()
    storage = ExportStorage.from_env()
    orchestrator = ServiceBusOrchestrator()
    worker = CleanupWorker(repo=repo, storage=storage, orchestrator=orchestrator)
    logger.info("Cleanup worker starting (interval=%ds)", POLL_INTERVAL_SECONDS)
    while True:
        logger.info("Cleanup pass starting")
        worker.reenqueue_stale_phases()
        worker.expire_ttl_jobs()
        worker.purge_pending_jobs()
        logger.info("Cleanup pass complete; sleeping %ds", POLL_INTERVAL_SECONDS)
        time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    run()
