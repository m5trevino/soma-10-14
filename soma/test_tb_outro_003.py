"""Unit tests for TB-OUTRO-003: journal nodes + outrobeaver checkpoint DONE."""
import collections
import hashlib
import json
import sys

import pytest

from store import Soma
from machinetalk.checkpoint import (
    CheckpointPrecondition,
    CheckpointStore,
    PriorNonceRejected,
    journal_field,
    journal_main,
    load_journal_object,
    resolve_set_number,
)
from machinetalk.hashes import (
    JournalNonceError,
    canonical_json,
    journal_hash_for,
    journal_nonce,
)
from nexus_dendrite import (
    JOURNAL_NODE_TYPE,
    JournalInputMissing,
    JournalNodeWriter,
    PriorJournalNonce,
    journal_main as nodes_main,
    journal_node_id,
    load_journal,
    normalise_journal_event,
)

SESSION = "25-11-20-multiclip.2.0.feature.overhaul"
NONCE = "ed98a4cb-e194-41b8-9b1d-76819fbe6ced"
CHATSET_HASH = "b3360fce198db743f1bb7021ecdd557885e39b941a03fb484a200b21b54505f2"
PLAN_HASH = "509d83c0303aac184c8a5b901d1897c96d666dcbaaca182a86df95a86b489500"
REQUIRED = ("session_id", "event_type", "timestamp", "source", "confidence")


def journal_event(index: int, **overrides) -> dict:
    """A journal event shaped like the tb-006 output."""
    event = {
        "event_id": f"JRN-{SESSION}-{index + 1:04d}",
        "entry_id": f"TB006-{SESSION}-{index + 1:04d}",
        "session_id": SESSION,
        "nonce": NONCE,
        "chatset_hash": CHATSET_HASH,
        "turn_index": index,
        "event_type": "JOURNAL_NONE",
        "timestamp": "2026-10-28T00:12:27.992042",
        "source": "USER",
        "confidence": 0.5,
        "confidence_basis": "turn_score.mutual_understanding",
        "state_delta": "NONE",
        "content_hash": "a1b2c3d4e5f60718",
        "content_hash_local": "1d180973a6cba0fd",
        "content_hash_verified": False,
        "tool_calls": [],
    }
    event.update(overrides)
    return event


def journal_object(events) -> dict:
    """A whole tb-006 journal object around ``events``."""
    return {
        "contract": "JOURNAL_EVENTS_V1",
        "session_id": SESSION,
        "nonce": NONCE,
        "chatset_hash": CHATSET_HASH,
        "plan_hash": PLAN_HASH,
        "event_type": "SESSION_JOURNAL",
        "timestamp": "2026-10-30T06:53:05Z",
        "source": "outrobeaver:outrobeaver",
        "confidence": 0.5,
        "status": "OK",
        "events": list(events),
    }


def write_journal(tmp_path, journal: dict, name: str = "journal.json") -> str:
    path = tmp_path / name
    path.write_text(json.dumps(journal), encoding="utf-8")
    return str(path)


def journal_nodes(soma: Soma, session_id: str = SESSION) -> list:
    return [n for n in soma.query_by_type(JOURNAL_NODE_TYPE)
            if n.properties.get("session_id") == session_id]


def type_counts(soma: Soma) -> collections.Counter:
    return collections.Counter(
        row[0] for row in soma.conn.execute(
            "SELECT node_type FROM nodes").fetchall())


@pytest.fixture()
def three_events() -> list:
    return [journal_event(0), journal_event(1), journal_event(2)]


@pytest.fixture()
def soma() -> Soma:
    store = Soma()
    yield store
    store.close()


@pytest.fixture()
def checkpointed(tmp_path):
    """A run dir whose chatset 1 is through planbeaver under NONCE."""
    out = tmp_path / "out"
    store = CheckpointStore(out)
    store.record_distiller_hash(SESSION, 1, f"sess:1", CHATSET_HASH, 533292)
    store.record_plan_hash(SESSION, 1, PLAN_HASH, nonce=NONCE,
                           chatset_hash=CHATSET_HASH)
    return out


# ── hashing ──────────────────────────────────────────────────────────────

def test_journal_hash_is_canonical_over_the_parsed_object(tmp_path):
    journal = journal_object([journal_event(0), journal_event(1)])
    expected = hashlib.sha256(
        json.dumps(journal, sort_keys=True, separators=(",", ":"),
                   ensure_ascii=False).encode()).hexdigest()

    assert journal_hash_for(journal) == expected
    # Indentation is not part of the hash; content is.
    path = tmp_path / "reindented.json"
    path.write_text(json.dumps(journal, indent=4), encoding="utf-8")
    assert journal_hash_for(load_journal_object(path)) == expected

    journal["events"][0]["confidence"] = 0.9
    assert journal_hash_for(journal) != expected


