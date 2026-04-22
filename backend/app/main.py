"""FastAPI skeleton for PFCD Video-First v1."""

from __future__ import annotations

import copy
import json
import logging
import os
import tempfile
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse
from uuid import uuid4

import anyio
from fastapi import APIRouter, Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse, Response
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

from app.auth import verify_api_key
from app.export_builder import (
    build_evidence_bundle,
    build_export_docx,
    build_export_markdown,
    build_export_pdf,
)
from app.job_logic import (
    DraftUpdateRequest,
    JobCreateRequest,
    JobStatus,
    ReviewSeverity,
    requires_cost_confirmation,
    _utc_now,
    default_job_payload,
)
from app.repository import ConcurrentModificationError, JobRepository
from app.servicebus import ServiceBusOrchestrator, build_message
from app.storage import ExportStorage, read_frame_bytes

MAX_UPLOAD_BYTES = 500 * 1024 * 1024
ALLOWED_FORMATS = {"json", "markdown", "pdf", "docx"}
UPLOADS_DIR = os.environ.get("UPLOADS_DIR", "./storage/uploads")
UPLOAD_META_DIR = os.environ.get("UPLOAD_META_DIR", os.path.join(UPLOADS_DIR, "_manifest"))
UPLOAD_SAS_EXPIRY_MINUTES = max(1, int(os.environ.get("PFCD_UPLOAD_SAS_EXPIRY_MINUTES", "30")))
UPLOAD_CONTAINER = os.environ.get("AZURE_STORAGE_CONTAINER_UPLOADS", "uploads")

JOB_REPO = JobRepository.from_env()
EXPORT_STORAGE = ExportStorage.from_env()
ORCHESTRATOR = ServiceBusOrchestrator()


@asynccontextmanager
async def _lifespan(app: FastAPI):
    await anyio.to_thread.run_sync(JOB_REPO.init_db)
    logger.info("Database initialised")
    try:
        yield
    finally:
        ORCHESTRATOR.close()


app = FastAPI(
    title="PFCD Video-First API",
    version="0.2.0",
    description="Durable job lifecycle and orchestration flow.",
    lifespan=_lifespan,
)

def _cors_origins() -> list[str]:
    raw = os.environ.get("PFCD_CORS_ORIGINS", "http://localhost:5173")
    env = os.environ.get("PFCD_ENV", "development").strip().lower()
    origins = [o.strip() for o in raw.split(",") if o.strip()]
    validated = []
    for origin in origins:
        parsed = urlparse(origin)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise RuntimeError(f"Invalid CORS origin: {origin!r}")
        if parsed.scheme == "http":
            logger.warning("Configured non-HTTPS CORS origin: %s", origin)
            if env == "production":
                raise RuntimeError("HTTPS origins are required for PFCD_CORS_ORIGINS in production.")
        validated.append(origin)
    return validated


def _resolve_upload_path(upload_id: str, file_name: str | None) -> str:
    file_part = file_name or "upload"
    return os.path.join(UPLOADS_DIR, upload_id, file_part)


def _upload_manifest_path(upload_id: str) -> str:
    safe_id = os.path.basename(upload_id.replace("\\", "/")).strip()
    if not safe_id or safe_id != upload_id:
        raise ValueError(f"Invalid upload id: {upload_id!r}")
    return os.path.join(UPLOAD_META_DIR, f"{safe_id}.json")


