"""FastAPI skeleton for PFCD Video-First v1."""

from __future__ import annotations

import asyncio
import copy
import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import uuid4

import os
import anyio
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse, PlainTextResponse, Response
from pydantic import BaseModel, Field
from fpdf import FPDF

from app.repository import JobRepository
from app.storage import ExportStorage

MAX_UPLOAD_BYTES = 500 * 1024 * 1024
ALLOWED_FORMATS = {"json", "markdown", "pdf", "docx"}


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


PIPELINE_TASKS: Dict[str, asyncio.Task[None]] = {}
JOB_REPO = JobRepository.from_env()
EXPORT_STORAGE = ExportStorage.from_env()


@asynccontextmanager
async def _lifespan(app: FastAPI):
    JOB_REPO.init_db()
    yield


app = FastAPI(
    title="PFCD Video-First API",
    version="0.1.0",
    description="Skeleton implementation for job lifecycle and review/finalize flow.",
    lifespan=_lifespan,
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_dict(value: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


async def _repo_get_job(job_id: str) -> Optional[Dict[str, Any]]:
    return await anyio.to_thread.run_sync(JOB_REPO.get_job, job_id)


async def _repo_upsert_job(job_id: str, payload: Dict[str, Any]) -> None:
    await anyio.to_thread.run_sync(JOB_REPO.upsert_job, job_id, payload)


def _profile_config(profile: Profile) -> Dict[str, Any]:
    if profile == Profile.QUALITY:
        return {
            "profile": profile.value,
            "provider": "azure_openai",
            "model": "gpt-4o",
            "cost_cap_usd": 8.0,
        }
    return {
        "profile": profile.value,
        "provider": "azure_openai",
        "model": "gpt-4.1-mini",
        "cost_cap_usd": 4.0,
    }


def _default_job_payload(payload: JobCreateRequest) -> Dict[str, Any]:
    has_video = any(item.source_type == "video" for item in payload.input_files)
    has_audio = any(item.source_type == "audio" for item in payload.input_files)
    has_transcript = any(item.source_type == "transcript" for item in payload.input_files)
    video_audio_detected = any(
        item.source_type == "video" and bool(item.audio_detected)
        for item in payload.input_files
    )
    frame_policy = payload.frame_extraction_policy.model_dump()
    profile_conf = _profile_config(payload.profile)

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
            "verdict": "inconclusive" if not (has_video and has_transcript) else "match",
            "similarity_score": None,
        },
        "review_notes": {"flags": [], "assumptions": []},
        "agent_signals": {
            "evidence_strength": "medium",
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
        "exports": {},
    }


def _add_agent_run(job: Dict[str, Any], agent: str, profile: str, status: str, *, cost: float = 0.0,
                  confidence_delta: float = 0.0, model: str = "gpt-4.1-mini", duration_ms: int = 0,
                  message: Optional[str] = None) -> None:
    job["agent_runs"].append({
        "agent": agent,
        "model": model,
        "profile": profile,
        "status": status,
        "duration_ms": duration_ms,
        "cost_estimate_usd": cost,
        "confidence_delta": confidence_delta,
        "message": message,
    })


async def _run_pipeline(job_id: str) -> None:
    job = await _repo_get_job(job_id)
    if not job:
        return
    # TODO: Reload from DB between phases once multi-worker concurrency is enabled.
    profile = job["profile_requested"]
    profile_conf = _profile_config(Profile(profile))
    try:
        job["status"] = JobStatus.PROCESSING.value
        job["updated_at"] = _utc_now()
        await _repo_upsert_job(job_id, job)
        _add_agent_run(job, "extraction", profile_conf["profile"], "running", model=profile_conf["model"])
        await asyncio.sleep(0.1)
        _add_agent_run(job, "extraction", profile_conf["profile"], "success", model=profile_conf["model"], duration_ms=100, cost=0.4)
        await _repo_upsert_job(job_id, job)

        _add_agent_run(job, "processing", profile_conf["profile"], "running", model=profile_conf["model"])
        await asyncio.sleep(0.1)
        _add_agent_run(job, "processing", profile_conf["profile"], "success", model=profile_conf["model"], duration_ms=120, cost=1.4)
        await _repo_upsert_job(job_id, job)

        _add_agent_run(job, "reviewing", profile_conf["profile"], "running", model=profile_conf["model"])
        await asyncio.sleep(0.1)
        _build_draft(job)
        _add_agent_run(job, "reviewing", profile_conf["profile"], "success", model=profile_conf["model"], duration_ms=140, cost=0.45)

        if job["status"] != JobStatus.DELETED.value:
            blocker = any(flag["severity"] == ReviewSeverity.BLOCKER.value for flag in job["review_notes"]["flags"])
            job["status"] = JobStatus.NEEDS_REVIEW.value
            job["agent_review"]["decision"] = "blocked" if blocker else "needs_review"
            job["agent_review"]["decision_at"] = _utc_now()
            job["updated_at"] = _utc_now()
            await _repo_upsert_job(job_id, job)
    except Exception as exc:
        job["status"] = JobStatus.FAILED.value
        job["updated_at"] = _utc_now()
        job["error"] = {"message": str(exc)}
        await _repo_upsert_job(job_id, job)
    finally:
        PIPELINE_TASKS.pop(job_id, None)


def _build_draft(job: Dict[str, Any]) -> None:
    source_quality = "high"
    if not job["has_video"]:
        source_quality = "medium"
    if not job["has_transcript"] and not job["has_audio"] and job["has_video"]:
        source_quality = "low"

    flags = []
    if job["has_video"] and not job["has_audio"]:
        flags.append({
            "code": "frame_first_evidence",
            "severity": ReviewSeverity.WARNING.value,
            "message": "Video audio is not available; sequence is derived with stronger frame evidence.",
            "requires_user_action": False,
        })
    if job["has_transcript"] and not job["has_video"]:
        flags.append({
            "code": "transcript_fallback",
            "severity": ReviewSeverity.WARNING.value,
            "message": "Transcript-first fallback used. Validate actor and action assignments before finalize.",
            "requires_user_action": False,
        })

    if not job["has_video"] and not job["has_audio"] and not job["has_transcript"]:
        flags.append({
            "code": "empty_inputs",
            "severity": ReviewSeverity.BLOCKER.value,
            "message": "No supported inputs found to generate draft.",
            "requires_user_action": True,
        })

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


def _build_export_markdown(draft: Dict[str, Any]) -> str:
    if not draft:
        return "No finalized draft available."
    parts = [
        "# Process Definition Document",
        "",
        f"Purpose: {draft['pdd'].get('purpose')}",
        f"Scope: {draft['pdd'].get('scope')}",
        "## Steps",
    ]
    for step in draft["pdd"].get("steps", []):
        parts.append(f"- {step.get('id')}: {step.get('summary')}")
    parts.extend(["", "## SIPOC", ""])
    for idx, row in enumerate(draft.get("sipoc", []), start=1):
        parts.append(f"{idx}. {row.get('process_step')} — anchor: {row.get('source_anchor')}")
    return "\n".join(parts)


def _build_export_pdf(draft: Dict[str, Any]) -> bytes:
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=12)
    pdf.cell(0, 10, "Process Definition Document", ln=True)
    pdf.ln(2)
    pdf.multi_cell(0, 8, f"Purpose: {draft.get('pdd', {}).get('purpose', '')}")
    pdf.multi_cell(0, 8, f"Scope: {draft.get('pdd', {}).get('scope', '')}")
    pdf.ln(2)
    pdf.cell(0, 8, "Steps:", ln=True)
    for step in draft.get("pdd", {}).get("steps", []):
        pdf.multi_cell(0, 8, f"- {step.get('id')}: {step.get('summary')}")
    pdf.ln(2)
    pdf.cell(0, 8, "SIPOC:", ln=True)
    for idx, row in enumerate(draft.get("sipoc", []), start=1):
        pdf.multi_cell(0, 8, f"{idx}. {row.get('process_step')} — anchor: {row.get('source_anchor')}")
    return pdf.output(dest="S").encode("latin-1")


