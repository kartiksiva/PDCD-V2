"""Export storage helpers for local and Azure Blob backends."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict, Optional

from azure.storage.blob import BlobServiceClient, ContentSettings


DEFAULT_EXPORT_CONTAINER = "exports"
DEFAULT_EXPORT_BASE_PATH = "./storage/exports"


@dataclass(frozen=True)
class ExportMeta:
    storage: str
    location: str
    content_type: str
    download_name: Optional[str] = None


class ExportStorage:
    def __init__(self, *, base_path: str, connection_string: Optional[str], container: str) -> None:
        self.base_path = base_path
        self.connection_string = connection_string
        self.container = container
        self._client = None
        if connection_string:
            self._client = BlobServiceClient.from_connection_string(connection_string)
            self._ensure_container()
        else:
            os.makedirs(self.base_path, exist_ok=True)

    @classmethod
    def from_env(cls) -> "ExportStorage":
        base_path = os.environ.get("EXPORTS_BASE_PATH", DEFAULT_EXPORT_BASE_PATH)
        connection_string = os.environ.get("AZURE_STORAGE_CONNECTION_STRING")
        container = os.environ.get("AZURE_STORAGE_CONTAINER_EXPORTS", DEFAULT_EXPORT_CONTAINER)
        return cls(base_path=base_path, connection_string=connection_string, container=container)

    @property
    def mode(self) -> str:
        return "blob" if self._client else "local"

    def _ensure_container(self) -> None:
        if not self._client:
            return
        container_client = self._client.get_container_client(self.container)
        try:
            container_client.create_container()
        except Exception:
            # Best-effort: container may already exist or permissions may be constrained.
            pass

    @staticmethod
    def _validate_path_components(job_id: str, fmt: str) -> None:
        if not job_id or "/" in job_id or "\\" in job_id or ".." in job_id:
            raise ValueError(f"Invalid job_id: {job_id!r}")
        if not fmt.isalnum():
            raise ValueError(f"Invalid export format: {fmt!r}")

    def save_bytes(self, job_id: str, fmt: str, content: bytes, content_type: str, *, download_name: Optional[str] = None) -> ExportMeta:
        self._validate_path_components(job_id, fmt)
        if self._client:
            blob_name = f"{job_id}/pdd.{fmt}"
            blob_client = self._client.get_blob_client(self.container, blob_name)
            blob_client.upload_blob(
                content,
                overwrite=True,
                content_settings=ContentSettings(content_type=content_type),
            )
            return ExportMeta(storage="blob", location=blob_name, content_type=content_type, download_name=download_name)

        job_dir = os.path.join(self.base_path, job_id)
        os.makedirs(job_dir, exist_ok=True)
        file_path = os.path.join(job_dir, f"pdd.{fmt}")
        with open(file_path, "wb") as handle:
            handle.write(content)
        return ExportMeta(storage="local", location=file_path, content_type=content_type, download_name=download_name)

    def load_bytes(self, meta: Dict[str, str]) -> bytes:
        storage = meta.get("storage")
        location = meta.get("location")
        if storage == "blob" and self._client:
            blob_client = self._client.get_blob_client(self.container, location)
            return blob_client.download_blob().readall()
        if not location:
            raise FileNotFoundError("Export location missing")
        with open(location, "rb") as handle:
            return handle.read()
