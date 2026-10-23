"""Fixed session_seeder — adapts flat file to work with rebuilt Soma."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from store import Soma, Node
from pipeline.chat_log_adapter import ChatSetRecord


def seed_session(
    soma: Soma,
    chat_sets: list[ChatSetRecord],
    session_id: str | None = None,
    session_type: str = "conversations",
) -> tuple[str, dict[str, int]]:
    """Seed a Soma graph with one session's ChatSets.

    Returns (anchor_id, stats_dict).
    """
    if not session_id and chat_sets:
        session_id = f"session-{uuid.uuid4().hex[:8]}"

    stats = {"nodes_created": 0, "edges_created": 0}

    # 1. Create SessionAnchor
    if session_id:
        anchor_id = soma.create_node("SessionAnchor", {
            "id": session_id,
            "session_id": session_id,
            "session_type": session_type,
            "chat_set_count": len(chat_sets),
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        stats["nodes_created"] += 1

    # 2. Create ChatSet nodes and edges
    for cs in chat_sets:
        cs_id = f"cs-{cs.chat_set_id}"
        soma.create_node("ChatSet", {
            "id": cs_id,
            "chat_set_id": cs.chat_set_id,
            "session_id": cs.session_id,
            "set_number": cs.set_number,
            "user_text": cs.user_text,
            "assistant_text": cs.assistant_text,
        })
        stats["nodes_created"] += 1

        # Edge from SessionAnchor (if session_id exists)
        if session_id:
            soma.create_edge(session_id, "HAS_CHATSET", cs_id)
            stats["edges_created"] += 1

    return anchor_id if session_id else "", stats