"""Unit tests for TB-TK-REPLACE-004: RetrogradeDendrite.

Verifies:
  - Outcome nodes are definitive and immutable post-creation
  - Drift nodes accurately map plan changes (from_node -> DRIFTS_FROM -> to_node)
  - Actions are linked to assigned dendrites
  - All node properties are verified against schema
  - Idempotency check prevents duplicate OutcomeNode creation on retry
  - Edge types: TRIGGERED_BY, PRODUCES, LEARNS, DRIFTS_FROM, ASSIGNED_TO
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

import pytest

_SOMA_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SOMA_DIR))

from store import Soma, Node, Edge
from pipeline.retrograde_dendrite import RetrogradeDendrite
from pipeline.drafter_dendrite import LLMResponse


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------

def _make_soma(
    cs_id: str = "cs-001",
    session_id: str = "sess-001",
    assistant_text: str = "Built the CLI. Deployed to staging.",
) -> Soma:
    soma = Soma(force_empty=True)
    soma.create_node("ChatSet", {
        "id": cs_id,
        "session_id": session_id,
        "set_number": 1,
        "user_text": "Build the CLI and deploy it.",
        "assistant_text": assistant_text,
    })
    return soma


def _full_payload() -> str:
    """Standard LLM response with all sections populated."""
    return json.dumps({
        "outcome": {
            "outcome_text": "CLI built and deployed to staging successfully.",
        },
        "deliverables": [
            {"deliverable_text": "CLI binary"},
            {"deliverable_text": "Deployment script"},
        ],
        "lessons": [
            {"lesson_text": "Always test with real DB first"},
        ],
        "drifts": [
            {
                "drift_description": "Switched from SQLite to PostgreSQL mid-build",
                "from_node": "plan-db-choice",
                "to_node": "plan-postgres-migrate",
                "drift_type": "technical_decision",
            },
        ],
        "actions": [
            {"action_text": "Run integration tests", "assigned_to": "test-dendrite"},
        ],
        "unresolved": [],
    })


def _minimal_payload() -> str:
    """Minimal LLM response."""
    return json.dumps({
        "outcome": {"outcome_text": "Done."},
        "deliverables": [],
        "lessons": [],
        "drifts": [],
        "actions": [],
        "unresolved": [],
    })


def _drift_only_payload() -> str:
    """LLM response with drifts but minimal other sections."""
    return json.dumps({
        "outcome": {"outcome_text": "Partial success."},
        "deliverables": [{"deliverable_text": "stub binary"}],
        "lessons": [{"lesson_text": "check env first"}],
        "drifts": [
            {
                "drift_description": "Scope shifted from MVP to full feature",
                "from_node": "mvp-plan",
                "to_node": "full-feature-plan",
                "drift_type": "scope_creep",
            },
        ],
        "actions": [
            {"action_text": "Update sprint plan", "assigned_to": "planning-dendrite"},
        ],
        "unresolved": ["cleanup debt"],
    })


class FakeLLMClient:
    """Returns a pre-programmed JSON response."""

    def __init__(self, response_text: str = "") -> None:
        self._response_text = response_text
        self.call_count = 0
        self.last_messages: list[dict[str, str]] = []

    def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> LLMResponse:
        self.call_count += 1
        self.last_messages = messages
        return LLMResponse(
            model_id="fake-llm",
            content=self._response_text,
            prompt_tokens=150,
            completion_tokens=80,
            total_tokens=230,
            latency_ms=25.0,
        )


def _make_retrograde(soma: Soma, llm_response: str) -> RetrogradeDendrite:
    llm = FakeLLMClient(llm_response)
    return RetrogradeDendrite(soma, llm)


# ---------------------------------------------------------------------------
# Tests: Outcome Immutability
# ---------------------------------------------------------------------------

class TestOutcomeImmutability:
    """Outcome nodes are definitive and immutable post-creation."""

    def test_outcome_node_created_with_immutable_flag(self) -> None:
        soma = _make_soma()
        dendrite = _make_retrograde(soma, _full_payload())
        result = dendrite.run("cs-001")
        outcome = soma.get_node(result["outcome_node_id"])
        assert outcome is not None
        assert outcome.node_type == "OutcomeNode"
        assert outcome.properties["immutable"] is True
        assert outcome.properties["outcome_text"] == "CLI built and deployed to staging successfully."

    def test_outcome_has_required_properties(self) -> None:
        soma = _make_soma()
        dendrite = _make_retrograde(soma, _full_payload())
        result = dendrite.run("cs-001")
        outcome = soma.get_node(result["outcome_node_id"])
        assert "session_id" in outcome.properties
        assert "chat_set_id" in outcome.properties
        assert "created_at" in outcome.properties
        assert outcome.properties["session_id"] == "sess-001"
        assert outcome.properties["chat_set_id"] == "cs-001"

    def test_outcome_triggers_by_edge_to_chatset(self) -> None:
        soma = _make_soma()
        dendrite = _make_retrograde(soma, _full_payload())
        result = dendrite.run("cs-001")
        outcome_id = result["outcome_node_id"]
        edges = soma.get_edges(outcome_id)
        triggered_by_edges = [
            e for e in edges
            if e.rel_type == "TRIGGERED_BY" and e.source == outcome_id
        ]
        assert len(triggered_by_edges) == 1
        assert triggered_by_edges[0].target == "cs-001"

    def test_no_code_generation_in_outcome(self) -> None:
        """Hard gate: outcome must not contain code generation."""
        soma = _make_soma()
        dendrite = _make_retrograde(soma, _full_payload())
        result = dendrite.run("cs-001")
        outcome = soma.get_node(result["outcome_node_id"])
        assert "generated_code" not in outcome.properties


# ---------------------------------------------------------------------------
# Tests: Drift Node Linking
# ---------------------------------------------------------------------------

class TestDriftNodeLinking:
    """Drift nodes accurately map plan changes (from_node -> DRIFTS_FROM -> to_node)."""

    def test_drift_nodes_created(self) -> None:
        soma = _make_soma()
        dendrite = _make_retrograde(soma, _full_payload())
        result = dendrite.run("cs-001")
        assert len(result["drift_node_ids"]) == 1

    def test_drift_node_properties(self) -> None:
        soma = _make_soma()
        dendrite = _make_retrograde(soma, _full_payload())
        result = dendrite.run("cs-001")
        drift_id = result["drift_node_ids"][0]
        drift = soma.get_node(drift_id)
        assert drift is not None
        assert drift.node_type == "DriftNode"
        assert drift.properties["drift_description"] == (
            "Switched from SQLite to PostgreSQL mid-build"
        )
        assert drift.properties["from_node"] == "plan-db-choice"
        assert drift.properties["to_node"] == "plan-postgres-migrate"
        assert drift.properties["drift_type"] == "technical_decision"

    def test_drifts_from_edges(self) -> None:
        """DriftNode -> DRIFTS_FROM -> from_node edges must exist."""
        soma = _make_soma()
        dendrite = _make_retrograde(soma, _full_payload())
        result = dendrite.run("cs-001")
        drift_id = result["drift_node_ids"][0]
        edges = soma.get_edges(drift_id)
        drift_edges = [
            e for e in edges
            if e.rel_type == "DRIFTS_FROM" and e.source == drift_id
        ]
        assert len(drift_edges) == 1
        assert drift_edges[0].target == "plan-db-choice"

    def test_multiple_drifts_all_have_edges(self) -> None:
        soma = _make_soma()
        payload = json.dumps({
            "outcome": {"outcome_text": "ok"},
            "deliverables": [],
            "lessons": [],
            "drifts": [
                {"drift_description": "d1", "from_node": "p1", "to_node": "p2", "drift_type": "scope_creep"},
                {"drift_description": "d2", "from_node": "p3", "to_node": "p4", "drift_type": "priority_shift"},
            ],
            "actions": [],
            "unresolved": [],
        })
        dendrite = _make_retrograde(soma, payload)
        result = dendrite.run("cs-001")
        assert len(result["drift_node_ids"]) == 2
        for drift_id in result["drift_node_ids"]:
            edges = soma.get_edges(drift_id)
            drift_edges = [e for e in edges if e.rel_type == "DRIFTS_FROM"]
            assert len(drift_edges) == 1

    def test_drift_type_validation_accepts_valid_types(self) -> None:
        """All valid drift types must be accepted."""
        for dt in ["scope_creep", "requirement_change", "technical_decision",
                    "constraint_override", "priority_shift", "unknown"]:
            soma = _make_soma()
            payload = json.dumps({
                "outcome": {"outcome_text": "ok"},
                "deliverables": [],
                "lessons": [],
                "drifts": [{"drift_description": "x", "from_node": "a", "to_node": "b", "drift_type": dt}],
                "actions": [],
                "unresolved": [],
            })
            dendrite = _make_retrograde(soma, payload)
            result = dendrite.run("cs-001")
            assert len(result["drift_node_ids"]) == 1

    def test_drift_with_invalid_type_is_skipped(self) -> None:
        soma = _make_soma()
        payload = json.dumps({
            "outcome": {"outcome_text": "ok"},
            "deliverables": [],
            "lessons": [],
            "drifts": [
                {"drift_description": "good", "from_node": "a", "to_node": "b", "drift_type": "scope_creep"},
                {"drift_description": "bad", "from_node": "a", "to_node": "b", "drift_type": "invalid_type"},
            ],
            "actions": [],
            "unresolved": [],
        })
        dendrite = _make_retrograde(soma, payload)
        result = dendrite.run("cs-001")
        assert len(result["drift_node_ids"]) == 1
        drift = soma.get_node(result["drift_node_ids"][0])
        assert drift.properties["drift_description"] == "good"

    def test_drift_missing_from_node_field_skipped(self) -> None:
        soma = _make_soma()
        payload = json.dumps({
            "outcome": {"outcome_text": "ok"},
            "deliverables": [],
            "lessons": [],
            "drifts": [
                {"drift_description": "missing from", "to_node": "b", "drift_type": "unknown"},
            ],
            "actions": [],
            "unresolved": [],
        })
        dendrite = _make_retrograde(soma, payload)
        result = dendrite.run("cs-001")
        assert len(result["drift_node_ids"]) == 0

    def test_drift_missing_to_node_field_skipped(self) -> None:
        soma = _make_soma()
        payload = json.dumps({
            "outcome": {"outcome_text": "ok"},
            "deliverables": [],
            "lessons": [],
            "drifts": [
                {"drift_description": "missing to", "from_node": "a", "drift_type": "unknown"},
            ],
            "actions": [],
            "unresolved": [],
        })
        dendrite = _make_retrograde(soma, payload)
        result = dendrite.run("cs-001")
        assert len(result["drift_node_ids"]) == 0


# ---------------------------------------------------------------------------
# Tests: Deliverable Linking
# ---------------------------------------------------------------------------

class TestDeliverableLinking:
    """Deliverable nodes linked to Outcome via PRODUCES edges."""

    def test_deliverable_nodes_created(self) -> None:
        soma = _make_soma()
        dendrite = _make_retrograde(soma, _full_payload())
        result = dendrite.run("cs-001")
        assert len(result["deliverable_node_ids"]) == 2

    def test_deliverable_node_properties(self) -> None:
        soma = _make_soma()
        dendrite = _make_retrograde(soma, _full_payload())
        result = dendrite.run("cs-001")
        deliverable = soma.get_node(result["deliverable_node_ids"][0])
        assert deliverable.node_type == "DeliverableNode"
        assert deliverable.properties["deliverable_text"] == "CLI binary"
        assert deliverable.properties["source_outcome_id"] == "outcome-cs-001"

    def test_produces_edges_from_outcome(self) -> None:
        soma = _make_soma()
        dendrite = _make_retrograde(soma, _full_payload())
        result = dendrite.run("cs-001")
        outcome_id = result["outcome_node_id"]
        for did in result["deliverable_node_ids"]:
            edges = soma.get_edges(outcome_id)
            produce_edges = [
                e for e in edges
                if e.rel_type == "PRODUCES" and e.source == outcome_id
            ]
            assert any(e.target == did for e in produce_edges)

    def test_deliverable_schema_validation(self) -> None:
        soma = _make_soma()
        dendrite = _make_retrograde(soma, _full_payload())
        result = dendrite.run("cs-001")
        for did in result["deliverable_node_ids"]:
            node = soma.get_node(did)
            assert "deliverable_text" in node.properties
            assert "source_outcome_id" in node.properties

    def test_empty_deliverables_no_nodes(self) -> None:
        soma = _make_soma()
        dendrite = _make_retrograde(soma, _minimal_payload())
        result = dendrite.run("cs-001")
        assert len(result["deliverable_node_ids"]) == 0


# ---------------------------------------------------------------------------
# Tests: Lesson Linking
# ---------------------------------------------------------------------------

class TestLessonLinking:
    """Lesson nodes linked to Outcome via LEARNS edges."""

    def test_lesson_nodes_created(self) -> None:
        soma = _make_soma()
        dendrite = _make_retrograde(soma, _full_payload())
        result = dendrite.run("cs-001")
        assert len(result["lesson_node_ids"]) == 1

    def test_learns_edges_from_outcome(self) -> None:
        soma = _make_soma()
        dendrite = _make_retrograde(soma, _full_payload())
        result = dendrite.run("cs-001")
        outcome_id = result["outcome_node_id"]
        for lid in result["lesson_node_ids"]:
            edges = soma.get_edges(outcome_id)
            learns_edges = [
                e for e in edges
                if e.rel_type == "LEARNS" and e.source == outcome_id
            ]
            assert any(e.target == lid for e in learns_edges)

    def test_lesson_node_properties(self) -> None:
        soma = _make_soma()
        dendrite = _make_retrograde(soma, _full_payload())
        result = dendrite.run("cs-001")
        lesson = soma.get_node(result["lesson_node_ids"][0])
        assert lesson.node_type == "LessonNode"
        assert lesson.properties["lesson_text"] == "Always test with real DB first"
        assert lesson.properties["source_outcome_id"] == "outcome-cs-001"


# ---------------------------------------------------------------------------
# Tests: Action Linking
# ---------------------------------------------------------------------------

class TestActionLinking:
    """Actions linked to assigned dendrites via ASSIGNED_TO edges."""

    def test_action_nodes_created(self) -> None:
        soma = _make_soma()
        dendrite = _make_retrograde(soma, _full_payload())
        result = dendrite.run("cs-001")
        assert len(result["action_node_ids"]) == 1

    def test_action_properties(self) -> None:
        soma = _make_soma()
        dendrite = _make_retrograde(soma, _full_payload())
        result = dendrite.run("cs-001")
        action = soma.get_node(result["action_node_ids"][0])
        assert action.node_type == "ActionNode"
        assert action.properties["action_text"] == "Run integration tests"
        assert action.properties["assigned_to"] == "test-dendrite"
        assert action.properties["status"] == "open"

    def test_assigned_to_edges(self) -> None:
        """ActionNode -> ASSIGNED_TO -> assigned target."""
        soma = _make_soma()
        dendrite = _make_retrograde(soma, _full_payload())
        result = dendrite.run("cs-001")
        action_id = result["action_node_ids"][0]
        edges = soma.get_edges(action_id)
        assigned_edges = [
            e for e in edges
            if e.rel_type == "ASSIGNED_TO" and e.source == action_id
        ]
        assert len(assigned_edges) == 1
        assert assigned_edges[0].target == "test-dendrite"

    def test_multiple_actions_all_assigned(self) -> None:
        soma = _make_soma()
        payload = json.dumps({
            "outcome": {"outcome_text": "ok"},
            "deliverables": [],
            "lessons": [],
            "drifts": [],
            "actions": [
                {"action_text": "fix A", "assigned_to": "dendrite-a"},
                {"action_text": "fix B", "assigned_to": "dendrite-b"},
            ],
            "unresolved": [],
        })
        dendrite = _make_retrograde(soma, payload)
        result = dendrite.run("cs-001")
        assert len(result["action_node_ids"]) == 2
        for action_id in result["action_node_ids"]:
            edges = soma.get_edges(action_id)
            assigned = [e for e in edges if e.rel_type == "ASSIGNED_TO"]
            assert len(assigned) == 1

    def test_empty_actions_no_nodes(self) -> None:
        soma = _make_soma()
        dendrite = _make_retrograde(soma, _minimal_payload())
        result = dendrite.run("cs-001")
        assert len(result["action_node_ids"]) == 0

    def test_action_missing_assigned_to_skipped(self) -> None:
        soma = _make_soma()
        payload = json.dumps({
            "outcome": {"outcome_text": "ok"},
            "deliverables": [],
            "lessons": [],
            "drifts": [],
            "actions": [
                {"action_text": "good action", "assigned_to": "test-dendrite"},
                {"action_text": "bad action"},
            ],
            "unresolved": [],
        })
        dendrite = _make_retrograde(soma, payload)
        result = dendrite.run("cs-001")
        assert len(result["action_node_ids"]) == 1
        action = soma.get_node(result["action_node_ids"][0])
        assert action.properties["action_text"] == "good action"


# ---------------------------------------------------------------------------
# Tests: Idempotency
# ---------------------------------------------------------------------------

class TestIdempotency:
    """Outcome nodes are cached — running twice must not create duplicates."""

    def test_outcome_cached_on_second_run(self) -> None:
        soma = _make_soma()
        dendrite = _make_retrograde(soma, _full_payload())
        r1 = dendrite.run("cs-001")
        r2 = dendrite.run("cs-001")
        assert r1["outcome_node_id"] == r2["outcome_node_id"]
        assert r2.get("cached") is True

    def test_no_duplicate_outcome_nodes(self) -> None:
        soma = _make_soma()
        dendrite = _make_retrograde(soma, _full_payload())
        dendrite.run("cs-001")
        first_count = len(soma.query_by_type("OutcomeNode"))
        dendrite.run("cs-001")
        second_count = len(soma.query_by_type("OutcomeNode"))
        assert first_count == second_count == 1

    def test_no_duplicate_edges_on_retry(self) -> None:
        soma = _make_soma()
        dendrite = _make_retrograde(soma, _full_payload())
        dendrite.run("cs-001")
        first_edge_count = len(soma.get_all_edges())
        dendrite.run("cs-001")
        second_edge_count = len(soma.get_all_edges())
        assert first_edge_count == second_edge_count

    def test_no_duplicate_deliverables_on_retry(self) -> None:
        soma = _make_soma()
        dendrite = _make_retrograde(soma, _full_payload())
        dendrite.run("cs-001")
        first_del_count = len(soma.query_by_type("DeliverableNode"))
        dendrite.run("cs-001")
        second_del_count = len(soma.query_by_type("DeliverableNode"))
        assert first_del_count == second_del_count

    def test_no_duplicate_lessons_on_retry(self) -> None:
        soma = _make_soma()
        dendrite = _make_retrograde(soma, _full_payload())
        dendrite.run("cs-001")
        first_lesson_count = len(soma.query_by_type("LessonNode"))
        dendrite.run("cs-001")
        second_lesson_count = len(soma.query_by_type("LessonNode"))
        assert first_lesson_count == second_lesson_count

    def test_no_duplicate_drifts_on_retry(self) -> None:
        soma = _make_soma()
        dendrite = _make_retrograde(soma, _full_payload())
        dendrite.run("cs-001")
        first_drift_count = len(soma.query_by_type("DriftNode"))
        dendrite.run("cs-001")
        second_drift_count = len(soma.query_by_type("DriftNode"))
        assert first_drift_count == second_drift_count

    def test_no_duplicate_actions_on_retry(self) -> None:
        soma = _make_soma()
        dendrite = _make_retrograde(soma, _full_payload())
        dendrite.run("cs-001")
        first_action_count = len(soma.query_by_type("ActionNode"))
        dendrite.run("cs-001")
        second_action_count = len(soma.query_by_type("ActionNode"))
        assert first_action_count == second_action_count

    def test_llm_not_called_on_cached_outcome(self) -> None:
        soma = _make_soma()
        llm = FakeLLMClient(_full_payload())
        dendrite = RetrogradeDendrite(soma, llm)
        dendrite.run("cs-001")
        first_call_count = llm.call_count
        dendrite.run("cs-001")
        second_call_count = llm.call_count
        assert first_call_count == second_call_count == 1


# ---------------------------------------------------------------------------
# Tests: Schema Validation
# ---------------------------------------------------------------------------

class TestSchemaValidation:
    """All node properties conform to the expected schemas."""

    def test_outcome_node_schema(self) -> None:
        soma = _make_soma()
        dendrite = _make_retrograde(soma, _full_payload())
        dendrite.run("cs-001")
        for node in soma.query_by_type("OutcomeNode"):
            assert "outcome_text" in node.properties
            assert "session_id" in node.properties
            assert "chat_set_id" in node.properties
            assert "created_at" in node.properties
            assert node.properties["immutable"] is True

    def test_deliverable_node_schema(self) -> None:
        soma = _make_soma()
        dendrite = _make_retrograde(soma, _full_payload())
        dendrite.run("cs-001")
        for node in soma.query_by_type("DeliverableNode"):
            assert "deliverable_text" in node.properties
            assert "source_outcome_id" in node.properties
            assert "chat_set_id" in node.properties

    def test_lesson_node_schema(self) -> None:
        soma = _make_soma()
        dendrite = _make_retrograde(soma, _full_payload())
        dendrite.run("cs-001")
        for node in soma.query_by_type("LessonNode"):
            assert "lesson_text" in node.properties
            assert "source_outcome_id" in node.properties
            assert "chat_set_id" in node.properties

    def test_drift_node_schema(self) -> None:
        soma = _make_soma()
        dendrite = _make_retrograde(soma, _full_payload())
        dendrite.run("cs-001")
        for node in soma.query_by_type("DriftNode"):
            assert "drift_description" in node.properties
            assert "from_node" in node.properties
            assert "to_node" in node.properties
            assert "drift_type" in node.properties
            assert "chat_set_id" in node.properties

    def test_action_node_schema(self) -> None:
        soma = _make_soma()
        dendrite = _make_retrograde(soma, _full_payload())
        dendrite.run("cs-001")
        for node in soma.query_by_type("ActionNode"):
            assert "action_text" in node.properties
            assert "assigned_to" in node.properties
            assert "status" in node.properties
            assert node.properties["status"] == "open"

    def test_invalid_outcome_missing_text_skipped(self) -> None:
        soma = _make_soma()
        payload = json.dumps({
            "outcome": {},
            "deliverables": [],
            "lessons": [],
            "drifts": [],
            "actions": [],
            "unresolved": [],
        })
        dendrite = _make_retrograde(soma, payload)
        result = dendrite.run("cs-001")
        assert result["outcome_node_id"] is None

    def test_invalid_deliverable_missing_text_skipped(self) -> None:
        soma = _make_soma()
        payload = json.dumps({
            "outcome": {"outcome_text": "ok"},
            "deliverables": [
                {"deliverable_text": "good"},
                {},
            ],
            "lessons": [],
            "drifts": [],
            "actions": [],
            "unresolved": [],
        })
        dendrite = _make_retrograde(soma, payload)
        result = dendrite.run("cs-001")
        assert len(result["deliverable_node_ids"]) == 1

    def test_invalid_lesson_missing_text_skipped(self) -> None:
        soma = _make_soma()
        payload = json.dumps({
            "outcome": {"outcome_text": "ok"},
            "deliverables": [],
            "lessons": [
                {"lesson_text": "good lesson"},
                {},
            ],
            "drifts": [],
            "actions": [],
            "unresolved": [],
        })
        dendrite = _make_retrograde(soma, payload)
        result = dendrite.run("cs-001")
        assert len(result["lesson_node_ids"]) == 1


# ---------------------------------------------------------------------------
# Tests: Edge Types
# ---------------------------------------------------------------------------

class TestEdgeTypes:
    """All edge types are present and correctly directed."""

    def test_all_edge_types_present(self) -> None:
        soma = _make_soma()
        dendrite = _make_retrograde(soma, _full_payload())
        dendrite.run("cs-001")
        all_edges = soma.get_all_edges()
        edge_types = {e.rel_type for e in all_edges}
        assert "TRIGGERED_BY" in edge_types
        assert "PRODUCES" in edge_types
        assert "LEARNS" in edge_types
        assert "DRIFTS_FROM" in edge_types
        assert "ASSIGNED_TO" in edge_types

    def test_no_orphan_edges(self) -> None:
        """Every edge source must exist as a node.

        DRIFTS_FROM targets are external plan node IDs (not Soma nodes).
        ASSIGNED_TO targets are dendrite names (not Soma nodes).
        These are allowed to reference external identifiers.
        """
        soma = _make_soma()
        dendrite = _make_retrograde(soma, _full_payload())
        dendrite.run("cs-001")
        for edge in soma.get_all_edges():
            assert soma.get_node(edge.source) is not None, f"Orphan source: {edge.source}"
            # DRIFTS_FROM and ASSIGNED_TO targets may be external refs
            if edge.rel_type in ("DRIFTS_FROM", "ASSIGNED_TO"):
                continue
            assert soma.get_node(edge.target) is not None, f"Orphan target: {edge.target}"

    def test_triggers_by_edge_direction(self) -> None:
        soma = _make_soma()
        dendrite = _make_retrograde(soma, _full_payload())
        dendrite.run("cs-001")
        outcome = soma.query_by_type("OutcomeNode")[0]
        edges = soma.get_edges(outcome.node_id)
        tbe = [e for e in edges if e.rel_type == "TRIGGERED_BY"]
        assert len(tbe) == 1
        assert tbe[0].source == outcome.node_id
        assert tbe[0].target == "cs-001"


# ---------------------------------------------------------------------------
# Tests: Missing ChatSet
# ---------------------------------------------------------------------------

class TestMissingChatSet:
    """Nonexistent ChatSet returns error."""

    def test_nonexistent_chatset(self) -> None:
        soma = Soma(force_empty=True)
        dendrite = _make_retrograde(soma, _minimal_payload())
        result = dendrite.run("nonexistent-001")
        assert "error" in result

    def test_wrong_type_node(self) -> None:
        soma = Soma(force_empty=True)
        soma.create_node("TaskNode", {"id": "cs-001", "task_text": "not a chat set"})
        dendrite = _make_retrograde(soma, _minimal_payload())
        result = dendrite.run("cs-001")
        assert "error" in result


# ---------------------------------------------------------------------------
# Tests: Non-JSON LLM Response
# ---------------------------------------------------------------------------

class TestNonJsonResponse:
    """LLM returns prose — should handle gracefully."""

    def test_prose_response_returns_error(self) -> None:
        soma = _make_soma()
        dendrite = _make_retrograde(soma, "This is not JSON at all")
        result = dendrite.run("cs-001")
        assert "error" in result
        assert "non-JSON" in result["error"]

    def test_markdown_fenced_json_parsed(self) -> None:
        soma = _make_soma()
        fenced = json.dumps({
            "outcome": {"outcome_text": "fenced outcome"},
            "deliverables": [],
            "lessons": [],
            "drifts": [],
            "actions": [],
            "unresolved": [],
        })
        dendrite = _make_retrograde(soma, f"```json\n{fenced}\n```")
        result = dendrite.run("cs-001")
        assert result["outcome_node_id"] is not None
        outcome = soma.get_node(result["outcome_node_id"])
        assert outcome.properties["outcome_text"] == "fenced outcome"


# ---------------------------------------------------------------------------
# Tests: Multiple ChatSets
# ---------------------------------------------------------------------------

class TestMultipleChatSets:
    """Retrograde works correctly with separate ChatSet nodes."""

    def test_separate_sets_get_separate_outcomes(self) -> None:
        soma = Soma(force_empty=True)
        soma.create_node("ChatSet", {"id": "cs-a", "session_id": "s1",
                                     "user_text": "Task A",
                                     "assistant_text": "Done A"})
        soma.create_node("ChatSet", {"id": "cs-b", "session_id": "s1",
                                     "user_text": "Task B",
                                     "assistant_text": "Done B"})
        payload = json.dumps({
            "outcome": {"outcome_text": "shared"},
            "deliverables": [],
            "lessons": [],
            "drifts": [],
            "actions": [],
            "unresolved": [],
        })
        llm = FakeLLMClient(payload)
        dendrite = RetrogradeDendrite(soma, llm)
        r1 = dendrite.run("cs-a")
        r2 = dendrite.run("cs-b")
        assert r1["outcome_node_id"] != r2["outcome_node_id"]
        assert len(soma.query_by_type("OutcomeNode")) == 2

    def test_separate_edges_per_chatset(self) -> None:
        soma = Soma(force_empty=True)
        soma.create_node("ChatSet", {"id": "cs-x", "session_id": "s1",
                                     "user_text": "Task X",
                                     "assistant_text": "Done X"})
        payload = json.dumps({
            "outcome": {"outcome_text": "ok"},
            "deliverables": [{"deliverable_text": "from cs-x"}],
            "lessons": [{"lesson_text": "learned from x"}],
            "drifts": [{"drift_description": "d", "from_node": "p1", "to_node": "p2", "drift_type": "unknown"}],
            "actions": [{"action_text": "fix", "assigned_to": "test-dendrite"}],
            "unresolved": [],
        })
        dendrite = _make_retrograde(soma, payload)
        dendrite.run("cs-x")
        outcome = soma.query_by_type("OutcomeNode")[0]
        edges = soma.get_edges(outcome.node_id)
        triggered = [e for e in edges if e.rel_type == "TRIGGERED_BY" and e.target == "cs-x"]
        assert len(triggered) == 1


# ---------------------------------------------------------------------------
# Tests: Metrics
# ---------------------------------------------------------------------------

class TestMetrics:
    """Results include token usage and latency metrics."""

    def test_metrics_in_result(self) -> None:
        soma = _make_soma()
        dendrite = _make_retrograde(soma, _minimal_payload())
        result = dendrite.run("cs-001")
        metrics = result["metrics"]
        assert "model_id" in metrics
        assert "prompt_tokens" in metrics
        assert "completion_tokens" in metrics
        assert "total_tokens" in metrics
        assert "latency_ms" in metrics

    def test_latency_ms_positive(self) -> None:
        soma = _make_soma()
        dendrite = _make_retrograde(soma, _minimal_payload())
        result = dendrite.run("cs-001")
        assert result["metrics"]["latency_ms"] >= 0

    def test_prompt_tokens_from_llm(self) -> None:
        soma = _make_soma()
        llm = FakeLLMClient(_minimal_payload())
        dendrite = RetrogradeDendrite(soma, llm)
        result = dendrite.run("cs-001")
        assert result["metrics"]["prompt_tokens"] == 150

    def test_cached_result_has_zero_metrics(self) -> None:
        soma = _make_soma()
        dendrite = _make_retrograde(soma, _minimal_payload())
        dendrite.run("cs-001")
        result = dendrite.run("cs-001")
        assert result["metrics"]["prompt_tokens"] == 0
        assert result["metrics"]["completion_tokens"] == 0


# ---------------------------------------------------------------------------
# Tests: Session ID Propagation
# ---------------------------------------------------------------------------

class TestSessionPropagation:
    """Session ID flows through all output nodes."""

    def test_session_id_in_outcome(self) -> None:
        soma = _make_soma(session_id="sess-custom")
        dendrite = _make_retrograde(soma, _full_payload())
        result = dendrite.run("cs-001")
        outcome = soma.get_node(result["outcome_node_id"])
        assert outcome.properties["session_id"] == "sess-custom"

    def test_session_id_in_deliverables(self) -> None:
        soma = _make_soma(session_id="sess-custom")
        dendrite = _make_retrograde(soma, _full_payload())
        result = dendrite.run("cs-001")
        for did in result["deliverable_node_ids"]:
            node = soma.get_node(did)
            assert node.properties["session_id"] == "sess-custom"

    def test_session_id_in_lessons(self) -> None:
        soma = _make_soma(session_id="sess-custom")
        dendrite = _make_retrograde(soma, _full_payload())
        result = dendrite.run("cs-001")
        for lid in result["lesson_node_ids"]:
            node = soma.get_node(lid)
            assert node.properties["session_id"] == "sess-custom"

    def test_session_id_in_drifts(self) -> None:
        soma = _make_soma(session_id="sess-custom")
        dendrite = _make_retrograde(soma, _full_payload())
        result = dendrite.run("cs-001")
        for did in result["drift_node_ids"]:
            node = soma.get_node(did)
            assert node.properties["session_id"] == "sess-custom"

    def test_session_id_in_actions(self) -> None:
        soma = _make_soma(session_id="sess-custom")
        dendrite = _make_retrograde(soma, _full_payload())
        result = dendrite.run("cs-001")
        for aid in result["action_node_ids"]:
            node = soma.get_node(aid)
            assert node.properties["session_id"] == "sess-custom"


# ---------------------------------------------------------------------------
# Tests: Empty assistant_text
# ---------------------------------------------------------------------------

class TestEmptyAssistantText:
    """Should handle empty assistant_text gracefully."""

    def test_empty_assistant_text(self) -> None:
        soma = Soma(force_empty=True)
        soma.create_node("ChatSet", {
            "id": "cs-001",
            "session_id": "sess-001",
            "user_text": "hello",
            "assistant_text": "",
        })
        dendrite = _make_retrograde(soma, _minimal_payload())
        result = dendrite.run("cs-001")
        assert result["outcome_node_id"] is not None


# ---------------------------------------------------------------------------
# Tests: Full Pipeline with Drifts
# ---------------------------------------------------------------------------

class TestFullPipelineWithDrifts:
    """End-to-end test with drifts, deliverables, lessons, and actions."""

    def test_full_pipeline(self) -> None:
        soma = _make_soma()
        dendrite = _make_retrograde(soma, _full_payload())
        result = dendrite.run("cs-001")

        # All node types created
        assert result["outcome_node_id"] is not None
        assert len(result["deliverable_node_ids"]) == 2
        assert len(result["lesson_node_ids"]) == 1
        assert len(result["drift_node_ids"]) == 1
        assert len(result["action_node_ids"]) == 1

        # All edges created
        all_edges = soma.get_all_edges()
        edge_types = {e.rel_type for e in all_edges}
        assert "TRIGGERED_BY" in edge_types
        assert "PRODUCES" in edge_types
        assert "LEARNS" in edge_types
        assert "DRIFTS_FROM" in edge_types
        assert "ASSIGNED_TO" in edge_types

    def test_idempotent_full_pipeline(self) -> None:
        soma = _make_soma()
        dendrite = _make_retrograde(soma, _full_payload())
        result1 = dendrite.run("cs-001")
        result2 = dendrite.run("cs-001")

        # Identical results
        assert result1["outcome_node_id"] == result2["outcome_node_id"]
        assert result1["deliverable_node_ids"] == result2["deliverable_node_ids"]
        assert result1["lesson_node_ids"] == result2["lesson_node_ids"]
        assert result1["drift_node_ids"] == result2["drift_node_ids"]
        assert result1["action_node_ids"] == result2["action_node_ids"]
        assert result2["cached"] is True
