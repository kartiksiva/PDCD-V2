"""Shared job logic for PFCD backend."""

from __future__ import annotations

import os
import logging
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class JobStatus(str, Enum):
    QUEUED = "queued"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
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
    upload_id: Optional[str] = None
    storage_key: Optional[str] = None
    audio_detected: Optional[bool] = None
    audio_declared: Optional[bool] = None


class JobCreateRequest(BaseModel):
    profile: Profile = Profile.BALANCED
    input_files: List[InputFile]
    teams_metadata: Optional[Dict[str, Any]] = None
    frame_extraction_policy: FrameExtractionPolicy = FrameExtractionPolicy()


class DraftUpdateRequest(BaseModel):
    draft_version: int
    pdd: Optional[Dict[str, Any]] = None
    sipoc: Optional[List[Dict[str, Any]]] = None
    assumptions: Optional[List[str]] = None
    speaker_resolutions: Optional[Dict[str, str]] = None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _utc_in_days(days: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


def _job_ttl_days() -> int:
    raw = os.environ.get("PFCD_JOB_TTL_DAYS", "7").strip()
    try:
        days = int(raw)
    except ValueError:
        return 7
    return max(1, days)


def _safe_dict(value: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _provider_name() -> str:
    return os.environ.get("PFCD_PROVIDER", "azure_openai").strip().lower() or "azure_openai"


def cost_confirmation_profiles() -> set[str]:
    raw = os.environ.get("PFCD_COST_CONFIRM_PROFILES", "quality")
    return {token.strip().lower() for token in raw.split(",") if token.strip()}


def requires_cost_confirmation(profile: Profile | str | None) -> bool:
    resolved = _coerce_profile(profile)
    return resolved.value in cost_confirmation_profiles()


def _coerce_profile(profile: Profile | str | None) -> Profile:
    if isinstance(profile, Profile):
        return profile
    if isinstance(profile, str):
        normalized = profile.strip().lower()
        if normalized == Profile.QUALITY.value:
            return Profile.QUALITY
    return Profile.BALANCED


def _default_chat_model() -> str:
    deployment = os.environ.get("AZURE_OPENAI_CHAT_DEPLOYMENT_NAME")
    if deployment:
        return deployment

    deployment_name_alias = os.environ.get("AZURE_OPENAI_DEPLOYMENT_NAME")
    if deployment_name_alias:
        logger.warning(
            "AZURE_OPENAI_DEPLOYMENT_NAME is deprecated; prefer AZURE_OPENAI_CHAT_DEPLOYMENT_NAME."
        )
        return deployment_name_alias

    deployment_alias = os.environ.get("AZURE_OPENAI_DEPLOYMENT")
    if deployment_alias:
        logger.warning(
            "AZURE_OPENAI_DEPLOYMENT is deprecated; prefer AZURE_OPENAI_CHAT_DEPLOYMENT_NAME."
        )
        return deployment_alias

    raise RuntimeError(
        "Azure OpenAI deployment is not configured. Set AZURE_OPENAI_CHAT_DEPLOYMENT_NAME "
        "(preferred) or legacy AZURE_OPENAI_DEPLOYMENT_NAME / AZURE_OPENAI_DEPLOYMENT."
    )


def _profile_chat_model(profile: Profile) -> str:
    provider = _provider_name()
    if provider == "openai":
        if profile == Profile.QUALITY:
            return os.environ.get("OPENAI_CHAT_MODEL_QUALITY", "gpt-4o")
        return os.environ.get("OPENAI_CHAT_MODEL_BALANCED", "gpt-4o-mini")

    if profile == Profile.QUALITY:
        return (
            os.environ.get("AZURE_OPENAI_DEPLOYMENT_QUALITY")
            or _default_chat_model()
        )
    return (
        os.environ.get("AZURE_OPENAI_DEPLOYMENT_BALANCED")
        or _default_chat_model()
    )


def get_vision_model(profile: Profile | str | None) -> str:
    resolved_profile = _coerce_profile(profile)
    provider = _provider_name()
    if provider == "openai":
        default_model = "gpt-4o-mini"
        if resolved_profile == Profile.QUALITY:
            return (
                os.environ.get("OPENAI_VISION_MODEL_QUALITY")
                or os.environ.get("OPENAI_VISION_MODEL")
                or "gpt-4o"
            )
        return (
            os.environ.get("OPENAI_VISION_MODEL_BALANCED")
            or os.environ.get("OPENAI_VISION_MODEL")
            or default_model
        )

    if resolved_profile == Profile.QUALITY:
        return (
            os.environ.get("AZURE_OPENAI_VISION_DEPLOYMENT_QUALITY")
            or os.environ.get("AZURE_OPENAI_VISION_DEPLOYMENT")
            or ""
        )
    return (
        os.environ.get("AZURE_OPENAI_VISION_DEPLOYMENT_BALANCED")
        or os.environ.get("AZURE_OPENAI_VISION_DEPLOYMENT")
        or ""
    )


def get_transcription_target(profile: Profile | str | None) -> Dict[str, str]:
    # Profile is accepted for parity with chat/vision routing and future
    # per-profile transcription targets.
    _ = _coerce_profile(profile)
    provider = _provider_name()
    if provider == "openai":
        return {
            "provider": "openai",
            "service": "openai_whisper",
            "model": os.environ.get("OPENAI_TRANSCRIPTION_MODEL", "whisper-1"),
        }
    return {
        "provider": "azure_openai",
        "service": "azure_openai_whisper",
        "model": os.environ.get("AZURE_OPENAI_WHISPER_DEPLOYMENT", "whisper"),
    }


def profile_config(profile: Profile) -> Dict[str, Any]:
    provider = _provider_name()
    chat_model = _profile_chat_model(profile)
    vision_model = get_vision_model(profile)
    transcription = get_transcription_target(profile)
    if profile == Profile.QUALITY:
        return {
            "profile": profile.value,
            "provider": provider,
            "model": chat_model,
            "chat_model": chat_model,
            "vision_model": vision_model,
            "transcription": transcription,
            "cost_cap_usd": 8.0,
        }
    return {
        "profile": profile.value,
        "provider": provider,
        "model": chat_model,
        "chat_model": chat_model,
        "vision_model": vision_model,
        "transcription": transcription,
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
        "version": 1,
        "status": JobStatus.QUEUED.value,
        "created_at": _utc_now(),
        "updated_at": _utc_now(),
        "profile_requested": payload.profile.value,
        "provider_effective": {
            "provider": profile_conf["provider"],
            "deployment": profile_conf["chat_model"],
            "chat_model": profile_conf["chat_model"],
            "profile": profile_conf["profile"],
            "cost_cap_usd": profile_conf["cost_cap_usd"],
            "transcription": profile_conf["transcription"],
            "vision_model": profile_conf["vision_model"],
            "phase_resolved": {},
        },
        "input_manifest": {
            "video": {
                "audio_detected": video_audio_detected,
                "audio_declared": any(
                    item.source_type == "video" and bool(item.audio_declared)
                    for item in payload.input_files
                ),
                "storage_key": next(
                    (item.storage_key for item in payload.input_files if item.source_type == "video" and item.storage_key),
                    None,
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
        "extracted_facts": {},
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
        "ttl_expires_at": _utc_in_days(_job_ttl_days()),
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
    model: str = "gpt-4.1",
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


def update_agent_run(
    job: Dict[str, Any],
    run_id: Optional[str],
    *,
    status: str,
    duration_ms: int,
    cost: float,
    message: Optional[str] = None,
) -> None:
    if not run_id:
        return
    for run in job.get("agent_runs", []):
        if run.get("agent_run_id") == run_id:
            run["status"] = status
            run["duration_ms"] = int(duration_ms)
            run["cost_estimate_usd"] = float(cost)
            run["message"] = message
            run["updated_at"] = _utc_now()
            return


def model_pricing_per_million(deployment: str) -> Tuple[float, float]:
    normalized = (deployment or "").lower().strip()
    if "gpt-4.1-mini" in normalized:
        return (0.40, 1.60)
    if "gpt-4.1" in normalized:
        return (2.00, 8.00)
    if "gpt-4o-mini" in normalized:
        return (0.15, 0.60)
    return (0.15, 0.60)


def estimate_cost_usd(deployment: str, prompt_tokens: int, completion_tokens: int) -> float:
    prompt_price, completion_price = model_pricing_per_million(deployment)
    return (prompt_tokens * prompt_price + completion_tokens * completion_price) / 1_000_000


def apply_cost_tracking_and_cap_warning(job: Dict[str, Any], *, phase: str, cost: float, cap_usd: float) -> None:
    agent_signals = job.setdefault("agent_signals", {})
    tracker = agent_signals.setdefault("cost_tracking", {"total_estimated_usd": 0.0, "warnings": []})
    tracker["total_estimated_usd"] = float(tracker.get("total_estimated_usd", 0.0)) + float(cost)
    total = tracker["total_estimated_usd"]
    if total <= float(cap_usd):
        return
    code = "cost_cap_exceeded"
    if any(flag.get("code") == code for flag in job.get("review_notes", {}).get("flags", [])):
        return
    warning = {
        "code": code,
        "severity": ReviewSeverity.WARNING.value,
        "message": (
            f"Estimated processing cost ${total:.4f} exceeded profile cap ${float(cap_usd):.2f} "
            f"during phase '{phase}'."
        ),
        "requires_user_action": False,
    }
    job.setdefault("review_notes", {}).setdefault("flags", []).append(warning)
    tracker.setdefault("warnings", []).append(
        {"code": code, "phase": phase, "at": _utc_now(), "total_estimated_usd": round(total, 6)}
    )


_UPLOADS_DIR = os.environ.get("UPLOADS_DIR", "./storage/uploads")


def _is_safe_storage_key(key: str) -> bool:
    """Return True if *key* is a relative path within the uploads directory."""
    abs_key = os.path.abspath(key)
    abs_dir = os.path.abspath(_UPLOADS_DIR) + os.sep
    return abs_key.startswith(abs_dir)


def load_transcript_text(job: Dict[str, Any], storage: Any) -> Optional[str]:
    """Load transcript text from storage. Returns None if no transcript input."""
    for inp in job.get("input_manifest", {}).get("inputs", []):
        if inp.get("source_type") == "transcript":
            if inp.get("storage_key"):
                key = inp["storage_key"]
                if not _is_safe_storage_key(key):
                    logger.warning("Rejecting transcript storage_key outside uploads dir: %r", key)
                    return None
                try:
                    with open(key, "rb") as handle:
                        return handle.read().decode("utf-8")
                except Exception:
                    return None
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
        "draft_source": "stub",
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