async def _job_or_404(job_id: str) -> Dict[str, Any]:
    job = await _repo_get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.get("/health")
def health() -> Dict[str, Any]:
    required_env = [
        "AZURE_STORAGE_ACCOUNT_NAME",
        "AZURE_SERVICE_BUS_NAMESPACE",
        "AZURE_SERVICE_BUS_QUEUE",
        "KEYVAULT_NAME",
        "AZURE_SQL_SERVER_NAME",
        "AZURE_SQL_DATABASE_NAME",
        "AZURE_OPENAI_ACCOUNT_NAME",
        "AZURE_SPEECH_ACCOUNT_NAME",
    ]
    checks = {name: bool(os.environ.get(name)) for name in required_env}
    degraded = [name for name, present in checks.items() if not present]
    status_code = 200 if not degraded else 503
    return JSONResponse(content={
        "status": "ok" if not degraded else "degraded",
        "timestamp": _utc_now(),
        "environment_checks": checks,
        "missing_environment": degraded,
    }, status_code=status_code)


@app.post("/api/jobs", status_code=201)
async def create_job(payload: JobCreateRequest) -> Dict[str, Any]:
    if not payload.input_files:
        raise HTTPException(status_code=400, detail="At least one input file is required.")
    oversized = [f.file_name or f"file-{idx}" for idx, f in enumerate(payload.input_files) if f.size_bytes > MAX_UPLOAD_BYTES]
    if oversized:
        raise HTTPException(
            status_code=413,
            detail={
                "code": "file_too_large",
                "message": "One or more files exceed 500MB limit.",
                "files": oversized,
                "remediation": "Trim/re-encode source media or use segmented upload in a future release.",
            },
        )

    job_id = str(uuid4())
    job = _default_job_payload(payload)
    job["job_id"] = job_id
    await _repo_upsert_job(job_id, job)
    PIPELINE_TASKS[job_id] = asyncio.create_task(_run_pipeline(job_id))
    return {"job_id": job_id, **job}


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str) -> Dict[str, Any]:
    return await _job_or_404(job_id)


