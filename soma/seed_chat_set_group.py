#!/usr/bin/env python3
"""Ingest one complete chat-set prefix group into a fresh Soma graph, verbatim.

A chat set is one prefix group: 16160 -> all 16160.*.json files.
This script writes a structural graph only. It does not interpret roles or
extract intent. The raw user_text and assistant_text are stored exactly as
they appear in the source JSON.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from store import Soma
from machinetalk.source import load_chatset


def _sha256_text(user_text: str, assistant_text: str) -> str:
    return hashlib.sha256(
        (user_text + "\x00" + assistant_text).encode("utf-8")
    ).hexdigest()


def _file_prefix(name: str) -> str:
    stem = name[:-5] if name.endswith(".json") else name
    return stem.split(".")[0]


def _natural_key(name: str):
    return tuple(int(p) if p.isdigit() else p for p in re.split(r"(\d+)", name))


def collect_group(session_dir: Path, prefix: str) -> list[Path]:
    files: list[Path] = []
    single = session_dir / f"{prefix}.json"
    if single.exists():
        files.append(single)
    files.extend(session_dir.glob(f"{prefix}.*.json"))
    return sorted({p.resolve() for p in files}, key=lambda p: _natural_key(p.name))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--session-dir", required=True)
    ap.add_argument("--prefix", required=True, help="chat set prefix, e.g. 16160")
    ap.add_argument("--out", required=True, help="Soma JSON path")
    ap.add_argument("--manifest", default=None, help="optional manifest JSON path")
    ap.add_argument("--force", action="store_true", help="overwrite an existing Soma DB")
    args = ap.parse_args()

    session_dir = Path(args.session_dir).expanduser().resolve()
    prefix = str(args.prefix)
    files = collect_group(session_dir, prefix)
    if not files:
        print(f"No files found for prefix {prefix} in {session_dir}", file=sys.stderr)
        return 1

    records: list[tuple[Path, dict]] = []
    for p in files:
        rec = json.loads(p.read_text())
        if rec.get("set_number") is None:
            print(f"Not a chat-set chunk (no set_number): {p}", file=sys.stderr)
            return 1
        records.append((p, rec))

    def order(item: tuple[Path, dict]):
        p, rec = item
        ci = rec.get("chunk_index")
        ci = int(ci) if ci is not None else 1
        return (ci, _natural_key(p.name))

    records.sort(key=order)

    chunk_count = len(records)
    first_rec = records[0][1]
    total_chunks = first_rec.get("total_chunks")
    total_chunks = int(total_chunks) if total_chunks else chunk_count
    present = {int(rec.get("chunk_index") or 1) for _, rec in records}
    missing = [i for i in range(1, total_chunks + 1) if i not in present]
    complete = chunk_count == total_chunks and not missing

    # Find duplicate exports by exact text hash under a different prefix.
    all_files = [
        p for p in session_dir.glob("*.json")
        if p.name != "session.json" and not p.name.startswith("tool-")
    ]
    hash_index: dict[str, set[str]] = {}
    for p in all_files:
        try:
            r = json.loads(p.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if "set_number" not in r:
            continue
        h = _sha256_text(r.get("user_text") or "", r.get("assistant_text") or "")
        hash_index.setdefault(h, set()).add(_file_prefix(p.name))

    total_chars = 0
    total_bytes = 0
    metadata_chars = 0
    duplicate_prefixes: set[str] = set()
    chunks: list[dict] = []

    for p, rec in records:
        user_text = rec.get("user_text") or ""
        assistant_text = rec.get("assistant_text") or ""
        text_hash = _sha256_text(user_text, assistant_text)
        chars = len(user_text) + len(assistant_text)
        total_chars += chars
        total_bytes += p.stat().st_size
        metadata_chars += int(rec.get("chars") or 0)
        dup = hash_index.get(text_hash, set()) - {prefix}
        duplicate_prefixes |= dup
        ci = int(rec.get("chunk_index") or 1)
        cs = load_chatset(session_dir.name, session_dir, ci, [p])
        chunks.append({
            "file": p,
            "rec": rec,
            "user_text": user_text,
            "assistant_text": assistant_text,
            "text_hash": text_hash,
            "chars": chars,
            "chunk_index": ci,
            "canonical_hash": cs.chatset_hash,
            "duplicate_prefixes": sorted(dup),
        })

    out = Path(args.out).expanduser().resolve()
    if out.exists() and not args.force:
        print(f"Refusing to overwrite {out} (use --force)", file=sys.stderr)
        return 1
    out.parent.mkdir(parents=True, exist_ok=True)

    soma = Soma(str(out), force_empty=True)
    soma.start_batch()

    session_id = session_dir.name
    anchor_id = f"anchor-{session_id}"
    group_id = f"group:{prefix}"
    now = datetime.now(timezone.utc).isoformat()

    soma.create_node("SessionAnchor", {
        "id": anchor_id,
        "session_id": session_id,
        "session_type": "chat_set_group",
        "set_count": 1,
        "chunk_count": chunk_count,
        "total_chars": total_chars,
        "source_dir": str(session_dir),
        "schema_version": "1",
        "created_at": now,
    })
    soma.create_node("ChatSetGroup", {
        "id": group_id,
        "prefix": prefix,
        "session_id": session_id,
        "chunk_count": chunk_count,
        "total_chunks": total_chunks,
        "complete": complete,
        "missing_chunks": missing,
        "total_chars": total_chars,
        "total_bytes": total_bytes,
        "metadata_chars": metadata_chars,
        "source_dir": str(session_dir),
        "duplicate_prefixes": sorted(duplicate_prefixes),
        "created_at": now,
    })
    soma.create_edge(anchor_id, "HAS_CHATSET_GROUP", group_id)

    prev_id = None
    for c in chunks:
        rec = c["rec"]
        chunk_id = str(rec.get("chat_set_id") or f"{prefix}.{c['chunk_index']}")
        node_id = f"cs-{chunk_id}"
        ci = c["chunk_index"]
        tc = rec.get("total_chunks")
        tc = int(tc) if tc is not None else 1
        dup = c["duplicate_prefixes"]
        if dup:
            dup_prefix = sorted(dup)[0]
            dup_file = f"{dup_prefix}.{ci}.json" if tc > 1 else f"{dup_prefix}.json"
        else:
            dup_file = None
        soma.create_node("ChatSet", {
            "id": node_id,
            "chat_set_id": chunk_id,
            "session_id": session_id,
            "set_number": int(rec.get("set_number") or 1),
            "chunk_index": ci,
            "chunk_total": tc,
            "parent_chat_set_id": rec.get("parent_chat_set_id"),
            "source_file": c["file"].name,
            "source_path": str(c["file"]),
            "bytes": c["file"].stat().st_size,
            "chars": c["chars"],
            "metadata_chars": int(rec.get("chars") or 0),
            "user_text": c["user_text"],
            "assistant_text": c["assistant_text"],
            "text_sha256": c["text_hash"],
            "canonical_hash": c["canonical_hash"],
            "provider": rec.get("provider"),
            "model": rec.get("model"),
            "model_dir": rec.get("model_dir"),
            "global_counter": rec.get("global_counter"),
            "is_chunked": bool(rec.get("is_chunked")),
            "duplicate_prefixes": dup,
            "duplicate_file": dup_file,
        })
        soma.create_edge(group_id, "HAS_CHUNK", node_id)
        if prev_id:
            soma.create_edge(prev_id, "NEXT_CHUNK", node_id)
        prev_id = node_id

    soma.commit_batch()

    check = Soma(str(out))
    types: dict[str, int] = {}
    for n in check._nodes.values():
        types[n.node_type] = types.get(n.node_type, 0) + 1

    print(f"Soma: {out}")
    print(f"prefix: {prefix}")
    print(f"chunks: {chunk_count}/{total_chunks} complete={complete} missing={missing}")
    print(f"nodes: {check.node_count()} edges: {check.edge_count()}")
    print(f"types: {types}")
    print(f"text chars: {total_chars:,}  metadata chars: {metadata_chars:,}  bytes: {total_bytes:,}")
    print(f"duplicate prefixes: {sorted(duplicate_prefixes)}")
    print(f"first: {chunks[0]['rec'].get('chat_set_id')} ({chunks[0]['chars']:,} chars)")
    print(f"last:  {chunks[-1]['rec'].get('chat_set_id')} ({chunks[-1]['chars']:,} chars)")

    manifest_path = Path(args.manifest) if args.manifest else out.with_suffix(".manifest.json")
    manifest = {
        "session_id": session_id,
        "prefix": prefix,
        "complete": complete,
        "chunk_count": chunk_count,
        "total_chunks": total_chunks,
        "missing_chunks": missing,
        "total_chars": total_chars,
        "metadata_chars": metadata_chars,
        "total_bytes": total_bytes,
        "duplicate_prefixes": sorted(duplicate_prefixes),
        "files": [
            {
                "chat_set_id": c["rec"].get("chat_set_id"),
                "file": c["file"].name,
                "path": str(c["file"]),
                "chunk_index": c["chunk_index"],
                "total_chunks": c["rec"].get("total_chunks"),
                "chars": c["chars"],
                "metadata_chars": c["rec"].get("chars"),
                "bytes": c["file"].stat().st_size,
                "text_sha256": c["text_hash"],
                "canonical_hash": c["canonical_hash"],
                "duplicate_prefixes": c["duplicate_prefixes"],
            }
            for c in chunks
        ],
    }
    Path(manifest_path).write_text(json.dumps(manifest, indent=2))
    print(f"manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
