"""SQLAlchemy models for PFCD backend."""

from __future__ import annotations

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class Job(Base):
    __tablename__ = "jobs"

    job_id = Column(String(64), primary_key=True)
    status = Column(String(32), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)
    profile_requested = Column(String(32), nullable=False)
    provider_effective = Column(Text, nullable=False)
    has_video = Column(Boolean, nullable=False, default=False)
    has_audio = Column(Boolean, nullable=False, default=False)
    has_transcript = Column(Boolean, nullable=False, default=False)
    teams_metadata = Column(Text, nullable=False, default="{}")
    transcript_media_consistency = Column(Text, nullable=False, default="{}")
    agent_signals = Column(Text, nullable=False, default="{}")
    agent_review = Column(Text, nullable=False, default="{}")
    speaker_resolutions = Column(Text, nullable=False, default="{}")
    user_saved_draft = Column(Boolean, nullable=False, default=False)
    user_saved_at = Column(DateTime(timezone=True), nullable=True)
    current_phase = Column(String(32), nullable=True)
    last_completed_phase = Column(String(32), nullable=True)
    phase_attempt = Column(Integer, nullable=False, default=0)
    payload_hash = Column(String(128), nullable=True)
    active_agent_run_id = Column(String(64), nullable=True)
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    cleanup_pending = Column(Boolean, nullable=False, default=False)
    ttl_expires_at = Column(DateTime(timezone=True), nullable=True)
    error = Column(Text, nullable=True)


class InputManifest(Base):
    __tablename__ = "input_manifests"

    job_id = Column(String(64), primary_key=True)
    payload = Column(Text, nullable=False)


class ReviewNotes(Base):
    __tablename__ = "review_notes"

    job_id = Column(String(64), primary_key=True)
    payload = Column(Text, nullable=False)


class Draft(Base):
    __tablename__ = "drafts"

    job_id = Column(String(64), primary_key=True)
    draft_kind = Column(String(32), primary_key=True)
    payload = Column(Text, nullable=False)
    version = Column(Integer, nullable=False, default=1)
    generated_at = Column(DateTime(timezone=True), nullable=True)
    user_reconciled_at = Column(DateTime(timezone=True), nullable=True)
    finalized_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), nullable=True)


class AgentRun(Base):
    __tablename__ = "agent_runs"
    __table_args__ = (Index("ix_agent_runs_job_id", "job_id"),)

    agent_run_id = Column(String(64), primary_key=True)
    job_id = Column(String(64), ForeignKey("jobs.job_id"), nullable=False)
    agent = Column(String(64), nullable=False)
    model = Column(String(64), nullable=False)
    profile = Column(String(32), nullable=False)
    status = Column(String(32), nullable=False)
    duration_ms = Column(Integer, nullable=False, default=0)
    cost_estimate_usd = Column(Float, nullable=False, default=0.0)
    confidence_delta = Column(Float, nullable=False, default=0.0)
    message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=True)


class ExportPayload(Base):
    __tablename__ = "exports"

    job_id = Column(String(64), primary_key=True)
    payload = Column(Text, nullable=False)


class JobEvent(Base):
    __tablename__ = "job_events"
    __table_args__ = (Index("ix_job_events_job_id", "job_id"),)

    event_id = Column(String(64), primary_key=True)
    job_id = Column(String(64), ForeignKey("jobs.job_id"), nullable=False)
    event_type = Column(String(64), nullable=False)
    payload = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)
