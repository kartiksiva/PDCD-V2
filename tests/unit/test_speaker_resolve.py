from __future__ import annotations

from app.agents.extraction import _build_speaker_hint


def test_extraction_prompt_includes_speaker_map_when_teams_metadata_present():
    job = {
        "teams_metadata": {
            "transcript_speaker_map": {
                "spk_001": "Alice (Manager)",
                "spk_002": "Bob",
            }
        }
    }

    hint = _build_speaker_hint(job)

    assert "Alice (Manager)" in hint
    assert "Bob" in hint


def test_extraction_prompt_empty_when_no_teams_metadata():
    assert _build_speaker_hint({}) == ""
