"""Unit tests for TB-FIX-002: TRACES_TO edge proof."""
import pytest
from store import Soma
from axon_hillock_oc import AxonHillockSlicer


class MockLLM:
    """Mock LLM client."""
    def complete(self, model, instruction, payload):
        return {
            "ok": True,
            "result": {"architecture_text": "Test", "source_requirements_id": "req-1"},
            "metrics": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30, "latency_ms": 5.0}
        }


class MockRotator:
    """Mock model rotator."""
    def next_model(self, role):
        return "mock-model"


def test_traces_to_edge_created_for_matching_slot_and_directive():
    """FunctionSlot named load_user and DirectiveNode containing load_user produce one TRACES_TO edge."""
    soma = Soma()
    llm = MockLLM()
    rotator = MockRotator()
    slicer = AxonHillockSlicer(soma, llm, rotator)

    session_id = "test-session-001"

    # Create FunctionSlot
    slot_id = "slot-test-001"
    soma.create_node("FunctionSlot", {
        "id": slot_id,
        "session_id": session_id,
        "name": "load_user",
        "file_path": "users.py",
        "parent_file_node_id": "file-1",
        "mandate": "Implement load_user",
        "terminal_id": "T-0",
        "status": "draft",
        "pin_hash": "pending",
        "code_block": "def load_user(): pass",
        "inputs": [],
        "outputs": [],
        "evidence_ids": [],
    })

    # Create DirectiveNode with matching text
    directive_id = "directive-1"
    soma.create_node("DirectiveNode", {
        "id": directive_id,
        "session_id": session_id,
        "source_text": "We need a load_user function to fetch users from the database"
    })

    # Call the method
    linked = slicer.link_evidence_to_slots(session_id)

    # Assert edge was created
    assert slot_id in linked
    assert directive_id in linked[slot_id]

    edges = soma.get_all_edges()
    traces_to_edges = [e for e in edges if e.rel_type == "TRACES_TO"]
    assert len(traces_to_edges) == 1
    assert traces_to_edges[0].source == slot_id
    assert traces_to_edges[0].target == directive_id
    assert traces_to_edges[0].rel_type == "TRACES_TO"


def test_no_traces_to_for_non_matching_directive():
    """DirectiveNode whose text does not contain slot name or file basename produces no TRACES_TO edge."""
    soma = Soma()
    llm = MockLLM()
    rotator = MockRotator()
    slicer = AxonHillockSlicer(soma, llm, rotator)

    session_id = "test-session-002"

    slot_id = "slot-test-002"
    soma.create_node("FunctionSlot", {
        "id": slot_id,
        "session_id": session_id,
        "name": "load_user",
        "file_path": "accounts.py",  # Different basename to avoid "users" match
        "parent_file_node_id": "file-1",
        "mandate": "Implement load_user",
        "terminal_id": "T-0",
        "status": "draft",
        "pin_hash": "pending",
        "code_block": "def load_user(): pass",
        "inputs": [],
        "outputs": [],
        "evidence_ids": [],
    })

    # Create DirectiveNode with NON-matching text (no "load_user" or "accounts")
    soma.create_node("DirectiveNode", {
        "id": "directive-2",
        "session_id": session_id,
        "source_text": "We need a save_user function to persist users"
    })

    linked = slicer.link_evidence_to_slots(session_id)

    assert slot_id in linked
    assert linked[slot_id] == []  # No matches

    edges = soma.get_all_edges()
    traces_to_edges = [e for e in edges if e.rel_type == "TRACES_TO"]
    assert len(traces_to_edges) == 0


def test_no_traces_to_for_foreign_session():
    """Node from another session produces no edge."""
    soma = Soma()
    llm = MockLLM()
    rotator = MockRotator()
    slicer = AxonHillockSlicer(soma, llm, rotator)

    session_id = "test-session-003"

    slot_id = "slot-test-003"
    soma.create_node("FunctionSlot", {
        "id": slot_id,
        "session_id": session_id,
        "name": "load_user",
        "file_path": "users.py",
        "parent_file_node_id": "file-1",
        "mandate": "Implement load_user",
        "terminal_id": "T-0",
        "status": "draft",
        "pin_hash": "pending",
        "code_block": "def load_user(): pass",
        "inputs": [],
        "outputs": [],
        "evidence_ids": [],
    })

    # Create DirectiveNode with DIFFERENT session_id
    soma.create_node("DirectiveNode", {
        "id": "directive-foreign",
        "session_id": "other-session",
        "source_text": "We need a load_user function"
    })

    linked = slicer.link_evidence_to_slots(session_id)

    assert slot_id in linked
    assert linked[slot_id] == []

    edges = soma.get_all_edges()
    traces_to_edges = [e for e in edges if e.rel_type == "TRACES_TO"]
    assert len(traces_to_edges) == 0


