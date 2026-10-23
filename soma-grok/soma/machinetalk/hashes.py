"""Canonical JSON + SHA-256 helpers for machine-talk payloads."""
from __future__ import annotations

import hashlib
import json


def canonical_json(obj) -> str:
    """Canonical serialization: sorted keys, compact separators, no ASCII escapes.

    This is the exact form the distiller hashes (and echoes back), so every
    downstream stage verifies against the same bytes.
    """
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def chatset_hash_for(raw_chat_set) -> str:
    """SHA-256 over the canonical raw_chat_set array (no whitespace variance)."""
    return sha256_hex(canonical_json(raw_chat_set))
