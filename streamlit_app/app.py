import json
import math
import mimetypes
import os
import tempfile
from datetime import datetime
from typing import Any, Dict, List

import pandas as pd
import streamlit as st

from api_client import (
    confirm_cost,
    create_job,
    dev_simulate,
    download_export,
    finalize_job,
    get_job,
    list_jobs,
    save_draft,
    upload_file,
)

SOURCE_TYPES = ["video", "audio", "transcript", "document"]
STATUS_DONE = {"needs_review", "completed"}
STATUS_TERMINAL = {"needs_review", "completed", "failed"}
PHASES = ["extracting", "processing", "reviewing"]
PDD_STRING_KEYS = [
    "purpose",
    "scope",
    "triggers",
    "preconditions",
    "business_rules",
    "exceptions",
    "outputs",
    "metrics",
    "risks",
]
PDD_LIST_KEYS = ["roles", "systems"]
SIPOC_COLUMNS = [
    "supplier",
    "input",
    "process_step",
    "output",
    "customer",
    "source_anchor",
    "step_anchor",
    "anchor_missing_reason",
]

MIME_TO_SOURCE = {
    "video/mp4": "video",
    "video/quicktime": "video",
    "video/x-msvideo": "video",
    "video/webm": "video",
    "audio/mpeg": "audio",
    "audio/mp4": "audio",
    "audio/wav": "audio",
    "audio/ogg": "audio",
    "text/plain": "transcript",
    "text/vtt": "transcript",
    "application/pdf": "document",
    "application/msword": "document",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "document",
}


def init_state() -> None:
    st.session_state.setdefault("api_base", os.getenv("API_BASE", "http://127.0.0.1:8000"))
    st.session_state.setdefault("api_key", os.getenv("PFCD_API_KEY", ""))
    st.session_state.setdefault("current_job", None)
    st.session_state.setdefault("api_base_input", st.session_state["api_base"])
    st.session_state.setdefault("api_key_input", st.session_state["api_key"])


def infer_source_type(name: str, mime_type: str) -> str:
    if mime_type in MIME_TO_SOURCE:
        return MIME_TO_SOURCE[mime_type]
    lower = name.lower()
    if any(lower.endswith(ext) for ext in [".mp4", ".mov", ".avi", ".webm", ".mkv"]):
        return "video"
    if any(lower.endswith(ext) for ext in [".mp3", ".wav", ".ogg", ".m4a"]):
        return "audio"
    if any(lower.endswith(ext) for ext in [".vtt", ".srt", ".txt"]):
        return "transcript"
    return "document"


def api_base() -> str:
    return st.session_state["api_base"]


def api_key() -> str:
    return st.session_state["api_key"]


def render_jobs_tab() -> None:
    st.subheader("Jobs")

    left, mid, right = st.columns([1, 1, 3])
    if left.button("Refresh", key="jobs_refresh", use_container_width=True):
        st.rerun()
    if mid.button("New Job", key="jobs_new_job", use_container_width=True):
        st.session_state["current_job"] = None
        st.rerun()

    try:
        payload = list_jobs(api_base(), api_key())
        if isinstance(payload, dict):
            jobs = payload.get("jobs", [])
        elif isinstance(payload, list):
            jobs = payload
        else:
            jobs = []
    except Exception as exc:
        st.error(f"Failed to list jobs: {exc}")
        return

    if not jobs:
        st.info("No jobs yet.")
        return

    df_rows = []
    for job in jobs:
        df_rows.append(
            {
                "job_id": job.get("job_id"),
                "status": job.get("status"),
                "profile": job.get("profile_requested"),
                "sources": ", ".join(
                    [
                        *(["video"] if job.get("has_video") else []),
                        *(["audio"] if job.get("has_audio") else []),
                        *(["transcript"] if job.get("has_transcript") else []),
                    ]
                ),
                "created_at": job.get("created_at"),
            }
        )

    st.dataframe(pd.DataFrame(df_rows), use_container_width=True)
    selected_job_id = st.selectbox("Open job", options=[r["job_id"] for r in df_rows], index=0)
    if st.button("Open Job", key="jobs_open_job", use_container_width=True):
        try:
            st.session_state["current_job"] = get_job(api_base(), api_key(), selected_job_id)
            st.success(f"Loaded {selected_job_id}")
        except Exception as exc:
            st.error(f"Failed to open job: {exc}")


