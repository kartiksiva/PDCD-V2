"""Unit tests for canonical anchor classification utilities."""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))


def test_classify_anchor_missing():
    from app.agents.anchor_utils import classify_anchor

    assert classify_anchor("") == "missing"
    assert classify_anchor("   ") == "missing"
    assert classify_anchor(None) == "missing"


def test_classify_anchor_timestamp_range_and_point():
    from app.agents.anchor_utils import classify_anchor

    assert classify_anchor("00:00:00-00:00:10") == "timestamp_range"
    assert classify_anchor("00:01:15") == "timestamp_range"
    assert classify_anchor("00:01:15.500-00:01:30.500") == "timestamp_range"


def test_classify_anchor_frame_id_variants():
    from app.agents.anchor_utils import classify_anchor

    assert classify_anchor("frame-42") == "frame_id"
    assert classify_anchor("frame_42") == "frame_id"
    assert classify_anchor("FRAME42") == "frame_id"


def test_classify_anchor_section_label_default():
    from app.agents.anchor_utils import classify_anchor

    assert classify_anchor("Section 1: Intake") == "section_label"
    assert classify_anchor("Intro notes") == "section_label"
