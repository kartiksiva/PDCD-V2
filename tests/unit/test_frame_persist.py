from __future__ import annotations

import builtins
import pathlib
import sys
from io import BytesIO

ROOT = pathlib.Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


def test_upload_frame_local_fallback_writes_file(tmp_path, monkeypatch):
    from app.storage import upload_frame

    monkeypatch.delenv("AZURE_STORAGE_ACCOUNT_URL", raising=False)
    monkeypatch.delenv("AZURE_STORAGE_CONNECTION_STRING", raising=False)
    monkeypatch.delenv("AZURE_STORAGE_ACCOUNT_NAME", raising=False)
    monkeypatch.setenv("EXPORTS_BASE_PATH", str(tmp_path))

    frame_path = upload_frame("job-1", 0, b"JPEG")

    assert frame_path is not None
    assert pathlib.Path(frame_path).exists()
    assert pathlib.Path(frame_path).read_bytes() == b"JPEG"


def test_upload_frame_returns_none_on_exception(monkeypatch, tmp_path):
    import builtins

    from app.storage import upload_frame

    monkeypatch.delenv("AZURE_STORAGE_ACCOUNT_URL", raising=False)
    monkeypatch.delenv("AZURE_STORAGE_CONNECTION_STRING", raising=False)
    monkeypatch.delenv("AZURE_STORAGE_ACCOUNT_NAME", raising=False)
    monkeypatch.setenv("EXPORTS_BASE_PATH", str(tmp_path))

    def _raise(*_args, **_kwargs):
        raise OSError("nope")

    monkeypatch.setattr(builtins, "open", _raise)

    assert upload_frame("job-1", 0, b"JPEG") is None


def test_upload_frame_retries_transient_blob_errors(monkeypatch):
    from azure.core.exceptions import ServiceRequestError

    from app.storage import upload_frame

    monkeypatch.delenv("AZURE_STORAGE_ACCOUNT_URL", raising=False)
    monkeypatch.setenv("AZURE_STORAGE_CONNECTION_STRING", "UseDevelopmentStorage=true")
    monkeypatch.delenv("AZURE_STORAGE_ACCOUNT_NAME", raising=False)

    upload_attempts = []

    class _FakeBlobClient:
        def upload_blob(self, *_args, **_kwargs):
            upload_attempts.append(True)
            if len(upload_attempts) < 3:
                raise ServiceRequestError("transient failure")

    class _FakeServiceClient:
        def get_blob_client(self, _container, _blob_name):
            return _FakeBlobClient()

    monkeypatch.setattr(
        "app.storage.BlobServiceClient.from_connection_string",
        lambda _conn: _FakeServiceClient(),
    )
    monkeypatch.setattr("app.storage.time.sleep", lambda _seconds: None)

    blob_name = upload_frame("job-1", 7, b"JPEG")

    assert blob_name == "job-1/frames/frame_0007.jpg"
    assert len(upload_attempts) == 3


def test_video_adapter_sets_frame_storage_keys_in_metadata(monkeypatch):
    from app.agents.adapters.video import VideoAdapter

    adapter = VideoAdapter()
    job = {
        "job_id": "job-1",
        "input_manifest": {
            "video": {
                "audio_detected": False,
                "audio_declared": False,
                "storage_key": "/tmp/frame-demo.mp4",
                "frame_extraction_policy": {"sample_interval_sec": 5},
            }
        },
        "agent_signals": {},
    }

    monkeypatch.setattr("app.agents.adapters.video.is_ffmpeg_available", lambda: True)
    monkeypatch.setattr(
        "app.agents.adapters.video.extract_keyframes",
        lambda _path, _tmp, _interval: [("/tmp/f.jpg", 0.0)],
    )
    monkeypatch.setattr("app.agents.adapters.video.upload_frame", lambda *_args: "evidence/job/0.jpg")
    monkeypatch.setattr("app.agents.adapters.video.analyze_frames", lambda *_args: "desc")

    def _fake_open(path, mode="r", *_args, **_kwargs):
        assert path == "/tmp/f.jpg"
        assert "rb" in mode
        return BytesIO(b"JPEG")

    monkeypatch.setattr(builtins, "open", _fake_open)

    ev = adapter.normalize(job)

    assert ev.metadata["frame_storage_keys"] == [("evidence/job/0.jpg", 0.0)]


def test_export_builder_includes_frame_captures_in_bundle():
    from app.export_builder import build_evidence_bundle

    draft = {
        "pdd": {"purpose": "p", "scope": "s", "steps": []},
        "sipoc": [],
    }
    job = {
        "agent_signals": {"frame_storage_keys": [("key", 1.5)]},
        "extracted_evidence": {
            "evidence_items": [
                {"metadata": {"frame_storage_keys": [("key", 1.5)]}},
            ]
        },
    }

    bundle = build_evidence_bundle(draft, job)

    assert isinstance(bundle["frame_captures"], list)
    assert bundle["frame_captures"][0]["storage_key"] == "key"
