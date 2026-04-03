"""FastAPI skeleton for PFCD Video-First v1."""

from __future__ import annotations

import copy
import json
import logging
import os
from contextlib import asynccontextmanager
from typing import Any, Dict, Optional
from uuid import uuid4

import anyio
from fastapi import APIRouter, Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse, Response
from fpdf import FPDF

logger = logging.getLogger(__name__)

from app.auth import verify_api_key
from app.job_logic import (
    DraftUpdateRequest,
    JobCreateRequest,
    JobStatus,
    ReviewSeverity,
    _utc_now,
    default_job_payload,
)
from app.repository import JobRepository
from app.servicebus import ServiceBusOrchestrator, build_message
from app.storage import ExportStorage

MAX_UPLOAD_BYTES = 500 * 1024 * 1024
ALLOWED_FORMATS = {"json", "markdown", "pdf", "docx"}
UPLOADS_DIR = os.environ.get("UPLOADS_DIR", "./storage/uploads")

JOB_REPO = JobRepository.from_env()
EXPORT_STORAGE = ExportStorage.from_env()
ORCHESTRATOR = ServiceBusOrchestrator()


@asynccontextmanager
async def _lifespan(app: FastAPI):
    await anyio.to_thread.run_sync(JOB_REPO.init_db)
    logger.info("Database initialised")
    yield


app = FastAPI(
    title="PFCD Video-First API",
    version="0.2.0",
    description="Durable job lifecycle and orchestration flow.",
    lifespan=_lifespan,
)

def _cors_origins() -> list[str]:
    raw = os.environ.get("PFCD_CORS_ORIGINS", "http://localhost:5173")
    return [o.strip() for o in raw.split(",") if o.strip()]


app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)

api_router = APIRouter(
    prefix="/api",
    dependencies=[Depends(verify_api_key)],
)


async def _repo_get_job(job_id: str) -> Optional[Dict[str, Any]]:
    return await anyio.to_thread.run_sync(JOB_REPO.get_job, job_id)


