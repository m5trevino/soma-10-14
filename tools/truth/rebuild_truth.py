#!/usr/bin/env python3
"""Rebuild extracted chunks from the anchors table and run truth inference.

The ``*.extracted.json`` files that produced the 611,299 anchors are gone
(``/home/flintx/k1-complete`` no longer exists), but every field the reader
needs survived in the ``anchors`` table itself. This reconstructs
``ExtractedChunk`` objects directly from that table — no intermediate files —
and hands them to truth-inference's own engine.

Nothing here reimplements the scoring. The grouping key, normalization,
composite score and conflict detection all come from
``truth_inference.inference.TruthInferenceEngine``.

Usage:
    PYTHONPATH=<truth-inference>/src python3 rebuild_truth.py \
        --db /media/storage/invariants/invariants.db \
        --out /media/storage/invariants/truth_records.jsonl \
        [--limit-chunks N]
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from truth_inference.inference import TruthInferenceEngine
from truth_inference.models import (
    AnchorRecord, EvidenceSpan, ExtractedChunk, Provenance, parse_datetime,
)


def _loads(text: str, fallback):
    if not text:
        return fallback
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return fallback


def build_chunks(db: str, limit_chunks: int | None = None) -> list[ExtractedChunk]:
    """Group anchor rows by chunk_id into ExtractedChunk objects."""
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row

    chunk_ids = [
        r["chunk_id"] for r in conn.execute(
            "SELECT chunk_id, COUNT(*) c FROM anchors "
            "WHERE chunk_id IS NOT NULL GROUP BY chunk_id ORDER BY c DESC"
        ).fetchall()
    ]
    if limit_chunks:
        chunk_ids = chunk_ids[:limit_chunks]
    wanted = set(chunk_ids)

    rows = conn.execute(
        "SELECT anchor_id, type, statement, family, confidence, repo, lens, "
        "chunk_id, valid_from, reference_time, assumptions, limitations, "
        "evidence_spans, provenance "
        "FROM anchors WHERE chunk_id IS NOT NULL"
    ).fetchall()

    by_chunk: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for r in rows:
        if r["chunk_id"] in wanted:
            by_chunk[r["chunk_id"]].append(r)

    chunks: list[ExtractedChunk] = []
    for cid, group in by_chunk.items():
        first = group[0]
        prov_raw = _loads(first["provenance"], {})
        provenance = Provenance(
            source_batch_id=prov_raw.get("source_batch_id"),
            source_file=prov_raw.get("source_file"),
            pipeline_version=prov_raw.get("pipeline_version"),
            extraction_model=prov_raw.get("extraction_model"),
            extraction_timestamp=parse_datetime(prov_raw.get("extraction_timestamp")),
            prompt_tokens=prov_raw.get("prompt_tokens"),
            completion_tokens=prov_raw.get("completion_tokens"),
            total_tokens=prov_raw.get("total_tokens"),
            input_shard_count=prov_raw.get("input_shard_count"),
            input_shard_ids=prov_raw.get("input_shard_ids") or [],
        )

        anchors: list[AnchorRecord] = []
        all_spans: list[EvidenceSpan] = []
        for r in group:
            spans_raw = _loads(r["evidence_spans"], [])
            spans = []
            for s in spans_raw:
                if not isinstance(s, dict):
                    continue
                spans.append(EvidenceSpan(
                    shard_id=s.get("shard_id"),
                    file_path=s.get("file_path"),
                    lines=s.get("lines") or [],
                    symbols=s.get("symbols") or [],
                    quote=s.get("quote"),
                ))
            all_spans.extend(spans)
            anchors.append(AnchorRecord(
                anchor_id=r["anchor_id"],
                type=r["type"],
                statement=r["statement"],
                family=r["family"] or "UNKNOWN",
                confidence=float(r["confidence"] or 0.5),
                shard_ids=[cid],
                chunk_id=cid,
                repo=r["repo"] or "unknown",
                lens=r["lens"] or "app",
                valid_from=parse_datetime(r["valid_from"]),
                reference_time=parse_datetime(r["reference_time"]),
                evidence_spans=spans,
                assumptions=_loads(r["assumptions"], []),
                limitations=_loads(r["limitations"], []),
                provenance=provenance,
            ))

        chunks.append(ExtractedChunk(
            chunk_id=cid,
            repo=first["repo"] or "unknown",
            lens=first["lens"] or "app",
            valid_from=parse_datetime(first["valid_from"]),
            reference_time=parse_datetime(first["reference_time"]),
            semantic_anchors=anchors,
            typed_relations=[],
            provenance=provenance,
            evidence_spans=all_spans,
            assumptions=_loads(first["assumptions"], []),
            limitations=_loads(first["limitations"], []),
            input_metadata=None,
        ))

    conn.close()
    return chunks


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="/media/storage/invariants/invariants.db")
    ap.add_argument("--out", default="/media/storage/invariants/truth_records.jsonl")
    ap.add_argument("--limit-chunks", type=int, default=None,
                    help="process only the N largest chunks (smoke test)")
    ap.add_argument("--conflicts", action="store_true",
                    help="also run conflict detection (quadratic; off by default)")
    args = ap.parse_args()

    print(f"reading chunks from {args.db}")
    chunks = build_chunks(args.db, args.limit_chunks)
    anchors = sum(len(c.semantic_anchors) for c in chunks)
    print(f"  chunks {len(chunks):,}   anchors {anchors:,}")

    engine = TruthInferenceEngine()
    print("running TruthInferenceEngine...")
    records = engine.run(chunks, detect_conflicts=args.conflicts)
    print(f"  truth records {len(records):,}")

    conflicts = sum(1 for r in records if getattr(r, "conflicts", None))
    if conflicts:
        print(f"  records with conflicts {conflicts:,}")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        for rec in records:
            f.write(rec.model_dump_json() + "\n")
    print(f"wrote {out}")

    scored = [r.score.composite for r in records if getattr(r, "score", None)]
    if scored:
        print(f"  composite  min {min(scored):.3f}  "
              f"avg {sum(scored)/len(scored):.3f}  max {max(scored):.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
