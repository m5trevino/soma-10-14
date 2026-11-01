#!/usr/bin/env python3
"""Stage 1: ingest a session into soma, then distil and extract per chunk.

The unit of work is the chat set chunk: one ``*.json`` file. A chat set is a
prefix group (``38439`` covers ``38439.1`` .. ``38439.40``); each file inside
it is one chunk and one model call.

Order of operations, and why:

  1. INGEST  -- the whole session is written to the graph before any model
               call. Every chunk carries the hash of the exact messages
               written, so a later run can verify what it is reading instead
               of re-deriving it from source files.
  2. DISTIL  -- one call per chunk, instructions read from the
               ``stage_instructions`` row for ``distiller``.
  3. EXTRACT -- one call per chunk, instructions from the ``introbeaver`` row.
               Every entry must equal the source text at the offsets it
               claims; a mismatch discards the entry.
  4. SUPER   -- supersession runs in code across the whole session, because no
               single call ever sees more than one chunk.

Usage:
    python3 run_stage1.py --session-dir <dir> --store <soma.db> [--stage ...]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from store import Soma                                  # noqa: E402
from machinetalk.hashes import chatset_hash_for         # noqa: E402
from machinetalk.client import EngineClient             # noqa: E402
from machinetalk.provenance import (                    # noqa: E402
    verify_distiller, verify_introbeaver, normalize,
)

DEFAULT_PROFILE = "/home/flintx/soma-10-14/turn-key-profile/today_2026-10-30T10-01-28.json"


# ── reading the export ───────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _natural(name: str):
    import re
    return tuple(int(p) if p.isdigit() else p for p in re.split(r"(\d+)", name))


def read_session(session_dir: Path) -> dict:
    """Group a session's files by chat set prefix, chunks in order.

    A chat set is identified by the prefix before the first dot. The number
    after the dot is the chunk position inside that chat set. Identical
    chunk content under a second prefix is a duplicate export, not a second
    chat set.
    """
    by_prefix: dict[str, list[dict]] = defaultdict(list)
    meta: dict = {}

    for f in sorted(session_dir.glob("*.json"), key=lambda p: _natural(p.name)):
        if f.name == "session.json" or f.name.endswith(".meta.json"):
            continue
        try:
            rec = json.loads(f.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if "set_number" not in rec:
            continue
        prefix = f.stem.split(".")[0]
        user_text = rec.get("user_text") or ""
        assistant_text = rec.get("assistant_text") or ""
        raw: list[dict] = []
        if user_text.strip():
            raw.append({"role": "USER", "content": normalize(user_text),
                        "timestamp": str(rec.get("timestamp") or "")})
        if assistant_text.strip():
            raw.append({"role": "AGENT", "content": normalize(assistant_text),
                        "timestamp": str(rec.get("timestamp") or "")})
        by_prefix[prefix].append({
            "file": f.name,
            "chunk_index": int(rec.get("chunk_index") or 0),
            "raw": raw,
            "chars": sum(len(m["content"]) for m in raw),
            "hash": chatset_hash_for(raw),
        })

    if not by_prefix:
        return {}

    sj = session_dir / "session.json"
    if sj.exists():
        try:
            meta = json.loads(sj.read_text())
        except (OSError, json.JSONDecodeError):
            meta = {}

    # Collapse duplicate exports: same ordered chunk hashes = same chat set.
    canonical: dict[tuple, str] = {}
    groups: dict[str, dict] = {}
    for prefix in sorted(by_prefix, key=_natural):
        chunks = sorted(by_prefix[prefix], key=lambda c: (c["chunk_index"], _natural(c["file"])))
        sig = tuple(c["hash"] for c in chunks)
        if sig in canonical:
            groups[canonical[sig]]["duplicates"].append(prefix)
            continue
        canonical[sig] = prefix
        groups[prefix] = {
            "prefix": prefix,
            "chunks": chunks,
            "duplicates": [],
            "chars": sum(c["chars"] for c in chunks),
        }

    return {
        "session_id": session_dir.name,
        "provider": (meta.get("provider") or ""),
        "groups": [groups[k] for k in sorted(groups, key=_natural)],
    }


# ── 1. ingest ────────────────────────────────────────────────────────────

def ingest(session: dict, soma: Soma) -> dict:
    """Write the whole session to the graph and verify each chunk's hash."""
    sid = session["session_id"]
    anchor_id = f"anchor-{sid}"

    soma.create_node("SessionAnchor", {
        "id": anchor_id,
        "session_id": sid,
        "project_context": "Dendritic",
        "total_sets": len(session["groups"]),
        "total_session_chars": sum(g["chars"] for g in session["groups"]),
        "provider": session["provider"],
        "created_at": _now(),
    })

    counts = {"ChatSet": 0, "Chunk": 0, "Message": 0, "duplicates": 0}
    verified = failed = 0

    for g in session["groups"]:
        set_id = f"{sid}:{g['prefix']}"
        soma.create_node("ChatSet", {
            "id": set_id,
            "session_id": sid,
            "prefix": g["prefix"],
            "chunk_count": len(g["chunks"]),
            "chars": g["chars"],
            "duplicate_prefixes": g["duplicates"],
            "created_at": _now(),
        })
        soma._ensure_edge(anchor_id, "CONTAINS", set_id)
        counts["ChatSet"] += 1
        counts["duplicates"] += len(g["duplicates"])

        prev_chunk = None
        for c in g["chunks"]:
            chunk_id = f"{sid}:{g['prefix']}.{c['chunk_index'] or 1}"
            soma.create_node("Chunk", {
                "id": chunk_id,
                "session_id": sid,
                "chat_set_id": set_id,
                "prefix": g["prefix"],
                "chunk_index": c["chunk_index"],
                "file": c["file"],
                "chars": c["chars"],
                "chatset_hash": c["hash"],
                "created_at": _now(),
            })
            soma._ensure_edge(set_id, "HAS_CHUNK", chunk_id)
            if prev_chunk:
                soma._ensure_edge(prev_chunk, "NEXT_CHUNK", chunk_id)
            prev_chunk = chunk_id
            counts["Chunk"] += 1

            for i, msg in enumerate(c["raw"]):
                mid = f"msg-{chunk_id}-{i}"
                soma.create_node("Message", {
                    "id": mid,
                    "session_id": sid,
                    "chat_set_id": set_id,
                    "chunk_id": chunk_id,
                    "turn_index": i,
                    "role": msg["role"],
                    "chars": len(msg["content"]),
                    "content": msg["content"],
                    "timestamp": msg["timestamp"],
                })
                soma._ensure_edge(chunk_id, "HAS_MESSAGE", mid)
                counts["Message"] += 1

            # Verify the bytes landed exactly as hashed.
            stored = soma.query_session("Message", sid)
            mine = [m for m in stored if m.properties.get("chunk_id") == chunk_id]
            mine.sort(key=lambda m: m.properties.get("turn_index") or 0)
            rebuilt = [{"role": m.properties["role"],
                        "content": m.properties["content"],
                        "timestamp": m.properties.get("timestamp") or ""}
                       for m in mine]
            if chatset_hash_for(rebuilt) == c["hash"]:
                verified += 1
            else:
                failed += 1
                print(f"  HASH MISMATCH {chunk_id}", file=sys.stderr)

    counts["verified"] = verified
    counts["failed"] = failed
    return counts


