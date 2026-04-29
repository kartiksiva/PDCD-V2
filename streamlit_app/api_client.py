import os
import re
from typing import Any, Dict, Optional, Tuple

import requests


def _api_root(base: str) -> str:
    return f"{base.rstrip('/')}/api"


def _headers(api_key: Optional[str], extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    headers: Dict[str, str] = {}
    if api_key:
        headers["X-API-Key"] = api_key
    if extra:
        headers.update(extra)
    return headers


def _request_json(method: str, url: str, api_key: Optional[str], **kwargs: Any) -> Dict[str, Any]:
    req_headers = kwargs.pop("headers", {})
    headers = _headers(api_key, req_headers)
    response = requests.request(method, url, headers=headers, timeout=120, **kwargs)
    if response.ok:
        return response.json() if response.content else {}

    try:
        payload = response.json()
        detail = payload.get("detail")
        if isinstance(detail, dict):
            message = detail.get("message", response.text)
        elif isinstance(detail, str):
            message = detail
        else:
            message = response.text
    except Exception:
        message = response.text

    raise RuntimeError(f"{response.status_code}: {message}")


def _resolve_upload_url(base: str, upload_url: str) -> str:
    if re.match(r"^https?://", upload_url, re.IGNORECASE):
        return upload_url
    if upload_url.startswith("/"):
        return f"{base.rstrip('/')}{upload_url}"
    return upload_url


def list_jobs(base: str, api_key: Optional[str]) -> Dict[str, Any]:
    return _request_json("GET", f"{_api_root(base)}/jobs", api_key)


def get_job(base: str, api_key: Optional[str], job_id: str) -> Dict[str, Any]:
    return _request_json("GET", f"{_api_root(base)}/jobs/{job_id}", api_key)


def upload_file(
    base: str,
    api_key: Optional[str],
    file_path: str,
    file_name: str,
    mime_type: str,
    source_type: str,
) -> Dict[str, Any]:
    upload_job_id = f"upload-{os.urandom(8).hex()}"
    upload_meta = _request_json(
        "POST",
        f"{_api_root(base)}/jobs/{upload_job_id}/upload-url",
        api_key,
        json={
            "file_name": file_name,
            "size_bytes": os.path.getsize(file_path),
            "mime_type": mime_type or "application/octet-stream",
            "source_type": source_type,
            "document_type": "document" if source_type == "document" else "video",
        },
    )

    upload = upload_meta.get("upload", {})
    upload_url = _resolve_upload_url(base, upload.get("url", ""))
    method = upload.get("method", "PUT")
    upload_headers = dict(upload.get("headers") or {})
    if upload.get("requires_api_auth"):
        upload_headers.update(_headers(api_key))

    with open(file_path, "rb") as handle:
        res = requests.request(method, upload_url, headers=upload_headers, data=handle, timeout=300)

    if not res.ok:
        try:
            err = res.json()
            detail = err.get("detail", res.text)
        except Exception:
            detail = res.text
        raise RuntimeError(f"Upload failed ({res.status_code}): {detail}")

    return {
        "upload_id": upload_meta.get("upload_id"),
        "file_name": upload_meta.get("file_name"),
        "size_bytes": upload_meta.get("size_bytes"),
        "mime_type": upload_meta.get("mime_type"),
        "source_type": upload_meta.get("source_type"),
        "storage_key": upload_meta.get("storage_key"),
    }


def create_job(base: str, api_key: Optional[str], payload: Dict[str, Any]) -> Dict[str, Any]:
    return _request_json("POST", f"{_api_root(base)}/jobs", api_key, json=payload)


def confirm_cost(base: str, api_key: Optional[str], job_id: str) -> Dict[str, Any]:
    return _request_json("POST", f"{_api_root(base)}/jobs/{job_id}/confirm-cost", api_key)


def save_draft(
    base: str,
    api_key: Optional[str],
    job_id: str,
    draft: Dict[str, Any],
    speaker_resolutions: Optional[Dict[str, str]],
) -> Dict[str, Any]:
    body: Dict[str, Any] = {
        "draft_version": draft.get("version", 1),
        "pdd": draft.get("pdd", {}),
        "sipoc": draft.get("sipoc", []),
        "assumptions": draft.get("assumptions", []),
    }
    if speaker_resolutions is not None:
        body["speaker_resolutions"] = speaker_resolutions
    return _request_json("PUT", f"{_api_root(base)}/jobs/{job_id}/draft", api_key, json=body)


def finalize_job(base: str, api_key: Optional[str], job_id: str) -> Dict[str, Any]:
    return _request_json("POST", f"{_api_root(base)}/jobs/{job_id}/finalize", api_key)


def download_export(base: str, api_key: Optional[str], job_id: str, fmt: str) -> Tuple[bytes, str]:
    response = requests.get(
        f"{_api_root(base)}/jobs/{job_id}/exports/{fmt}",
        headers=_headers(api_key),
        timeout=120,
    )
    if not response.ok:
        try:
            err = response.json()
            detail = err.get("detail", response.text)
        except Exception:
            detail = response.text
        raise RuntimeError(f"{response.status_code}: {detail}")

    content_disposition = response.headers.get("Content-Disposition", "")
    match = re.search(r'filename="?([^\"]+)"?', content_disposition)
    if match:
        filename = match.group(1)
    elif fmt == "markdown":
        filename = f"pdd-{job_id}.md"
    else:
        filename = f"pdd-{job_id}.{fmt}"

    return response.content, filename


def dev_simulate(base: str, api_key: Optional[str], job_id: str) -> Dict[str, Any]:
    return _request_json("POST", f"{base.rstrip('/')}/dev/jobs/{job_id}/simulate", api_key)