async def _repo_upsert_job(job_id: str, payload: Dict[str, Any]) -> None:
    await anyio.to_thread.run_sync(JOB_REPO.upsert_job, job_id, payload)


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
    from fpdf.enums import XPos, YPos

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=12)
    page_width = pdf.w - pdf.l_margin - pdf.r_margin

    def _row(text: str) -> None:
        pdf.set_x(pdf.l_margin)
        pdf.multi_cell(page_width, 8, text)

    pdf.cell(page_width, 10, "Process Definition Document", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(2)
    _row(f"Purpose: {draft.get('pdd', {}).get('purpose', '')}")
    _row(f"Scope: {draft.get('pdd', {}).get('scope', '')}")
    pdf.ln(2)
    pdf.set_x(pdf.l_margin)
    pdf.cell(page_width, 8, "Steps:", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    for step in draft.get("pdd", {}).get("steps", []):
        _row(f"- {step.get('id')}: {step.get('summary')}")
    pdf.ln(2)
    pdf.set_x(pdf.l_margin)
    pdf.cell(page_width, 8, "SIPOC:", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    for idx, row in enumerate(draft.get("sipoc", []), start=1):
        _row(f"{idx}. {row.get('process_step')} - anchor: {row.get('source_anchor')}")
    return bytes(pdf.output())


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
        "AZURE_SERVICE_BUS_CONNECTION_STRING",
        "AZURE_SERVICE_BUS_QUEUE_EXTRACTING",
        "AZURE_SERVICE_BUS_QUEUE_PROCESSING",
        "AZURE_SERVICE_BUS_QUEUE_REVIEWING",
        "KEYVAULT_NAME",
        "AZURE_SQL_SERVER_NAME",
        "AZURE_SQL_DATABASE_NAME",
        "AZURE_OPENAI_ACCOUNT_NAME",
        "AZURE_SPEECH_ACCOUNT_NAME",
    ]
    checks = {name: bool(os.environ.get(name)) for name in required_env}
    degraded = [name for name, present in checks.items() if not present]
    status_code = 200 if not degraded else 503
    return JSONResponse(
        content={
            "status": "ok" if not degraded else "degraded",
            "timestamp": _utc_now(),
            "environment_checks": checks,
            "missing_environment": degraded,
        },
        status_code=status_code,
    )


MIME_TO_SOURCE_TYPE: Dict[str, str] = {
    "video/mp4": "video", "video/quicktime": "video", "video/x-msvideo": "video",
    "video/webm": "video", "video/mkv": "video",
    "audio/mpeg": "audio", "audio/mp4": "audio", "audio/wav": "audio",
    "audio/ogg": "audio", "audio/webm": "audio",
    "text/plain": "transcript", "text/vtt": "transcript", "application/x-subrip": "transcript",
    "application/pdf": "document", "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "document",
    "application/msword": "document", "application/vnd.ms-powerpoint": "document",
}


@api_router.post("/upload", status_code=201)
async def upload_file(file: UploadFile = File(...)) -> Dict[str, Any]:
    upload_id = str(uuid4())
    content = await file.read()
    size_bytes = len(content)
    if size_bytes > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail=f"File exceeds 500MB limit.")

    dest_dir = os.path.join(UPLOADS_DIR, upload_id)
    await anyio.to_thread.run_sync(lambda: os.makedirs(dest_dir, exist_ok=True))
    dest_path = os.path.join(dest_dir, file.filename or "upload")
    def _write():
        with open(dest_path, "wb") as fh:
            fh.write(content)
    await anyio.to_thread.run_sync(_write)

    source_type = MIME_TO_SOURCE_TYPE.get(file.content_type or "", "document")
    return {
        "upload_id": upload_id,
        "file_name": file.filename,
        "size_bytes": size_bytes,
        "mime_type": file.content_type,
        "source_type": source_type,
        "location": dest_path,
    }


@api_router.post("/jobs", status_code=201)
async def create_job(payload: JobCreateRequest) -> Dict[str, Any]:
    if not payload.input_files:
        raise HTTPException(status_code=400, detail="At least one input file is required.")
    oversized = [
        f.file_name or f"file-{idx}"
        for idx, f in enumerate(payload.input_files)
        if f.size_bytes > MAX_UPLOAD_BYTES
    ]
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
    job = default_job_payload(payload)
    job["job_id"] = job_id
    await _repo_upsert_job(job_id, job)
    await anyio.to_thread.run_sync(
        JOB_REPO.append_job_event,
        job_id,
        "job_created",
        {"job_id": job_id, "profile": job["profile_requested"], "at": _utc_now()},
    )

    trace_id = str(uuid4())
    message = build_message(
        job_id=job_id,
        phase="extracting",
        attempt=0,
        requested_by="api",
        trace_id=trace_id,
    )
    await anyio.to_thread.run_sync(ORCHESTRATOR.enqueue, "extracting", message)
    logger.info("Job created: job_id=%s profile=%s", job_id, job["profile_requested"])
    return {"job_id": job_id, **job}


@api_router.get("/jobs/{job_id}")
async def get_job(job_id: str) -> Dict[str, Any]:
    return await _job_or_404(job_id)


@api_router.get("/jobs/{job_id}/draft")
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


@api_router.put("/jobs/{job_id}/draft")
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
    job["user_saved_at"] = _utc_now()
    job["updated_at"] = _utc_now()
    job["draft"]["user_reconciled_at"] = _utc_now()
    await _repo_upsert_job(job_id, job)
    await anyio.to_thread.run_sync(
        JOB_REPO.append_job_event,
        job_id,
        "draft_updated",
        {"job_id": job_id, "at": _utc_now()},
    )
    return {
        "job_id": job_id,
        "status": job["status"],
        "draft": job["draft"],
        "speaker_resolutions": job["speaker_resolutions"],
        "user_saved_draft": True,
    }


@api_router.post("/jobs/{job_id}/finalize")
async def finalize_job(job_id: str) -> Dict[str, Any]:
    job = await _job_or_404(job_id)
    if job["status"] == JobStatus.DELETED.value:
        raise HTTPException(status_code=410, detail="Deleted jobs cannot be finalized.")
    # Idempotent: already completed or currently finalizing — return current state.
    if job["status"] in {JobStatus.COMPLETED.value, JobStatus.FINALIZING.value}:
        return {"job_id": job_id, "status": job["status"], "exports": job["exports"]}
    if job["draft"] is None:
        raise HTTPException(status_code=409, detail="No draft available.")
    if not job["user_saved_draft"]:
        raise HTTPException(status_code=409, detail="Draft must be saved before finalize.")
    blockers = [f for f in job["review_notes"]["flags"] if f["severity"] == ReviewSeverity.BLOCKER.value]
    if blockers:
        raise HTTPException(status_code=409, detail="Blocker flags must be resolved before finalize.")

    job["status"] = JobStatus.FINALIZING.value
    job["updated_at"] = _utc_now()
    await _repo_upsert_job(job_id, job)
    await anyio.to_thread.run_sync(
        JOB_REPO.append_job_event,
        job_id,
        "finalize_started",
        {"job_id": job_id, "at": _utc_now()},
    )

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
    await anyio.to_thread.run_sync(
        JOB_REPO.append_job_event,
        job_id,
        "finalize_completed",
        {"job_id": job_id, "at": _utc_now()},
    )
    logger.info("Job finalized: job_id=%s", job_id)
    return {"job_id": job_id, "status": job["status"], "exports": job["exports"]}


@api_router.get("/jobs/{job_id}/exports/{fmt}")
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

    if not job.get("finalized_draft"):
        raise HTTPException(status_code=409, detail="Finalized draft not available; re-run finalize.")
    draft = job["finalized_draft"]
    if fmt == "json":
        return JSONResponse(
            {
                "job_id": job_id,
                "status": job["status"],
                "provider_effective": job["provider_effective"],
                "draft": draft,
                "review_notes": job["review_notes"],
                "exports_manifest": {
                    "format": "json",
                    "evidence_bundle": [],
                },
            }
        )
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


@api_router.delete("/jobs/{job_id}")
async def delete_job(job_id: str) -> Dict[str, Any]:
    job = await _job_or_404(job_id)
    if job["status"] == JobStatus.DELETED.value:
        return {"job_id": job_id, "status": JobStatus.DELETED.value}
    previous_status = job["status"]
    job["status"] = JobStatus.DELETED.value
    job["deleted_at"] = _utc_now()
    job["cleanup_pending"] = True
    job["updated_at"] = _utc_now()
    await _repo_upsert_job(job_id, job)
    await anyio.to_thread.run_sync(
        JOB_REPO.append_job_event,
        job_id,
        "deleted",
        {"job_id": job_id, "from": previous_status, "to": JobStatus.DELETED.value, "at": _utc_now()},
    )
    return {"job_id": job_id, "status": job["status"], "detail": "Job deleted; cleanup marked."}


app.include_router(api_router)


# ---------------------------------------------------------------------------
# Dev-only endpoint — NOT for production use
# ---------------------------------------------------------------------------
@app.post("/dev/jobs/{job_id}/simulate", tags=["dev"])
async def dev_simulate(job_id: str) -> Dict[str, Any]:
    """Advance a queued/processing job to needs_review with a mock draft.
    Only useful for local development without Service Bus workers."""
    job = await _repo_get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    mock_draft = {
        "pdd": {
            "purpose": "Demonstrate the PFCD review workflow end-to-end.",
            "scope": "Single process from intake to approval.",
            "roles": ["Analyst", "Reviewer", "Approver"],
            "systems": ["CRM", "Document Store"],
            "steps": [
                {
                    "id": "step-1",
                    "summary": "Analyst receives and logs intake request",
                    "actor": "Analyst",
                    "system": "CRM",
                    "input": "Email request",
                    "output": "Logged ticket",
                    "source_anchor": "00:00:30",
                },
                {
                    "id": "step-2",
                    "summary": "Reviewer validates completeness",
                    "actor": "Reviewer",
                    "system": "Document Store",
                    "input": "Logged ticket",
                    "output": "Validated document",
                    "source_anchor": "00:01:15",
                },
                {
                    "id": "step-3",
                    "summary": "Approver signs off and closes ticket",
                    "actor": "Approver",
                    "system": "CRM",
                    "input": "Validated document",
                    "output": "Approved record",
                    "source_anchor": "00:02:45",
                },
            ],
        },
        "sipoc": [
            {
                "supplier": "Client",
                "input": "Email request",
                "process_step": "Log intake",
                "output": "Ticket",
                "customer": "Analyst",
                "source_anchor": "00:00:30",
            },
            {
                "supplier": "Analyst",
                "input": "Ticket",
                "process_step": "Validate completeness",
                "output": "Validated doc",
                "customer": "Reviewer",
                "source_anchor": "00:01:15",
            },
            {
                "supplier": "Reviewer",
                "input": "Validated doc",
                "process_step": "Approve and close",
                "output": "Approved record",
                "customer": "Approver",
                "source_anchor": "00:02:45",
            },
        ],
        "confidence_summary": {
            "overall": 0.82,
            "evidence_strength": "medium",
            "source_quality": "good",
        },
        "assumptions": [],
        "generated_at": _utc_now(),
    }

    job["status"] = JobStatus.NEEDS_REVIEW.value
    job["current_phase"] = "reviewing"
    job["draft"] = mock_draft
    job["review_notes"] = {
        "flags": [
            {
                "severity": "warning",
                "code": "low_confidence_step",
                "message": "Step 3 confidence below threshold (0.65)",
                "field": "pdd.steps[2]",
            },
            {
                "severity": "info",
                "code": "speaker_unresolved",
                "message": "One speaker identity not confirmed",
                "field": None,
            },
        ]
    }
    job["user_saved_draft"] = True
    job["user_saved_at"] = _utc_now()
    job["updated_at"] = _utc_now()
    await _repo_upsert_job(job_id, job)
    return {"job_id": job_id, "status": job["status"], "detail": "Simulated needs_review state."}
