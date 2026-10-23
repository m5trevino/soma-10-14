"""Unit tests for TB-FIX-001: ArchitectureNode CONSTRAINED_BY edges."""
import pytest
from store import Soma
from falcon_dendrite import FalconDendrite


class MockLLM:
    """Mock LLM client that returns a fixed architecture."""
    def complete(self, model, instruction, payload):
        return {
            "ok": True,
            "result": {
                "architecture_text": "Test architecture",
                "source_requirements_id": "req-123"
            },
            "metrics": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30, "latency_ms": 5.0}
        }


class MockRotator:
    """Mock model rotator."""
    def next_model(self, role):
        return "mock-model"


def test_create_constrained_by_two_same_session_constraints():
    """Given one ArchitectureNode and two ConstraintNodes with same session_id,
    creates two CONSTRAINED_BY edges."""
    soma = Soma()
    llm = MockLLM()
    rotator = MockRotator()
    falcon = FalconDendrite(soma, llm, rotator)

    session_id = "test-session-001"
    arch_id = "arch-test-session-001"

    # Create ArchitectureNode
    soma.create_node("ArchitectureNode", {
        "id": arch_id,
        "session_id": session_id,
        "architecture_text": "Test architecture",
        "source_requirements_id": "req-123"
    })

    # Create two ConstraintNodes with same session_id
    c1 = soma.create_node("ConstraintNode", {
        "id": "constraint-1",
        "session_id": session_id,
        "source_text": "CHOSEN: store=postgresql"
    })
    c2 = soma.create_node("ConstraintNode", {
        "id": "constraint-2",
        "session_id": session_id,
        "source_text": "CHOSEN: navigation=react"
    })

    # Call the method
    created_edges = falcon.create_constrained_by(arch_id, session_id)

    # Assert two edges created
    assert len(created_edges) == 2

    # Verify edges exist
    edges = soma.get_all_edges()
    constrained_by_edges = [e for e in edges if e.rel_type == "CONSTRAINED_BY"]
    assert len(constrained_by_edges) == 2

    # Verify edge properties
    targets = {e.target for e in constrained_by_edges}
    assert targets == {"constraint-1", "constraint-2"}
    for e in constrained_by_edges:
        assert e.source == arch_id
        assert e.rel_type == "CONSTRAINED_BY"


def test_create_constrained_by_foreign_session_no_edge():
    """A ConstraintNode with a different session_id gets no edge."""
    soma = Soma()
    llm = MockLLM()
    rotator = MockRotator()
    falcon = FalconDendrite(soma, llm, rotator)

    session_id = "test-session-002"
    arch_id = "arch-test-session-002"

    soma.create_node("ArchitectureNode", {
        "id": arch_id,
        "session_id": session_id,
        "architecture_text": "Test architecture",
        "source_requirements_id": "req-123"
    })

    # Create ConstraintNode with DIFFERENT session_id
    soma.create_node("ConstraintNode", {
        "id": "constraint-foreign",
        "session_id": "other-session",
        "source_text": "CHOSEN: store=postgresql"
    })

    created_edges = falcon.create_constrained_by(arch_id, session_id)

    assert len(created_edges) == 0
    edges = soma.get_all_edges()
    constrained_by_edges = [e for e in edges if e.rel_type == "CONSTRAINED_BY"]
    assert len(constrained_by_edges) == 0


def test_create_constrained_by_idempotent():
    """Running the method twice does not duplicate edges."""
    soma = Soma()
    llm = MockLLM()
    rotator = MockRotator()
    falcon = FalconDendrite(soma, llm, rotator)

    session_id = "test-session-003"
    arch_id = "arch-test-session-003"

    soma.create_node("ArchitectureNode", {
        "id": arch_id,
        "session_id": session_id,
        "architecture_text": "Test architecture",
        "source_requirements_id": "req-123"
    })

    soma.create_node("ConstraintNode", {
        "id": "constraint-1",
        "session_id": session_id,
        "source_text": "CHOSEN: store=postgresql"
    })

    # First call
    created_1 = falcon.create_constrained_by(arch_id, session_id)
    assert len(created_1) == 1

    # Second call
    created_2 = falcon.create_constrained_by(arch_id, session_id)
    assert len(created_2) == 0  # No new edges

    # Total edges should still be 1
    edges = soma.get_all_edges()
    constrained_by_edges = [e for e in edges if e.rel_type == "CONSTRAINED_BY"]
    assert len(constrained_by_edges) == 1