def test_journal_hash_covers_the_header_too():
    journal = journal_object([journal_event(0)])
    before = journal_hash_for(journal)
    journal["status"] = "ERROR"
    assert journal_hash_for(journal) != before


def test_journal_hash_rejects_a_non_object():
    with pytest.raises(ValueError):
        journal_hash_for([journal_event(0)])


def test_journal_nonce_is_the_single_stamped_nonce():
    journal = journal_object([journal_event(0), journal_event(1)])
    assert journal_nonce(journal) == NONCE
    assert journal_nonce(journal, NONCE) == NONCE


def test_journal_nonce_rejects_a_mismatch():
    journal = journal_object([journal_event(0)])
    with pytest.raises(JournalNonceError):
        journal_nonce(journal, "prior-nonce")


def test_journal_nonce_rejects_mixed_events():
    journal = journal_object([journal_event(0),
                              journal_event(1, nonce="prior-nonce")])
    with pytest.raises(JournalNonceError):
        journal_nonce(journal)


def test_journal_without_any_nonce_returns_empty():
    journal = journal_object([journal_event(0)])
    journal.pop("nonce")
    journal["events"][0].pop("nonce")
    assert journal_nonce(journal) == ""


# ── node count and required properties ───────────────────────────────────

def test_node_count_equals_event_count(soma, tmp_path, three_events):
    result = JournalNodeWriter(soma).run(
        SESSION, write_journal(tmp_path, journal_object(three_events)))

    assert result["nodes_created"] == len(three_events)
    assert len(journal_nodes(soma)) == len(three_events)


def test_each_node_has_the_contract_fields(soma, tmp_path, three_events):
    JournalNodeWriter(soma).run(
        SESSION, write_journal(tmp_path, journal_object(three_events)))

    nodes = sorted(journal_nodes(soma),
                   key=lambda n: n.properties["turn_index"])
    assert len(nodes) == 3
    for node, event in zip(nodes, three_events):
        props = node.properties
        for key in REQUIRED:
            assert key in props, f"{event['event_id']} missing {key}"
        assert node.node_type == JOURNAL_NODE_TYPE
        assert props["session_id"] == SESSION
        assert props["event_type"] == event["event_type"]
        assert props["timestamp"] == event["timestamp"]
        assert props["source"] == event["source"]
        assert props["confidence"] == event["confidence"]
        assert props["event_id"] == event["event_id"]
        assert props["turn_index"] == event["turn_index"]


def test_nodes_carry_the_journal_hash_and_nonce(soma, tmp_path, three_events):
    journal = journal_object(three_events)
    expected = journal_hash_for(journal)
    JournalNodeWriter(soma).run(SESSION, write_journal(tmp_path, journal))

    for node in journal_nodes(soma):
        assert node.properties["journal_hash"] == expected
        assert node.properties["nonce"] == NONCE
        assert node.properties["journal_contract"] == "JOURNAL_EVENTS_V1"


def test_rerun_upserts_instead_of_duplicating(soma, tmp_path, three_events):
    path = write_journal(tmp_path, journal_object(three_events))
    writer = JournalNodeWriter(soma)
    writer.run(SESSION, path)
    writer.run(SESSION, path)

    assert len(journal_nodes(soma)) == len(three_events)


def test_node_id_is_stable(soma, tmp_path, three_events):
    path = write_journal(tmp_path, journal_object(three_events))
    first = JournalNodeWriter(soma).run(SESSION, path)["node_ids"]
    second = JournalNodeWriter(soma).run(SESSION, path)["node_ids"]

    assert first == second
    assert first[0] == journal_node_id(SESSION, three_events[0]["event_id"])


def test_duplicate_event_ids_are_written_once(soma, tmp_path):
    journal = journal_object([journal_event(0), journal_event(0),
                              journal_event(1)])
    result = JournalNodeWriter(soma).run(
        SESSION, write_journal(tmp_path, journal))

    assert result["duplicates_skipped"] == 1
    assert len(journal_nodes(soma)) == 2


# ── write scope: nodes only, no engine ───────────────────────────────────