@app.get("/api/jobs/{job_id}/draft")
async def get_draft(job_id: str) -> Dict[str, Any]:
    job = await _job_or_404(job_id)
    if job["draft"] is None:
        raise HTTPException(status_code=409, detail="Draft not available yet.")
    return {
        "job_id": job_id,
        "status": job["status"],
        "agent_review": job["agent_review"],
        "draft": job["draft"],
        "review_notes": job["review_notes"],
        "speaker_resolutions": job["speaker_resolutions"],
        "user_saved_draft": job["user_saved_draft"],
    }


@app.put("/api/jobs/{job_id}/draft")
async def update_draft(job_id: str, payload: DraftUpdateRequest) -> Dict[str, Any]:
    job = await _job_or_404(job_id)
    if job["draft"] is None:
        raise HTTPException(status_code=409, detail="Draft not available for update.")
    if payload.pdd is not None:
        job["draft"]["pdd"] = payload.pdd
    if payload.sipoc is not None:
        job["draft"]["sipoc"] = payload.sipoc
    if payload.assumptions is not None:
        job["draft"]["assumptions"] = payload.assumptions
    if payload.speaker_resolutions is not None:
        job["speaker_resolutions"].update(payload.speaker_resolutions)
    job["user_saved_draft"] = True
    job["updated_at"] = _utc_now()
    job["draft"]["user_reconciled_at"] = _utc_now()
    if job["status"] == JobStatus.NEEDS_REVIEW.value:
        job["status"] = JobStatus.NEEDS_REVIEW.value
    await _repo_upsert_job(job_id, job)
    return {
        "job_id": job_id,
        "status": job["status"],
        "draft": job["draft"],
        "speaker_resolutions": job["speaker_resolutions"],
        "user_saved_draft": True,
    }


