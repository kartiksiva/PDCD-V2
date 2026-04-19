from __future__ import annotations

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


def test_read_message_body_rejects_oversized_payload():
    from app.workers.runner import MAX_MESSAGE_BODY_BYTES, _read_message_body

    chunks = [b"a" * MAX_MESSAGE_BODY_BYTES, b"b"]

    with pytest.raises(ValueError, match="exceeds"):
        _read_message_body(chunks)
