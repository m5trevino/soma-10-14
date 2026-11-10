#!/usr/bin/env python3
"""Session census — stamp duplicate + paste-context fields into session.json.

Two facts are recoverable from a session directory without reading a single
chunk boundary:

  1. duplicate_of   -- session.json already carries an exact fingerprint
                       (total_sets + total_session_chars). Two directories that
                       agree on both hold the same conversation exported twice.

  2. paste_context  -- a pasted prior conversation is marked in the chunk text
                       by an ``Original URL:`` header. The file that carries it
                       tells us which chat set and chunk the paste starts on.

Neither fact requires resolving where a paste *ends*. That boundary is left to
a later pass, so ``boundary_confirmed`` is written as ``False`` and every
consumer is told not to assume the span is exact.

Usage:
    # read-only census, prints a summary, writes nothing
    python3 tools/session_census.py

    # write the fields into every session.json (backs up first)
    python3 tools/session_census.py --apply

    # only look at the first N sessions
    python3 tools/session_census.py --limit 50

The script is idempotent: re-running recomputes and overwrites the two fields
it owns, and leaves every other key in session.json untouched.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_ROOT = Path("/media/storage/dendritic123/chat-logs/sessions")

PASTE_MARKER = "Original URL:"
HEAD_BYTES = 200_000

# Groups at or below this char count are treated as trivial (empty/greeting
# sessions) and are reported separately rather than being folded together.
TRIVIAL_CHARS = 500

CENSUS_VERSION = 1

_DATE_PATTERNS = (
    re.compile(r"^(\d{4})-(\d{2})-(\d{2})-"),   # 2026-01-28-...
    re.compile(r"^(\d{2})-(\d{2})-(\d{2})-"),   # 25-11-20-...
    re.compile(r"^(\d{2})(\d{2})(\d{2})-"),     # 260128-...
)
_NO_DATE = (9999, 99, 99)


def _session_date(name: str) -> tuple[int, int, int]:
    """Best-effort leading date, used only to pick a canonical duplicate."""
    for pattern in _DATE_PATTERNS:
        m = pattern.match(name)
        if not m:
            continue
        a, b, c = m.groups()
        if len(a) == 4:
            year, month, day = int(a), int(b), int(c)
        else:
            year, month, day = 2000 + int(a), int(b), int(c)
        if 1 <= month <= 12 and 1 <= day <= 31:
            return (year, month, day)
    return _NO_DATE


def _read_json(path: Path) -> dict | None:
    try:
        with path.open() as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _chunk_files(session_dir: Path) -> list[Path]:
    """Chat-set chunk files, excluding session.json and *.meta.json."""
    out = []
    try:
        entries = list(session_dir.iterdir())
    except OSError:
        return out
    for p in entries:
        if not p.is_file() or p.suffix.lower() != ".json":
            continue
        if p.name == "session.json" or p.name.endswith(".meta.json"):
            continue
        out.append(p)
    return out


def _has_paste_marker(path: Path) -> bool:
    """True when the chunk carries an ``Original URL:`` header in its head."""
    try:
        with path.open("r", errors="ignore") as fh:
            return PASTE_MARKER in fh.read(HEAD_BYTES)
    except OSError:
        return False


def _locate_in_chunk_set(paths: list[Path]) -> tuple[int, int, str, int] | None:
    """Map a marker file to (set_number, chunk_index, chat_set_id, chunk total).

    Reads only the chunk files of the session, and only far enough to learn
    which set the marker file belongs to.
    """
    indexed: dict[str, dict] = {}
    for p in paths:
        data = _read_json(p)
        if not data or "set_number" not in data:
            continue
        cid = str(data.get("chat_set_id") or p.stem)
        indexed[p.stem] = {
            "set": int(data.get("set_number") or 0),
            "chunk": int(data.get("chunk_index") or 0),
            "cid": cid,
        }
    if not indexed:
        return None

    per_set = defaultdict(int)
    for meta in indexed.values():
        per_set[meta["set"]] += 1

    return indexed, per_set


def scan(root: Path, limit: int | None = None) -> dict:
    """Read every session directory and return the census result."""
    try:
        names = sorted(
            d.name for d in root.iterdir()
            if d.is_dir() and (d / "session.json").is_file()
        )
    except OSError as exc:
        raise SystemExit(f"cannot read {root}: {exc}") from exc

    if limit:
        names = names[:limit]

    sessions: dict[str, dict] = {}
    skipped = 0
    for i, name in enumerate(names, 1):
        if i % 500 == 0:
            print(f"  … session.json {i}/{len(names)}", file=sys.stderr, flush=True)
        sdir = root / name
        meta = _read_json(sdir / "session.json")
        if meta is None:
            skipped += 1
            continue
        sessions[name] = {
            "dir": sdir,
            "meta": meta,
            "sets": meta.get("total_sets"),
            "chars": meta.get("total_session_chars"),
        }

    # ---- duplicates ------------------------------------------------------
    groups: dict[tuple, list[str]] = defaultdict(list)
    trivial_groups: dict[tuple, list[str]] = defaultdict(list)
    for name, info in sessions.items():
        sets, chars = info["sets"], info["chars"]
        if not sets or not chars:
            continue
        key = (sets, chars)
        if chars < TRIVIAL_CHARS:
            trivial_groups[key].append(name)
        else:
            groups[key].append(name)

    duplicate_of: dict[str, str | None] = {n: None for n in sessions}
    duplicate_groups = []
    for key, members in groups.items():
        if len(members) < 2:
            continue
        canonical = min(members, key=lambda n: (_session_date(n), n))
        for member in members:
            if member != canonical:
                duplicate_of[member] = canonical
        duplicate_groups.append({
            "sets": key[0],
            "chars": key[1],
            "canonical": canonical,
            "members": sorted(members),
        })

    # ---- paste context ---------------------------------------------------
    paste: dict[str, dict] = {}
    for i, (name, info) in enumerate(sessions.items(), 1):
        if i % 200 == 0:
            print(f"  … paste scan {i}/{len(sessions)}",
                  file=sys.stderr, flush=True)
        sdir = info["dir"]
        chunks = _chunk_files(sdir)
        if not chunks:
            continue
        marked = [p for p in chunks if _has_paste_marker(p)]
        if not marked:
            continue

        located = _locate_in_chunk_set(chunks)
        if located is None:
            paste[name] = {
                "detected": True,
                "start_chunk": None,
                "start_set": None,
                "candidate_span_chunks": None,
                "boundary_confirmed": False,
                "marker_file": Path(marked[0]).name,
                "marker_files": len(marked),
                "note": "marker found but no chunk metadata to locate it",
            }
            continue

        indexed, per_set = located
        # First marker in chunk order decides where the paste starts.
        first = None
        for p in marked:
            meta = indexed.get(p.stem)
            if meta is None:
                continue
            if first is None or (meta["set"], meta["chunk"]) < (first["set"], first["chunk"]):
                first = meta
        if first is None:
            continue

        paste[name] = {
            "detected": True,
            "start_chunk": first["chunk"],
            "start_set": first["set"],
            "candidate_span_chunks": per_set.get(first["set"], 0),
            "boundary_confirmed": False,
            "marker_file": Path(marked[0]).name,
            "marker_files": len(marked),
        }

    return {
        "root": str(root),
        "scanned_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "version": CENSUS_VERSION,
        "sessions": sessions,
        "skipped": skipped,
        "duplicate_of": duplicate_of,
        "duplicate_groups": duplicate_groups,
        "trivial_groups": [
            {"sets": k[0], "chars": k[1], "members": sorted(v)}
            for k, v in trivial_groups.items() if len(v) > 1
        ],
        "paste": paste,
    }


def _atomic_write(path: Path, payload: dict) -> None:
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(payload, fh, indent=2)
            fh.write("\n")
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def apply(census: dict, root: Path) -> dict:
    """Write duplicate_of / paste_context into each session.json."""
    backup_root = root / ".session_census_backup"
    written = 0
    backed_up = 0
    for name, info in census["sessions"].items():
        sdir = info["dir"]
        path = sdir / "session.json"
        meta = _read_json(path)
        if meta is None:
            continue

        bak_dir = backup_root / name
        bak = bak_dir / "session.json"
        if not bak.exists():
            bak_dir.mkdir(parents=True, exist_ok=True)
            _atomic_write(bak, meta)
            backed_up += 1

        meta["duplicate_of"] = census["duplicate_of"].get(name)
        meta["paste_context"] = census["paste"].get(name)
        meta["census_version"] = CENSUS_VERSION

        _atomic_write(path, meta)
        written += 1

    return {"written": written, "backed_up": backed_up,
            "backup_root": str(backup_root)}


def summarise(census: dict) -> None:
    total = len(census["sessions"])
    dup_groups = census["duplicate_groups"]
    dup_sessions = sum(len(g["members"]) for g in dup_groups)
    redundant = sum(len(g["members"]) - 1 for g in dup_groups)
    paste = census["paste"]

    print()
    print("=" * 62)
    print("  SESSION CENSUS")
    print("=" * 62)
    print(f"  sessions scanned        : {total}")
    print(f"  unreadable session.json : {census['skipped']}")
    print()
    print(f"  duplicate groups        : {len(dup_groups)}")
    print(f"  sessions in those       : {dup_sessions}")
    print(f"  redundant copies        : {redundant}")
    print(f"  trivial groups (<{TRIVIAL_CHARS} chars): {len(census['trivial_groups'])}")
    print()
    print(f"  sessions with a paste   : {len(paste)}")
    starts = defaultdict(int)
    for info in paste.values():
        starts[(info["start_set"], info["start_chunk"])] += 1
    for (s, c), n in sorted(starts.items(), key=lambda x: -x[1])[:5]:
        print(f"    start set {s} chunk {c}: {n} session(s)")
    print()

    if dup_groups:
        print("  Largest duplicate groups:")
        for g in sorted(dup_groups, key=lambda g: -len(g["members"]))[:10]:
            print(f"    {len(g['members']):>2} copies  "
                  f"sets={g['sets']:<4} chars={g['chars']:<9} "
                  f"canonical={g['canonical'][:44]}")
        print()

    if paste:
        print("  Largest pastes (span is an upper bound, not exact):")
        for name, info in sorted(
                paste.items(),
                key=lambda kv: -(kv[1].get("candidate_span_chunks") or 0))[:10]:
            print(f"    {name[:44]:44} set {str(info['start_set']):>3} "
                  f"chunk {str(info['start_chunk']):>3} "
                  f"span<={info['candidate_span_chunks']}")
        print()


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Stamp duplicate_of / paste_context into session.json")
    ap.add_argument("--root", default=str(DEFAULT_ROOT))
    ap.add_argument("--apply", action="store_true",
                    help="write the fields (backs up session.json first)")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--report", default=None,
                    help="write the full census JSON to this path")
    args = ap.parse_args()

    root = Path(args.root).expanduser().resolve()
    if not root.is_dir():
        print(f"error: {root} is not a directory", file=sys.stderr)
        return 1

    print(f"scanning {root}", file=sys.stderr)
    census = scan(root, limit=args.limit)
    summarise(census)

    if args.report:
        out = Path(args.report).expanduser()
        out.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "root": census["root"],
            "scanned_at": census["scanned_at"],
            "version": census["version"],
            "duplicate_groups": census["duplicate_groups"],
            "trivial_groups": census["trivial_groups"],
            "paste": census["paste"],
            "duplicate_of": census["duplicate_of"],
        }
        out.write_text(json.dumps(payload, indent=2) + "\n")
        print(f"report written to {out}")

    if not args.apply:
        print("dry run — nothing written. re-run with --apply to stamp the fields.")
        return 0

    result = apply(census, root)
    print(f"stamped {result['written']} session.json file(s)")
    print(f"backed up {result['backed_up']} to {result['backup_root']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