def test_traces_to_idempotent():
    """Calling the method twice does not duplicate the same TRACES_TO pair."""
    soma = Soma()
    llm = MockLLM()
    rotator = MockRotator()
    slicer = AxonHillockSlicer(soma, llm, rotator)

    session_id = "test-session-004"

    slot_id = "slot-test-004"
    soma.create_node("FunctionSlot", {
        "id": slot_id,
        "session_id": session_id,
        "name": "load_user",
        "file_path": "users.py",
        "parent_file_node_id": "file-1",
        "mandate": "Implement load_user",
        "terminal_id": "T-0",
        "status": "draft",
        "pin_hash": "pending",
        "code_block": "def load_user(): pass",
        "inputs": [],
        "outputs": [],
        "evidence_ids": [],
    })

    directive_id = "directive-4"
    soma.create_node("DirectiveNode", {
        "id": directive_id,
        "session_id": session_id,
        "source_text": "We need a load_user function"
    })

    # First call
    linked_1 = slicer.link_evidence_to_slots(session_id)
    assert len(linked_1[slot_id]) == 1

    # Second call
    linked_2 = slicer.link_evidence_to_slots(session_id)
    assert len(linked_2[slot_id]) == 1

    # Total edges should still be 1
    edges = soma.get_all_edges()
    traces_to_edges = [e for e in edges if e.rel_type == "TRACES_TO"]
    assert len(traces_to_edges) == 1


def test_returned_map_lists_matched_evidence_id():
    """The returned map still lists the matched evidence id for that slot."""
    soma = Soma()
    llm = MockLLM()
    rotator = MockRotator()
    slicer = AxonHillockSlicer(soma, llm, rotator)

    session_id = "test-session-005"

    slot_id = "slot-test-005"
    soma.create_node("FunctionSlot", {
        "id": slot_id,
        "session_id": session_id,
        "name": "load_user",
        "file_path": "users.py",
        "parent_file_node_id": "file-1",
        "mandate": "Implement load_user",
        "terminal_id": "T-0",
        "status": "draft",
        "pin_hash": "pending",
        "code_block": "def load_user(): pass",
        "inputs": [],
        "outputs": [],
        "evidence_ids": [],
    })

    directive_id = "directive-5"
    soma.create_node("DirectiveNode", {
        "id": directive_id,
        "session_id": session_id,
        "source_text": "We need a load_user function"
    })

    linked = slicer.link_evidence_to_slots(session_id)

    assert slot_id in linked
    assert linked[slot_id] == [directive_id]


def test_traces_to_with_constraint_node():
    """TRACES_TO edge also created for ConstraintNode."""
    soma = Soma()
    llm = MockLLM()
    rotator = MockRotator()
    slicer = AxonHillockSlicer(soma, llm, rotator)

    session_id = "test-session-006"

    slot_id = "slot-test-006"
    soma.create_node("FunctionSlot", {
        "id": slot_id,
        "session_id": session_id,
        "name": "save_user",
        "file_path": "users.py",
        "parent_file_node_id": "file-1",
        "mandate": "Implement save_user",
        "terminal_id": "T-0",
        "status": "draft",
        "pin_hash": "pending",
        "code_block": "def save_user(): pass",
        "inputs": [],
        "outputs": [],
        "evidence_ids": [],
    })

    constraint_id = "constraint-1"
    soma.create_node("ConstraintNode", {
        "id": constraint_id,
        "session_id": session_id,
        "source_text": "The save_user function must use postgresql"
    })

    linked = slicer.link_evidence_to_slots(session_id)

    assert slot_id in linked
    assert constraint_id in linked[slot_id]

    edges = soma.get_all_edges()
    traces_to_edges = [e for e in edges if e.rel_type == "TRACES_TO"]
    assert len(traces_to_edges) == 1
    assert traces_to_edges[0].source == slot_id
    assert traces_to_edges[0].target == constraint_id


def test_traces_to_with_task_node():
    """TRACES_TO edge also created for TaskNode."""
    soma = Soma()
    llm = MockLLM()
    rotator = MockRotator()
    slicer = AxonHillockSlicer(soma, llm, rotator)

    session_id = "test-session-007"

    slot_id = "slot-test-007"
    soma.create_node("FunctionSlot", {
        "id": slot_id,
        "session_id": session_id,
        "name": "delete_user",
        "file_path": "users.py",
        "parent_file_node_id": "file-1",
        "mandate": "Implement delete_user",
        "terminal_id": "T-0",
        "status": "draft",
        "pin_hash": "pending",
        "code_block": "def delete_user(): pass",
        "inputs": [],
        "outputs": [],
        "evidence_ids": [],
    })

    task_id = "task-1"
    soma.create_node("TaskNode", {
        "id": task_id,
        "session_id": session_id,
        "task_text": "Implement delete_user endpoint"
    })

    linked = slicer.link_evidence_to_slots(session_id)

    assert slot_id in linked
    assert task_id in linked[slot_id]

    edges = soma.get_all_edges()
    traces_to_edges = [e for e in edges if e.rel_type == "TRACES_TO"]
    assert len(traces_to_edges) == 1
    assert traces_to_edges[0].source == slot_id
    assert traces_to_edges[0].target == task_id


if __name__ == "__main__":
    pytest.main([__file__, "-v"])