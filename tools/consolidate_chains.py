#!/usr/bin/env python3
"""Consolidate session chains → chronological deduped sessions.

One logical conversation spills across several session directories when a
context-limit handoff pastes the prior conversation at the *front* of a new
session. The carryover is a verbatim prefix, so a single content hash (the
same ``sha256(user_text + "\\x00" + assistant_text)`` that
``soma.machinetalk.source.load_session`` uses for its within-session dedup)
collapses it: walk every chunk oldest→newest across the chain and keep the
first occurrence of each hash.

Output is written to a *mirror* directory (``--target``), never into the
source root, so the source stays pristine. A consolidated session is just a
plain session directory (``session.json`` + ``NNNNN.json`` chunks), so the
pipeline ingests it unchanged via ``source.load_source``.

Usage:
    python3 tools/consolidate_chains.py --chain 25-12-02-copy.of.copy.of.current.code.issues --dry-run
    python3 tools/consolidate_chains.py --chain <name> --target /path/to/lineage
    python3 tools/consolidate_chains.py --all --target /path/to/lineage
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

# Reuse the census's date parsing (import, don't copy).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from session_census import _session_date  # noqa: E402

DEFAULT_ROOT = Path("/media/storage/dendritic123/chat-logs/sessions")
DEFAULT_DB = Path("/media/storage/graphdb/session_site/vault.db")
DEFAULT_TARGET = Path("/media/storage/dendritic123/chat-logs/lineage")

# A content-prefix edge requires at least this many shared chunks so a single
# coincidental first-chunk match cannot merge unrelated sessions.
MIN_SHARED = 2
# A first-chunk hash appearing in more than this many sessions is treated as
# non-significant (a generic opener), not a paste signal.
MAX_FANOUT = 100


def chunk_digest(user_text: str, assistant_text: str) -> str:
    """Content digest identical to ``source.load_session``'s within-session dedup."""
    return hashlib.sha256(
        (user_text + "\x00" + assistant_text).encode("utf-8")).hexdigest()


@dataclass
class Chunk:
    filename: str
    record: dict
    digest: str


