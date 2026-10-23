from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence


@dataclass(frozen=True, slots=True)
class ChatSetRecord:
    chat_set_id: str
    session_id: str
    set_number: int
    user_text: str
    assistant_text: str = ""

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ChatSetRecord":
        required = ("chat_set_id", "session_id", "set_number", "user_text")
        for key in required:
            if key not in d:
                raise ValueError(f"Missing required field: {key}")
        return cls(
            chat_set_id=d["chat_set_id"],
            session_id=d["session_id"],
            set_number=d["set_number"],
            user_text=d["user_text"],
            assistant_text=d.get("assistant_text", ""),
        )


def parse_chat_log(data: Any) -> list[ChatSetRecord]:
    """Parse a chat log (list, dict, or nested session) into ChatSetRecords."""
    if isinstance(data, list):
        raw = data
    elif isinstance(data, dict):
        # Try common keys
        for key in ("chat_sets", "messages", "turns"):
            if key in data and isinstance(data[key], list):
                raw = data[key]
                break
        else:
            # Maybe a single-session dict — look for any list value
            for v in data.values():
                if isinstance(v, list) and v:
                    if isinstance(v[0], dict):
                        raw = v
                        break
            else:
                raise ValueError("Cannot find list of chat sets in dict")
    else:
        raise TypeError(f"Expected list or dict, got {type(data).__name__}")

    records: list[ChatSetRecord] = []
    seen_ids: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        rec = ChatSetRecord.from_dict(item)
        if rec.chat_set_id in seen_ids:
            raise ValueError(f"Duplicate chat_set_id: {rec.chat_set_id}")
        seen_ids.add(rec.chat_set_id)
        records.append(rec)

    records.sort(key=lambda r: r.set_number)
    return records


def parse_directory(dirpath: str | Path) -> dict[str, list[ChatSetRecord]]:
    """Parse all JSON files in a directory, grouping by session_id."""
    results: dict[str, list[ChatSetRecord]] = {}
    for fp in sorted(Path(dirpath).glob("*.json")):
        with open(fp) as f:
            data = json.load(f)
        try:
            records = parse_chat_log(data)
        except (ValueError, TypeError, KeyError):
            continue
        for r in records:
            results.setdefault(r.session_id, []).append(r)
    return results