def _parse_iso8601(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _save_upload_manifest(upload_id: str, payload: Dict[str, Any]) -> None:
    os.makedirs(UPLOAD_META_DIR, exist_ok=True)
    with open(_upload_manifest_path(upload_id), "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=True, separators=(",", ":"))


def _load_upload_manifest(upload_id: str) -> Dict[str, Any] | None:
    manifest_path = _upload_manifest_path(upload_id)
    if not os.path.isfile(manifest_path):
        return None
    with open(manifest_path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _update_upload_manifest(upload_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
    manifest = _load_upload_manifest(upload_id)
    if not manifest:
        raise HTTPException(status_code=404, detail=f"Upload id {upload_id!r} was not found.")
    manifest.update(updates)
    _save_upload_manifest(upload_id, manifest)
    return manifest


def _parse_storage_connection_string() -> Dict[str, str]:
    raw = os.environ.get("AZURE_STORAGE_CONNECTION_STRING", "")
    parts: Dict[str, str] = {}
    for chunk in raw.split(";"):
        if "=" not in chunk:
            continue
        key, value = chunk.split("=", 1)
        parts[key] = value
    return parts


def _build_blob_upload_contract(job_id: str, upload_id: str, safe_name: str, mime_type: str) -> Dict[str, Any] | None:
    try:
        from azure.storage.blob import BlobSasPermissions, BlobServiceClient, generate_blob_sas
    except Exception:
        return None

    conn = os.environ.get("AZURE_STORAGE_CONNECTION_STRING")
    conn_parts = _parse_storage_connection_string()
    account_name = conn_parts.get("AccountName") or os.environ.get("AZURE_STORAGE_ACCOUNT_NAME")
    account_key = conn_parts.get("AccountKey")
    if not conn or not account_name or not account_key:
        return None

    blob_name = f"{job_id}/{upload_id}/{safe_name}"
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=UPLOAD_SAS_EXPIRY_MINUTES)
    blob_service = BlobServiceClient.from_connection_string(conn)
    container_client = blob_service.get_container_client(UPLOAD_CONTAINER)
    try:
        container_client.create_container()
    except Exception:
        pass

    sas_token = generate_blob_sas(
        account_name=account_name,
        container_name=UPLOAD_CONTAINER,
        blob_name=blob_name,
        account_key=account_key,
        permission=BlobSasPermissions(create=True, write=True),
        expiry=expires_at,
    )
    blob_client = blob_service.get_blob_client(UPLOAD_CONTAINER, blob_name)
    return {
        "mode": "blob",
        "storage_key": blob_name,
        "upload": {
            "method": "PUT",
            "url": f"{blob_client.url}?{sas_token}",
            "headers": {
                "x-ms-blob-type": "BlockBlob",
                "Content-Type": mime_type,
            },
            "requires_api_auth": False,
        },
        "expires_at": expires_at.isoformat(),
    }


def _blob_upload_exists(blob_name: str) -> bool:
    try:
        from azure.storage.blob import BlobServiceClient
    except Exception:
        return False
    conn = os.environ.get("AZURE_STORAGE_CONNECTION_STRING")
    if not conn:
        return False
    try:
        blob_service = BlobServiceClient.from_connection_string(conn)
        blob_client = blob_service.get_blob_client(UPLOAD_CONTAINER, blob_name)
        blob_client.get_blob_properties()
        return True
    except Exception:
        return False


def _build_local_upload_contract(upload_id: str, safe_name: str, mime_type: str) -> Dict[str, Any]:
    storage_key = _resolve_upload_path(upload_id, safe_name)
    return {
        "mode": "local_api",
        "storage_key": storage_key,
        "upload": {
            "method": "PUT",
            "url": f"/api/uploads/{upload_id}/content",
            "headers": {
                "Content-Type": mime_type,
            },
            "requires_api_auth": True,
        },
        "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=UPLOAD_SAS_EXPIRY_MINUTES)).isoformat(),
    }


def _resolve_input_files(payload: JobCreateRequest) -> JobCreateRequest:
    resolved_inputs = []
    for item in payload.input_files:
        resolved = item.model_copy(deep=True)
        if resolved.upload_id:
            manifest = _load_upload_manifest(resolved.upload_id)
            if manifest:
                if manifest.get("mode") == "blob":
                    storage_key = manifest.get("storage_key")
                    if not storage_key or not _blob_upload_exists(storage_key):
                        raise HTTPException(
                            status_code=400,
                            detail=f"input_files upload_id {resolved.upload_id!r} has no uploaded blob content.",
                        )
                else:
                    storage_key = manifest.get("storage_key")
                    if not storage_key or not os.path.isfile(storage_key):
                        raise HTTPException(
                            status_code=400,
                            detail=f"input_files upload_id {resolved.upload_id!r} has no uploaded local content.",
                        )
                resolved.storage_key = storage_key
                if not resolved.file_name:
                    resolved.file_name = manifest.get("file_name")
                if not resolved.size_bytes:
                    resolved.size_bytes = int(manifest.get("size_bytes") or 0)
                if not resolved.mime_type:
                    resolved.mime_type = manifest.get("mime_type")
                resolved_inputs.append(resolved)
                continue

            # Backward-compatible fallback for legacy /api/upload path.
            legacy_storage_key = _resolve_upload_path(resolved.upload_id, resolved.file_name)
            if not os.path.isfile(legacy_storage_key):
                raise HTTPException(
                    status_code=400,
                    detail=f"input_files upload_id {resolved.upload_id!r} does not reference an existing upload.",
                )
            resolved.storage_key = legacy_storage_key
            if not resolved.file_name:
                resolved.file_name = os.path.basename(legacy_storage_key)
            if not resolved.size_bytes:
                resolved.size_bytes = os.path.getsize(legacy_storage_key)
        resolved_inputs.append(resolved)
    return payload.model_copy(update={"input_files": resolved_inputs})


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
    try:
        await anyio.to_thread.run_sync(JOB_REPO.upsert_job, job_id, payload)
    except ConcurrentModificationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


def _resolve_frame_bytes_map(evidence_bundle: Dict[str, Any]) -> Dict[str, bytes]:
    frame_bytes_map: Dict[str, bytes] = {}
    for capture in evidence_bundle.get("frame_captures") or []:
        key = capture.get("storage_key", "")
        if not key:
            continue
        frame_bytes = read_frame_bytes(key)
        if frame_bytes:
            frame_bytes_map[key] = frame_bytes
    return frame_bytes_map


def _safe_upload_name(filename: str | None) -> str:
    candidate = os.path.basename((filename or "upload").replace("\\", "/")).strip()
    candidate = candidate.lstrip(".")
    return candidate or "upload"



async def _job_or_404(job_id: str) -> Dict[str, Any]:
    job = await _repo_get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.get("/health")
def health() -> Dict[str, Any]:
    required_env = [
        "DATABASE_URL",
        "AZURE_STORAGE_ACCOUNT_NAME",
        "AZURE_SERVICE_BUS_NAMESPACE",
        "AZURE_SERVICE_BUS_CONNECTION_STRING",
        "AZURE_SERVICE_BUS_QUEUE_EXTRACTING",
        "AZURE_SERVICE_BUS_QUEUE_PROCESSING",
        "AZURE_SERVICE_BUS_QUEUE_REVIEWING",
        "KEYVAULT_NAME",
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


def _required_readiness_env() -> List[str]:
    return [
        "DATABASE_URL",
        "AZURE_STORAGE_CONNECTION_STRING",
        "AZURE_SERVICE_BUS_CONNECTION_STRING",
        "AZURE_SERVICE_BUS_QUEUE_EXTRACTING",
        "AZURE_SERVICE_BUS_QUEUE_PROCESSING",
        "AZURE_SERVICE_BUS_QUEUE_REVIEWING",
    ]


def _check_database_readiness() -> Dict[str, Any]:
    try:
        JOB_REPO.get_recent_jobs(limit=1)
        return {"status": "ok"}
    except Exception as exc:  # pragma: no cover - covered by endpoint tests
        return {"status": "error", "error": str(exc)}


def _check_storage_readiness() -> Dict[str, Any]:
    try:
        os.makedirs(UPLOADS_DIR, exist_ok=True)
        fd, test_path = tempfile.mkstemp(prefix="ready_", dir=UPLOADS_DIR)
        os.close(fd)
        os.unlink(test_path)
        return {"status": "ok", "uploads_dir": UPLOADS_DIR}
    except Exception as exc:  # pragma: no cover - covered by endpoint tests
        return {"status": "error", "error": str(exc), "uploads_dir": UPLOADS_DIR}


def _check_service_bus_readiness() -> Dict[str, Any]:
    queues = {
        "extracting": os.environ.get("AZURE_SERVICE_BUS_QUEUE_EXTRACTING"),
        "processing": os.environ.get("AZURE_SERVICE_BUS_QUEUE_PROCESSING"),
        "reviewing": os.environ.get("AZURE_SERVICE_BUS_QUEUE_REVIEWING"),
    }
    missing_queues = [name for name, value in queues.items() if not value]
    if not os.environ.get("AZURE_SERVICE_BUS_CONNECTION_STRING"):
        return {"status": "error", "error": "Missing AZURE_SERVICE_BUS_CONNECTION_STRING", "queues": queues}
    if missing_queues:
        return {
            "status": "error",
            "error": f"Missing queue config: {', '.join(missing_queues)}",
            "queues": queues,
        }
    return {"status": "ok", "queues": queues}


def _check_openai_readiness() -> Dict[str, Any]:
    provider = (os.environ.get("PFCD_PROVIDER", "azure_openai") or "azure_openai").strip().lower()
    if provider == "openai":
        missing = [name for name in ("OPENAI_API_KEY",) if not os.environ.get(name)]
        if missing:
            return {"status": "error", "provider": provider, "error": f"Missing env: {', '.join(missing)}"}
        return {"status": "ok", "provider": provider}

    missing = [
        name
        for name in ("AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_CHAT_DEPLOYMENT_NAME")
        if not os.environ.get(name)
    ]
    if missing:
        return {"status": "error", "provider": provider, "error": f"Missing env: {', '.join(missing)}"}
    return {
        "status": "ok",
        "provider": provider,
        "endpoint": os.environ.get("AZURE_OPENAI_ENDPOINT"),
        "deployment": os.environ.get("AZURE_OPENAI_CHAT_DEPLOYMENT_NAME"),
    }


def _check_speech_readiness() -> Dict[str, Any]:
    account = os.environ.get("AZURE_SPEECH_ACCOUNT_NAME")
    if not account:
        return {"status": "error", "error": "Missing AZURE_SPEECH_ACCOUNT_NAME"}
    return {"status": "ok", "account": account}


@app.get("/health/readiness")
def readiness_health() -> Dict[str, Any]:
    required_env = _required_readiness_env()
    missing = [name for name in required_env if not os.environ.get(name)]
    checks = {
        "database": _check_database_readiness(),
        "storage": _check_storage_readiness(),
        "service_bus": _check_service_bus_readiness(),
        "openai": _check_openai_readiness(),
        "speech": _check_speech_readiness(),
    }
    all_checks_ok = all(check.get("status") == "ok" for check in checks.values())
    ready = not missing and all_checks_ok
    return JSONResponse(
        content={
            "status": "ready" if ready else "not_ready",
            "timestamp": _utc_now(),
            "checks": checks,
            "missing_environment": missing,
        },
        status_code=200 if ready else 503,
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


class UploadUrlRequest(BaseModel):
    file_name: str = Field(min_length=1, max_length=512)
    size_bytes: int = Field(gt=0, le=MAX_UPLOAD_BYTES)
    mime_type: Optional[str] = None
    source_type: Optional[str] = None
    document_type: Optional[str] = "video"


@api_router.post("/jobs/{job_id}/upload-url", status_code=201)
async def create_upload_url(job_id: str, payload: UploadUrlRequest) -> Dict[str, Any]:
    upload_id = str(uuid4())
    safe_name = _safe_upload_name(payload.file_name)
    mime_type = payload.mime_type or "application/octet-stream"
    source_type = payload.source_type or MIME_TO_SOURCE_TYPE.get(mime_type, "document")

    contract = _build_blob_upload_contract(job_id, upload_id, safe_name, mime_type)
    if not contract:
        contract = _build_local_upload_contract(upload_id, safe_name, mime_type)

    manifest = {
        "upload_id": upload_id,
        "job_id": job_id,
        "file_name": safe_name,
        "size_bytes": payload.size_bytes,
        "mime_type": mime_type,
        "source_type": source_type,
        "document_type": payload.document_type or "video",
        "storage_key": contract["storage_key"],
        "mode": contract["mode"],
        "uploaded_at": None,
        "expires_at": contract["expires_at"],
        "created_at": _utc_now(),
    }
    _save_upload_manifest(upload_id, manifest)
    return {
        "upload_id": upload_id,
        "job_id": job_id,
        "file_name": safe_name,
        "size_bytes": payload.size_bytes,
        "mime_type": mime_type,
        "source_type": source_type,
        "storage_key": contract["storage_key"],
        "expires_at": contract["expires_at"],
        "upload": contract["upload"],
    }


@api_router.put("/uploads/{upload_id}/content", status_code=201)
async def upload_content_via_api(upload_id: str, request: Request) -> Dict[str, Any]:
    manifest = _load_upload_manifest(upload_id)
    if not manifest:
        raise HTTPException(status_code=404, detail=f"Upload id {upload_id!r} was not found.")
    if manifest.get("mode") != "local_api":
        raise HTTPException(status_code=409, detail="Upload content must be written to blob URL for this upload id.")
    expires_at = _parse_iso8601(manifest.get("expires_at"))
    if expires_at and expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=410, detail="Upload URL has expired.")

    body = await request.body()
    size_bytes = len(body)
    if size_bytes > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File exceeds 500MB limit.")
    expected_size = int(manifest.get("size_bytes") or 0)
    if expected_size and expected_size != size_bytes:
        raise HTTPException(
            status_code=400,
            detail=f"Upload size mismatch for {upload_id}: expected {expected_size}, got {size_bytes}",
        )

    storage_key = manifest["storage_key"]
    await anyio.to_thread.run_sync(lambda: os.makedirs(os.path.dirname(storage_key), exist_ok=True))

    def _write() -> None:
        with open(storage_key, "wb") as fh:
            fh.write(body)

    await anyio.to_thread.run_sync(_write)
    updated = _update_upload_manifest(upload_id, {"uploaded_at": _utc_now()})
    return {
        "upload_id": upload_id,
        "file_name": updated["file_name"],
        "size_bytes": size_bytes,
        "mime_type": updated["mime_type"],
        "source_type": updated.get("source_type", "document"),
        "location": storage_key,
    }


@api_router.post("/upload", status_code=201)
async def upload_file(file: UploadFile = File(...)) -> Dict[str, Any]:
    upload_id = str(uuid4())
    content = await file.read()
    size_bytes = len(content)
    if size_bytes > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail=f"File exceeds 500MB limit.")

    safe_name = _safe_upload_name(file.filename)
    dest_dir = os.path.join(UPLOADS_DIR, upload_id)
    await anyio.to_thread.run_sync(lambda: os.makedirs(dest_dir, exist_ok=True))
    dest_path = os.path.join(dest_dir, safe_name)
    def _write():
        with open(dest_path, "wb") as fh:
            fh.write(content)
    await anyio.to_thread.run_sync(_write)

    source_type = MIME_TO_SOURCE_TYPE.get(file.content_type or "", "document")
    _save_upload_manifest(
        upload_id,
        {
            "upload_id": upload_id,
            "job_id": None,
            "file_name": safe_name,
            "size_bytes": size_bytes,
            "mime_type": file.content_type,
            "source_type": source_type,
            "document_type": "video",
            "storage_key": dest_path,
            "mode": "local_api",
            "uploaded_at": _utc_now(),
            "expires_at": None,
            "created_at": _utc_now(),
        },
    )
    return {
        "upload_id": upload_id,
        "file_name": safe_name,
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
    payload = _resolve_input_files(payload)
    job_id = str(uuid4())
    job = default_job_payload(payload)
    job["job_id"] = job_id
    needs_confirmation = requires_cost_confirmation(job.get("profile_requested"))
    if needs_confirmation:
        job["status"] = JobStatus.AWAITING_CONFIRMATION.value
    await _repo_upsert_job(job_id, job)
    await anyio.to_thread.run_sync(
        JOB_REPO.append_job_event,
        job_id,
        "job_created",
        {"job_id": job_id, "profile": job["profile_requested"], "at": _utc_now()},
    )

    if not needs_confirmation:
        trace_id = str(uuid4())
        message = build_message(
            job_id=job_id,
            phase="extracting",
            attempt=0,
            requested_by="api",
            trace_id=trace_id,
        )
        await anyio.to_thread.run_sync(ORCHESTRATOR.enqueue, "extracting", message)

    logger.info(
        "Job created: job_id=%s profile=%s status=%s",
        job_id,
        job["profile_requested"],
        job["status"],
    )
    response = {"job_id": job_id, **job}
    response["cost_estimate"] = {
        "profile": job["provider_effective"].get("profile"),
        "cost_cap_usd": job["provider_effective"].get("cost_cap_usd"),
        "requires_confirmation": needs_confirmation,
    }
    return response


@api_router.post("/jobs/{job_id}/confirm-cost")
async def confirm_cost(job_id: str) -> Dict[str, Any]:
    job = await _job_or_404(job_id)
    if job["status"] == JobStatus.DELETED.value:
        raise HTTPException(status_code=404, detail="Job not found")
    if job["status"] != JobStatus.AWAITING_CONFIRMATION.value:
        raise HTTPException(status_code=409, detail="Job is not awaiting cost confirmation.")

    job["status"] = JobStatus.QUEUED.value
    job["updated_at"] = _utc_now()
    await _repo_upsert_job(job_id, job)
    await anyio.to_thread.run_sync(
        JOB_REPO.append_job_event,
        job_id,
        "cost_confirmed",
        {"job_id": job_id, "at": _utc_now()},
    )

    trace_id = str(uuid4())
    message = build_message(
        job_id=job_id,
        phase="extracting",
        attempt=0,
        requested_by="api:confirm-cost",
        trace_id=trace_id,
    )
    await anyio.to_thread.run_sync(ORCHESTRATOR.enqueue, "extracting", message)
    return {"job_id": job_id, **job}


@api_router.get("/jobs")
async def list_jobs(limit: int = 50) -> List[Dict[str, Any]]:
    bounded_limit = max(0, min(limit, 200))
    return await anyio.to_thread.run_sync(lambda: JOB_REPO.list_jobs(limit=bounded_limit))


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
    current_draft_version = int((job.get("draft") or {}).get("version", 1))
    if payload.draft_version != current_draft_version:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Draft version conflict for {job_id}: expected {payload.draft_version}, "
                f"current {current_draft_version}"
            ),
        )
    if payload.pdd is not None:
        job["draft"]["pdd"] = payload.pdd
    if payload.sipoc is not None:
        job["draft"]["sipoc"] = payload.sipoc
    if payload.assumptions is not None:
        job["draft"]["assumptions"] = payload.assumptions
    if payload.speaker_resolutions is not None:
        job["speaker_resolutions"].update(payload.speaker_resolutions)
    job["updated_at"] = _utc_now()
    job["user_saved_draft"] = True
    job["user_saved_at"] = job["updated_at"]
    job["draft"]["user_reconciled_at"] = _utc_now()
    job["draft"]["version"] = current_draft_version + 1
    await _repo_upsert_job(job_id, job)
    # Re-run the pure-Python reviewing gate so flags reflect the edited draft.
    from app.agents.reviewing import run_reviewing

    rerunnable_codes = {
        "stub_draft_detected",
        "pdd_incomplete",
        "frame_first_evidence",
        "transcript_fallback",
        "insufficient_evidence",
        "transcript_mismatch",
        "unknown_speaker",
        "SLA_UNRESOLVED",
        "FREQUENCY_UNRESOLVED",
        "EXCEPTIONS_SUPPRESSED",
    }
    job["review_notes"]["flags"] = [
        flag
        for flag in job["review_notes"]["flags"]
        if flag.get("code") not in rerunnable_codes
        and not str(flag.get("code", "")).startswith("sipoc_")
    ]
    run_reviewing(job, {})
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
        "review_notes": job["review_notes"],
        "agent_review": job["agent_review"],
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
    draft_saved = bool(
        job.get("user_saved_draft")
        or (job.get("draft") or {}).get("user_reconciled_at")
    )
    if not draft_saved:
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

    try:
        finalized_draft = copy.deepcopy(job["draft"])
        finalized_draft["finalized_at"] = _utc_now()
        evidence_bundle = build_evidence_bundle(finalized_draft, job)
        frame_bytes_map = _resolve_frame_bytes_map(evidence_bundle)
        exports_payload = {
            "job_id": job_id,
            "status": JobStatus.COMPLETED.value,
            "provider_effective": job["provider_effective"],
            "draft": finalized_draft,
            "review_notes": job["review_notes"],
            "exports_manifest": {"format": "json", "evidence_bundle": evidence_bundle},
        }
        json_bytes = json.dumps(exports_payload, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
        markdown_bytes = await anyio.to_thread.run_sync(
            lambda: build_export_markdown(finalized_draft, evidence_bundle).encode("utf-8")
        )
        pdf_bytes = await anyio.to_thread.run_sync(
            lambda: build_export_pdf(finalized_draft, evidence_bundle, frame_bytes_map=frame_bytes_map)
        )
        docx_bytes = await anyio.to_thread.run_sync(
            lambda: build_export_docx(
                finalized_draft,
                evidence_bundle,
                job_id,
                frame_bytes_map=frame_bytes_map,
            )
        )

        json_meta = await anyio.to_thread.run_sync(
            EXPORT_STORAGE.save_bytes, job_id, "json", json_bytes, "application/json"
        )
        md_meta = await anyio.to_thread.run_sync(
            EXPORT_STORAGE.save_bytes, job_id, "markdown", markdown_bytes, "text/markdown; charset=utf-8"
        )
        pdf_meta = await anyio.to_thread.run_sync(
            lambda: EXPORT_STORAGE.save_bytes(
                job_id, "pdf", pdf_bytes, "application/pdf", download_name=f"pdd-{job_id}.pdf"
            )
        )
        docx_meta = await anyio.to_thread.run_sync(
            lambda: EXPORT_STORAGE.save_bytes(
                job_id,
                "docx",
                docx_bytes,
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                download_name=f"pdd-{job_id}.docx",
            )
        )

        job["finalized_draft"] = finalized_draft
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
    except Exception as exc:
        logger.error("Finalize failed for job %s: %s", job_id, exc, exc_info=True)
        try:
            await anyio.to_thread.run_sync(EXPORT_STORAGE.delete_job_exports, job_id)
        except Exception:
            logger.warning("Failed to clean partial exports for job %s after finalize error", job_id, exc_info=True)
        job["status"] = JobStatus.FAILED.value
        job["error"] = {"message": str(exc), "phase": "finalize"}
        job["updated_at"] = _utc_now()
        await _repo_upsert_job(job_id, job)
        await anyio.to_thread.run_sync(
            JOB_REPO.append_job_event,
            job_id,
            "finalize_failed",
            {"job_id": job_id, "at": _utc_now(), "message": str(exc)},
        )
        raise HTTPException(status_code=500, detail="Failed to generate exports.") from exc


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
        bundle = build_evidence_bundle(draft, job)
        return JSONResponse(
            {
                "job_id": job_id,
                "status": job["status"],
                "provider_effective": job["provider_effective"],
                "draft": draft,
                "review_notes": job["review_notes"],
                "exports_manifest": {
                    "format": "json",
                    "evidence_bundle": bundle,
                },
            }
        )
    bundle = build_evidence_bundle(draft, job)
    frame_bytes_map = _resolve_frame_bytes_map(bundle)
    if fmt == "markdown":
        return PlainTextResponse(build_export_markdown(draft, bundle))
    if fmt == "pdf":
        return Response(
            content=build_export_pdf(draft, bundle, frame_bytes_map=frame_bytes_map),
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="pdd-{job_id}.pdf"'},
        )
    return Response(
        content=build_export_docx(draft, bundle, job_id, frame_bytes_map=frame_bytes_map),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
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
@app.post("/dev/jobs/{job_id}/simulate", tags=["dev"], dependencies=[Depends(verify_api_key)])
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
            "triggers": ["User submits a new intake request."],
            "preconditions": ["Required documents are available."],
            "roles": ["Analyst", "Reviewer", "Approver"],
            "systems": ["CRM", "Document Store"],
            "business_rules": ["Requests must be validated before approval."],
            "exceptions": [],
            "outputs": ["Approved record"],
            "metrics": {"coverage": "good", "confidence": 0.82},
            "risks": ["Step 3 confidence below threshold (0.65)."],
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
                "step_anchor": ["step-1"],
                "source_anchor": "00:00:30",
                "anchor_missing_reason": None,
            },
            {
                "supplier": "Analyst",
                "input": "Ticket",
                "process_step": "Validate completeness",
                "output": "Validated doc",
                "customer": "Reviewer",
                "step_anchor": ["step-2"],
                "source_anchor": "00:01:15",
                "anchor_missing_reason": None,
            },
            {
                "supplier": "Reviewer",
                "input": "Validated doc",
                "process_step": "Approve and close",
                "output": "Approved record",
                "customer": "Approver",
                "step_anchor": ["step-3"],
                "source_anchor": "00:02:45",
                "anchor_missing_reason": None,
            },
        ],
        "confidence_summary": {
            "overall": 0.82,
            "evidence_strength": "medium",
            "source_quality": "good",
        },
        "assumptions": [],
        "generated_at": _utc_now(),
        "version": 1,
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
    job["user_saved_draft"] = False
    job["user_saved_at"] = None
    job["updated_at"] = _utc_now()
    await _repo_upsert_job(job_id, job)
    return {"job_id": job_id, "status": job["status"], "detail": "Simulated needs_review state."}
