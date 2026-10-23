"""Shared workspace path for Drafter and AxonHillock.

Both stages must read and write the same directory.
"""
from __future__ import annotations

import re
from pathlib import Path


def sanitize_session_id(session_id: str) -> str:
    return re.sub(r"[^\w.-]", "_", session_id)


def workspace_for(session_id: str, root: Path | None = None) -> Path:
    """Return the workspace directory for a session. Creates it if missing."""
    base = root if root is not None else Path("/workspace/artifacts/soma-grok/workspaces")
    path = base / sanitize_session_id(session_id)
    path.mkdir(parents=True, exist_ok=True)
    return path