def render_new_job_tab() -> None:
    st.subheader("New Job")
    uploads = st.file_uploader(
        "Select files",
        accept_multiple_files=True,
        type=["mp4", "mov", "avi", "webm", "mkv", "mp3", "wav", "ogg", "m4a", "txt", "vtt", "pdf", "doc", "docx"],
    )

    per_file_sources: Dict[str, str] = {}
    if uploads:
        for item in uploads:
            guessed = infer_source_type(item.name, item.type or "")
            per_file_sources[item.name] = st.selectbox(
                f"Source type for {item.name}", SOURCE_TYPES, index=SOURCE_TYPES.index(guessed), key=f"src_{item.name}"
            )

    profile = st.radio("Profile", options=["balanced", "quality"], horizontal=True)

    teams_metadata = {}
    with st.expander("Teams metadata (optional)"):
        meeting_id = st.text_input("meeting_id")
        meeting_subject = st.text_input("meeting_subject")
        start_time_utc = st.text_input("start_time_utc")
        organizer_name = st.text_input("organizer_name")
        organizer_id = st.text_input("organizer_id")
        participants = st.text_area("participants (comma or newline-separated)")
        transcript_speaker_map = st.text_area("transcript_speaker_map (JSON object)")
        recording_markers = st.text_area("recording_markers (JSON array)")

        if meeting_id.strip():
            teams_metadata["meeting_id"] = meeting_id.strip()
        if meeting_subject.strip():
            teams_metadata["meeting_subject"] = meeting_subject.strip()
        if start_time_utc.strip():
            teams_metadata["start_time_utc"] = start_time_utc.strip()
        if organizer_name.strip():
            teams_metadata["organizer_name"] = organizer_name.strip()
        if organizer_id.strip():
            teams_metadata["organizer_id"] = organizer_id.strip()
        participants_list = [p.strip() for p in participants.replace("\n", ",").split(",") if p.strip()]
        if participants_list:
            teams_metadata["participants"] = participants_list
        if transcript_speaker_map.strip():
            teams_metadata["transcript_speaker_map"] = json.loads(transcript_speaker_map)
        if recording_markers.strip():
            teams_metadata["recording_markers"] = json.loads(recording_markers)

    if st.button("Create Job", key="new_create_job", type="primary", use_container_width=True):
        if not uploads:
            st.warning("Upload at least one file.")
            return

        try:
            uploaded_meta: List[Dict[str, Any]] = []
            for item in uploads:
                src = per_file_sources[item.name]
                with tempfile.NamedTemporaryFile(delete=False, suffix=f"-{item.name}") as tmp:
                    tmp.write(item.getbuffer())
                    temp_path = tmp.name
                try:
                    meta = upload_file(
                        api_base(),
                        api_key(),
                        temp_path,
                        item.name,
                        item.type or mimetypes.guess_type(item.name)[0] or "application/octet-stream",
                        src,
                    )
                finally:
                    os.unlink(temp_path)
                uploaded_meta.append({**meta, "source_type": src})

            payload = {
                "profile": profile,
                "input_files": [
                    {
                        "source_type": file_info["source_type"],
                        "file_name": file_info["file_name"],
                        "size_bytes": file_info["size_bytes"],
                        "mime_type": file_info["mime_type"],
                        "upload_id": file_info["upload_id"],
                    }
                    for file_info in uploaded_meta
                ],
            }
            if teams_metadata:
                payload["teams_metadata"] = teams_metadata

            create_res = create_job(api_base(), api_key(), payload)
            if create_res.get("status") == "awaiting_confirmation":
                st.warning(
                    f"Estimated profile={create_res.get('cost_estimate', {}).get('profile', profile)}, "
                    f"cap=${create_res.get('cost_estimate', {}).get('cost_cap_usd', 'n/a')}."
                )
                if st.button("Confirm cost and start", key="new_confirm_cost", use_container_width=True):
                    confirmed = confirm_cost(api_base(), api_key(), create_res["job_id"])
                    st.session_state["current_job"] = get_job(api_base(), api_key(), confirmed["job_id"])
                    st.success(f"Job started: {confirmed['job_id']}")
            else:
                st.session_state["current_job"] = get_job(api_base(), api_key(), create_res["job_id"])
                st.success(f"Job created: {create_res['job_id']}")
        except Exception as exc:
            st.error(f"Create job failed: {exc}")


def _phase_dot(done: bool, active: bool) -> str:
    if done:
        return "🟢"
    if active:
        return "🟡"
    return "⚪"


