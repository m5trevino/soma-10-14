"""Unit tests for TB-PLAN-003: one DirectivePlanNode per planbeaver plan item."""
import collections
import json
import sys

import pytest

from store import Soma
from nexus_dendrite import (
    PLAN_NODE_TYPE,
    PlanbeaverPlanNodeWriter,
    PlanInputMissing,
    load_plan_items,
    normalise_plan_item,
    plan_main,
    plan_node_id,
)

SESSION = "25-11-20-multiclip.2.0.feature.overhaul"
NONCE = "ed98a4cb-e194-41b8-9b1d-76819fbe6ced"
REQUIRED = ("session_id", "plan_item_type", "description", "priority",
            "dependencies")


def plan_item(index: int, **overrides) -> dict:
    """A plan item shaped like the planbeaver output."""
    item = {
        "id": f"PLAN-ITEM-{index}",
        "session_id": SESSION,
        "chatset_hash": "b" * 64,
        "plan_id": f"PLAN-{SESSION}",
        "type": "file",
        "description": f"file_{index}.py — task {index}",
        "priority": 3,
        "dependencies": [f"PLAN-ITEM-{index - 1}"] if index else [],
        "source_ref": f"FILE-{index}",
        "consumers": ["FILE-0"],
        "derived_from": f"planbeaver_output.files[{index}]",
        "nonce": NONCE,
    }
    item.update(overrides)
    return item


def write_plan(tmp_path, items) -> str:
    path = tmp_path / "soma_planbeaver_plan.json"
    path.write_text(json.dumps(items), encoding="utf-8")
    return str(path)


def plan_nodes(soma: Soma, session_id: str = SESSION) -> list:
    return [n for n in soma.query_by_type(PLAN_NODE_TYPE)
            if n.properties.get("session_id") == session_id]


def type_counts(soma: Soma) -> collections.Counter:
    return collections.Counter(
        row[0] for row in soma.conn.execute(
            "SELECT node_type FROM nodes").fetchall())


@pytest.fixture()
def three_items() -> list:
    return [plan_item(0), plan_item(1), plan_item(2)]


@pytest.fixture()
def soma() -> Soma:
    store = Soma()
    yield store
    store.close()


# ── node count and required properties ───────────────────────────────────

def test_node_count_equals_plan_item_count(soma, tmp_path, three_items):
    writer = PlanbeaverPlanNodeWriter(soma)
    result = writer.run(SESSION, write_plan(tmp_path, three_items))

    assert result["nodes_created"] == len(three_items)
    assert len(plan_nodes(soma)) == len(three_items)


def test_each_node_has_required_properties(soma, tmp_path, three_items):
    PlanbeaverPlanNodeWriter(soma).run(SESSION, write_plan(tmp_path, three_items))

    nodes = plan_nodes(soma)
    assert len(nodes) == 3
    for node, item in zip(sorted(nodes, key=lambda n: n.properties["plan_item_id"]),
                          three_items):
        props = node.properties
        for key in REQUIRED:
            assert key in props, f"{item['id']} missing {key}"
        assert props["session_id"] == SESSION
        assert props["plan_item_type"] == item["type"]
        assert props["description"] == item["description"]
        assert props["priority"] == item["priority"]
        assert props["dependencies"] == item["dependencies"]


def test_dependencies_survive_a_save_and_reload(soma, tmp_path, three_items):
    path = tmp_path / "soma.json"
    store = Soma(str(path))
    PlanbeaverPlanNodeWriter(store).run(SESSION, write_plan(tmp_path, three_items))
    store.save()
    store.close()

    reloaded = Soma(str(path))
    try:
        nodes = plan_nodes(reloaded)
        assert len(nodes) == 3
        deps = sorted(tuple(n.properties["dependencies"]) for n in nodes)
        assert deps == [(), ("PLAN-ITEM-0",), ("PLAN-ITEM-1",)]
    finally:
        reloaded.close()


def test_rerun_upserts_instead_of_duplicating(soma, tmp_path, three_items):
    plan = write_plan(tmp_path, three_items)
    writer = PlanbeaverPlanNodeWriter(soma)
    writer.run(SESSION, plan)
    writer.run(SESSION, plan)

    assert len(plan_nodes(soma)) == len(three_items)


def test_node_id_is_stable(soma, tmp_path, three_items):
    plan = write_plan(tmp_path, three_items)
    first = PlanbeaverPlanNodeWriter(soma).run(SESSION, plan)["node_ids"]
    second = PlanbeaverPlanNodeWriter(soma).run(SESSION, plan)["node_ids"]

    assert first == second
    assert first[0] == plan_node_id(SESSION, "PLAN-ITEM-0")


# ── write scope: nodes only ──────────────────────────────────────────────

def test_creates_no_other_node_types_and_no_edges(soma, tmp_path, three_items):
    before_types = type_counts(soma)
    before_edges = soma.edge_count()

    PlanbeaverPlanNodeWriter(soma).run(SESSION, write_plan(tmp_path, three_items))

    after_types = type_counts(soma)
    assert after_types[PLAN_NODE_TYPE] == len(three_items)
    assert after_types[PLAN_NODE_TYPE] - before_types[PLAN_NODE_TYPE] == 3
    for node_type, count in before_types.items():
        assert after_types[node_type] == count, f"{node_type} count changed"
    assert soma.edge_count() == before_edges