def read_session_chunks(session_dir: Path) -> list[Chunk]:
    """Read a session's chunks, within-session-deduped, in deterministic order.

    Mirrors ``soma.machinetalk.source.load_session``: same candidate filter,
    same sort (set_number, chunk_index, source_chunk_id, filename), same digest.
    """
    candidates: list[dict] = []
    for f in session_dir.glob("*.json"):
        if f.name == "session.json" or f.name.startswith("tool-"):
            continue
        try:
            rec = json.loads(f.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        if "set_number" not in rec:
            continue
        user_text = rec.get("user_text") or ""
        asst_text = rec.get("assistant_text") or ""
        candidates.append({
            "file": f,
            "group": int(rec["set_number"]),
            "chunk_index": int(rec.get("chunk_index") or 0),
            "source_chunk_id": str(rec.get("chat_set_id") or f.stem),
            "record": rec,
            "digest": chunk_digest(user_text, asst_text),
        })
    candidates.sort(key=lambda u: (
        u["group"], u["chunk_index"], u["source_chunk_id"], u["file"].name))

    chunks: list[Chunk] = []
    seen: set[str] = set()
    for cand in candidates:
        if cand["digest"] in seen:
            continue
        seen.add(cand["digest"])
        chunks.append(Chunk(cand["file"].name, cand["record"], cand["digest"]))
    return chunks


def _dir_name(session_id: str) -> str:
    return (session_id or "").split("/")[-1]


@dataclass
class Chain:
    key: str
    members: list[str]  # dir names, oldest → newest
    total_chunks: int = 0       # raw chunk count across all members
    unique_chunks: int = 0      # distinct chunk hashes after dedup
    generations: int = 0        # distinct content sets (full dups collapse)


def _order_members(members: list[str], digest_sets: dict[str, set[str]]) -> list[str]:
    """Order a chain's members oldest→newest by the paste direction.

    A continuation pastes its parent's content at the front, so the child's
    chunk-hash set is a strict superset of the parent's. Topologically sorting
    by ``digest_sets[A] ⊊ digest_sets[B]`` (parent first) reconstructs the
    lineage even when several generations share the same calendar date.
    Strict subset is acyclic, so Kahn's algorithm terminates without a guard.
    """
    children: dict[str, set[str]] = {m: set() for m in members}
    indeg: dict[str, int] = {m: 0 for m in members}
    for b in members:
        sb = digest_sets[b]
        for a in members:
            if a == b:
                continue
            if digest_sets[a] < sb:  # a is a strict subset → a is the parent
                children[a].add(b)
                indeg[b] += 1

    order: list[str] = []
    remaining: set[str] = set(members)
    while remaining:
        ready = [m for m in remaining if indeg[m] == 0]
        if not ready:  # defensive: strict subset is acyclic, this cannot happen
            ready = [min(remaining, key=lambda m: (_session_date(m), m))]
        for m in sorted(ready, key=lambda m: (_session_date(m), m)):
            order.append(m)
            remaining.discard(m)
            for c in children[m]:
                indeg[c] -= 1
    return order


def resolve_chains(root: Path, db_path: Path,
                   min_shared: int = MIN_SHARED,
                   max_fanout: int = MAX_FANOUT) -> list[Chain]:
    """Resolve every chain (connected component) across three edge types."""
    dirs = sorted(
        d.name for d in root.iterdir()
        if d.is_dir() and (d / "session.json").is_file())

    parent = {d: d for d in dirs}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    # ── read every chunk once: build the reverse index + per-dir metadata ──
    digest_to_dirs: dict[str, set[str]] = defaultdict(set)
    digest_sets: dict[str, set[str]] = {}
    first_digest: dict[str, str | None] = {}
    chunk_counts: dict[str, int] = {}
    for d in dirs:
        chunks = read_session_chunks(root / d)
        ds = {c.digest for c in chunks}
        digest_sets[d] = ds
        first_digest[d] = chunks[0].digest if chunks else None
        chunk_counts[d] = len(chunks)
        for dg in ds:
            digest_to_dirs[dg].add(d)

    # ── edge 1: census duplicate_of (full copies) ────────────────────────
    for d in dirs:
        try:
            meta = json.loads((root / d / "session.json").read_text())
        except (OSError, json.JSONDecodeError):
            continue
        dup = meta.get("duplicate_of")
        if dup and dup in parent:
            union(d, dup)

    # ── edge 2: session_chains (same dir name under multiple accounts) ───
    try:
        conn = sqlite3.connect(str(db_path))
        cur = conn.cursor()
        rows = cur.execute("SELECT session_ids FROM session_chains").fetchall()
        conn.close()
    except sqlite3.Error:
        rows = []
    for (sids_json,) in rows:
        try:
            sids = json.loads(sids_json)
        except (json.JSONDecodeError, TypeError):
            continue
        members = [n for n in (_dir_name(s) for s in sids) if n in parent]
        for m in members[1:]:
            union(members[0], m)

    # ── edge 3: content-prefix (B's first chunk is carried from an older A) ──
    for d in dirs:
        fd = first_digest.get(d)
        if not fd:
            continue
        others = digest_to_dirs.get(fd)
        if not others or len(others) > max_fanout:
            continue
        for other in others:
            if other == d:
                continue
            if len(digest_sets[d] & digest_sets[other]) >= min_shared:
                union(d, other)

    # ── group into components, ordered oldest → newest ──────────────────
    groups: dict[str, list[str]] = defaultdict(list)
    for d in dirs:
        groups[find(d)].append(d)

    chains: list[Chain] = []
    for members in groups.values():
        members = _order_members(members, digest_sets)
        union_digests: set[str] = set()
        for m in members:
            union_digests |= digest_sets[m]
        generations = len({frozenset(digest_sets[m]) for m in members})
        chains.append(Chain(
            key=members[0],
            members=members,
            total_chunks=sum(chunk_counts[m] for m in members),
            unique_chunks=len(union_digests),
            generations=generations,
        ))
    chains.sort(key=lambda c: (_session_date(c.key), c.key))
    return chains


def dedup_chain(root: Path, members: list[str]) -> tuple[list[Chunk], list[dict]]:
    """Dedup a chain's chunks chronologically without writing anything.

    Returns ``(emitted, dropped)`` where ``emitted`` is the unique chunk list
    (oldest→newest) and ``dropped`` records every carried-forward duplicate.
    """
    seen: set[str] = set()
    emitted: list[Chunk] = []
    dropped: list[dict] = []
    for member in members:
        for c in read_session_chunks(root / member):
            if c.digest in seen:
                dropped.append({"digest": c.digest, "from": member,
                                "file": c.filename})
                continue
            seen.add(c.digest)
            emitted.append(c)
    return emitted, dropped


def consolidate_chain(root: Path, target: Path, chain: Chain) -> dict:
    """Dedup one chain chronologically and write a consolidated session dir."""
    emitted, dropped = dedup_chain(root, chain.members)

    # Consolidated output lives under a dedicated subdir so it never collides
    # with (or replaces) the mirrored source dirs that share the same name.
    out_dir = target / "consolidated" / chain.key
    out_dir.mkdir(parents=True, exist_ok=True)

    total_chars = 0
    providers: Counter = Counter()
    models: Counter = Counter()
    for i, c in enumerate(emitted, 1):
        rec = dict(c.record)
        rec["set_number"] = i
        (out_dir / f"{i:05d}.json").write_text(
            json.dumps(rec, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        total_chars += len(rec.get("user_text") or "") + len(rec.get("assistant_text") or "")
        if rec.get("provider"):
            providers[rec["provider"]] += 1
        if rec.get("model"):
            models[rec["model"]] += 1

    session_meta = {
        "session_id": chain.key,
        "provider": providers.most_common(1)[0][0] if providers else "",
        "total_sets": len(emitted),
        "total_session_chars": total_chars,
        "models_used": dict(models),
        # Normalized source-session fields (stamped by session_census.py).
        # A consolidated session is canonical: not a duplicate, no paste.
        "duplicate_of": None,
        "paste_context": None,
        "census_version": 1,
    }
    (out_dir / "session.json").write_text(
        json.dumps(session_meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # Audit provenance lives in a sidecar so session.json stays normalized.
    provenance = {
        "source_members": chain.members,
        "emitted_chunks": len(emitted),
        "dropped_chunks": len(dropped),
        "dropped_sample": dropped[:20],
        "ordering_rule": "chronological oldest→newest, content-hash dedup",
    }
    (out_dir / "provenance.json").write_text(
        json.dumps(provenance, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    return {
        "key": chain.key,
        "members": chain.members,
        "emitted": len(emitted),
        "dropped": len(dropped),
        "output_dir": str(out_dir),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Consolidate session chains")
    ap.add_argument("--root", default=str(DEFAULT_ROOT))
    ap.add_argument("--db", default=str(DEFAULT_DB))
    ap.add_argument("--target", default=str(DEFAULT_TARGET))
    ap.add_argument("--chain", default=None,
                    help="session dir name to consolidate (resolves its chain)")
    ap.add_argument("--all", action="store_true",
                    help="consolidate every chain")
    ap.add_argument("--min-members", type=int, default=1,
                    help="with --all, only consolidate chains with at least N members")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the plan, write nothing")
    ap.add_argument("--min-shared", type=int, default=MIN_SHARED)
    args = ap.parse_args()

    root = Path(args.root).expanduser()
    db = Path(args.db).expanduser()
    target = Path(args.target).expanduser()

    chains = resolve_chains(root, db, min_shared=args.min_shared)

    if args.chain:
        match = next((c for c in chains if args.chain in c.members), None)
        if match is None:
            print(f"no chain contains session dir {args.chain!r}", file=sys.stderr)
            return 1
        selected = [match]
    elif args.all:
        selected = [c for c in chains if len(c.members) >= args.min_members]
    else:
        multi = sum(1 for c in chains if len(c.members) > 1)
        print(f"{len(chains)} chain(s); {multi} with >1 member.")
        print("pass --chain <name> or --all")
        return 0

    for chain in selected:
        if args.dry_run:
            print(f"[dry-run] {chain.key}")
            print(f"  members ({len(chain.members)}): {', '.join(chain.members)}")
            continue
        result = consolidate_chain(root, target, chain)
        print(f"{result['key']}: emitted {result['emitted']} chunks, "
              f"dropped {result['dropped']} → {result['output_dir']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
