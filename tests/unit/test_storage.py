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


def test_read_frame_bytes_local_path(tmp_path):
    from app.storage import read_frame_bytes

    frame_path = tmp_path / "frame_0001.jpg"
    payload = b"\xff\xd8\xff\xd9"
    frame_path.write_bytes(payload)

    assert read_frame_bytes(str(frame_path)) == payload


def test_read_frame_bytes_missing_returns_none(tmp_path):
    from app.storage import read_frame_bytes

    missing = tmp_path / "does_not_exist.jpg"
    assert read_frame_bytes(str(missing)) is None
