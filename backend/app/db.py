"""Database helpers for PFCD backend."""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

DEFAULT_DATABASE_URL = "sqlite:///./pfcd.db"

_engine_cache: dict[str, object] = {}
_factory_cache: dict[str, object] = {}


def _build_engine(database_url: str):
    if database_url.startswith("sqlite"):
        return create_engine(
            database_url,
            future=True,
            connect_args={"check_same_thread": False},
        )
    return create_engine(database_url, future=True)


def get_database_url() -> str:
    return os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)


def get_engine(database_url: str | None = None):
    """Return a cached SQLAlchemy engine for *database_url* (or env URL)."""
    url = database_url or get_database_url()
    if url not in _engine_cache:
        _engine_cache[url] = _build_engine(url)
    return _engine_cache[url]


def _get_session_factory(database_url: str | None = None):
    url = database_url or get_database_url()
    if url not in _factory_cache:
        _factory_cache[url] = sessionmaker(
            bind=get_engine(url), autoflush=False, autocommit=False, future=True
        )
    return _factory_cache[url]


def clear_engine_cache() -> None:
    """Dispose all cached engines and clear caches (test isolation helper)."""
    for engine in _engine_cache.values():
        try:
            engine.dispose()
        except Exception:
            pass
    _engine_cache.clear()
    _factory_cache.clear()


@contextmanager
def session_scope(database_url: str | None = None) -> Iterator[Session]:
    session = _get_session_factory(database_url)()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