def render_status_tab() -> None:
    st.subheader("Status")
    job = st.session_state.get("current_job")
    if not job:
        st.info("Open or create a job first.")
        return

    job_id = job["job_id"]
    refresh, simulate = st.columns(2)
    if refresh.button("Refresh", key="status_refresh", use_container_width=True):
        try:
            st.session_state["current_job"] = get_job(api_base(), api_key(), job_id)
        except Exception as exc:
            st.error(f"Refresh failed: {exc}")
    if simulate.button("Dev Simulate", key="status_simulate", use_container_width=True):
        try:
            dev_simulate(api_base(), api_key(), job_id)
            st.session_state["current_job"] = get_job(api_base(), api_key(), job_id)
        except Exception as exc:
            st.error(f"Simulate failed: {exc}")

    latest = st.session_state["current_job"]
    current_phase = latest.get("current_phase")
    status = latest.get("status")

    phase_bits = []
    for phase in PHASES:
        done = PHASES.index(phase) < PHASES.index(current_phase) if current_phase in PHASES else phase in PHASES
        active = phase == current_phase and status not in {"failed"}
        phase_bits.append(f"{_phase_dot(done, active)} {phase.capitalize()}")
    st.markdown(" → ".join(phase_bits))

    st.write(f"Status: `{status}`")
    if status in STATUS_DONE:
        st.success("Job is ready for review/exports.")
    if status == "failed":
        st.error(latest.get("error", "Job failed."))


def _unknown_speakers(job: Dict[str, Any]) -> List[str]:
    speakers = (job.get("extracted_evidence") or {}).get("speakers_detected") or (job.get("agent_signals") or {}).get("speakers_detected") or []
    return [s for s in speakers if isinstance(s, str) and "unknown" in s.lower()]


def _sanitize_json_value(value: Any) -> Any:
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    if isinstance(value, dict):
        return {k: _sanitize_json_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_sanitize_json_value(v) for v in value]
    return value


def _coerce_pdd_types(edited_pdd: Dict[str, Any], original_pdd: Dict[str, Any]) -> Dict[str, Any]:
    """Preserve list/dict-typed PDD fields to avoid stringifying structured data."""
    coerced = dict(edited_pdd)
    for key, original in (original_pdd or {}).items():
        current = coerced.get(key)
        if isinstance(current, str) and isinstance(original, (list, dict)):
            raw = current.strip()
            if not raw:
                coerced[key] = original
                continue
            try:
                parsed = json.loads(raw)
            except Exception:
                # If user didn't provide valid JSON, keep existing structured payload.
                coerced[key] = original
                continue
            if isinstance(original, list) and isinstance(parsed, list):
                coerced[key] = parsed
            elif isinstance(original, dict) and isinstance(parsed, dict):
                coerced[key] = parsed
            else:
                coerced[key] = original
    return coerced


def render_review_tab() -> None:
    st.subheader("Review")
    job = st.session_state.get("current_job")
    if not job:
        st.info("Open or create a job first.")
        return

    if job.get("status") not in {"needs_review", "completed"}:
        st.info("Job is not in reviewable state yet. Use the Status tab.")
        return

    draft = dict(job.get("finalized_draft") or job.get("draft") or {})
    original_pdd = dict(draft.get("pdd") or {})
    pdd = dict(original_pdd)
    sipoc = list(draft.get("sipoc") or [])
    flags = ((job.get("review_notes") or {}).get("flags") or [])

    blockers = [f for f in flags if str(f.get("severity", "")).lower() == "blocker"]
    if flags:
        st.write("Flags")
        for flag in flags:
            st.write(f"- `{flag.get('severity', 'info')}` {flag.get('code', '')}: {flag.get('message', '')}")

    unknown = _unknown_speakers(job)
    speaker_resolutions = dict(job.get("speaker_resolutions") or {})
    if unknown:
        with st.expander("Speaker resolution"):
            for speaker in unknown:
                speaker_resolutions[speaker] = st.text_input(f"Resolve {speaker}", value=speaker_resolutions.get(speaker, ""))

    st.markdown("#### PDD")
    for key in PDD_STRING_KEYS:
        pdd[key] = st.text_area(key, value=pdd.get(key, ""), key=f"pdd_{key}")
    for key in PDD_LIST_KEYS:
        pdd[key] = [x.strip() for x in st.text_input(key, value=", ".join(pdd.get(key, [])), key=f"pdd_list_{key}").split(",") if x.strip()]

    st.markdown("#### SIPOC")
    sipoc_rows = []
    if sipoc:
        for row in sipoc:
            mapped = {col: row.get(col, "") for col in SIPOC_COLUMNS}
            if isinstance(mapped["step_anchor"], list):
                mapped["step_anchor"] = ", ".join(mapped["step_anchor"])
            sipoc_rows.append(mapped)
    else:
        sipoc_rows.append({col: "" for col in SIPOC_COLUMNS})

    edited = st.data_editor(pd.DataFrame(sipoc_rows), use_container_width=True, num_rows="dynamic")
    sipoc_payload: List[Dict[str, Any]] = []
    for row in edited.to_dict(orient="records"):
        out = _sanitize_json_value(dict(row))
        step_anchor_raw = out.get("step_anchor")
        if isinstance(step_anchor_raw, list):
            out["step_anchor"] = [str(x).strip() for x in step_anchor_raw if str(x).strip()]
        else:
            out["step_anchor"] = [x.strip() for x in str(step_anchor_raw or "").split(",") if x.strip()]
        sipoc_payload.append(out)

    left, right = st.columns(2)
    if left.button("Save Draft", key="review_save_draft", use_container_width=True):
        try:
            pdd_for_save = _coerce_pdd_types(pdd, original_pdd)
            save_res = save_draft(
                api_base(),
                api_key(),
                job["job_id"],
                {
                    "version": draft.get("version", 1),
                    "pdd": pdd_for_save,
                    "sipoc": sipoc_payload,
                    "assumptions": draft.get("assumptions", []),
                },
                speaker_resolutions,
            )
            st.session_state["current_job"] = get_job(api_base(), api_key(), save_res["job_id"])
            st.success("Draft saved.")
        except Exception as exc:
            st.error(f"Save failed: {exc}")

    if right.button("Finalize", key="review_finalize", use_container_width=True, disabled=len(blockers) > 0):
        try:
            pdd_for_save = _coerce_pdd_types(pdd, original_pdd)
            save_draft(
                api_base(),
                api_key(),
                job["job_id"],
                {
                    "version": draft.get("version", 1),
                    "pdd": pdd_for_save,
                    "sipoc": sipoc_payload,
                    "assumptions": draft.get("assumptions", []),
                },
                speaker_resolutions,
            )
            fin = finalize_job(api_base(), api_key(), job["job_id"])
            st.session_state["current_job"] = fin
            st.success("Job finalized.")
        except Exception as exc:
            st.error(f"Finalize failed: {exc}")