# ── 2/3. stages, one chunk per call ──────────────────────────────────────

def _chunks(soma: Soma, sid: str) -> list:
    nodes = soma.query_session("Chunk", sid)
    nodes.sort(key=lambda n: (str(n.properties.get("prefix") or ""),
                              int(n.properties.get("chunk_index") or 0)))
    return nodes


def _messages(soma: Soma, sid: str, chunk_id: str) -> list[dict]:
    msgs = [m for m in soma.query_session("Message", sid)
            if m.properties.get("chunk_id") == chunk_id]
    msgs.sort(key=lambda m: m.properties.get("turn_index") or 0)
    return [{"role": m.properties["role"],
             "content": m.properties["content"],
             "timestamp": m.properties.get("timestamp") or ""} for m in msgs]


def run_chunk_stage(client, soma, sid, stage, chunk, raw, rescan):
    """One model call for one chunk, instructions from the database."""
    chunk_id = chunk.node_id
    payload = {
        "session_id": sid,
        "chatset_id": chunk_id,
        "timestamp_utc": _now(),
        "chatset_hash": chunk.properties["chatset_hash"],
        "raw_chat_set": raw,
    }
    transcript = "\n\n".join(f"[{m['role']}]\n{m['content']}" for m in raw)
    t0 = time.monotonic()
    res = client.call_stage(
        stage, session_id=sid, chatset_id=chunk_id,
        chunk=transcript, payload=payload,
        expected_hash=chunk.properties["chatset_hash"],
        soma=soma, raw_chat_set=raw,
    )
    elapsed = time.monotonic() - t0
    gate = res.record.gate
    return gate, elapsed