def test_no_engine_or_checkpoint_is_used(soma, tmp_path, three_items):
    PlanbeaverPlanNodeWriter(soma).run(SESSION, write_plan(tmp_path, three_items))

    assert "soma.machinetalk.engine" not in sys.modules
    assert "soma.machinetalk.checkpoint" not in sys.modules


def test_dry_run_writes_nothing(soma, tmp_path, three_items):
    before = soma.node_count()
    result = PlanbeaverPlanNodeWriter(soma).run(
        SESSION, write_plan(tmp_path, three_items), dry_run=True)

    assert result["nodes_created"] == 0
    assert result["node_ids"]
    assert soma.node_count() == before


# ── plan reading ─────────────────────────────────────────────────────────

def test_missing_plan_file_raises(tmp_path):
    with pytest.raises(PlanInputMissing):
        load_plan_items(tmp_path / "nope.json")


def test_unreadable_plan_file_raises(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError):
        load_plan_items(bad)


def test_plan_must_be_a_list(tmp_path):
    bad = tmp_path / "obj.json"
    bad.write_text(json.dumps({"items": []}), encoding="utf-8")
    with pytest.raises(ValueError):
        load_plan_items(bad)


@pytest.mark.parametrize("missing", ["type", "description", "priority",
                                     "dependencies"])
def test_item_without_required_field_is_rejected(missing):
    item = plan_item(0)
    item.pop(missing)
    with pytest.raises(ValueError):
        normalise_plan_item(item, 0)


def test_dependencies_must_be_a_list():
    with pytest.raises(ValueError):
        normalise_plan_item(plan_item(0, dependencies="PLAN-ITEM-0"), 0)


def test_conflicting_session_ids_are_rejected(tmp_path):
    plan = write_plan(tmp_path, [plan_item(0),
                                 plan_item(1, session_id="other-session")])
    with pytest.raises(ValueError):
        load_plan_items(plan)


def test_duplicate_item_ids_are_written_once(soma, tmp_path):
    plan = write_plan(tmp_path, [plan_item(0), plan_item(0), plan_item(1)])
    result = PlanbeaverPlanNodeWriter(soma).run(SESSION, plan)

    assert result["duplicates_skipped"] == 1
    assert len(plan_nodes(soma)) == 2


def test_item_without_id_falls_back_to_its_position(soma, tmp_path):
    item = plan_item(0)
    item.pop("id")
    plan = write_plan(tmp_path, [item])
    result = PlanbeaverPlanNodeWriter(soma).run(SESSION, plan)

    assert result["node_ids"] == [plan_node_id(SESSION, "PLAN-ITEM-0")]
    assert len(plan_nodes(soma)) == 1


# ── nonce ────────────────────────────────────────────────────────────────

def test_supplied_nonce_is_echoed_and_stamped(soma, tmp_path, three_items):
    result = PlanbeaverPlanNodeWriter(soma).run(
        SESSION, write_plan(tmp_path, three_items))

    assert result["nonce"] == NONCE
    assert all(n.properties["nonce"] == NONCE for n in plan_nodes(soma))


def test_conflicting_nonces_are_rejected(tmp_path):
    plan = write_plan(tmp_path, [plan_item(0),
                                 plan_item(1, nonce="prior-nonce")])
    with pytest.raises(ValueError):
        load_plan_items(plan)


# ── CLI ──────────────────────────────────────────────────────────────────

def test_cli_prints_nonce_and_node_count(tmp_path, capsys, three_items):
    plan = write_plan(tmp_path, three_items)
    store_path = tmp_path / "soma.json"

    assert plan_main(["--plan", plan, "--store", str(store_path)]) == 0

    out = capsys.readouterr().out
    assert f"NONCE: {NONCE}" in out
    assert "nodes: 3" in out
    payload = json.loads(out[out.index("\n{"):])
    assert payload["nodes_created"] == 3

    store = Soma(str(store_path))
    try:
        assert len(plan_nodes(store)) == 3
    finally:
        store.close()


def test_cli_reports_missing_plan(tmp_path, capsys):
    code = plan_main(["--plan", str(tmp_path / "nope.json"),
                      "--store", str(tmp_path / "soma.json")])

    assert code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["error"] == "PLAN_INPUT_MISSING"
    assert payload["nodes_created"] == 0


def test_cli_rejects_session_mismatch(tmp_path, capsys, three_items):
    plan = write_plan(tmp_path, three_items)
    code = plan_main(["--plan", plan, "--session-id", "other-session",
                      "--store", str(tmp_path / "soma.json")])

    assert code == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["error"] == "PLAN_INPUT_INVALID"


# ── store: node types beyond the schema's CHECK list ─────────────────────

def test_store_accepts_a_node_type_missing_from_its_check_list(soma):
    soma.create_node("Directive", {"id": "dir-1", "session_id": SESSION,
                                   "source_text": "keep me"})

    soma.create_node(PLAN_NODE_TYPE, {"id": "plan-1", "session_id": SESSION,
                                      "priority": 2, "dependencies": []})

    assert soma.get_node("dir-1").properties["source_text"] == "keep me"
    assert soma.get_node("plan-1").node_type == PLAN_NODE_TYPE
    indexes = {row[0] for row in soma.conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index'").fetchall()}
    assert {"idx_nodes_type", "idx_nodes_sid"} <= indexes


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
