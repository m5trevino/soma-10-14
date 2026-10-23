"""Unit tests for TB-TK-REPLACE-002: ClassifierDendrite.

Verifies:
  - All output nodes are schema-validated against the 6 disposition lanes
  - Signal nodes include session_id, chat_set_id, confidence, source_text
  - EXTRACTED_FROM edges correctly link ChatSet -> SignalNode
  - Heuristic fallback works when LLM fails
  - Disposition lane enum enforcement (rejects non-lane types)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

_SOMA_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SOMA_DIR))

from store import Soma
from pipeline.classifier_dendrite import (
    ClassifierDendrite,
    heuristic_classify,
    validate_signal,
    DISPOSITION_LANES,
)
from pipeline.drafter_dendrite import MockLLMClient, LLMResponse


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_soma(cs_id: str = "cs-001", session_id: str = "sess-001",
               user_text: str = "Build the CLI and run it now.") -> Soma:
    """Helper to build a Soma with one ChatSet node."""
    soma = Soma(force_empty=True)
    soma.create_node("ChatSet", {
        "id": cs_id,
        "session_id": session_id,
        "set_number": 1,
        "user_text": user_text,
        "assistant_text": "Sure thing.",
    })
    return soma


class FakeLLMClient:
    """A fake LLM client that returns pre-programmed JSON."""

    def __init__(self, response_text: str) -> None:
        self._response_text = response_text
        self.call_count = 0

    def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> LLMResponse:
        self.call_count += 1
        return LLMResponse(
            model_id="fake",
            content=self._response_text,
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            latency_ms=10.0,
        )


# ---------------------------------------------------------------------------
# Tests: Disposition Lane Enforcement
# ---------------------------------------------------------------------------

class TestDispositionLaneEnforcement:
    """Only the 6 defined lanes are valid."""

    def test_valid_lanes_accepted(self) -> None:
        for lane in DISPOSITION_LANES:
            err = validate_signal({"signal_type": lane, "confidence": 0.8,
                                   "source_text": "test", "rationale": "ok"})
            assert err is None, f"{lane} should be valid"

    def test_invalid_type_rejected(self) -> None:
        err = validate_signal({"signal_type": "SomeOtherNode", "confidence": 0.5,
                               "source_text": "x", "rationale": "y"})
        assert err is not None
        assert "invalid signal_type" in err

    def test_missing_rationale_key_rejected(self) -> None:
        err = validate_signal({"signal_type": "IntentNode", "confidence": 0.5,
                               "source_text": "x"})
        assert err is not None
        assert "missing key: rationale" in err

    def test_confidence_out_of_range_rejected(self) -> None:
        err = validate_signal({"signal_type": "IntentNode", "confidence": 1.5,
                               "source_text": "x", "rationale": "y"})
        assert err is not None

    def test_negative_confidence_rejected(self) -> None:
        err = validate_signal({"signal_type": "IntentNode", "confidence": -0.1,
                               "source_text": "x", "rationale": "y"})
        assert err is not None


# ---------------------------------------------------------------------------
# Tests: Heuristic (regex) Fallback
# ---------------------------------------------------------------------------

class TestHeuristicFallback:
    """When LLM fails, regex classify runs correctly."""

    def test_question_detected(self) -> None:
        signals = heuristic_classify("How do I create a node?")
        types = [s.signal_type for s in signals]
        assert "QuestionNode" in types

    def test_directive_detected(self) -> None:
        signals = heuristic_classify("Create a new file")
        types = [s.signal_type for s in signals]
        assert "DirectiveNode" in types

    def test_constraint_detected(self) -> None:
        signals = heuristic_classify("This must use PostgreSQL")
        types = [s.signal_type for s in signals]
        assert "ConstraintNode" in types

    def test_preference_detected(self) -> None:
        signals = heuristic_classify("I prefer TypeScript over JavaScript")
        types = [s.signal_type for s in signals]
        assert "PreferenceNode" in types

    def test_correction_detected(self) -> None:
        signals = heuristic_classify("Actually, wait — use MySQL")
        types = [s.signal_type for s in signals]
        assert "CorrectionNode" in types

    def test_noise_detected(self) -> None:
        signals = heuristic_classify("hello")
        types = [s.signal_type for s in signals]
        assert "NoiseNode" in types

    def test_empty_text_returns_noise(self) -> None:
        signals = heuristic_classify("")
        assert len(signals) == 1
        assert signals[0].signal_type == "NoiseNode"

    def test_unclassified_defaults_to_intent(self) -> None:
        signals = heuristic_classify("some random text")
        types = [s.signal_type for s in signals]
        assert "IntentNode" in types

    def test_minimum_one_signal(self) -> None:
        """Always returns at least one signal."""
        signals = heuristic_classify("")
        assert len(signals) >= 1


# ---------------------------------------------------------------------------
# Tests: Tool-calling with Mock LLM
# ---------------------------------------------------------------------------

class TestToolCalling:
    """LLM tool-calling produces schema-validated nodes and edges."""

    def test_valid_signals_created_and_linked(self) -> None:
        soma = _make_soma()
        payload = json.dumps([
            {"signal_type": "IntentNode", "confidence": 0.85,
             "source_text": "Build the CLI and run it now.", "rationale": "command"},
            {"signal_type": "DirectiveNode", "confidence": 0.75,
             "source_text": "Build the CLI and run it now.", "rationale": "imperative"},
        ])
        llm = FakeLLMClient(payload)
        dendrite = ClassifierDendrite(soma, llm)

        result = dendrite.run("cs-001")

        assert "error" not in result
        assert len(result["signal_node_ids"]) == 2
        assert result["signal_counts"]["IntentNode"] == 1
        assert result["signal_counts"]["DirectiveNode"] == 1

        # Verify nodes exist with required fields
        for node_id in result["signal_node_ids"]:
            node = soma.get_node(node_id)
            assert node is not None
            assert node.properties.get("session_id") == "sess-001"
            assert node.properties.get("chat_set_id") == "cs-001"
            assert "confidence" in node.properties
            assert "source_text" in node.properties

        # Verify EXTRACTED_FROM edges
        edges = soma.get_edges("cs-001")
        extract_edges = [e for e in edges if e.rel_type == "EXTRACTED_FROM"]
        assert len(extract_edges) == 2

    def test_invalid_signals_rejected(self) -> None:
        """Non-lane signal types are dropped, not created."""
        soma = _make_soma()
        payload = json.dumps([
            {"signal_type": "InvalidNode", "confidence": 0.5,
             "source_text": "x", "rationale": "bad type"},
        ])
        llm = FakeLLMClient(payload)
        dendrite = ClassifierDendrite(soma, llm)

        result = dendrite.run("cs-001")
        assert result["signal_node_ids"] == []
        assert soma.node_count() == 1  # only the ChatSet

    def test_confidence_clamped_and_stored(self) -> None:
        soma = _make_soma()
        payload = json.dumps([
            {"signal_type": "QuestionNode", "confidence": 0.95,
             "source_text": "Why?", "rationale": "question"},
        ])
        llm = FakeLLMClient(payload)
        dendrite = ClassifierDendrite(soma, llm)

        result = dendrite.run("cs-001")
        node_id = result["signal_node_ids"][0]
        node = soma.get_node(node_id)
        assert node.properties["confidence"] == 0.95

    def test_missing_chatset_returns_error(self) -> None:
        soma = _make_soma()
        llm = FakeLLMClient("[]")
        dendrite = ClassifierDendrite(soma, llm)
        result = dendrite.run("nonexistent:99")
        assert "error" in result

    def test_empty_user_text_returns_empty_signals(self) -> None:
        soma = _make_soma(user_text="")
        llm = FakeLLMClient("[]")
        dendrite = ClassifierDendrite(soma, llm)
        result = dendrite.run("cs-001")
        assert result["signal_node_ids"] == []
        assert result["signal_counts"] == {}


# ---------------------------------------------------------------------------
# Tests: Idempotency — duplicate nodes skipped
# ---------------------------------------------------------------------------

class TestIdempotency:
    """Running twice does not create duplicate nodes."""

    def test_repeated_run_no_duplicates(self) -> None:
        soma = _make_soma()
        payload = json.dumps([
            {"signal_type": "IntentNode", "confidence": 0.8,
             "source_text": "x", "rationale": "y"},
        ])
        llm = FakeLLMClient(payload)
        dendrite = ClassifierDendrite(soma, llm)

        dendrite.run("cs-001")
        first_count = soma.node_count()

        dendrite.run("cs-001")
        second_count = soma.node_count()

        assert first_count == second_count, "Duplicate nodes created on retry"


# ---------------------------------------------------------------------------
# Tests: Edge Lineage
# ---------------------------------------------------------------------------

class TestEdgeLineage:
    """EXTRACTED_FROM edges link ChatSet -> SignalNode correctly."""

    def test_edge_source_is_chatset_id(self) -> None:
        soma = _make_soma()
        payload = json.dumps([
            {"signal_type": "DirectiveNode", "confidence": 0.7,
             "source_text": "build it", "rationale": "cmd"},
        ])
        llm = FakeLLMClient(payload)
        dendrite = ClassifierDendrite(soma, llm)

        dendrite.run("cs-001")
        edges = soma.get_edges("cs-001")

        for e in edges:
            if e.rel_type == "EXTRACTED_FROM":
                assert e.source == "cs-001"
                # target is a valid node
                assert soma.get_node(e.target) is not None

    def test_edge_count_matches_signal_count(self) -> None:
        soma = _make_soma()
        payload = json.dumps([
            {"signal_type": "IntentNode", "confidence": 0.8,
             "source_text": "a", "rationale": "1"},
            {"signal_type": "DirectiveNode", "confidence": 0.7,
             "source_text": "b", "rationale": "2"},
            {"signal_type": "ConstraintNode", "confidence": 0.6,
             "source_text": "c", "rationale": "3"},
        ])
        llm = FakeLLMClient(payload)
        dendrite = ClassifierDendrite(soma, llm)

        result = dendrite.run("cs-001")
        edges = [e for e in soma.get_all_edges() if e.rel_type == "EXTRACTED_FROM"]
        assert len(edges) == len(result["signal_node_ids"])


# ---------------------------------------------------------------------------
# Tests: Regex Fallback when LLM fails
# ---------------------------------------------------------------------------

class TestRegexFallback:
    """When LLM raises, heuristic classify runs and nodes are created."""

    def test_fallback_creates_nodes_on_llm_failure(self) -> None:
        """A bare MockLLMClient has .chat() which complete_stage wraps to .call() —
           so we use a mock that raises."""
        soma = _make_soma(user_text="How do I build the CLI?")

        class FailingLLM:
            def chat(self, *a, **kw):
                raise RuntimeError("LLM unavailable")

        llm = FailingLLM()
        dendrite = ClassifierDendrite(soma, llm)

        result = dendrite.run("cs-001")
        # Should have gotten regex fallback signals
        assert len(result["signal_node_ids"]) >= 1
        assert "error" not in result

        # Verify node exists
        for nid in result["signal_node_ids"]:
            node = soma.get_node(nid)
            assert node is not None


# ---------------------------------------------------------------------------
# Tests: Metrics
# ---------------------------------------------------------------------------

class TestMetrics:
    """Metrics dict contains required keys."""

    def test_metrics_has_latency_ms(self) -> None:
        soma = _make_soma()
        payload = json.dumps([{"signal_type": "IntentNode", "confidence": 0.8,
                                "source_text": "x", "rationale": "y"}])
        llm = FakeLLMClient(payload)
        dendrite = ClassifierDendrite(soma, llm)

        result = dendrite.run("cs-001")
        metrics = result["metrics"]
        assert "latency_ms" in metrics
        assert "model_id" in metrics
        assert "prompt_tokens" in metrics


# ---------------------------------------------------------------------------
# Tests: Multiple ChatSets
# ---------------------------------------------------------------------------

class TestMultipleChatSets:
    """Classifier works across separate ChatSet nodes."""

    def test_separate_sets_get_separate_nodes(self) -> None:
        soma = Soma(force_empty=True)
        soma.create_node("ChatSet", {"id": "cs-a", "session_id": "s1",
                                     "set_number": 1, "user_text": "Build it",
                                     "assistant_text": "ok"})
        soma.create_node("ChatSet", {"id": "cs-b", "session_id": "s1",
                                     "set_number": 2, "user_text": "Run it",
                                     "assistant_text": "done"})

        payload = json.dumps([{"signal_type": "DirectiveNode", "confidence": 0.75,
                                "source_text": "", "rationale": "cmd"}])
        llm = FakeLLMClient(payload)
        dendrite = ClassifierDendrite(soma, llm)

        r1 = dendrite.run("cs-a")
        r2 = dendrite.run("cs-b")

        assert len(r1["signal_node_ids"]) == 1
        assert len(r2["signal_node_ids"]) == 1
        assert r1["signal_node_ids"][0] != r2["signal_node_ids"][0]
