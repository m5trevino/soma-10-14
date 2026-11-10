"""Tests for tools/consolidate_chains.py."""
import json
import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import consolidate_chains as cc


def _chunk(d: Path, stem: str, set_number: int, user: str, asst: str, **extra):
    rec = {"set_number": set_number, "chat_set_id": stem,
           "user_text": user, "assistant_text": asst}
    rec.update(extra)
    (d / f"{stem}.json").write_text(json.dumps(rec))
    return rec


def _session(d: Path, session_id: str, **extra):
    d.mkdir(parents=True, exist_ok=True)
    meta = {"session_id": session_id, "total_sets": 1}
    meta.update(extra)
    (d / "session.json").write_text(json.dumps(meta))


def _empty_db(path: Path):
    conn = sqlite3.connect(str(path))
    conn.close()


def test_grouping_content_prefix(tmp_path):
    """A continuation (child pastes parent's chunks at the front) is one chain."""
    root = tmp_path / "sessions"
    db = tmp_path / "vault.db"
    _empty_db(db)

    g0 = root / "25-12-01-current.code.issues"
    _session(g0, "25-12-01-current.code.issues", total_sets=2)
    _chunk(g0, "1", 1, "hello world", "hi there")
    _chunk(g0, "2", 2, "second thing", "ok")

    g1 = root / "25-12-02-copy.of.current.code.issues"
    _session(g1, "25-12-02-copy.of.current.code.issues", total_sets=3)
    _chunk(g1, "1", 1, "hello world", "hi there")   # carried forward
    _chunk(g1, "2", 2, "second thing", "ok")        # carried forward
    _chunk(g1, "3", 3, "new work", "done")          # genuinely new

    chains = cc.resolve_chains(root, db)
    merged = [c for c in chains if len(c.members) > 1]
    assert len(merged) == 1, f"expected one merged chain, got {chains}"
    assert set(merged[0].members) == {
        "25-12-01-current.code.issues", "25-12-02-copy.of.current.code.issues"}
    # oldest first
    assert merged[0].members[0] == "25-12-01-current.code.issues"


def test_grouping_duplicate_of(tmp_path):
    """duplicate_of folds a full copy into its canonical's component."""
    root = tmp_path / "sessions"
    db = tmp_path / "vault.db"
    _empty_db(db)

    a = root / "aaa"
    _session(a, "aaa", total_sets=1)
    _chunk(a, "1", 1, "original content", "reply")

    b = root / "bbb"
    _session(b, "bbb", total_sets=1, duplicate_of="aaa")
    _chunk(b, "1", 1, "completely different", "reply")  # no content overlap

    chains = cc.resolve_chains(root, db)
    merged = [c for c in chains if len(c.members) > 1]
    assert len(merged) == 1
    assert set(merged[0].members) == {"aaa", "bbb"}


def test_dedup_chain(tmp_path):
    """Cross-session dedup drops the carried-forward prefix; output re-ingests."""
    root = tmp_path / "sessions"
    db = tmp_path / "vault.db"
    target = tmp_path / "lineage"
    _empty_db(db)

    a = root / "a1"
    _session(a, "a1", total_sets=2)
    _chunk(a, "1", 1, "shared one", "r1")
    _chunk(a, "2", 2, "shared two", "r2")

    b = root / "b1"
    _session(b, "b1", total_sets=3)
    _chunk(b, "1", 1, "shared one", "r1")   # dup
    _chunk(b, "2", 2, "shared two", "r2")   # dup
    _chunk(b, "3", 3, "unique new", "r3")   # new

    chains = cc.resolve_chains(root, db)
    chain = next(c for c in chains if len(c.members) > 1)
    result = cc.consolidate_chain(root, target, chain)

    assert result["emitted"] == 3
    assert result["dropped"] == 2

    out_dir = Path(result["output_dir"])
    assert (out_dir / "session.json").is_file()
    # re-ingest with the pipeline's own loader
    from soma.machinetalk.source import load_session
    sess = load_session(out_dir)
    assert len(sess.chatsets) == 3
    assert sess.duplicate_files == []


def test_normalized_session_schema(tmp_path):
    """Consolidated session.json matches the source schema; provenance is a sidecar."""
    root = tmp_path / "sessions"
    db = tmp_path / "vault.db"
    target = tmp_path / "lineage"
    _empty_db(db)

    a = root / "a1"
    _session(a, "a1", total_sets=2)
    _chunk(a, "1", 1, "shared one", "r1", provider="p1", model="m1")
    _chunk(a, "2", 2, "shared two", "r2", provider="p1", model="m2")

    b = root / "b1"
    _session(b, "b1", total_sets=3)
    _chunk(b, "1", 1, "shared one", "r1", provider="p1", model="m1")
    _chunk(b, "2", 2, "shared two", "r2", provider="p1", model="m2")
    _chunk(b, "3", 3, "unique new", "r3", provider="p1", model="m3")

    chains = cc.resolve_chains(root, db)
    chain = next(c for c in chains if len(c.members) > 1)
    result = cc.consolidate_chain(root, target, chain)
    out_dir = Path(result["output_dir"])

    meta = json.loads((out_dir / "session.json").read_text())
    assert set(meta.keys()) == {
        "session_id", "provider", "total_sets", "total_session_chars",
        "models_used", "duplicate_of", "paste_context", "census_version"}
    assert meta["duplicate_of"] is None
    assert meta["paste_context"] is None
    assert meta["census_version"] == 1
    assert meta["total_sets"] == 3
    assert set(meta["models_used"]) == {"m1", "m2", "m3"}

    prov = json.loads((out_dir / "provenance.json").read_text())
    assert prov["emitted_chunks"] == 3
    assert prov["dropped_chunks"] == 2


def test_cli_dry_run(tmp_path, capsys):
    """--dry-run prints the plan and writes nothing."""
    root = tmp_path / "sessions"
    db = tmp_path / "vault.db"
    target = tmp_path / "lineage"
    _empty_db(db)

    a = root / "x1"
    _session(a, "x1", total_sets=1)
    _chunk(a, "1", 1, "solo", "r")

    sys.argv = ["consolidate_chains.py", "--root", str(root),
                "--db", str(db), "--target", str(target),
                "--all", "--dry-run"]
    rc = cc.main()
    assert rc == 0
    assert not target.exists(), "dry-run must not write to target"