def supersede_session(soma: Soma, sid: str) -> dict:
    """Resolve supersession across the whole session, in code.

    Step 9 runs inside one call, so it can only see one chunk. This is the
    session-wide pass that the model can never do: group every extracted
    entry by ``intent_key``, order them by position in the conversation
    (chat set, then chunk, then message), and label the earlier ones
    SUPERSEDED with ``superseded_by`` pointing at their winner.

    Nothing is deleted and no text is merged — the template forbids both.
    Supersession is a label on an existing entry, never a rewrite.
    """
    chunks = soma.query_session("Chunk", sid)
    order: dict[str, tuple] = {}
    for c in chunks:
        p = c.properties
        order[c.node_id] = (
            int(p.get("chunk_index") or 0),
            str(p.get("prefix") or ""),
            int(p.get("chunk_index") or 0),
        )
    # rank chunks by (prefix, chunk_index) so "later" means later in the set
    ranked = sorted(chunks, key=lambda n: (str(n.properties.get("prefix") or ""),
                                          int(n.properties.get("chunk_index") or 0)))
    pos = {n.node_id: i for i, n in enumerate(ranked)}

    by_key: dict[str, list] = defaultdict(list)
    tagged = 0
    for node in soma.query_by_type("IntentEntry"):
        p = dict(node.properties)
        key = str(p.get("intent_key") or "")
        if not key:
            continue
        rank = (pos.get(str(p.get("chunk_id") or ""), 0),
                int(p.get("source_msg_index") or 0),
                int(p.get("sentence_index") or 0))
        by_key[key].append((rank, node))

    groups = 0
    superseded = 0
    for key, items in by_key.items():
        if len(items) < 2:
            continue
        groups += 1
        items.sort(key=lambda t: t[0])
        winner = items[-1][1]
        winner_props = dict(winner.properties)
        winner_props["entry_status"] = "ACTIVE"
        winner_props["superseded_by"] = None
        soma.create_node("IntentEntry", winner_props)
        for _, loser in items[:-1]:
            lp = dict(loser.properties)
            lp["entry_status"] = "SUPERSEDED"
            lp["superseded_by"] = winner.node_id
            soma.create_node("IntentEntry", lp)
            superseded += 1
            tagged += 1

    return {"groups": groups, "superseded": superseded,
            "chunks_ranked": len(ranked), "entries": sum(len(v) for v in by_key.values())}


