"""Tests for tools/run_consolidator.py (interactive launcher)."""
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import consolidate_chains as cc
import run_consolidator as rc


def _chains():
    return [
        cc.Chain(key="chain-a", members=["a"], total_chunks=10,
                 unique_chunks=8, generations=1),
        cc.Chain(key="chain-b", members=["b1", "b2"], total_chunks=20,
                 unique_chunks=12, generations=2),
    ]


def _input(responses):
    """input() stub that replays responses, then auto-quits ('q')."""
    it = iter(responses)

    def fn(prompt=""):
        try:
            return next(it)
        except StopIteration:
            return "q"
    return fn


def test_select_execute(monkeypatch):
    """Choosing an index + 'e' routes to consolidate_chain (a write)."""
    calls = []
    exported = []

    def fake_consolidate(root, target, chain):
        calls.append(chain.key)
        return {"key": chain.key, "members": chain.members,
                "emitted": 99, "dropped": 3, "output_dir": "/tmp/x"}

    monkeypatch.setattr(cc, "consolidate_chain", fake_consolidate)
    monkeypatch.setattr(cc, "dedup_chain", lambda r, m: ([], []))
    monkeypatch.setattr(rc, "export_to_soma_json",
                        lambda paths, qp=None: exported.append(paths) or {})

    rc.run(_chains(), input_fn=_input(["1", "e"]), out=io.StringIO())
    assert calls == ["chain-a"]
    assert exported == [["/tmp/x"]]


def test_dry_run(monkeypatch):
    """Choosing an index + 'd' previews via dedup_chain, writes nothing."""
    calls = []

    monkeypatch.setattr(cc, "consolidate_chain",
                        lambda r, t, c: calls.append("WRITE") or {})
    monkeypatch.setattr(cc, "dedup_chain",
                        lambda r, m: (calls.append(("dedup", tuple(m))) or ([], [])))

    rc.run(_chains(), input_fn=_input(["2", "d"]), out=io.StringIO())
    assert ("dedup", ("b1", "b2")) in calls
    assert "WRITE" not in calls


def test_all_execute(monkeypatch):
    """'a' + 'e' consolidates every chain."""
    calls = []
    exported = []
    monkeypatch.setattr(cc, "consolidate_chain",
                        lambda r, t, c: calls.append(c.key) or {
                            "key": c.key, "members": c.members,
                            "emitted": 1, "dropped": 0, "output_dir": "/tmp/" + c.key})
    monkeypatch.setattr(cc, "dedup_chain", lambda r, m: ([], []))
    monkeypatch.setattr(rc, "export_to_soma_json",
                        lambda paths, qp=None: exported.append(paths) or {})

    rc.run(_chains(), input_fn=_input(["a", "e"]), out=io.StringIO())
    assert calls == ["chain-a", "chain-b"]
    assert exported == [["/tmp/chain-a", "/tmp/chain-b"]]


def test_quit(monkeypatch):
    """'q' exits without calling anything."""
    calls = []
    monkeypatch.setattr(cc, "consolidate_chain",
                        lambda r, t, c: calls.append(c.key) or {})
    monkeypatch.setattr(cc, "dedup_chain", lambda r, m: calls.append("dedup"))

    rc.run(_chains(), input_fn=_input(["q"]), out=io.StringIO())
    assert calls == []


def test_invalid_input_loops(monkeypatch):
    """Invalid choices and out-of-range indices loop back without crashing."""
    calls = []
    monkeypatch.setattr(cc, "consolidate_chain",
                        lambda r, t, c: calls.append(c.key) or {
                            "key": c.key, "members": c.members,
                            "emitted": 1, "dropped": 0, "output_dir": "/tmp"})
    monkeypatch.setattr(cc, "dedup_chain", lambda r, m: ([], []))
    monkeypatch.setattr(rc, "export_to_soma_json", lambda paths, qp=None: {})

    out = io.StringIO()
    # bogus → out-of-range → valid → execute
    rc.run(_chains(), input_fn=_input(["xyz", "99", "1", "e"]), out=out)
    assert calls == ["chain-a"]
    assert "invalid" in out.getvalue()


def test_export_to_soma_json_schema(tmp_path):
    """The export writes the legacy /api/select queue schema exactly."""
    qp = tmp_path / "soma_queue.json"
    data = rc.export_to_soma_json(["/a/b", "/c/d"], queue_path=qp)

    assert set(data.keys()) == {"selected", "count", "timestamp"}
    assert data["selected"] == ["/a/b", "/c/d"]
    assert data["count"] == 2
    assert isinstance(data["timestamp"], float)

    # What load_queue() reads: data["selected"] parses back identically.
    back = json.loads(qp.read_text())
    assert back["selected"] == ["/a/b", "/c/d"]
    assert back["count"] == 2
