"""Export storage helpers for local and Azure Blob backends."""

from __future__ import annotations

import logging
import os
import shutil
from dataclasses import dataclass
from typing import Dict, Optional

from azure.storage.blob import BlobServiceClient, ContentSettings

logger = logging.getLogger(__name__)


DEFAULT_EXPORT_CONTAINER = "exports"
DEFAULT_EXPORT_BASE_PATH = "./storage/exports"
_EVIDENCE_CONTAINER = os.environ.get("AZURE_STORAGE_CONTAINER_EVIDENCE", "evidence")


@dataclass(frozen=True)
class ExportMeta:
    storage: str
    location: str
    content_type: str
    download_name: Optional[str] = None


class ExportStorage:
    def __init__(
        self,
        *,
        base_path: str,
        connection_string: Optional[str],
        account_url: Optional[str],
        container: str,
    ) -> None:
        self.base_path = base_path
        self.connection_string = connection_string
        self.account_url = account_url
        self.container = container
        self._client = None
        if account_url:
            try:
                from azure.identity import DefaultAzureCredential

                self._client = BlobServiceClient(account_url=account_url, credential=DefaultAzureCredential())
            except Exception as exc:
                logger.warning("Falling back to storage connection string after DAC init failure: %s", exc)
        if self._client is None and connection_string:
            self._client = BlobServiceClient.from_connection_string(connection_string)
        if self._client:
            self._ensure_container()
        else:
            os.makedirs(self.base_path, exist_ok=True)

    @classmethod
    def from_env(cls) -> "ExportStorage":
        base_path = os.environ.get("EXPORTS_BASE_PATH", DEFAULT_EXPORT_BASE_PATH)
        connection_string = os.environ.get("AZURE_STORAGE_CONNECTION_STRING")
        account_url = os.environ.get("AZURE_STORAGE_ACCOUNT_URL")
        if not account_url:
            account_name = os.environ.get("AZURE_STORAGE_ACCOUNT_NAME")
            if account_name:
                account_url = f"https://{account_name}.blob.core.windows.net"
        container = os.environ.get("AZURE_STORAGE_CONTAINER_EXPORTS", DEFAULT_EXPORT_CONTAINER)
        return cls(
            base_path=base_path,
            connection_string=connection_string,
            account_url=account_url,
            container=container,
        )

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
        if storage == "blob":
            if not self._client:
                raise FileNotFoundError("Blob export metadata cannot be read in local storage mode.")
            blob_client = self._client.get_blob_client(self.container, location)
            return blob_client.download_blob().readall()
        if storage == "local" and self._client:
            raise FileNotFoundError("Local export metadata cannot be read in blob storage mode.")
        if not location:
            raise FileNotFoundError("Export location missing")
        with open(location, "rb") as handle:
            return handle.read()

    def delete_job_exports(self, job_id: str) -> None:
        """Delete all export files for a job (blob folder or local directory)."""
        if self._client:
            container = self._client.get_container_client(self.container)
            blobs = container.list_blobs(name_starts_with=f"{job_id}/")
            for blob in blobs:
                container.delete_blob(blob.name)
        else:
            job_dir = os.path.join(self.base_path, job_id)
            if os.path.isdir(job_dir):
                shutil.rmtree(job_dir)


def upload_frame(job_id: str, frame_index: int, jpg_bytes: bytes) -> str | None:
    """Upload a frame JPEG to the evidence container.

    Returns the storage key (blob path or local file path) on success, None on any
    failure. Never raises.
    """
    try:
        account_url = os.environ.get("AZURE_STORAGE_ACCOUNT_URL")
        if not account_url:
            account_name = os.environ.get("AZURE_STORAGE_ACCOUNT_NAME")
            if account_name:
                account_url = f"https://{account_name}.blob.core.windows.net"
        connection_string = os.environ.get("AZURE_STORAGE_CONNECTION_STRING")

        blob_name = f"{job_id}/frames/frame_{frame_index:04d}.jpg"

        if account_url:
            from azure.identity import DefaultAzureCredential

            client = BlobServiceClient(account_url=account_url, credential=DefaultAzureCredential())
            blob_client = client.get_blob_client(_EVIDENCE_CONTAINER, blob_name)
            blob_client.upload_blob(
                jpg_bytes,
                overwrite=True,
                content_settings=ContentSettings(content_type="image/jpeg"),
            )
            return blob_name

        if connection_string:
            client = BlobServiceClient.from_connection_string(connection_string)
            blob_client = client.get_blob_client(_EVIDENCE_CONTAINER, blob_name)
            blob_client.upload_blob(
                jpg_bytes,
                overwrite=True,
                content_settings=ContentSettings(content_type="image/jpeg"),
            )
            return blob_name

        base = os.environ.get("EXPORTS_BASE_PATH", DEFAULT_EXPORT_BASE_PATH)
        local_path = os.path.join(base, job_id, "frames", f"frame_{frame_index:04d}.jpg")
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        with open(local_path, "wb") as handle:
            handle.write(jpg_bytes)
        return local_path
    except Exception as exc:
        logger.warning("Frame upload failed for job %s frame %d: %s", job_id, frame_index, exc)
        return None