def test_creates_no_other_node_types_and_no_edges(soma, tmp_path, three_events):
    soma.create_node("Directive", {"id": "dir-1", "session_id": SESSION,
                                   "source_text": "keep me"})
    before_types = type_counts(soma)
    before_edges = soma.edge_count()

    JournalNodeWriter(soma).run(
        SESSION, write_journal(tmp_path, journal_object(three_events)))

    after_types = type_counts(soma)
    assert after_types[JOURNAL_NODE_TYPE] == len(three_events)
    for node_type, count in before_types.items():
        assert after_types[node_type] == count, f"{node_type} count changed"
    assert soma.edge_count() == before_edges
    assert soma.get_node("dir-1").properties["source_text"] == "keep me"


def test_no_engine_or_llm_is_used(soma, tmp_path, three_events):
    watched = ("engine", "turnkey", "openai", "anthropic")
    before = {m for m in sys.modules if any(w in m for w in watched)}

    JournalNodeWriter(soma).run(
        SESSION, write_journal(tmp_path, journal_object(three_events)))

    after = {m for m in sys.modules if any(w in m for w in watched)}
    assert after == before


def test_dry_run_writes_nothing(soma, tmp_path, three_events):
    before = soma.node_count()
    result = JournalNodeWriter(soma).run(
        SESSION, write_journal(tmp_path, journal_object(three_events)),
        dry_run=True)

    assert result["nodes_created"] == 0
    assert len(result["node_ids"]) == len(three_events)
    assert soma.node_count() == before


# ── journal reading ──────────────────────────────────────────────────────

def test_missing_journal_file_raises(tmp_path):
    with pytest.raises(JournalInputMissing):
        load_journal(tmp_path / "nope.json")


def test_unreadable_journal_raises(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError):
        load_journal(bad)


def test_journal_must_be_an_object(tmp_path):
    bad = tmp_path / "list.json"
    bad.write_text(json.dumps([journal_event(0)]), encoding="utf-8")
    with pytest.raises(ValueError):
        load_journal(bad)


def test_wrong_contract_is_rejected(tmp_path):
    journal = journal_object([journal_event(0)])
    journal["contract"] = "SOMETHING_ELSE_V1"
    with pytest.raises(ValueError):
        load_journal(write_journal(tmp_path, journal))


@pytest.mark.parametrize("missing", REQUIRED)
def test_event_without_required_field_is_rejected(missing):
    event = journal_event(0)
    event.pop(missing)
    with pytest.raises(ValueError):
        normalise_journal_event(event, 0)


def test_event_without_event_id_is_rejected():
    event = journal_event(0)
    event.pop("event_id")
    with pytest.raises(ValueError):
        normalise_journal_event(event, 0)


@pytest.mark.parametrize("confidence", [None, "high", True, 1.5, -0.1])
def test_bad_confidence_is_rejected(confidence):
    with pytest.raises(ValueError):
        normalise_journal_event(journal_event(0, confidence=confidence), 0)


def test_conflicting_session_ids_are_rejected(tmp_path):
    journal = journal_object([journal_event(0),
                              journal_event(1, session_id="other-session")])
    with pytest.raises(ValueError):
        load_journal(write_journal(tmp_path, journal))


def test_header_session_mismatch_is_rejected(tmp_path):
    journal = journal_object([journal_event(0)])
    journal["session_id"] = "other-session"
    with pytest.raises(ValueError):
        load_journal(write_journal(tmp_path, journal))


def test_session_id_argument_must_match_the_journal(soma, tmp_path,
                                                    three_events):
    path = write_journal(tmp_path, journal_object(three_events))
    with pytest.raises(ValueError):
        JournalNodeWriter(soma).run("other-session", path)


# ── nonce gates ──────────────────────────────────────────────────────────

def test_supplied_nonce_is_echoed_and_stamped(soma, tmp_path, three_events):
    result = JournalNodeWriter(soma).run(
        SESSION, write_journal(tmp_path, journal_object(three_events)))

    assert result["nonce"] == NONCE
    assert all(n.properties["nonce"] == NONCE for n in journal_nodes(soma))


def test_supplied_nonce_mismatch_is_rejected(soma, tmp_path, three_events):
    path = write_journal(tmp_path, journal_object(three_events))
    with pytest.raises(JournalNonceError):
        JournalNodeWriter(soma).run(SESSION, path, nonce="prior-nonce")


def test_journal_without_a_nonce_is_rejected(soma, tmp_path):
    journal = journal_object([journal_event(0)])
    journal.pop("nonce")
    journal["events"][0].pop("nonce")
    with pytest.raises(JournalNonceError):
        JournalNodeWriter(soma).run(SESSION, write_journal(tmp_path, journal))


