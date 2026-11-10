#!/usr/bin/env python3
"""Seed one whole session into a single Soma DB, verbatim.

A session contains many chat sets. A chat set is one prefix group:
16160 -> all 16160.*.json files. Identical content under a second prefix
(for example 16293.*) is recorded as duplicate provenance, not as a second
group.

One session -> one Soma JSON database.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from store import Soma
from machinetalk.source import load_chatset
from seed_chat_set_group import _file_prefix, _natural_key, _sha256_text


def _ordered(records: list[tuple[Path, dict]]) -> list[tuple[Path, dict]]:
    def key(item: tuple[Path, dict]):
        p, rec = item
        ci = rec.get("chunk_index")
        ci = int(ci) if ci is not None else 1
        return (ci, _natural_key(p.name))
    return sorted(records, key=key)


def _scan(session_dir: Path) -> dict[str, list[tuple[Path, dict]]]:
    prefixes: dict[str, list[tuple[Path, dict]]] = defaultdict(list)
    for p in session_dir.glob("*.json"):
        if p.name == "session.json" or p.name.startswith("tool-"):
            continue
        try:
            rec = json.loads(p.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if "set_number" not in rec:
            continue
        prefixes[_file_prefix(p.name)].append((p, rec))
    for prefix in prefixes:
        prefixes[prefix] = _ordered(prefixes[prefix])
    return dict(prefixes)


def _signature(records: list[tuple[Path, dict]]) -> tuple[str, ...]:
    return tuple(
        _sha256_text(rec.get("user_text") or "", rec.get("assistant_text") or "")
        for _, rec in records
    )


def _chunks_for(records: list[tuple[Path, dict]], session_dir: Path,
                prefix: str) -> tuple[list[dict], int, int, int]:
    total_chars = 0
    total_bytes = 0
    metadata_chars = 0
    chunks: list[dict] = []
    for p, rec in records:
        user_text = rec.get("user_text") or ""
        assistant_text = rec.get("assistant_text") or ""
        text_hash = _sha256_text(user_text, assistant_text)
        chars = len(user_text) + len(assistant_text)
        total_chars += chars
        total_bytes += p.stat().st_size
        metadata_chars += int(rec.get("chars") or 0)
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
        })
    return chunks, total_chars, total_bytes, metadata_chars


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--session-dir", required=True)
    ap.add_argument("--out", required=True, help="single session Soma JSON path")
    ap.add_argument("--manifest", default=None)
    ap.add_argument("--force", action="store_true", help="overwrite an existing session DB")
    args = ap.parse_args()

    session_dir = Path(args.session_dir).expanduser().resolve()
    session_id = session_dir.name
    prefixes = _scan(session_dir)
    if not prefixes:
        print(f"No chat-set files found in {session_dir}", file=sys.stderr)
        return 1

    # Group prefixes by their ordered text-hash signature. The same signature
    # under multiple prefixes is one canonical group plus duplicate exports.
    by_sig: dict[tuple[str, ...], list[str]] = defaultdict(list)
    for prefix, records in prefixes.items():
        by_sig[_signature(records)].append(prefix)

    canonical_groups: list[dict] = []
    duplicate_prefixes: set[str] = set()
    for sig, members in by_sig.items():
        members_sorted = sorted(members, key=int)
        canonical = members_sorted[0]
        duplicates = members_sorted[1:]
        duplicate_prefixes.update(duplicates)
        records = prefixes[canonical]
        chunks, total_chars, total_bytes, metadata_chars = _chunks_for(
            records, session_dir, canonical)
        first = records[0][1]
        total_chunks = first.get("total_chunks")
        total_chunks = int(total_chunks) if total_chunks else len(records)
        present = {int(rec.get("chunk_index") or 1) for _, rec in records}
        missing = [i for i in range(1, total_chunks + 1) if i not in present]
        complete = len(records) == total_chunks and not missing
        canonical_groups.append({
            "prefix": canonical,
            "duplicates": duplicates,
            "records": records,
            "chunks": chunks,
            "chunk_count": len(records),
            "total_chunks": total_chunks,
            "complete": complete,
            "missing": missing,
            "total_chars": total_chars,
            "total_bytes": total_bytes,
            "metadata_chars": metadata_chars,
        })

    canonical_groups.sort(key=lambda g: int(g["prefix"]))

    out = Path(args.out).expanduser().resolve()
    if out.exists() and not args.force:
        print(f"Refusing to overwrite {out} (use --force)", file=sys.stderr)
        return 1
    out.parent.mkdir(parents=True, exist_ok=True)

    soma = Soma(str(out), force_empty=True)
    soma.start_batch()
    now = datetime.now(timezone.utc).isoformat()
    anchor_id = f"anchor-{session_id}"

    total_chunks = sum(g["chunk_count"] for g in canonical_groups)
    total_chars = sum(g["total_chars"] for g in canonical_groups)
    total_bytes = sum(g["total_bytes"] for g in canonical_groups)
    metadata_chars = sum(g["metadata_chars"] for g in canonical_groups)

    soma.create_node("SessionAnchor", {
        "id": anchor_id,
        "session_id": session_id,
        "session_type": "chat_sets",
        "set_count": len(canonical_groups),
        "chunk_count": total_chunks,
        "total_chars": total_chars,
        "metadata_chars": metadata_chars,
        "source_dir": str(session_dir),
        "duplicate_prefixes": sorted(duplicate_prefixes, key=int),
        "schema_version": "1",
        "created_at": now,
    })

    prev_group_id = None
    for g in canonical_groups:
        prefix = g["prefix"]
        group_id = f"group:{prefix}"
        soma.create_node("ChatSetGroup", {
            "id": group_id,
            "prefix": prefix,
            "session_id": session_id,
            "set_number": int(g["records"][0][1].get("set_number") or 0),
            "chunk_count": g["chunk_count"],
            "total_chunks": g["total_chunks"],
            "complete": g["complete"],
            "missing_chunks": g["missing"],
            "total_chars": g["total_chars"],
            "metadata_chars": g["metadata_chars"],
            "total_bytes": g["total_bytes"],
            "duplicate_prefixes": g["duplicates"],
            "created_at": now,
        })
        soma.create_edge(anchor_id, "HAS_CHATSET_GROUP", group_id)
        if prev_group_id:
            soma.create_edge(prev_group_id, "NEXT_GROUP", group_id)
        prev_group_id = group_id

        prev_chunk_id = None
        for c in g["chunks"]:
            rec = c["rec"]
            chunk_id = str(rec.get("chat_set_id") or f"{prefix}.{c['chunk_index']}")
            node_id = f"cs-{chunk_id}"
            ci = c["chunk_index"]
            tc = rec.get("total_chunks")
            tc = int(tc) if tc is not None else 1
            dup = g["duplicates"]
            if dup:
                dup_prefix = sorted(dup, key=int)[0]
                dup_file = f"{dup_prefix}.{ci}.json" if tc > 1 else f"{dup_prefix}.json"
            else:
                dup_file = None
            soma.create_node("ChatSet", {
                "id": node_id,
                "chat_set_id": chunk_id,
                "session_id": session_id,
                "set_number": int(rec.get("set_number") or 0),
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
            if prev_chunk_id:
                soma.create_edge(prev_chunk_id, "NEXT_CHUNK", node_id)
            prev_chunk_id = node_id

    soma.commit_batch()

    check = Soma(str(out))
    types: dict[str, int] = {}
    for n in check._nodes.values():
        types[n.node_type] = types.get(n.node_type, 0) + 1

    print(f"Soma: {out}")
    print(f"session: {session_id}")
    print(f"groups: {len(canonical_groups)}  chunks: {total_chunks}")
    print(f"nodes: {check.node_count()} edges: {check.edge_count()}")
    print(f"types: {types}")
    print(f"text chars: {total_chars:,}  metadata chars: {metadata_chars:,}  bytes: {total_bytes:,}")
    print(f"duplicate prefixes: {len(duplicate_prefixes)}")
    first_g = canonical_groups[0]
    last_g = canonical_groups[-1]
    print(f"first group: {first_g['prefix']} ({first_g['chunk_count']} chunks, {first_g['total_chars']:,} chars)")
    print(f"last group:  {last_g['prefix']} ({last_g['chunk_count']} chunks, {last_g['total_chars']:,} chars)")

    manifest_path = Path(args.manifest) if args.manifest else out.with_suffix(".manifest.json")
    manifest = {
        "session_id": session_id,
        "group_count": len(canonical_groups),
        "chunk_count": total_chunks,
        "total_chars": total_chars,
        "metadata_chars": metadata_chars,
        "total_bytes": total_bytes,
        "duplicate_prefixes": sorted(duplicate_prefixes, key=int),
        "groups": [
            {
                "prefix": g["prefix"],
                "chunk_count": g["chunk_count"],
                "total_chunks": g["total_chunks"],
                "complete": g["complete"],
                "missing_chunks": g["missing"],
                "total_chars": g["total_chars"],
                "metadata_chars": g["metadata_chars"],
                "duplicate_prefixes": g["duplicates"],
                "files": [
                    {
                        "chat_set_id": c["rec"].get("chat_set_id"),
                        "file": c["file"].name,
                        "chunk_index": c["chunk_index"],
                        "chars": c["chars"],
                        "metadata_chars": c["rec"].get("chars"),
                        "text_sha256": c["text_hash"],
                        "canonical_hash": c["canonical_hash"],
                    }
                    for c in g["chunks"]
                ],
            }
            for g in canonical_groups
        ],
    }
    Path(manifest_path).write_text(json.dumps(manifest, indent=2))
    print(f"manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
