"""Unit tests for ExportStorage mode mismatch scenarios."""

from __future__ import annotations

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))


def test_load_blob_meta_in_local_mode_raises(tmp_path):
    from app.storage import ExportStorage

    store = ExportStorage(
        base_path=str(tmp_path),
        connection_string=None,
        account_url=None,
        container="exports",
    )

    with pytest.raises(FileNotFoundError, match="local storage mode"):
        store.load_bytes({"storage": "blob", "location": "job-1/pdd.json"})


def test_load_local_meta_in_blob_mode_raises(tmp_path):
    from app.storage import ExportStorage

    store = ExportStorage(
        base_path=str(tmp_path),
        connection_string=None,
        account_url=None,
        container="exports",
    )
    store._client = object()  # simulate blob-backed runtime

    with pytest.raises(FileNotFoundError, match="blob storage mode"):
        store.load_bytes({"storage": "local", "location": str(tmp_path / "job-1" / "pdd.json")})