def render_exports_tab() -> None:
    st.subheader("Exports")
    job = st.session_state.get("current_job")
    if not job:
        st.info("Open or create a job first.")
        return

    # Keep exports metrics in sync with latest backend state (post-finalize).
    try:
        live_job = get_job(api_base(), api_key(), job["job_id"])
        st.session_state["current_job"] = live_job
        job = live_job
    except Exception:
        # Non-blocking: still allow download attempts with current in-memory state.
        pass

    draft = (job.get("finalized_draft") or job.get("draft") or {})
    summary = draft.get("confidence_summary") or {}
    col1, col2, col3 = st.columns(3)
    col1.metric("Confidence", f"{round((summary.get('overall') or 0) * 100)}%")
    col2.metric("Evidence", str(summary.get("evidence_strength") or "n/a"))
    col3.metric("Updated", str(job.get("updated_at") or draft.get("finalized_at") or "n/a"))

    for fmt, label, mime in [
        ("json", "Download JSON", "application/json"),
        ("markdown", "Download Markdown", "text/markdown"),
        ("pdf", "Download PDF", "application/pdf"),
        ("docx", "Download DOCX", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    ]:
        try:
            blob, filename = download_export(api_base(), api_key(), job["job_id"], fmt)
            st.download_button(
                label,
                data=blob,
                file_name=filename,
                mime=mime,
                key=f"exports_download_{fmt}",
                use_container_width=True,
            )
        except Exception as exc:
            st.warning(f"{fmt.upper()} unavailable: {exc}")


def main() -> None:
    st.set_page_config(page_title="PFCD Streamlit UI", layout="wide")
    init_state()

    st.sidebar.header("Connection")
    st.sidebar.text_input("API_BASE", key="api_base_input")
    st.sidebar.text_input("PFCD_API_KEY", key="api_key_input", type="password")
    st.session_state["api_base"] = st.session_state.get("api_base_input", st.session_state["api_base"])
    st.session_state["api_key"] = st.session_state.get("api_key_input", st.session_state["api_key"])
    job = st.session_state.get("current_job")
    st.sidebar.caption(f"Current job: {job.get('job_id') if job else 'none'}")

    tabs = st.tabs(["📋 Jobs", "➕ New Job", "⏳ Status", "✏️ Review", "📥 Exports"])
    with tabs[0]:
        render_jobs_tab()
    with tabs[1]:
        render_new_job_tab()
    with tabs[2]:
        render_status_tab()
    with tabs[3]:
        render_review_tab()
    with tabs[4]:
        render_exports_tab()


if __name__ == "__main__":
    main()