def test_a_prior_nonce_in_the_graph_is_rejected(soma, tmp_path):
    JournalNodeWriter(soma).run(
        SESSION, write_journal(tmp_path, journal_object([journal_event(0)]),
                               name="first.json"))
    second = journal_object([journal_event(1)])
    second["nonce"] = "fresh-nonce"
    second["events"][0]["nonce"] = "fresh-nonce"

    with pytest.raises(PriorJournalNonce):
        JournalNodeWriter(soma).run(
            SESSION, write_journal(tmp_path, second, name="second.json"))


# ── journal nodes CLI ────────────────────────────────────────────────────

def test_cli_prints_nonce_hash_and_node_count(tmp_path, capsys, three_events):
    path = write_journal(tmp_path, journal_object(three_events))
    store_path = tmp_path / "soma.json"
    expected = journal_hash_for(journal_object(three_events))

    assert nodes_main(["--journal", path, "--store", str(store_path)]) == 0

    out = capsys.readouterr().out
    assert f"NONCE: {NONCE}" in out
    assert f"JOURNAL_HASH: {expected}" in out
    assert "nodes: 3" in out
    payload = json.loads(out[out.index("\n{"):])
    assert payload["nodes_created"] == 3
    assert payload["journal_hash"] == expected

    store = Soma(str(store_path))
    try:
        assert len(journal_nodes(store)) == 3
    finally:
        store.close()


def test_cli_reports_a_missing_journal(tmp_path, capsys):
    code = nodes_main(["--journal", str(tmp_path / "nope.json"),
                       "--store", str(tmp_path / "soma.json")])

    assert code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["error"] == "JOURNAL_INPUT_MISSING"
    assert payload["nodes_created"] == 0


def test_cli_rejects_a_prior_nonce(tmp_path, capsys, soma):
    path = write_journal(tmp_path, journal_object([journal_event(0)]))
    store_path = tmp_path / "soma.json"
    assert nodes_main(["--journal", path, "--store", str(store_path)]) == 0
    capsys.readouterr()

    second = journal_object([journal_event(1)])
    second["nonce"] = "fresh-nonce"
    second["events"][0]["nonce"] = "fresh-nonce"
    other = write_journal(tmp_path, second, name="second.json")

    code = nodes_main(["--journal", other, "--store", str(store_path)])
    assert code == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["error"] == "NONCE_REJECTED"
    assert payload["nodes_created"] == 0


# ── checkpoint: outrobeaver DONE ─────────────────────────────────────────

def test_checkpoint_stage_becomes_done_with_the_journal_hash(checkpointed):
    store = CheckpointStore(checkpointed)
    digest = journal_hash_for(journal_object([journal_event(0)]))

    stage = store.record_journal_hash(
        SESSION, 1, digest, nonce=NONCE, chatset_hash=CHATSET_HASH,
        plan_hash=PLAN_HASH, events=1)

    assert stage["status"] == "DONE"
    assert stage["journal_hash"] == digest
    assert stage["nonce"] == NONCE
    assert stage["plan_hash"] == PLAN_HASH
    assert store.cs_is_done(SESSION, 1, "outrobeaver")
    assert store.cs_stage(SESSION, 1, "outrobeaver")["journal_hash"] == digest


def test_checkpoint_rejects_a_bad_hash_digest(checkpointed):
    store = CheckpointStore(checkpointed)
    with pytest.raises(ValueError):
        store.record_journal_hash(SESSION, 1, "not-a-digest", nonce=NONCE)


def test_checkpoint_requires_an_initialized_chatset(tmp_path):
    store = CheckpointStore(tmp_path)
    with pytest.raises(CheckpointPrecondition):
        store.record_journal_hash(SESSION, 1, "a" * 64, nonce=NONCE)


def test_checkpoint_requires_planbeaver_done(tmp_path):
    out = tmp_path / "out"
    store = CheckpointStore(out)
    store.record_distiller_hash(SESSION, 1, "sess:1", CHATSET_HASH, 533292)

    with pytest.raises(CheckpointPrecondition):
        store.record_journal_hash(SESSION, 1, "a" * 64, nonce=NONCE,
                                  chatset_hash=CHATSET_HASH)


def test_checkpoint_rejects_a_foreign_chatset_hash(checkpointed):
    store = CheckpointStore(checkpointed)
    with pytest.raises(CheckpointPrecondition):
        store.record_journal_hash(SESSION, 1, "a" * 64, nonce=NONCE,
                                  chatset_hash="a" * 64)


def test_checkpoint_rejects_a_foreign_plan_hash(checkpointed):
    store = CheckpointStore(checkpointed)
    with pytest.raises(CheckpointPrecondition):
        store.record_journal_hash(SESSION, 1, "a" * 64, nonce=NONCE,
                                  plan_hash="c" * 64)


