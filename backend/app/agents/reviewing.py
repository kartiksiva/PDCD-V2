"""Reviewing agent: pure-Python quality gates + review flags.

No LLM call — deterministic checks applied to the draft produced by the
processing agent.
"""

from __future__ import annotations

from typing import Any, Dict, List

from app.agents.evidence import compute_evidence_strength
from app.agents.sipoc_validator import validate_sipoc

_PDD_REQUIRED_KEYS = [
    "purpose", "scope", "triggers", "preconditions", "steps",
    "roles", "systems", "business_rules", "exceptions", "outputs",
    "metrics", "risks",
]


def _flag(code: str, severity: str, message: str, *, requires_user_action: bool = False) -> Dict[str, Any]:
    return {
        "code": code,
        "severity": severity,
        "message": message,
        "requires_user_action": requires_user_action,
    }


def run_reviewing(job: Dict[str, Any], profile_conf: Dict[str, Any]) -> float:  # noqa: ARG001
    """Apply deterministic quality checks; mutate job in-place. Returns 0.0 (no LLM cost)."""
    flags: List[Dict[str, Any]] = []
    draft = job.get("draft") or {}
    pdd = draft.get("pdd") or {}
    sipoc = draft.get("sipoc") or []

    if draft.get("draft_source") == "stub":
        flags.append(_flag(
            "stub_draft_detected",
            "blocker",
            "Draft content is a fallback stub and must be replaced before finalize.",
            requires_user_action=True,
        ))

    # 1. PDD completeness — key must be present (not None); empty lists are valid
    for key in _PDD_REQUIRED_KEYS:
        val = pdd.get(key)
        is_missing = val is None or (isinstance(val, str) and not val.strip())
        if is_missing:
            flags.append(_flag(
                "pdd_incomplete",
                "blocker",
                f"PDD is missing required field: '{key}'",
                requires_user_action=True,
            ))

    # 2. SIPOC schema validation (PRD §8.8 and §10)
    pdd_steps = pdd.get("steps") or []
    sipoc_result = validate_sipoc(sipoc, pdd_steps)
    for sipoc_flag in sipoc_result.flags:
        flags.append(sipoc_flag)

    # 3. Evidence strength routing
    has_video = job.get("has_video", False)
    has_audio = job.get("has_audio", False)
    has_transcript = job.get("has_transcript", False)

    evidence_items = (job.get("extracted_evidence") or {}).get("evidence_items")
    evidence_strength = compute_evidence_strength(
        has_video=has_video,
        has_audio=has_audio,
        has_transcript=has_transcript,
        evidence_items=evidence_items,
    )

    if has_video and has_transcript and not has_audio:
        flags.append(_flag(
            "frame_first_evidence",
            "warning",
            "Video audio is not available; sequence is derived with stronger frame evidence.",
        ))
    elif has_transcript and not has_video:
        flags.append(_flag(
            "transcript_fallback",
            "warning",
            "Transcript-first fallback used. Validate actor and action assignments before finalize.",
        ))
    elif has_video and not has_audio and not has_transcript:
        flags.append(_flag(
            "insufficient_evidence",
            "blocker",
            "Video has no audio and no transcript. Cannot extract process steps reliably.",
            requires_user_action=True,
        ))

    job["agent_signals"]["evidence_strength"] = evidence_strength

    # 4. Transcript/media consistency — only relevant when both media and transcript exist
    consistency = job.get("transcript_media_consistency") or {}
    if (
        (has_video or has_audio)
        and has_transcript
        and consistency.get("verdict") == "suspected_mismatch"
    ):
        flags.append(_flag(
            "transcript_mismatch",
            "warning",
            "Transcript content appears inconsistent with the video/audio source.",
        ))

    # 5. Unknown speakers
    extracted = job.get("extracted_evidence") or {}
    speakers = extracted.get("speakers_detected") or []
    if "Unknown" in speakers:
        flags.append(_flag(
            "unknown_speaker",
            "warning",
            "One or more speakers could not be identified in the transcript.",
        ))

    # 6. Completeness checks from extracted_facts (warning only; do not block finalize)
    extracted_facts = job.get("extracted_facts") or {}
    quantitative_facts = extracted_facts.get("quantitative_facts") or []
    has_sla_fact = any(
        isinstance(fact, dict) and str(fact.get("fact_type", "")).strip().lower() == "sla"
        for fact in quantitative_facts
    )
    has_volume_fact = any(
        isinstance(fact, dict) and str(fact.get("fact_type", "")).strip().lower() == "volume"
        for fact in quantitative_facts
    )
    exception_patterns = extracted_facts.get("exception_patterns") or []
    pdd_exceptions = pdd.get("exceptions") or []

    if has_sla_fact and str(pdd.get("sla", "")).strip() == "Needs Review":
        flags.append(_flag(
            "SLA_UNRESOLVED",
            "warning",
            "PDD SLA is 'Needs Review' even though extracted facts include SLA values.",
        ))
    if has_volume_fact and str(pdd.get("frequency", "")).strip() == "Needs Review":
        flags.append(_flag(
            "FREQUENCY_UNRESOLVED",
            "warning",
            "PDD frequency is 'Needs Review' even though extracted facts include volume values.",
        ))
    if exception_patterns and not pdd_exceptions:
        flags.append(_flag(
            "EXCEPTIONS_SUPPRESSED",
            "warning",
            "Exception patterns were extracted but pdd.exceptions is empty.",
        ))

    # Merge flags (preserve any flags already set by build_draft fallback)
    existing_codes = {f["code"] for f in job["review_notes"]["flags"]}
    for f in flags:
        if f["code"] not in existing_codes:
            job["review_notes"]["flags"].append(f)

    # 7. Overall confidence + decision
    all_flags = job["review_notes"]["flags"]
    has_blocker = any(f["severity"] == "blocker" for f in all_flags)
    has_mismatch_warning = any(f["code"] == "transcript_mismatch" for f in all_flags)

    if has_blocker:
        decision = "blocked"
        overall_confidence = 0.40
    elif evidence_strength == "high" and not has_mismatch_warning:
        decision = "approve_for_draft"
        overall_confidence = 0.88
    else:
        decision = "needs_review"
        overall_confidence = 0.65

    job["agent_review"]["decision"] = decision

    # Update confidence_summary in draft if present
    if draft.get("confidence_summary") is not None:
        draft["confidence_summary"]["overall"] = overall_confidence
        draft["confidence_summary"]["evidence_strength"] = evidence_strength

    job["agent_signals"]["alignment"] = job.get("transcript_media_consistency", {}).get("verdict")

    return 0.0
