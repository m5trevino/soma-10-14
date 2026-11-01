"""Provenance checks: does an emitted claim actually exist in the source?

The distiller and introbeaver both emit ``char_start`` / ``char_end`` with a
verbatim string. Nothing else in the pipeline reads those offsets, so an
emitted directive can describe text that was never in the conversation and
still be accepted. This module closes that: every entry is checked against
the NFC-normalized source before it is allowed into the graph.

``GROUND_TRUTH.md`` invariant 3:
    An emitted directive must be a literal substring of the source at the
    ``char_start``/``char_end`` it claims. Otherwise the stage fails.

Offsets are Unicode codepoint offsets into the normalized content, half-open
``[start, end)`` — the contract the instruction bodies already specify.
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field


def normalize(text: str) -> str:
    """NFC-normalize, the encoding the instruction contracts require."""
    return unicodedata.normalize("NFC", text or "")


@dataclass
class ProvenanceIssue:
    entry_id: str
    kind: str
    detail: str

    def __str__(self) -> str:
        return f"{self.entry_id}: {self.kind} ({self.detail})"


@dataclass
class ProvenanceReport:
    checked: int = 0
    verified: int = 0
    issues: list[ProvenanceIssue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.issues

    def summary(self) -> str:
        if not self.issues:
            return f"{self.verified}/{self.checked} entries verified against source"
        kinds = sorted({i.kind for i in self.issues})
        return (f"{self.verified}/{self.checked} verified; "
                f"{len(self.issues)} rejected ({', '.join(kinds)})")


def _source_text(raw_chat_set: list[dict]) -> str:
    """The exact string offsets refer to: every turn joined as given.

    The instruction contracts define offsets into ``content`` per message.
    Entries carry ``source_msg_index``, so a check is performed against that
    one message's normalized content.
    """
    return "\n".join(normalize(m.get("content") or "") for m in raw_chat_set or [])


def _message_text(raw_chat_set: list[dict], index: int) -> str | None:
    if not isinstance(index, int) or index < 0 or index >= len(raw_chat_set or []):
        return None
    return normalize((raw_chat_set[index] or {}).get("content") or "")


def verify_entries(raw_chat_set: list[dict], entries: list[dict],
                   text_key: str = "verbatim_text",
                   id_key: str = "entry_id",
                   index_key: str = "source_msg_index") -> ProvenanceReport:
    """Check every entry's claimed slice against the message it cites.

    A rejection means the entry describes text that is not in the transcript
    at the position it names. That is the difference between an extraction
    and a fabrication.

    ``text_key`` / ``index_key`` name the fields the stage's own output
    contract uses: the distiller writes ``text`` and ``turn``, the
    introbeaver writes ``verbatim_text`` and ``source_msg_index``.
    """
    report = ProvenanceReport()
    joined = _source_text(raw_chat_set)

    for i, entry in enumerate(entries or []):
        if not isinstance(entry, dict):
            continue
        report.checked += 1
        eid = str(entry.get(id_key) or entry.get("text", "")[:24] or f"entry[{i}]")
        text = entry.get(text_key)
        if text is None and text_key != "text":
            text = entry.get("text")
        start = entry.get("char_start")
        end = entry.get("char_end")

        if not isinstance(text, str) or not text:
            report.issues.append(ProvenanceIssue(eid, "missing_text", text_key))
            continue
        if not isinstance(start, int) or not isinstance(end, int):
            report.issues.append(ProvenanceIssue(eid, "missing_offsets", ""))
            continue
        if start < 0 or end <= start:
            report.issues.append(
                ProvenanceIssue(eid, "bad_range", f"{start}..{end}"))
            continue

        msg_index = entry.get(index_key)
        if msg_index is None and index_key != "turn":
            msg_index = entry.get("turn")
        if isinstance(msg_index, int):
            source = _message_text(raw_chat_set, msg_index)
            if source is None:
                report.issues.append(
                    ProvenanceIssue(eid, "bad_msg_index", str(msg_index)))
                continue
        else:
            source = joined

        if end > len(source):
            report.issues.append(
                ProvenanceIssue(eid, "offset_past_end",
                                f"{end} > {len(source)}"))
            continue

        actual = source[start:end]
        if actual != normalize(text):
            report.issues.append(
                ProvenanceIssue(
                    eid, "text_mismatch",
                    f"claimed {normalize(text)[:40]!r} "
                    f"actual {actual[:40]!r}"))
            continue

        report.verified += 1

    return report


def verify_distiller(payload: dict, raw_chat_set: list[dict]) -> ProvenanceReport:
    """Verify every list in a distiller output that carries offsets.

    The TB-001 contract writes ``text`` / ``turn`` / ``char_start`` /
    ``char_end``, so those are the field names checked here.
    """
    body = payload.get("distiller_output") if isinstance(
        payload.get("distiller_output"), dict) else payload
    entries: list[dict] = []
    for key in ("directives", "constraints", "preferences", "questions",
                "corrections", "confirmations", "artifacts"):
        for i, item in enumerate(body.get(key) or []):
            if isinstance(item, dict):
                item = dict(item)
                item.setdefault("entry_id", f"{key}[{i}]")
                entries.append(item)
    return verify_entries(raw_chat_set, entries, text_key="text",
                          index_key="turn")


def verify_distiller(payload: dict, raw_chat_set: list[dict]) -> ProvenanceReport:
    """Verify every list in a distiller output that carries offsets."""
    body = payload.get("distiller_output") if isinstance(
        payload.get("distiller_output"), dict) else payload
    entries: list[dict] = []
    for key in ("directives", "constraints", "preferences", "questions",
                "corrections", "confirmations", "artifacts"):
        for i, item in enumerate(body.get(key) or []):
            if isinstance(item, dict):
                item = dict(item)
                item.setdefault("entry_id", f"{key}[{i}]")
                entries.append(item)
    return verify_entries(raw_chat_set, entries)


def verify_introbeaver(payload: dict, raw_chat_set: list[dict]) -> ProvenanceReport:
    """Verify introbeaver's ``entries[]`` against the messages they cite."""
    body = payload.get("introbeaver_output") if isinstance(
        payload.get("introbeaver_output"), dict) else payload
    return verify_entries(raw_chat_set, body.get("entries") or [],
                          text_key="verbatim_text", id_key="entry_id")
