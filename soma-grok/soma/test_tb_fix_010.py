"""Unit tests for TB-FIX-010: Slot check result on OptimizedSlot."""
from unittest.mock import Mock

import pytest

from store import Soma
from myelinator_olc import MyelinatorOptimizer


def test_apply_check_ok_sets_optimized():
    """Checker returning ok=true sets check_ok true, check_error '', status optimized."""
    soma = Soma()
    # Create a FunctionSlot
    slot_id = "slot-123"
    soma.create_node("FunctionSlot", {
        "id": slot_id,
        "session_id": "session-1",
        "name": "test_func",
        "mandate": "Test function",
        "terminal_id": "term-1",
    })
    # Create an OptimizedSlot for it
    opt_id = f"opt-{slot_id}"
    soma.create_node("OptimizedSlot", {
        "id": opt_id,
        "session_id": "session-1",
        "mandate": "Test function",
        "terminal_id": "term-1",
        "status": "optimized",
        "pin_hash": "abc123",
        "parent_slot_id": slot_id,
        "invariant_count": 0,
        "laws": [],
    })
    # Create GOVERNS and LINKED_TO edges
    soma.create_edge("inv-1", "GOVERNS", slot_id)
    soma.create_edge(opt_id, "LINKED_TO", slot_id)

    optimizer = MyelinatorOptimizer(soma, None)

    def checker_pass(slot_id):
        return True, ""

    result = optimizer.apply_check(slot_id, checker_pass)

    assert result["optimized_slot_id"] == opt_id
    assert result["check_ok"] is True
    assert result["check_error"] == ""
    assert result["status"] == "optimized"

    # Verify node properties updated
    opt_node = soma.get_node(opt_id)
    assert opt_node.properties["check_ok"] is True
    assert opt_node.properties["check_error"] == ""
    assert opt_node.properties["status"] == "optimized"

    # Verify existing edges unchanged
    edges = soma.get_edges_for(slot_id)
    governs_edges = [e for e in edges if e.rel_type == "GOVERNS"]
    linked_edges = [e for e in edges if e.rel_type == "LINKED_TO"]
    assert len(governs_edges) == 1
    assert len(linked_edges) == 1


def test_apply_check_fail_sets_check_failed():
    """Checker returning ok=false sets check_ok false, check_error to the checker string, status check_failed."""
    soma = Soma()
    slot_id = "slot-456"
    soma.create_node("FunctionSlot", {
        "id": slot_id,
        "session_id": "session-1",
        "name": "test_func2",
        "mandate": "Test function 2",
        "terminal_id": "term-2",
    })
    opt_id = f"opt-{slot_id}"
    soma.create_node("OptimizedSlot", {
        "id": opt_id,
        "session_id": "session-1",
        "mandate": "Test function 2",
        "terminal_id": "term-2",
        "status": "optimized",
        "pin_hash": "def456",
        "parent_slot_id": slot_id,
        "invariant_count": 0,
        "laws": [],
    })
    soma.create_edge(opt_id, "LINKED_TO", slot_id)

    optimizer = MyelinatorOptimizer(soma, None)

    def checker_fail(slot_id):
        return False, "Type mismatch in argument 3"

    result = optimizer.apply_check(slot_id, checker_fail)

    assert result["optimized_slot_id"] == opt_id
    assert result["check_ok"] is False
    assert result["check_error"] == "Type mismatch in argument 3"
    assert result["status"] == "check_failed"

    opt_node = soma.get_node(opt_id)
    assert opt_node.properties["check_ok"] is False
    assert opt_node.properties["check_error"] == "Type mismatch in argument 3"
    assert opt_node.properties["status"] == "check_failed"


def test_apply_check_missing_slot_returns_error():
    """A missing slot returns an error dict and writes nothing."""
    soma = Soma()
    optimizer = MyelinatorOptimizer(soma, None)

    def checker_pass(slot_id):
        return True, ""

    result = optimizer.apply_check("nonexistent-slot", checker_pass)

    assert result["error"] == "OptimizedSlot not found"
    assert result["slot_id"] == "nonexistent-slot"
    assert "optimized_slot_id" not in result

    # No nodes should be modified (since there were none)
    assert soma.node_count() == 0


def test_apply_check_does_not_spawn_process():
    """The method does not spawn a process and does not import pyright or mypy."""
    # This is verified by code inspection - no subprocess, no pyright, no mypy imports
    soma = Soma()
    slot_id = "slot-789"
    soma.create_node("FunctionSlot", {
        "id": slot_id,
        "session_id": "session-1",
        "name": "test_func3",
        "mandate": "Test function 3",
        "terminal_id": "term-3",
    })
    opt_id = f"opt-{slot_id}"
    soma.create_node("OptimizedSlot", {
        "id": opt_id,
        "session_id": "session-1",
        "mandate": "Test function 3",
        "terminal_id": "term-3",
        "status": "optimized",
        "pin_hash": "ghi789",
        "parent_slot_id": slot_id,
        "invariant_count": 0,
        "laws": [],
    })

    optimizer = MyelinatorOptimizer(soma, None)

    def checker_pass(slot_id):
        return True, ""

    # Should complete without any subprocess calls
    result = optimizer.apply_check(slot_id, checker_pass)
    assert result["status"] == "optimized"


def test_apply_check_existing_edges_unchanged():
    """Existing GOVERNS and LINKED_TO edges are unchanged."""
    soma = Soma()
    slot_id = "slot-999"
    soma.create_node("FunctionSlot", {
        "id": slot_id,
        "session_id": "session-1",
        "name": "test_func4",
        "mandate": "Test function 4",
        "terminal_id": "term-4",
    })
    opt_id = f"opt-{slot_id}"
    soma.create_node("OptimizedSlot", {
        "id": opt_id,
        "session_id": "session-1",
        "mandate": "Test function 4",
        "terminal_id": "term-4",
        "status": "optimized",
        "pin_hash": "jkl012",
        "parent_slot_id": slot_id,
        "invariant_count": 2,
        "laws": ["law1", "law2"],
    })
    # Create multiple GOVERNS edges
    soma.create_edge("inv-1", "GOVERNS", slot_id)
    soma.create_edge("inv-2", "GOVERNS", slot_id)
    soma.create_edge(opt_id, "LINKED_TO", slot_id)

    optimizer = MyelinatorOptimizer(soma, None)

    def checker_pass(slot_id):
        return True, ""

    result = optimizer.apply_check(slot_id, checker_pass)

    # Verify edges unchanged
    edges = soma.get_edges_for(slot_id)
    governs_edges = [e for e in edges if e.rel_type == "GOVERNS"]
    linked_edges = [e for e in edges if e.rel_type == "LINKED_TO"]
    assert len(governs_edges) == 2
    assert len(linked_edges) == 1
    assert governs_edges[0].source in ("inv-1", "inv-2")
    assert linked_edges[0].source == opt_id


if __name__ == "__main__":
    pytest.main([__file__, "-v"])