"""Project-agnostic source loader.

A source directory contains one or more session directories. Each session
directory has `session.json` plus one JSON file per physical chatset chunk
(``NNNNNN.json`` or ``NNNNNN.K.json`` for chunked sets).

ChatSet unit (verified against every session.json `total_sets`):
    all files sharing a `set_number` (== `source_chat_set_id`) form ONE
    logical ChatSet. Chunks are sorted by their natural chunk index and
    concatenated to reconstruct the full transcript.

The canonical `raw_chat_set` (the array that gets hashed and echoed by
every stage) is built per ChatSet as:

    [{"role": "USER",  "content": <full user text>},
     {"role": "AGENT", "content": <full assistant text>}]

(empty roles dropped; order fixed). The distiller receives the same
content as a readable transcript under [RAW_CHAT_TRANSCRIPT].
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

_CHUNK_RE = re.compile(r"^(\d+)\.(\d+)\.json$")


@dataclass
class ChatSet:
    session_id: str
    set_number: int
    source_chat_set_id: str
    files: list[str]                        # chunk filenames in order
    raw_chat_set: list[dict]                # canonical hashed array
    user_text: str
    assistant_text: str
    is_chunked: bool
    chars: int
    chatset_hash: str = ""
    models: list[str] = field(default_factory=list)
    provider: str = ""
    total_sets: int = 0

    @property
    def chatset_id(self) -> str:
        return f"{self.session_id}:{self.set_number}"

    def transcript(self) -> str:
        """Readable transcript for the distiller's [RAW_CHAT_TRANSCRIPT]."""
        parts = []
        for m in self.raw_chat_set:
            parts.append(f"[{m['role']}]\n{m['content']}")
        return "\n\n".join(parts)


@dataclass
class Session:
    session_id: str
    path: Path
    total_sets: int | None = None
    provider: str = ""
    models_used: dict = field(default_factory=dict)
    chatsets: list[ChatSet] = field(default_factory=list)
    title: str = ""

    @property
    def sort_key(self) -> str:
        # Oldest first. Session ids embed a YYMMDD-HHMM timestamp.
        return self.session_id


def _natural_chunk_index(filename: str) -> int:
    m = _CHUNK_RE.match(filename)
    return int(m.group(2)) if m else 0


def load_chatset(session_id: str, path: Path, set_number: int,
                 files: list[Path]) -> ChatSet:
    """Assemble one logical ChatSet from its physical chunk files."""
    files.sort(key=lambda p: _natural_chunk_index(p.name))
    user_parts: list[str] = []
    asst_parts: list[str] = []
    models: list[str] = []
    provider = ""
    src_id = ""
    is_chunked = False
    for p in files:
        rec = json.loads(p.read_text())
        src_id = rec.get("source_chat_set_id", src_id)
        provider = rec.get("provider", provider)
        if rec.get("model") and rec["model"] not in models:
            models.append(rec["model"])
        is_chunked = is_chunked or bool(rec.get("is_chunked"))
        user_parts.append(rec.get("user_text", "") or "")
        asst_parts.append(rec.get("assistant_text", "") or "")
    user_text = "".join(user_parts).strip()
    asst_text = "".join(asst_parts).strip()
    raw: list[dict] = []
    if user_text:
        raw.append({"role": "USER", "content": user_text})
    if asst_text:
        raw.append({"role": "AGENT", "content": asst_text})
    from .hashes import chatset_hash_for
    return ChatSet(
        session_id=session_id,
        set_number=int(set_number),
        source_chat_set_id=src_id,
        files=[p.name for p in files],
        raw_chat_set=raw,
        user_text=user_text,
        assistant_text=asst_text,
        is_chunked=is_chunked,
        chars=len(user_text) + len(asst_text),
        chatset_hash=chatset_hash_for(raw),
        models=models,
        provider=provider,
    )


def load_session(session_dir: Path) -> Session:
    session_id = session_dir.name
    sess = Session(session_id=session_id, path=session_dir)
    sj = session_dir / "session.json"
    if sj.exists():
        meta = json.loads(sj.read_text())
        sess.total_sets = meta.get("total_sets")
        sess.provider = meta.get("provider", "")
        sess.models_used = meta.get("models_used", {})
        # Set title from session.json, fall back to session_id
        sess.title = meta.get("title") or meta.get("name", session_id)
    by_set: dict[int, list[Path]] = {}
    for f in sorted(session_dir.glob("*.json")):
        if f.name == "session.json" or f.name.startswith("tool-"):
            continue
        try:
            rec = json.loads(f.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        if "set_number" not in rec:
            continue
        by_set.setdefault(int(rec["set_number"]), []).append(f)
    for set_number in sorted(by_set):
        chatset = load_chatset(session_id, session_dir, set_number, by_set[set_number])
        chatset.total_sets = sess.total_sets or len(by_set)
        sess.chatsets.append(chatset)
    return sess


def load_source(source_dir: Path) -> list[Session]:
    """Load every session under source_dir, oldest first.

    Accepts either a directory OF session dirs, or a single session dir
    (detected by the presence of session.json + chatset .json files).
    """
    source_dir = Path(source_dir).resolve()
    if not source_dir.is_dir():
        raise FileNotFoundError(f"source dir not found: {source_dir}")
    if (source_dir / "session.json").exists():
        return [load_session(source_dir)]
    sessions = []
    for child in sorted(source_dir.iterdir()):
        if child.is_dir() and (child / "session.json").exists():
            sessions.append(load_session(child))
    if not sessions:
        raise FileNotFoundError(
            f"no session dirs (with session.json) found under {source_dir}")
    sessions.sort(key=lambda s: s.sort_key)
    return sessions