def test_checkpoint_rejects_the_plan_run_s_prior_nonce(checkpointed):
    store = CheckpointStore(checkpointed)
    with pytest.raises(PriorNonceRejected):
        store.record_journal_hash(SESSION, 1, "a" * 64, nonce="prior-nonce",
                                  plan_hash=PLAN_HASH)


def test_checkpoint_rejects_a_nonce_bound_to_another_journal(checkpointed):
    store = CheckpointStore(checkpointed)
    store.record_journal_hash(SESSION, 1, "a" * 64, nonce=NONCE)
    with pytest.raises(PriorNonceRejected):
        store.record_journal_hash(SESSION, 1, "b" * 64, nonce=NONCE)


def test_checkpoint_is_idempotent_for_the_same_journal(checkpointed):
    store = CheckpointStore(checkpointed)
    first = store.record_journal_hash(SESSION, 1, "a" * 64, nonce=NONCE)
    second = store.record_journal_hash(SESSION, 1, "a" * 64, nonce=NONCE)

    assert first["journal_hash"] == second["journal_hash"] == "a" * 64
    assert second["status"] == "DONE"


# ── checkpoint CLI: hash file + DONE ─────────────────────────────────────

def test_journal_cli_writes_hash_file_and_marks_done(checkpointed, tmp_path,
                                                     capsys):
    journal = journal_object([journal_event(0), journal_event(1)])
    path = write_journal(tmp_path, journal)
    hash_file = tmp_path / "soma_outrobeaver_hash.txt"
    expected = journal_hash_for(journal)

    code = journal_main(["--journal", path, "--out-dir", str(checkpointed),
                         "--hash-out", str(hash_file)])
    assert code == 0

    out = capsys.readouterr().out
    assert f"NONCE: {NONCE}" in out
    assert f"JOURNAL_HASH: {expected}" in out
    assert "STAGE: outrobeaver DONE" in out

    assert hash_file.read_text().strip() == expected
    # Independent check: canonical JSON, never the file's bytes.
    parsed = json.loads(open(path, encoding="utf-8").read())
    independent = hashlib.sha256(canonical_json(parsed).encode()).hexdigest()
    assert independent == expected

    store = CheckpointStore(checkpointed)
    stage = store.cs_stage(SESSION, 1, "outrobeaver")
    assert stage["status"] == "DONE"
    assert stage["journal_hash"] == expected
    assert stage["events"] == 2


def test_journal_cli_auto_detects_the_chatset(checkpointed):
    store = CheckpointStore(checkpointed)
    assert resolve_set_number(store, SESSION, CHATSET_HASH) == "1"


def test_journal_cli_rejects_an_unknown_chatset_hash(checkpointed, tmp_path):
    store = CheckpointStore(checkpointed)
    with pytest.raises(ValueError):
        resolve_set_number(store, SESSION, "a" * 64)


def test_journal_cli_reports_a_missing_journal(checkpointed, tmp_path, capsys):
    code = journal_main(["--journal", str(tmp_path / "nope.json"),
                         "--out-dir", str(checkpointed)])

    assert code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["error"] == "JOURNAL_INPUT_MISSING"


def test_journal_cli_rejects_a_prior_nonce(checkpointed, tmp_path, capsys):
    path = write_journal(tmp_path, journal_object([journal_event(0)]))
    code = journal_main(["--journal", path, "--out-dir", str(checkpointed),
                         "--nonce", "prior-nonce"])

    assert code == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["error"] == "NONCE_REJECTED"


def test_journal_cli_dry_run_writes_nothing(checkpointed, tmp_path, capsys):
    path = write_journal(tmp_path, journal_object([journal_event(0)]))
    hash_file = tmp_path / "hash.txt"

    assert journal_main(["--journal", path, "--out-dir", str(checkpointed),
                         "--hash-out", str(hash_file),
                         "--dry-run"]) == 0

    assert not hash_file.exists()
    store = CheckpointStore(checkpointed)
    assert store.cs_stage(SESSION, 1, "outrobeaver")["status"] == "PENDING"
    assert "DRY-RUN" in capsys.readouterr().out


# ── checkpoint helpers ───────────────────────────────────────────────────

def test_load_journal_object_rejects_a_list(tmp_path):
    bad = tmp_path / "list.json"
    bad.write_text(json.dumps([]), encoding="utf-8")
    with pytest.raises(ValueError):
        load_journal_object(bad)


def test_journal_field_rejects_a_mixed_value():
    journal = journal_object([journal_event(0),
                              journal_event(1, session_id="other-session")])
    with pytest.raises(ValueError):
        journal_field(journal, "session_id")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
