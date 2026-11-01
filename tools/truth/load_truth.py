#!/usr/bin/env python3
"""Load truth_records.jsonl into a queryable SQLite table with FTS.

The truth records are the canonical layer: one row per collapsed invariant,
carrying the composite score, scope, sources and evidence. Scout needs to
retrieve from them by text, so they go into the same database as the raw
anchors with an FTS5 index alongside.

Usage:
    python3 load_truth.py [--db ...] [--jsonl ...]
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

SCHEMA = """
DROP TABLE IF EXISTS truth;
CREATE TABLE truth (
    truth_id      TEXT PRIMARY KEY,
    statement     TEXT NOT NULL,
    family        TEXT,
    repo          TEXT,
    scope         TEXT,
    types         TEXT,
    composite     REAL,
    confidence    REAL,
    model_strength REAL,
    evidence      REAL,
    provenance    REAL,
    instance_count INTEGER,
    model_names   TEXT,
    source_count  INTEGER,
    valid_from    TEXT,
    assumptions   TEXT,
    limitations   TEXT
);
CREATE INDEX idx_truth_family ON truth(family);
CREATE INDEX idx_truth_repo   ON truth(repo);
CREATE INDEX idx_truth_scope  ON truth(scope);
CREATE INDEX idx_truth_score  ON truth(composite DESC);
CREATE INDEX idx_truth_family_score ON truth(family, composite DESC);
"""

FTS = """
DROP TABLE IF EXISTS truth_fts;
CREATE VIRTUAL TABLE truth_fts USING fts5(
    statement, content='truth', content_rowid='rowid');
INSERT INTO truth_fts(truth_fts) VALUES('rebuild');
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="/media/storage/invariants/invariants.db")
    ap.add_argument("--jsonl", default="/media/storage/invariants/truth_records.jsonl")
    args = ap.parse_args()

    src = Path(args.jsonl)
    if not src.exists():
        print(f"missing {src}")
        return 1

    conn = sqlite3.connect(args.db)
    conn.executescript(SCHEMA)

    rows = []
    with src.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            score = r.get("score") or {}
            rows.append((
                r["truth_id"], r["statement"], r.get("family"), r.get("repo"),
                r.get("scope"),
                json.dumps(r.get("types") or []),
                score.get("composite"),
                score.get("confidence_component"),
                score.get("model_strength_component"),
                score.get("evidence_richness_component"),
                score.get("provenance_richness_component"),
                score.get("instance_count"),
                json.dumps(score.get("model_names") or []),
                len(r.get("sources") or []),
                r.get("valid_from"),
                json.dumps(r.get("assumptions") or []),
                json.dumps(r.get("limitations") or []),
            ))
            if len(rows) >= 20000:
                conn.executemany(
                    "INSERT OR REPLACE INTO truth VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    rows)
                rows.clear()

    if rows:
        conn.executemany(
            "INSERT OR REPLACE INTO truth VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            rows)
    conn.commit()

    print(f"loaded {conn.execute('SELECT COUNT(*) FROM truth').fetchone()[0]:,} truth records")
    conn.executescript(FTS)
    conn.commit()
    print(f"indexed {conn.execute('SELECT COUNT(*) FROM truth_fts').fetchone()[0]:,} rows in truth_fts")

    row = conn.execute(
        "SELECT min(composite), round(avg(composite),3), max(composite) FROM truth"
    ).fetchone()
    print(f"composite  min {row[0]:.3f}  avg {row[1]:.3f}  max {row[2]:.3f}")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