@app.post("/api/jobs/{job_id}/finalize")
async def finalize_job(job_id: str) -> Dict[str, Any]:
    job = await _job_or_404(job_id)
    if job["status"] == JobStatus.DELETED.value:
        raise HTTPException(status_code=410, detail="Deleted jobs cannot be finalized.")
    if job["draft"] is None:
        raise HTTPException(status_code=409, detail="No draft available.")
    if not job["user_saved_draft"]:
        raise HTTPException(status_code=409, detail="Draft must be saved before finalize.")
    blockers = [f for f in job["review_notes"]["flags"] if f["severity"] == ReviewSeverity.BLOCKER.value]
    if blockers:
        raise HTTPException(status_code=409, detail="Blocker flags must be resolved before finalize.")
    if job["status"] == JobStatus.COMPLETED.value:
        return {"job_id": job_id, "status": job["status"], "exports": job["exports"]}

    job["status"] = JobStatus.FINALIZING.value
    job["updated_at"] = _utc_now()
    job["finalized_draft"] = copy.deepcopy(job["draft"])
    job["finalized_draft"]["finalized_at"] = _utc_now()
    exports_payload = {
        "job_id": job_id,
        "status": JobStatus.COMPLETED.value,
        "provider_effective": job["provider_effective"],
        "draft": job["finalized_draft"],
        "review_notes": job["review_notes"],
        "exports_manifest": {"format": "json", "evidence_bundle": []},
    }
    json_bytes = json.dumps(exports_payload, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    markdown_bytes = _build_export_markdown(job["finalized_draft"]).encode("utf-8")
    pdf_bytes = _build_export_pdf(job["finalized_draft"])
    docx_bytes = f"PFCD DOCX placeholder for {job_id}\n".encode("utf-8")

    json_meta = EXPORT_STORAGE.save_bytes(job_id, "json", json_bytes, "application/json")
    md_meta = EXPORT_STORAGE.save_bytes(job_id, "markdown", markdown_bytes, "text/markdown; charset=utf-8")
    pdf_meta = EXPORT_STORAGE.save_bytes(job_id, "pdf", pdf_bytes, "application/pdf", download_name=f"pdd-{job_id}.pdf")
    docx_meta = EXPORT_STORAGE.save_bytes(job_id, "docx", docx_bytes, "text/plain; charset=utf-8", download_name=f"pdd-{job_id}.docx")

    job["exports"] = {
        "json": json_meta.__dict__,
        "markdown": md_meta.__dict__,
        "pdf": pdf_meta.__dict__,
        "docx": docx_meta.__dict__,
        "endpoints": {
            "json": f"/api/jobs/{job_id}/exports/json",
            "markdown": f"/api/jobs/{job_id}/exports/markdown",
            "pdf": f"/api/jobs/{job_id}/exports/pdf",
            "docx": f"/api/jobs/{job_id}/exports/docx",
        },
    }
    job["status"] = JobStatus.COMPLETED.value
    job["updated_at"] = _utc_now()
    await _repo_upsert_job(job_id, job)
    return {"job_id": job_id, "status": job["status"], "exports": job["exports"]}


@app.get("/api/jobs/{job_id}/exports/{fmt}")
async def get_export(job_id: str, fmt: str):
    job = await _job_or_404(job_id)
    if fmt.lower() not in ALLOWED_FORMATS:
        raise HTTPException(status_code=400, detail=f"Unsupported export format: {fmt}")
    if job["status"] != JobStatus.COMPLETED.value:
        raise HTTPException(status_code=409, detail="Finalize first to generate exports.")

    meta = job.get("exports", {}).get(fmt)
    if isinstance(meta, dict) and meta.get("location"):
        content = EXPORT_STORAGE.load_bytes(meta)
        headers = {}
        if meta.get("download_name"):
            headers["Content-Disposition"] = f'attachment; filename="{meta["download_name"]}"'
        return Response(content=content, media_type=meta.get("content_type", "application/octet-stream"), headers=headers)

    draft = job["finalized_draft"] or {}
    if fmt == "json":
        return JSONResponse({
            "job_id": job_id,
            "status": job["status"],
            "provider_effective": job["provider_effective"],
            "draft": draft,
            "review_notes": job["review_notes"],
            "exports_manifest": {
                "format": "json",
                "evidence_bundle": [],
            },
        })
    if fmt == "markdown":
        return PlainTextResponse(_build_export_markdown(draft))
    if fmt == "pdf":
        return Response(
            content=_build_export_pdf(draft),
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="pdd-{job_id}.pdf"'},
        )
    return Response(
        content=f"PFCD DOCX placeholder for {job_id}\n".encode("utf-8"),
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="pdd-{job_id}.docx"'},
    )


@app.delete("/api/jobs/{job_id}")
async def delete_job(job_id: str) -> Dict[str, Any]:
    job = await _job_or_404(job_id)
    if job["status"] == JobStatus.DELETED.value:
        return {"job_id": job_id, "status": JobStatus.DELETED.value}
    task = PIPELINE_TASKS.get(job_id)
    if task is not None and not task.done():
        task.cancel()
    job["status"] = JobStatus.DELETED.value
    job["deleted_at"] = _utc_now()
    job["cleanup_pending"] = True
    job["updated_at"] = _utc_now()
    await _repo_upsert_job(job_id, job)
    return {"job_id": job_id, "status": job["status"], "detail": "Job deleted; cleanup marked."}
