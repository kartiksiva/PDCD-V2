"""Durable job persistence for PFCD backend."""

from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional

from sqlalchemy import Column, MetaData, String, Table, Text, create_engine, select


DEFAULT_DATABASE_URL = "sqlite:///./pfcd.db"


class JobRepository:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        self.engine = create_engine(database_url, future=True)
        self.metadata = MetaData()
        self.jobs = Table(
            "jobs",
            self.metadata,
            Column("job_id", String(64), primary_key=True),
            Column("status", String(32), nullable=False),
            Column("created_at", String(64), nullable=False),
            Column("updated_at", String(64), nullable=False),
            Column("payload", Text, nullable=False),
        )

    @classmethod
    def from_env(cls) -> "JobRepository":
        database_url = os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)
        return cls(database_url)

    def init_db(self) -> None:
        self.metadata.create_all(self.engine)

    def _serialize(self, payload: Dict[str, Any]) -> str:
        return json.dumps(payload, ensure_ascii=True, separators=(",", ":"))

    def _deserialize(self, payload: str) -> Dict[str, Any]:
        return json.loads(payload)

    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        with self.engine.connect() as conn:
            row = conn.execute(
                select(self.jobs.c.payload).where(self.jobs.c.job_id == job_id)
            ).fetchone()
        if not row:
            return None
        return self._deserialize(row[0])

    def upsert_job(self, job_id: str, payload: Dict[str, Any]) -> None:
        created_at = payload.get("created_at") or payload.get("updated_at")
        updated_at = payload.get("updated_at") or payload.get("created_at")
        status = payload.get("status", "unknown")
        serialized = self._serialize(payload)
        with self.engine.begin() as conn:
            result = conn.execute(
                self.jobs.update()
                .where(self.jobs.c.job_id == job_id)
                .values(
                    status=status,
                    created_at=created_at,
                    updated_at=updated_at,
                    payload=serialized,
                )
            )
            if result.rowcount == 0:
                conn.execute(
                    self.jobs.insert().values(
                        job_id=job_id,
                        status=status,
                        created_at=created_at,
                        updated_at=updated_at,
                        payload=serialized,
                    )
                )

    def delete_job(self, job_id: str) -> None:
        with self.engine.begin() as conn:
            conn.execute(self.jobs.delete().where(self.jobs.c.job_id == job_id))