def write_intent_entries(soma: Soma, sid: str, chunk_id: str,
                         payload: dict) -> int:
    """Store introbeaver's entries as IntentEntry nodes.

    Each entry keeps the fields supersession needs — ``intent_key`` and its
    position — plus the provenance that proves it came from the source.
    """
    body = payload.get("introbeaver_output") if isinstance(
        payload.get("introbeaver_output"), dict) else payload
    entries = body.get("entries") or []
    written = 0
    for i, e in enumerate(entries):
        if not isinstance(e, dict):
            continue
        eid = str(e.get("entry_id") or f"{chunk_id}-{i:04d}")
        # entry_id is TB004-{session}-{seq:04d} and the sequence restarts on
        # every call, so the same id recurs across chunks. Namespacing the
        # node id by chunk keeps entries from different chunks distinct.
        node_id = f"ie-{chunk_id}-{eid}"
        soma.create_node("IntentEntry", {
            "id": node_id,
            "session_id": sid,
            "chunk_id": chunk_id,
            "entry_id": eid,
            "source_msg_index": e.get("source_msg_index"),
            "sentence_index": e.get("sentence_index"),
            "char_start": e.get("char_start"),
            "char_end": e.get("char_end"),
            "verbatim_text": e.get("verbatim_text") or "",
            "instruction_type": e.get("instruction_type") or "",
            "confidence": e.get("confidence"),
            "intent_key": e.get("intent_key") or "",
            "normalized_form": e.get("normalized_form") or "",
            "entry_status": e.get("entry_status") or "ACTIVE",
            "superseded_by": e.get("superseded_by"),
            "flags": e.get("flags") or [],
            "downstream_action": e.get("downstream_action") or "",
            "created_at": _now(),
        })
        soma._ensure_edge(chunk_id, "YIELDS", node_id)
        written += 1
    return written


def write_invariant_nodes(soma: Soma, sid: str, slot_node, laws: list[dict]) -> int:
    """Store corpus laws as InvariantQueryNodes governed onto a slot.

    ``harden_slot`` in myelinator_olc reads InvariantQueryNode.properties
    ['invariant_text'] and matches it against the slot's name, mandate and
    path. Writing the nodes is therefore what turns retrieval into a
    GOVERNS edge and, eventually, an OptimizedSlot.
    """
    written = 0
    for law in laws:
        stmt = law.get("statement") or ""
        if not stmt:
            continue
        node_id = f"inv-{sid}-{abs(hash(stmt)) & 0xFFFFFFFF:08x}"
        soma.create_node("InvariantQueryNode", {
            "id": node_id,
            "session_id": sid,
            "invariant_text": stmt,
            "statement": stmt,
            "family": law.get("family") or "",
            "confidence": law.get("confidence"),
            "composite": law.get("composite"),
            "scope": law.get("scope") or "",
            "repo": law.get("repo") or "",
            "occurrences": law.get("occurrences"),
            "repo_count": law.get("repo_count"),
            "repos": law.get("repos") or "",
            "bm25": law.get("score"),
            "source": "truth_corpus",
            "created_at": _now(),
        })
        if slot_node is not None:
            soma._ensure_edge(node_id, "GOVERNS", slot_node.node_id)
        written += 1
    return written


_SIG_RE = re.compile(r"^\s*(?:async\s+)?(?:def\s+(\w+)|class\s+(\w+))", re.MULTILINE)


