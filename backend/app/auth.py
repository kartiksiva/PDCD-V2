"""API key authentication for PFCD backend."""

from __future__ import annotations

import os
import secrets
from typing import Optional

from fastapi import HTTPException, Security
from fastapi.security import APIKeyHeader

_API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)


def _reload_configured_key() -> None:
    """No-op shim — kept for lifespan callers. The key is read per-request."""


async def verify_api_key(api_key: Optional[str] = Security(_API_KEY_HEADER)) -> None:
    """Enforce X-API-Key header when PFCD_API_KEY env var is set.

    - PFCD_API_KEY unset → auth disabled (local dev).
    - Header missing, auth enabled → 401 Unauthorized.
    - Header wrong → 403 Forbidden.
    - Uses secrets.compare_digest to prevent timing attacks.
    """
    configured_key = os.environ.get("PFCD_API_KEY", "")
    if not configured_key:
        return
    if api_key is None:
        raise HTTPException(status_code=401, detail="Missing X-API-Key header.")
    if not secrets.compare_digest(api_key, configured_key):
        raise HTTPException(status_code=403, detail="Invalid API key.")