def test_create_constrained_by_preserves_existing_edges():
    """Existing DERIVED_FROM and LOCKS edges are still present after new edges."""
    soma = Soma()
    llm = MockLLM()
    rotator = MockRotator()
    falcon = FalconDendrite(soma, llm, rotator)

    session_id = "test-session-004"
    arch_id = "arch-test-session-004"
    req_id = "req-456"
    contract_id = "arch-contract-test-session-004"

    # Create ArchitectureNode
    soma.create_node("ArchitectureNode", {
        "id": arch_id,
        "session_id": session_id,
        "architecture_text": "Test architecture",
        "source_requirements_id": req_id
    })

    # Create RequirementsNode
    soma.create_node("RequirementsNode", {
        "id": req_id,
        "session_id": session_id,
        "requirement_text": "Test requirements"
    })

    # Create ArchitectureContractNode
    soma.create_node("ArchitectureContractNode", {
        "id": contract_id,
        "session_id": session_id,
        "contract_text": "Test contract"
    })

    # Pre-create DERIVED_FROM and LOCKS edges
    soma.create_edge(arch_id, "DERIVED_FROM", req_id)
    soma.create_edge(arch_id, "LOCKS", contract_id)

    # Create ConstraintNode
    soma.create_node("ConstraintNode", {
        "id": "constraint-1",
        "session_id": session_id,
        "source_text": "CHOSEN: store=postgresql"
    })

    # Call the method
    falcon.create_constrained_by(arch_id, session_id)

    # Verify all three edge types exist
    edges = soma.get_all_edges()
    derived_from = [e for e in edges if e.rel_type == "DERIVED_FROM"]
    locks = [e for e in edges if e.rel_type == "LOCKS"]
    constrained_by = [e for e in edges if e.rel_type == "CONSTRAINED_BY"]

    assert len(derived_from) == 1
    assert len(locks) == 1
    assert len(constrained_by) == 1


def test_create_constrained_by_zero_constraints():
    """Zero ConstraintNodes does not raise. Zero CONSTRAINED_BY edges written."""
    soma = Soma()
    llm = MockLLM()
    rotator = MockRotator()
    falcon = FalconDendrite(soma, llm, rotator)

    session_id = "test-session-005"
    arch_id = "arch-test-session-005"

    soma.create_node("ArchitectureNode", {
        "id": arch_id,
        "session_id": session_id,
        "architecture_text": "Test architecture",
        "source_requirements_id": "req-123"
    })

    # No ConstraintNodes created

    created_edges = falcon.create_constrained_by(arch_id, session_id)

    assert len(created_edges) == 0
    edges = soma.get_all_edges()
    constrained_by_edges = [e for e in edges if e.rel_type == "CONSTRAINED_BY"]
    assert len(constrained_by_edges) == 0


def test_create_constrained_by_missing_architecture_returns_empty():
    """Missing architecture_id returns empty list (no error raised)."""
    soma = Soma()
    llm = MockLLM()
    rotator = MockRotator()
    falcon = FalconDendrite(soma, llm, rotator)

    session_id = "test-session-006"
    arch_id = "arch-nonexistent"

    # Create a ConstraintNode (but no ArchitectureNode)
    soma.create_node("ConstraintNode", {
        "id": "constraint-1",
        "session_id": session_id,
        "source_text": "CHOSEN: store=postgresql"
    })

    created_edges = falcon.create_constrained_by(arch_id, session_id)

    assert len(created_edges) == 0
    edges = soma.get_all_edges()
    constrained_by_edges = [e for e in edges if e.rel_type == "CONSTRAINED_BY"]
    assert len(constrained_by_edges) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])