def write_function_slots_from_dir(soma: Soma, sid: str, root: Path,
                                  limit_files: int | None = None) -> dict:
    """Create FileNode + FunctionSlot rows from real source files.

    This is the entry point the invariant path needs: without slots there is
    nothing for ``harden_slot`` to harden. It scans Python sources, records
    each file, and slices one slot per top-level def/class.
    """
    files = sorted(root.rglob("*.py"))[:limit_files or None]
    counts = {"FileNode": 0, "FunctionSlot": 0}
    for fi, path in enumerate(files):
        try:
            text = path.read_text(errors="ignore")
        except OSError:
            continue
        rel = str(path.relative_to(root))
        fid = f"file-{sid}-{fi}"
        soma.create_node("FileNode", {
            "id": fid,
            "session_id": sid,
            "file_path": rel,
            "content_preview": text[:5000],
            "language": "python",
            "chars": len(text),
            "created_at": _now(),
        })
        counts["FileNode"] += 1

        matches = list(_SIG_RE.finditer(text))
        for i, m in enumerate(matches):
            name = m.group(1) or m.group(2) or f"slot_{i}"
            start = m.start()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            slot_id = f"slot-{fid}-{name}-{i}"
            soma.create_node("FunctionSlot", {
                "id": slot_id,
                "session_id": sid,
                "name": name,
                "code_block": text[start:end][:4000],
                "language": "python",
                "file_path": rel,
                "parent_file_id": fid,
                "mandate": f"Implement {name} from {rel}",
                "created_at": _now(),
            })
            soma._ensure_edge(slot_id, "SLICED_FROM", fid)
            counts["FunctionSlot"] += 1
    return counts


