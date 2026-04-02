"""Durable job persistence for PFCD backend."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional
from uuid import uuid4

logger = logging.getLogger(__name__)

from sqlalchemy import delete, select

from app.db import ENGINE, session_scope
from app.job_logic import _utc_now
from app.models import AgentRun, Draft, ExportPayload, InputManifest, Job, JobEvent, ReviewNotes


class JobRepository:
    def __init__(self) -> None:
        self.engine = ENGINE

    @classmethod
    def from_env(cls) -> "JobRepository":
        return cls()

    def init_db(self) -> None:
        from app.models import Base

        Base.metadata.create_all(self.engine)

    def _serialize(self, payload: Dict[str, Any]) -> str:
        return json.dumps(payload, ensure_ascii=True, separators=(",", ":"))

    def _deserialize(self, payload: str) -> Dict[str, Any]:
        return json.loads(payload) if payload else {}

    def _job_to_payload(
        self,
        job: Job,
        input_manifest: Optional[InputManifest],
        review_notes: Optional[ReviewNotes],
        drafts: List[Draft],
        agent_runs: List[AgentRun],
        exports: Optional[ExportPayload],
    ) -> Dict[str, Any]:
        draft_payload = None
        finalized_payload = None
        for draft in drafts:
            payload = self._deserialize(draft.payload)
            if draft.draft_kind == "finalized":
                finalized_payload = payload
            else:
                draft_payload = payload

        payload = {
            "job_id": job.job_id,
            "status": job.status,
            "created_at": job.created_at,
            "updated_at": job.updated_at,
            "profile_requested": job.profile_requested,
            "provider_effective": self._deserialize(job.provider_effective),
            "input_manifest": self._deserialize(input_manifest.payload) if input_manifest else {},
            "has_video": job.has_video,
            "has_audio": job.has_audio,
            "has_transcript": job.has_transcript,
            "teams_metadata": self._deserialize(job.teams_metadata),
            "agent_runs": [self._agent_run_to_dict(run) for run in agent_runs],
            "transcript_media_consistency": self._deserialize(job.transcript_media_consistency),
            "review_notes": self._deserialize(review_notes.payload) if review_notes else {"flags": [], "assumptions": []},
            "agent_signals": self._deserialize(job.agent_signals),
            "agent_review": self._deserialize(job.agent_review),
            "draft": draft_payload,
            "finalized_draft": finalized_payload,
            "speaker_resolutions": self._deserialize(job.speaker_resolutions),
            "user_saved_draft": job.user_saved_draft,
            "user_saved_at": job.user_saved_at,
            "exports": self._deserialize(exports.payload) if exports else {},
            "current_phase": job.current_phase,
            "last_completed_phase": job.last_completed_phase,
            "phase_attempt": job.phase_attempt,
            "payload_hash": job.payload_hash,
            "active_agent_run_id": job.active_agent_run_id,
            "deleted_at": job.deleted_at,
            "cleanup_pending": job.cleanup_pending,
            "ttl_expires_at": job.ttl_expires_at,
            "error": self._deserialize(job.error) if job.error else None,
        }
        return payload

    def _agent_run_to_dict(self, run: AgentRun) -> Dict[str, Any]:
        return {
            "agent_run_id": run.agent_run_id,
            "agent": run.agent,
            "model": run.model,
            "profile": run.profile,
            "status": run.status,
            "duration_ms": run.duration_ms,
            "cost_estimate_usd": run.cost_estimate_usd,
            "confidence_delta": run.confidence_delta,
            "message": run.message,
            "created_at": run.created_at,
            "updated_at": run.updated_at,
        }

    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        with session_scope() as session:
            job = session.get(Job, job_id)
            if not job:
                return None
            input_manifest = session.get(InputManifest, job_id)
            review_notes = session.get(ReviewNotes, job_id)
            drafts = session.execute(
                select(Draft).where(Draft.job_id == job_id)
            ).scalars().all()
            agent_runs = session.execute(
                select(AgentRun).where(AgentRun.job_id == job_id)
            ).scalars().all()
            exports = session.get(ExportPayload, job_id)
            return self._job_to_payload(job, input_manifest, review_notes, drafts, agent_runs, exports)

    def upsert_job(self, job_id: str, payload: Dict[str, Any]) -> None:
        logger.debug("Upserting job %s status=%s", job_id, payload.get("status"))
        with session_scope() as session:
            job = session.get(Job, job_id)
            if not job:
                job = Job(job_id=job_id)
                session.add(job)

            job.status = payload.get("status", job.status)
            job.created_at = payload.get("created_at", job.created_at or _utc_now())
            job.updated_at = payload.get("updated_at", job.updated_at or _utc_now())
            job.profile_requested = payload.get("profile_requested", job.profile_requested or "balanced")
            job.provider_effective = self._serialize(payload.get("provider_effective", {}))
            job.has_video = bool(payload.get("has_video"))
            job.has_audio = bool(payload.get("has_audio"))
            job.has_transcript = bool(payload.get("has_transcript"))
            job.teams_metadata = self._serialize(payload.get("teams_metadata", {}))
            job.transcript_media_consistency = self._serialize(payload.get("transcript_media_consistency", {}))
            job.agent_signals = self._serialize(payload.get("agent_signals", {}))
            job.agent_review = self._serialize(payload.get("agent_review", {}))
            job.speaker_resolutions = self._serialize(payload.get("speaker_resolutions", {}))
            job.user_saved_draft = bool(payload.get("user_saved_draft"))
            job.user_saved_at = payload.get("user_saved_at")
            job.current_phase = payload.get("current_phase")
            job.last_completed_phase = payload.get("last_completed_phase")
            job.phase_attempt = int(payload.get("phase_attempt", 0))
            job.payload_hash = payload.get("payload_hash")
            job.active_agent_run_id = payload.get("active_agent_run_id")
            job.deleted_at = payload.get("deleted_at")
            job.cleanup_pending = bool(payload.get("cleanup_pending"))
            job.ttl_expires_at = payload.get("ttl_expires_at")
            if payload.get("error") is not None:
                job.error = self._serialize(payload.get("error"))
            else:
                job.error = None

            input_manifest = session.get(InputManifest, job_id)
            if not input_manifest:
                input_manifest = InputManifest(job_id=job_id, payload=self._serialize(payload.get("input_manifest", {})))
                session.add(input_manifest)
            else:
                input_manifest.payload = self._serialize(payload.get("input_manifest", {}))

            review_notes = session.get(ReviewNotes, job_id)
            review_payload = payload.get("review_notes", {"flags": [], "assumptions": []})
            if not review_notes:
                review_notes = ReviewNotes(job_id=job_id, payload=self._serialize(review_payload))
                session.add(review_notes)
            else:
                review_notes.payload = self._serialize(review_payload)

            session.execute(delete(Draft).where(Draft.job_id == job_id))
            if payload.get("draft") is not None:
                draft_payload = payload["draft"]
                session.add(
                    Draft(
                        job_id=job_id,
                        draft_kind="draft",
                        payload=self._serialize(draft_payload),
                        version=int(draft_payload.get("version", 1)),
                        generated_at=draft_payload.get("generated_at"),
                        user_reconciled_at=draft_payload.get("user_reconciled_at"),
                        finalized_at=draft_payload.get("finalized_at"),
                        updated_at=payload.get("updated_at"),
                    )
                )
            if payload.get("finalized_draft") is not None:
                final_payload = payload["finalized_draft"]
                session.add(
                    Draft(
                        job_id=job_id,
                        draft_kind="finalized",
                        payload=self._serialize(final_payload),
                        version=int(final_payload.get("version", 1)),
                        generated_at=final_payload.get("generated_at"),
                        user_reconciled_at=final_payload.get("user_reconciled_at"),
                        finalized_at=final_payload.get("finalized_at"),
                        updated_at=payload.get("updated_at"),
                    )
                )

            session.execute(delete(AgentRun).where(AgentRun.job_id == job_id))
            for run in payload.get("agent_runs", []):
                session.add(
                    AgentRun(
                        agent_run_id=run.get("agent_run_id") or str(uuid4()),
                        job_id=job_id,
                        agent=run.get("agent", "unknown"),
                        model=run.get("model", "unknown"),
                        profile=run.get("profile", "balanced"),
                        status=run.get("status", "unknown"),
                        duration_ms=int(run.get("duration_ms") or 0),
                        cost_estimate_usd=float(run.get("cost_estimate_usd") or 0.0),
                        confidence_delta=float(run.get("confidence_delta") or 0.0),
                        message=run.get("message"),
                        created_at=run.get("created_at") or _utc_now(),
                        updated_at=run.get("updated_at"),
                    )
                )

            exports = session.get(ExportPayload, job_id)
            if payload.get("exports") is not None:
                exports_payload = self._serialize(payload.get("exports", {}))
                if not exports:
                    session.add(ExportPayload(job_id=job_id, payload=exports_payload))
                else:
                    exports.payload = exports_payload

    def append_job_event(self, job_id: str, event_type: str, payload: Dict[str, Any]) -> None:
        with session_scope() as session:
            session.add(
                JobEvent(
                    event_id=str(uuid4()),
                    job_id=job_id,
                    event_type=event_type,
                    payload=self._serialize(payload),
                    created_at=_utc_now(),
                )
            )
