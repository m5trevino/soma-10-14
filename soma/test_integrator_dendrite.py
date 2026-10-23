"""Unit tests for TB-TK-REPLACE-003: IntegratorDendrite.

Verifies:
  - TaskNodes are generated with sequence_number and priority
  - All edges (REQUIRES_ACTION, INTRODUCES_RISK, ADDRESSES) are physically linked
  - Idempotency check prevents duplicate TaskNode creation on retry
  - Token usage and latency are logged (metrics dict)
  - Schema validation of output nodes
  - Signal-only consumption (no raw chat log access)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

_SOMA_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SOMA_DIR))

from store import Soma, Node
from pipeline.integrator_dendrite import IntegratorDendrite
from pipeline.drafter_dendrite import LLMResponse


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------

def _make_soma(
    cs_id: str = "cs-001",
    session_id: str = "sess-001",
    user_text: str = "Build the CLI and deploy it.",
) -> Soma:
    soma = Soma(force_empty=True)
    soma.create_node("ChatSet", {
        "id": cs_id,
        "session_id": session_id,
        "set_number": 1,
        "user_text": user_text,
        "assistant_text": "Understood.",
    })
    return soma


def _populate_signals(soma: Soma, chat_set_id: str, session_id: str) -> list[str]:
    """Add pre-classified signal nodes linked via EXTRACTED_FROM edges."""
    signals = [
        ("IntentNode", 0.85, "Build the CLI"),
        ("DirectiveNode", 0.75, "Deploy it"),
        ("ConstraintNode", 0.70, "Use PostgreSQL"),
    ]
    node_ids: list[str] = []
    for stype, conf, text in signals:
        nid = f"sig-{chat_set_id}-{stype}-{len(node_ids)}"
        soma.create_node(stype, {
            "id": nid,
            "session_id": session_id,
            "chat_set_id": chat_set_id,
            "confidence": conf,
            "source_text": text,
            "rationale": "classified",
        })
        soma.create_edge(chat_set_id, "EXTRACTED_FROM", nid)
        node_ids.append(nid)
    return node_ids


def _make_integrator(soma: Soma, llm_response: str) -> IntegratorDendrite:
    llm = FakeLLMClient(llm_response)
    return IntegratorDendrite(soma, llm)


def _standard_payload() -> str:
    """Standard LLM response with one item per output type."""
    return json.dumps({
        "tasks": [
            {"task_text": "Set up database", "priority": "HIGH"},
            {"task_text": "Build CLI", "priority": "MEDIUM"},
            {"task_text": "Write docs", "priority": "LOW"},
        ],
        "risks": [{"risk_text": "DB connection timeout", "severity": "HIGH"}],
        "decisions": [{"decision_text": "Use PostgreSQL", "rationale": "stability"}],
        "stack": [{"stack_text": "Python + FastAPI", "role": "backend"}],
    })


def _minimal_payload() -> str:
    """Minimal LLM response."""
    return json.dumps({
        "tasks": [{"task_text": "x", "priority": "HIGH"}],
        "risks": [{"risk_text": "y", "severity": "LOW"}],
        "decisions": [{"decision_text": "z", "rationale": "w"}],
        "stack": [{"stack_text": "s", "role": "r"}],
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
            prompt_tokens=200,
            completion_tokens=100,
            total_tokens=300,
            latency_ms=30.0,
        )


# ---------------------------------------------------------------------------
# Tests: Task Sequence Ordering
# ---------------------------------------------------------------------------

class TestTaskSequenceOrdering:
    """TaskNodes must carry sequence_number and priority."""

    def test_sequence_numbers_in_order(self) -> None:
        soma = _make_soma()
        signals = _populate_signals(soma, "cs-001", "sess-001")
        dendrite = _make_integrator(soma, _standard_payload())
        result = dendrite.run("cs-001")
        assert result["task_node_ids"]
        for i, nid in enumerate(result["task_node_ids"]):
            node = soma.get_node(nid)
            assert node is not None
            assert node.properties["sequence_number"] == i + 1

    def test_priorities_preserved(self) -> None:
        soma = _make_soma()
        _populate_signals(soma, "cs-001", "sess-001")
        dendrite = _make_integrator(soma, _standard_payload())
        result = dendrite.run("cs-001")
        expected_priorities = ["HIGH", "MEDIUM", "LOW"]
        for i, nid in enumerate(result["task_node_ids"]):
            node = soma.get_node(nid)
            assert node.properties["priority"] == expected_priorities[i]

    def test_task_text_preserved(self) -> None:
        soma = _make_soma()
        _populate_signals(soma, "cs-001", "sess-001")
        dendrite = _make_integrator(soma, _standard_payload())
        result = dendrite.run("cs-001")
        expected_texts = ["Set up database", "Build CLI", "Write docs"]
        for i, nid in enumerate(result["task_node_ids"]):
            node = soma.get_node(nid)
            assert node.properties["task_text"] == expected_texts[i]

    def test_empty_tasks_produces_no_task_nodes(self) -> None:
        soma = _make_soma()
        _populate_signals(soma, "cs-001", "sess-001")
        payload = json.dumps({"tasks": [], "risks": [], "decisions": [], "stack": []})
        dendrite = _make_integrator(soma, payload)
        result = dendrite.run("cs-001")
        assert result["task_node_ids"] == []

    def test_sequence_resumes_after_idempotent_skip(self) -> None:
        soma = _make_soma()
        _populate_signals(soma, "cs-001", "sess-001")
        dendrite = _make_integrator(soma, _standard_payload())
        dendrite.run("cs-001")
        dendrite.run("cs-001")
        task_nodes = soma.query_by_type("TaskNode")
        assert len(task_nodes) == 3
        for node in task_nodes:
            assert node.properties["sequence_number"] > 0


# ---------------------------------------------------------------------------
# Tests: Graph Linkage (Edge types)
# ---------------------------------------------------------------------------

class TestGraphLinkage:
    """REQUIRES_ACTION, INTRODUCES_RISK, ADDRESSES edges must exist and link correctly."""

    def test_requires_action_edges_from_session(self) -> None:
        soma = _make_soma()
        _populate_signals(soma, "cs-001", "sess-001")
        dendrite = _make_integrator(soma, _standard_payload())
        dendrite.run("cs-001")
        session_nodes = [n for n in soma._nodes.values() if n.node_type == "SessionNode"]
        assert len(session_nodes) >= 1
        session_id = session_nodes[0].node_id
        edges = soma.get_edges(session_id)
        ra_edges = [e for e in edges if e.rel_type == "REQUIRES_ACTION"]
        assert len(ra_edges) == 3
        for edge in ra_edges:
            assert edge.source == session_id
            assert soma.get_node(edge.target) is not None
            assert soma.get_node(edge.target).node_type == "TaskNode"

    def test_introduces_risk_edges_from_session(self) -> None:
        soma = _make_soma()
        _populate_signals(soma, "cs-001", "sess-001")
        dendrite = _make_integrator(soma, _standard_payload())
        dendrite.run("cs-001")
        session_nodes = [n for n in soma._nodes.values() if n.node_type == "SessionNode"]
        session_id = session_nodes[0].node_id
        edges = soma.get_edges(session_id)
        ir_edges = [e for e in edges if e.rel_type == "INTRODUCES_RISK"]
        assert len(ir_edges) == 1

    def test_addresses_edges_task_to_signal(self) -> None:
        soma = _make_soma()
        signal_ids = _populate_signals(soma, "cs-001", "sess-001")
        dendrite = _make_integrator(soma, _standard_payload())
        dendrite.run("cs-001")
        task_nodes = soma.query_by_type("TaskNode")
        assert len(task_nodes) == 3
        for task in task_nodes:
            edges = soma.get_edges(task.node_id)
            addr_edges = [e for e in edges if e.rel_type == "ADDRESSES" and e.source == task.node_id]
            assert len(addr_edges) == len(signal_ids)
            for ae in addr_edges:
                assert ae.target in signal_ids

    def test_all_edge_types_present(self) -> None:
        soma = _make_soma()
        _populate_signals(soma, "cs-001", "sess-001")
        dendrite = _make_integrator(soma, _standard_payload())
        dendrite.run("cs-001")
        all_edges = soma.get_all_edges()
        edge_types = {e.rel_type for e in all_edges}
        assert "REQUIRES_ACTION" in edge_types
        assert "INTRODUCES_RISK" in edge_types
        assert "ADDRESSES" in edge_types

    def test_no_orphan_edges(self) -> None:
        soma = _make_soma()
        _populate_signals(soma, "cs-001", "sess-001")
        dendrite = _make_integrator(soma, _standard_payload())
        dendrite.run("cs-001")
        for edge in soma.get_all_edges():
            assert soma.get_node(edge.source) is not None, f"Orphan edge source: {edge.source}"
            assert soma.get_node(edge.target) is not None, f"Orphan edge target: {edge.target}"


# ---------------------------------------------------------------------------
# Tests: Idempotency
# ---------------------------------------------------------------------------

class TestIdempotency:
    """Running twice must not create duplicate nodes."""

    def test_no_duplicate_task_nodes(self) -> None:
        soma = _make_soma()
        _populate_signals(soma, "cs-001", "sess-001")
        dendrite = _make_integrator(soma, _standard_payload())
        dendrite.run("cs-001")
        first_task_count = soma.node_count()
        dendrite.run("cs-001")
        second_task_count = soma.node_count()
        assert first_task_count == second_task_count

    def test_no_duplicate_risk_nodes(self) -> None:
        soma = _make_soma()
        _populate_signals(soma, "cs-001", "sess-001")
        dendrite = _make_integrator(soma, _standard_payload())
        dendrite.run("cs-001")
        first_risk_count = len(soma.query_by_type("RiskNode"))
        dendrite.run("cs-001")
        second_risk_count = len(soma.query_by_type("RiskNode"))
        assert first_risk_count == second_risk_count

    def test_no_duplicate_decision_nodes(self) -> None:
        soma = _make_soma()
        _populate_signals(soma, "cs-001", "sess-001")
        dendrite = _make_integrator(soma, _standard_payload())
        dendrite.run("cs-001")
        first_dec_count = len(soma.query_by_type("DecisionNode"))
        dendrite.run("cs-001")
        second_dec_count = len(soma.query_by_type("DecisionNode"))
        assert first_dec_count == second_dec_count

    def test_no_duplicate_stack_nodes(self) -> None:
        soma = _make_soma()
        _populate_signals(soma, "cs-001", "sess-001")
        dendrite = _make_integrator(soma, _standard_payload())
        dendrite.run("cs-001")
        first_stack_count = len(soma.query_by_type("StackNode"))
        dendrite.run("cs-001")
        second_stack_count = len(soma.query_by_type("StackNode"))
        assert first_stack_count == second_stack_count

    def test_idempotent_no_extra_edges(self) -> None:
        soma = _make_soma()
        _populate_signals(soma, "cs-001", "sess-001")
        dendrite = _make_integrator(soma, _standard_payload())
        dendrite.run("cs-001")
        first_edge_count = len(soma.get_all_edges())
        dendrite.run("cs-001")
        second_edge_count = len(soma.get_all_edges())
        assert first_edge_count == second_edge_count


# ---------------------------------------------------------------------------
# Tests: Metrics (Token usage, latency)
# ---------------------------------------------------------------------------

class TestMetrics:
    """Results include token usage and latency metrics."""

    def test_metrics_in_result(self) -> None:
        soma = _make_soma()
        _populate_signals(soma, "cs-001", "sess-001")
        dendrite = _make_integrator(soma, _minimal_payload())
        result = dendrite.run("cs-001")
        metrics = result["metrics"]
        assert "model_id" in metrics
        assert "prompt_tokens" in metrics
        assert "completion_tokens" in metrics
        assert "total_tokens" in metrics
        assert "latency_ms" in metrics

    def test_latency_ms_positive(self) -> None:
        soma = _make_soma()
        _populate_signals(soma, "cs-001", "sess-001")
        dendrite = _make_integrator(soma, _minimal_payload())
        result = dendrite.run("cs-001")
        assert result["metrics"]["latency_ms"] >= 0

    def test_prompt_tokens_from_llm(self) -> None:
        soma = _make_soma()
        _populate_signals(soma, "cs-001", "sess-001")
        llm = FakeLLMClient(_minimal_payload())
        dendrite = IntegratorDendrite(soma, llm)
        result = dendrite.run("cs-001")
        assert result["metrics"]["prompt_tokens"] == 200

    def test_completion_tokens_from_llm(self) -> None:
        soma = _make_soma()
        _populate_signals(soma, "cs-001", "sess-001")
        llm = FakeLLMClient(_minimal_payload())
        dendrite = IntegratorDendrite(soma, llm)
        result = dendrite.run("cs-001")
        assert result["metrics"]["completion_tokens"] == 100

    def test_total_tokens_from_llm(self) -> None:
        soma = _make_soma()
        _populate_signals(soma, "cs-001", "sess-001")
        llm = FakeLLMClient(_minimal_payload())
        dendrite = IntegratorDendrite(soma, llm)
        result = dendrite.run("cs-001")
        assert result["metrics"]["total_tokens"] == 300


# ---------------------------------------------------------------------------
# Tests: Schema Validation
# ---------------------------------------------------------------------------

class TestSchemaValidation:
    """Output node properties must conform to the expected schemas."""

    def test_task_node_schema(self) -> None:
        soma = _make_soma()
        _populate_signals(soma, "cs-001", "sess-001")
        dendrite = _make_integrator(soma, _standard_payload())
        dendrite.run("cs-001")
        for nid in soma.query_by_type("TaskNode"):
            assert "task_text" in nid.properties
            assert "sequence_number" in nid.properties
            assert "priority" in nid.properties
            assert "source_signal_ids" in nid.properties
            assert nid.properties["priority"] in ("HIGH", "MEDIUM", "LOW")

    def test_risk_node_schema(self) -> None:
        soma = _make_soma()
        _populate_signals(soma, "cs-001", "sess-001")
        dendrite = _make_integrator(soma, _standard_payload())
        dendrite.run("cs-001")
        for nid in soma.query_by_type("RiskNode"):
            assert "risk_text" in nid.properties
            assert "severity" in nid.properties
            assert nid.properties["severity"] in ("HIGH", "MEDIUM", "LOW")

    def test_decision_node_schema(self) -> None:
        soma = _make_soma()
        _populate_signals(soma, "cs-001", "sess-001")
        dendrite = _make_integrator(soma, _standard_payload())
        dendrite.run("cs-001")
        for nid in soma.query_by_type("DecisionNode"):
            assert "decision_text" in nid.properties
            assert "rationale" in nid.properties

    def test_stack_node_schema(self) -> None:
        soma = _make_soma()
        _populate_signals(soma, "cs-001", "sess-001")
        dendrite = _make_integrator(soma, _standard_payload())
        dendrite.run("cs-001")
        for nid in soma.query_by_type("StackNode"):
            assert "stack_text" in nid.properties
            assert "role" in nid.properties

    def test_source_signal_ids_stored(self) -> None:
        soma = _make_soma()
        signal_ids = _populate_signals(soma, "cs-001", "sess-001")
        dendrite = _make_integrator(soma, _standard_payload())
        dendrite.run("cs-001")
        for nid in soma.query_by_type("TaskNode"):
            sids = json.loads(nid.properties["source_signal_ids"])
            assert set(sids) == set(signal_ids)

    def test_invalid_task_priority_skipped(self) -> None:
        soma = _make_soma()
        _populate_signals(soma, "cs-001", "sess-001")
        payload = json.dumps({
            "tasks": [
                {"task_text": "good task", "priority": "HIGH"},
                {"task_text": "bad task", "priority": "CRITICAL"},
            ],
            "risks": [],
            "decisions": [],
            "stack": [],
        })
        dendrite = _make_integrator(soma, payload)
        result = dendrite.run("cs-001")
        assert len(result["task_node_ids"]) == 1
        node = soma.get_node(result["task_node_ids"][0])
        assert node.properties["task_text"] == "good task"


# ---------------------------------------------------------------------------
# Tests: Signal-Only Consumption
# ---------------------------------------------------------------------------

class TestSignalOnlyConsumption:
    """Must consume signal nodes, not raw chat logs."""

    def test_collects_signals_via_extracted_from_edges(self) -> None:
        soma = _make_soma()
        _populate_signals(soma, "cs-001", "sess-001")
        llm = FakeLLMClient(_minimal_payload())
        dendrite = IntegratorDendrite(soma, llm)
        signal_ids = dendrite._collect_signal_ids("cs-001")
        assert len(signal_ids) == 3

    def test_no_llm_call_when_no_signals(self) -> None:
        soma = _make_soma(user_text="Some task")
        llm = FakeLLMClient(_minimal_payload())
        dendrite = IntegratorDendrite(soma, llm)
        result = dendrite.run("cs-001")
        assert result["task_node_ids"] == []
        assert llm.call_count == 0

    def test_noise_node_is_considered(self) -> None:
        soma = _make_soma()
        soma.create_node("NoiseNode", {
            "id": "sig-cs-001-NoiseNode-0",
            "session_id": "sess-001",
            "chat_set_id": "cs-001",
            "confidence": 0.9,
            "source_text": "hello",
            "rationale": "noise",
        })
        soma.create_edge("cs-001", "EXTRACTED_FROM", "sig-cs-001-NoiseNode-0")
        payload = json.dumps({"tasks": [], "risks": [], "decisions": [], "stack": []})
        llm = FakeLLMClient(payload)
        dendrite = IntegratorDendrite(soma, llm)
        result = dendrite.run("cs-001")
        assert result["task_node_ids"] == []
        assert llm.call_count == 1


# ---------------------------------------------------------------------------
# Tests: Missing ChatSet
# ---------------------------------------------------------------------------

class TestMissingChatSet:
    """Nonexistent ChatSet returns error."""

    def test_nonexistent_chatset(self) -> None:
        soma = Soma(force_empty=True)
        llm = FakeLLMClient(_minimal_payload())
        dendrite = IntegratorDendrite(soma, llm)
        result = dendrite.run("nonexistent-001")
        assert "error" in result

    def test_wrong_type_node(self) -> None:
        soma = Soma(force_empty=True)
        soma.create_node("TaskNode", {"id": "cs-001", "task_text": "not a chat set"})
        llm = FakeLLMClient(_minimal_payload())
        dendrite = IntegratorDendrite(soma, llm)
        result = dendrite.run("cs-001")
        assert "error" in result


# ---------------------------------------------------------------------------
# Tests: Non-JSON LLM Response
# ---------------------------------------------------------------------------

class TestNonJsonResponse:
    """LLM returns prose — integration should handle gracefully."""

    def test_prose_response_returns_error(self) -> None:
        soma = _make_soma()
        _populate_signals(soma, "cs-001", "sess-001")
        llm = FakeLLMClient("This is not JSON at all")
        dendrite = IntegratorDendrite(soma, llm)
        result = dendrite.run("cs-001")
        assert "error" in result
        assert "non-JSON" in result["error"]

    def test_markdown_fenced_json_parsed(self) -> None:
        soma = _make_soma()
        _populate_signals(soma, "cs-001", "sess-001")
        fenced = json.dumps({
            "tasks": [{"task_text": "fenced task", "priority": "HIGH"}],
            "risks": [],
            "decisions": [],
            "stack": [],
        })
        llm = FakeLLMClient(f"```json\n{fenced}\n```")
        dendrite = IntegratorDendrite(soma, llm)
        result = dendrite.run("cs-001")
        assert result["task_node_ids"]
        node = soma.get_node(result["task_node_ids"][0])
        assert node.properties["task_text"] == "fenced task"


# ---------------------------------------------------------------------------
# Tests: Multiple ChatSets
# ---------------------------------------------------------------------------

class TestMultipleChatSets:
    """Integrator works correctly with separate ChatSet nodes."""

    def test_separate_sets_get_separate_nodes(self) -> None:
        soma = Soma(force_empty=True)
        soma.create_node("ChatSet", {"id": "cs-a", "session_id": "s1",
                                     "user_text": "Task A", "assistant_text": "ok"})
        soma.create_node("ChatSet", {"id": "cs-b", "session_id": "s1",
                                     "user_text": "Task B", "assistant_text": "done"})
        _populate_signals(soma, "cs-a", "s1")
        _populate_signals(soma, "cs-b", "s1")
        payload = json.dumps({
            "tasks": [{"task_text": "shared task", "priority": "HIGH"}],
            "risks": [],
            "decisions": [],
            "stack": [],
        })
        llm = FakeLLMClient(payload)
        dendrite = IntegratorDendrite(soma, llm)
        r1 = dendrite.run("cs-a")
        r2 = dendrite.run("cs-b")
        assert len(r1["task_node_ids"]) == 1
        assert len(r2["task_node_ids"]) == 1
        # Idempotent by task_text — same text → same node
        assert r1["task_node_ids"] == r2["task_node_ids"]