def main() -> int:
    ap = argparse.ArgumentParser(description="Ingest a session, then run stage 1")
    ap.add_argument("--session-dir", required=True)
    ap.add_argument("--store", required=True)
    ap.add_argument("--profile", default=DEFAULT_PROFILE)
    ap.add_argument("--stage", default="all",
                    choices=["all", "ingest", "distiller", "introbeaver"])
    ap.add_argument("--max-chunks", type=int, default=None)
    ap.add_argument("--force-ingest", action="store_true")
    ap.add_argument("--invariants", action="store_true",
                    help="retrieve corpus laws for every FunctionSlot")
    ap.add_argument("--law-db", default="/media/storage/invariants/invariants.db")
    ap.add_argument("--law-limit", type=int, default=50)
    ap.add_argument("--code-dir", default=None,
                    help="scan this source tree to create FunctionSlots")
    ap.add_argument("--code-limit", type=int, default=40)
    args = ap.parse_args()

    sdir = Path(args.session_dir).expanduser().resolve()
    session = read_session(sdir)
    if not session:
        print(f"no chat-set files in {sdir}", file=sys.stderr)
        return 1

    sid = session["session_id"]
    soma = Soma(args.store)
    groups = len(session["groups"])
    chunks = sum(len(g["chunks"]) for g in session["groups"])
    print(f"session : {sid}")
    print(f"chat sets: {groups}   chunks: {chunks}   "
          f"chars: {sum(g['chars'] for g in session['groups']):,}")

    if args.stage in ("all", "ingest"):
        t0 = time.monotonic()
        c = ingest(session, soma)
        print(f"\ningested in {time.monotonic() - t0:.1f}s")
        print(f"  ChatSet {c['ChatSet']}  Chunk {c['Chunk']}  Message {c['Message']}")
        print(f"  duplicate prefixes collapsed: {c['duplicates']}")
        print(f"  hash verified: {c['verified']}/{c['verified'] + c['failed']}")
        if c["failed"]:
            print("  ingest did NOT verify; stopping", file=sys.stderr)
            return 1
        if args.stage == "ingest" and not args.invariants:
            return 0

    todo = _chunks(soma, sid)
    if args.max_chunks:
        todo = todo[:args.max_chunks]

    client = EngineClient(args.profile)
    stages = ["distiller", "introbeaver"] if args.stage == "all" else [args.stage]

    for stage in stages:
        done = skipped = failed = 0
        extracted = 0
        print(f"\n=== {stage.upper()} — {len(todo)} chunk(s) ===")
        for i, chunk in enumerate(todo, 1):
            raw = _messages(soma, sid, chunk.node_id)
            if not raw:
                print(f"  [{i}/{len(todo)}] {chunk.node_id} no messages, skipped")
                skipped += 1
                continue
            try:
                gate, elapsed = run_chunk_stage(
                    client, soma, sid, stage, chunk, raw, None)
            except Exception as exc:
                print(f"  [{i}/{len(todo)}] {chunk.node_id} "
                      f"FAILED {type(exc).__name__}: {exc}")
                failed += 1
                continue

            label = chunk.node_id.split(":", 1)[-1]
            if not gate.ok:
                print(f"  [{i}/{len(todo)}] {label:14} FAILED "
                      f"{gate.first_reason()}  {elapsed:.0f}s")
                failed += 1
                continue

            prov = getattr(gate, "provenance", "") or ""
            if gate.skipped:
                print(f"  [{i}/{len(todo)}] {label:14} SKIP "
                      f"{gate.verdict or 'no signal'}  {elapsed:.0f}s")
                skipped += 1
            else:
                if stage == "distiller":
                    body = (gate.parsed.get("distiller_output")
                            if isinstance(gate.parsed, dict) else None) or gate.parsed or {}
                    n = sum(len(body.get(k) or []) for k in (
                        "directives", "constraints", "preferences", "questions",
                        "corrections", "confirmations", "artifacts"))
                    extracted += n
                    detail = f"{n} item(s)"
                else:
                    body = (gate.parsed.get("introbeaver_output")
                            if isinstance(gate.parsed, dict) else None) or gate.parsed or {}
                    n = len(body.get("entries") or [])
                    if n:
                        write_intent_entries(soma, sid, chunk.node_id, gate.parsed)
                    extracted += n
                    detail = f"{n} entr(y/ies) {prov}"
                print(f"  [{i}/{len(todo)}] {label:14} DONE "
                      f"{detail}  {elapsed:.0f}s")
                done += 1

        print(f"\n  {stage}: done {done}  skip {skipped}  fail {failed}  "
              f"items {extracted}")

    # Session-wide supersession: the pass no single call can perform.
    if "introbeaver" in stages:
        print("\n=== SUPERSESSION (session-wide) ===")
        s = supersede_session(soma, sid)
        print(f"  chunks ranked {s['chunks_ranked']}  entries {s['entries']}  "
              f"intent groups {s['groups']}  superseded {s['superseded']}")

    # Invariant retrieval: give every FunctionSlot the corpus laws that match
    # its mandate. This is the step that connects the 604K-law database to the
    # hardening path OLC already implements.
    if args.invariants:
        from machinetalk.invariants import LawCorpus

        if args.code_dir:
            cdir = Path(args.code_dir).expanduser().resolve()
            if cdir.is_dir():
                print(f"\n=== FUNCTION SLOTS ({cdir}) ===")
                fc = write_function_slots_from_dir(
                    soma, sid, cdir, args.code_limit)
                print(f"  FileNode {fc['FileNode']}  FunctionSlot {fc['FunctionSlot']}")
            else:
                print(f"  code dir not found: {cdir}")

        corpus = LawCorpus(args.law_db)
        print("\n=== INVARIANTS ===")
        if not corpus.available:
            print(f"  law corpus unavailable at {args.law_db}")
        else:
            slots = soma.query_by_type("FunctionSlot")
            print(f"  corpus {corpus.count():,} laws   slots {len(slots)}")
            total = 0
            for slot in slots:
                p = slot.properties
                # Query on what the function IS, not where it lives. Including
                # the file path made every function in a file inherit that
                # file's laws: ``_now`` in checkpoint.py was getting checkpoint
                # saver requirements it has nothing to do with.
                name = str(p.get("name") or "")
                code = str(p.get("code_block") or "")
                body_words = " ".join(re.findall(r"[A-Za-z_]{4,}", code))[:600]
                text = f"{name} {body_words}"
                laws = corpus.search(text, limit=args.law_limit)
                n = write_invariant_nodes(soma, sid, slot, laws)
                total += n
                print(f"  {str(p.get('name'))[:28]:28} {n:3} law(s)")
            print(f"  total InvariantQueryNode: {total}")
            corpus.close()

    soma.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
