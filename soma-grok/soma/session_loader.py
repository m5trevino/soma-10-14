"""Session loader — pure function to load chat-set records from a directory.

TB-FIX-003: Load chat-set records from a directory.
A missing or empty directory returns an empty list and a reason. It never raises IndexError.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


REQUIRED_KEYS = ("chat_set_id", "session_id", "set_number", "user_text")


def load_session(path: Path) -> tuple[list[dict[str, Any]], str]:
    """Load chat-set records from a directory.

    Args:
        path: Directory containing JSON files (one ChatSet per file).

    Returns:
        Tuple of (records, reason) where:
        - records: list of dicts with keys chat_set_id, session_id, set_number, user_text,
                   and optionally assistant_text
        - reason: 'ok' | 'missing_dir' | 'no_records'

    Behavior:
        - Missing path -> ([], 'missing_dir')
        - Empty directory -> ([], 'no_records')
        - Valid JSON with all required keys -> record included, reason 'ok'
        - JSON missing required keys -> skipped (not raised)
        - Invalid JSON -> skipped (not raised)
        - Never indexes [0] on empty list
    """
    if not path.exists():
        return [], "missing_dir"

    if not path.is_dir():
        return [], "missing_dir"

    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for fp in sorted(path.glob("*.json")):
        try:
            with open(fp) as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue  # Skip invalid JSON / unreadable files

        if not isinstance(data, dict):
            continue  # Skip non-dict JSON (arrays, primitives)

        # Check required keys
        if not all(k in data for k in REQUIRED_KEYS):
            continue  # Skip records missing required keys

        cs_id = data["chat_set_id"]
        if cs_id in seen_ids:
            continue  # Skip duplicates
        seen_ids.add(cs_id)

        # Parse set_number as int
        try:
            sn = int(data.get("set_number", 0))
        except (ValueError, TypeError):
            sn = 0

        records.append({
            "chat_set_id": cs_id,
            "session_id": data["session_id"],
            "set_number": sn,
            "user_text": str(data.get("user_text", "")),
            "assistant_text": str(data.get("assistant_text", "")),
        })

    if not records:
        return [], "no_records"

    records.sort(key=lambda r: r["set_number"])
    return records, "ok"