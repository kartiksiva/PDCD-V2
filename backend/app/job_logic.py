"""Shared job logic for PFCD backend."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    NEEDS_REVIEW = "needs_review"
    FINALIZING = "finalizing"
    COMPLETED = "completed"
    FAILED = "failed"
    EXPIRED = "expired"
    DELETED = "deleted"


class Profile(str, Enum):
    BALANCED = "balanced"
    QUALITY = "quality"


class ReviewSeverity(str, Enum):
    BLOCKER = "blocker"
    WARNING = "warning"
    INFO = "info"


class FrameExtractionPolicy(BaseModel):
    sample_interval_sec: int = 5
    scene_change_threshold: float = 0.68
    ocr_enabled: bool = True
    ocr_trigger: str = "scene_change_only"
    frame_anchor_format: str = "timestamp_range"


class InputFile(BaseModel):
    source_type: str
    document_type: str = "video"
    file_name: Optional[str] = None
    size_bytes: int = Field(default=0, ge=0)
    mime_type: Optional[str] = None
    audio_detected: Optional[bool] = None
    audio_declared: Optional[bool] = None


class JobCreateRequest(BaseModel):
    profile: Profile = Profile.BALANCED
    input_files: List[InputFile]
    teams_metadata: Optional[Dict[str, Any]] = None
    frame_extraction_policy: FrameExtractionPolicy = FrameExtractionPolicy()


class DraftUpdateRequest(BaseModel):
    pdd: Optional[Dict[str, Any]] = None
    sipoc: Optional[List[Dict[str, Any]]] = None
    assumptions: Optional[List[str]] = None
    speaker_resolutions: Optional[Dict[str, str]] = None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _utc_in_days(days: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


def _safe_dict(value: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _default_openai_deployment() -> str:
    # Prefer explicit env config from App Service settings; fall back to the
    # currently provisioned deployment name in Azure OpenAI.
    return (
        os.environ.get("AZURE_OPENAI_DEPLOYMENT_NAME")
        or os.environ.get("AZURE_OPENAI_DEPLOYMENT")
        or "gpt-4o-mini"
    )


def profile_config(profile: Profile) -> Dict[str, Any]:
    deployment = _default_openai_deployment()
    if profile == Profile.QUALITY:
        return {
            "profile": profile.value,
            "provider": "azure_openai",
            "model": deployment,
            "cost_cap_usd": 8.0,
        }
    return {
        "profile": profile.value,
        "provider": "azure_openai",
        "model": deployment,
        "cost_cap_usd": 4.0,
    }


def default_job_payload(payload: JobCreateRequest) -> Dict[str, Any]:
    has_video = any(item.source_type == "video" for item in payload.input_files)
    has_audio = any(item.source_type == "audio" for item in payload.input_files)
    has_transcript = any(item.source_type == "transcript" for item in payload.input_files)
    video_audio_detected = any(
        item.source_type == "video" and bool(item.audio_detected)
        for item in payload.input_files
    )
    frame_policy = payload.frame_extraction_policy.model_dump()
    profile_conf = profile_config(payload.profile)

    return {
        "status": JobStatus.QUEUED.value,
        "created_at": _utc_now(),
        "updated_at": _utc_now(),
        "profile_requested": payload.profile.value,
        "provider_effective": {
            "provider": "azure_openai",
            "deployment": profile_conf["model"],
            "profile": profile_conf["profile"],
            "cost_cap_usd": profile_conf["cost_cap_usd"],
        },
        "input_manifest": {
            "video": {
                "audio_detected": video_audio_detected,
                "audio_declared": any(
                    item.source_type == "video" and bool(item.audio_declared)
                    for item in payload.input_files
                ),
                "frame_extraction_policy": frame_policy,
            },
            "inputs": [item.model_dump() for item in payload.input_files],
            "source_types": sorted({item.source_type for item in payload.input_files}),
            "duration_hint_sec": None,
            "input_manifest_version": 1,
            "transcript_declared_vs_detected": {
                "declared": has_transcript,
                "detected": has_transcript,
            },
        },
        "has_video": has_video,
        "has_audio": has_audio,
        "has_transcript": has_transcript,
        "teams_metadata": _safe_dict(payload.teams_metadata),
        "agent_runs": [],
        "transcript_media_consistency": {
            # Seeded as "inconclusive"; run_anchor_alignment will compute the
            # real verdict from anchor-validation results during extraction.
            "verdict": "inconclusive",
            "similarity_score": None,
        },
        "review_notes": {"flags": [], "assumptions": []},
        "agent_signals": {
            "evidence_strength": None,  # set authoritatively by reviewing agent
            "alignment": None,
        },
        "agent_review": {
            "decision": None,
            "decision_at": None,
            "reviewer": "review_agent_v1",
        },
        "draft": None,
        "finalized_draft": None,
        "speaker_resolutions": {},
        "user_saved_draft": False,
        "user_saved_at": None,
        "exports": {},
        "current_phase": None,
        "last_completed_phase": None,
        "phase_attempt": 0,
        "payload_hash": None,
        "active_agent_run_id": None,
        "deleted_at": None,
        "cleanup_pending": False,
        "ttl_expires_at": _utc_in_days(7),
        "error": None,
    }


def add_agent_run(
    job: Dict[str, Any],
    agent: str,
    profile: str,
    status: str,
    *,
    cost: float = 0.0,
    confidence_delta: float = 0.0,
    model: str = "gpt-4o-mini",
    duration_ms: int = 0,
    message: Optional[str] = None,
) -> str:
    run_id = str(uuid4())
    job["agent_runs"].append(
        {
            "agent_run_id": run_id,
            "agent": agent,
            "model": model,
            "profile": profile,
            "status": status,
            "duration_ms": duration_ms,
            "cost_estimate_usd": cost,
            "confidence_delta": confidence_delta,
            "message": message,
            "created_at": _utc_now(),
        }
    )
    job["active_agent_run_id"] = run_id
    return run_id


def load_transcript_text(job: Dict[str, Any], storage: Any) -> Optional[str]:
    """Load transcript text from storage. Returns None if no transcript input."""
    for inp in job.get("input_manifest", {}).get("inputs", []):
        if inp.get("source_type") == "transcript" and inp.get("file_name"):
            meta = {
                "location": f"{job['job_id']}/inputs/{inp['file_name']}",
                "content_type": "text/plain",
            }
            try:
                return storage.load_bytes(meta).decode("utf-8")
            except Exception:
                return None
    # Fallback: inline transcript_text injected for testing
    return job.get("_transcript_text_inline")


def build_draft(job: Dict[str, Any]) -> None:
    source_quality = "high"
    if not job["has_video"]:
        source_quality = "medium"
    if not job["has_transcript"] and not job["has_audio"] and job["has_video"]:
        source_quality = "low"

    flags = []
    if job["has_video"] and not job["has_audio"]:
        flags.append(
            {
                "code": "frame_first_evidence",
                "severity": ReviewSeverity.WARNING.value,
                "message": "Video audio is not available; sequence is derived with stronger frame evidence.",
                "requires_user_action": False,
            }
        )
    if job["has_transcript"] and not job["has_video"]:
        flags.append(
            {
                "code": "transcript_fallback",
                "severity": ReviewSeverity.WARNING.value,
                "message": "Transcript-first fallback used. Validate actor and action assignments before finalize.",
                "requires_user_action": False,
            }
        )

    if not job["has_video"] and not job["has_audio"] and not job["has_transcript"]:
        flags.append(
            {
                "code": "empty_inputs",
                "severity": ReviewSeverity.BLOCKER.value,
                "message": "No supported inputs found to generate draft.",
                "requires_user_action": True,
            }
        )

    if flags:
        job["review_notes"]["flags"] = flags
        if any(f["severity"] == ReviewSeverity.BLOCKER.value for f in flags):
            job["agent_signals"]["evidence_strength"] = "insufficient"

    pdd_steps = [
        {
            "id": "step-01",
            "summary": "Process starts with first verifiable operator action.",
            "actor": "Unknown Speaker",
            "system": "Unknown",
            "input": "Initial project trigger",
            "output": "Context prepared",
            "exception": None,
            "source_anchors": [
                {
                    "source": "frame",
                    "anchor": "00:00:00-00:00:10",
                    "confidence": 0.62,
                }
            ],
        }
    ]
    sipoc_row = {
        "step_anchor": ["step-01"],
        "source_anchor": "00:00:00-00:00:10",
        "supplier": "Operator",
        "input": "Task request",
        "process_step": "Start process and capture evidence",
        "output": "Process step list available",
        "customer": "Operations lead",
        "anchor_missing_reason": None,
    }
    job["draft"] = {
        "pdd": {
            "purpose": "Extract structured process steps from supplied evidence.",
            "scope": "Captured workflow from first-class evidence sources only.",
            "triggers": ["Recorded operational request"],
            "preconditions": ["At least one source is available"],
            "steps": pdd_steps,
            "roles": ["Unknown Speaker"],
            "systems": ["Recorded system context"],
            "business_rules": ["Use evidence-first reconstruction"],
            "exceptions": [],
            "outputs": ["Draft PDD and SIPOC"],
            "metrics": {
                "coverage": source_quality,
                "confidence": 0.72 if source_quality == "high" else 0.58,
            },
            "risks": [flag["code"] for flag in flags],
        },
        "sipoc": [sipoc_row],
        "assumptions": ["Evidence confidence is bounded by source availability."],
        "confidence_summary": {
            "overall": 0.72 if source_quality == "high" else 0.58,
            "source_quality": source_quality,
            "evidence_strength": job["agent_signals"]["evidence_strength"],
        },
        "generated_at": _utc_now(),
        "version": 1,
    }
    job["agent_signals"]["alignment"] = job["transcript_media_consistency"]["verdict"]
