"""Unit tests for TB-FIX-003: Empty session loader."""
import json
import tempfile
from pathlib import Path

import pytest

from session_loader import load_session


def test_load_session_missing_dir():
    """A missing path returns records=[] and reason='missing_dir'."""
    missing_path = Path("/tmp/this_directory_does_not_exist_12345")
    records, reason = load_session(missing_path)

    assert records == []
    assert reason == "missing_dir"


def test_load_session_empty_dir():
    """An empty directory returns records=[] and reason='no_records'."""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir)
        records, reason = load_session(path)

        assert records == []
        assert reason == "no_records"


def test_load_session_valid_record():
    """A directory with one valid JSON object returns that record and reason='ok'."""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir)

        valid_record = {
            "chat_set_id": "cs-001",
            "session_id": "session-123",
            "set_number": 1,
            "user_text": "Hello world",
            "assistant_text": "Hi there"
        }

        (path / "chat1.json").write_text(json.dumps(valid_record))

        records, reason = load_session(path)

        assert reason == "ok"
        assert len(records) == 1
        assert records[0]["chat_set_id"] == "cs-001"
        assert records[0]["session_id"] == "session-123"
        assert records[0]["set_number"] == 1
        assert records[0]["user_text"] == "Hello world"
        assert records[0]["assistant_text"] == "Hi there"


def test_load_session_missing_key_skipped():
    """A JSON file missing a required key is skipped, not raised."""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir)

        # Missing chat_set_id
        (path / "chat1.json").write_text(json.dumps({
            "session_id": "session-123",
            "set_number": 1,
            "user_text": "Hello"
        }))

        # Valid record
        (path / "chat2.json").write_text(json.dumps({
            "chat_set_id": "cs-002",
            "session_id": "session-123",
            "set_number": 2,
            "user_text": "World"
        }))

        records, reason = load_session(path)

        assert reason == "ok"
        assert len(records) == 1
        assert records[0]["chat_set_id"] == "cs-002"


def test_load_session_invalid_json_skipped():
    """Invalid JSON is skipped, not raised."""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir)

        # Invalid JSON
        (path / "chat1.json").write_text("{ not valid json }")

        # Valid record
        (path / "chat2.json").write_text(json.dumps({
            "chat_set_id": "cs-002",
            "session_id": "session-123",
            "set_number": 2,
            "user_text": "World"
        }))

        records, reason = load_session(path)

        assert reason == "ok"
        assert len(records) == 1
        assert records[0]["chat_set_id"] == "cs-002"


def test_load_session_does_not_index_zero():
    """The function does not index [0] on empty list."""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir)

        # Empty directory - should not raise IndexError
        records, reason = load_session(path)

        assert records == []
        assert reason == "no_records"

    # Missing directory - should not raise IndexError
    missing_path = Path("/tmp/this_directory_does_not_exist_12345")
    records, reason = load_session(missing_path)

    assert records == []
    assert reason == "missing_dir"


def test_load_session_multiple_valid_sorted():
    """Multiple valid records are sorted by set_number."""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir)

        (path / "chat3.json").write_text(json.dumps({
            "chat_set_id": "cs-003",
            "session_id": "session-123",
            "set_number": 3,
            "user_text": "Third"
        }))
        (path / "chat1.json").write_text(json.dumps({
            "chat_set_id": "cs-001",
            "session_id": "session-123",
            "set_number": 1,
            "user_text": "First"
        }))
        (path / "chat2.json").write_text(json.dumps({
            "chat_set_id": "cs-002",
            "session_id": "session-123",
            "set_number": 2,
            "user_text": "Second"
        }))

        records, reason = load_session(path)

        assert reason == "ok"
        assert len(records) == 3
        assert records[0]["chat_set_id"] == "cs-001"
        assert records[1]["chat_set_id"] == "cs-002"
        assert records[2]["chat_set_id"] == "cs-003"


def test_load_session_non_dict_json_skipped():
    """JSON arrays or primitives are skipped."""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir)

        # JSON array
        (path / "chat1.json").write_text(json.dumps([1, 2, 3]))

        # Valid record
        (path / "chat2.json").write_text(json.dumps({
            "chat_set_id": "cs-002",
            "session_id": "session-123",
            "set_number": 2,
            "user_text": "World"
        }))

        records, reason = load_session(path)

        assert reason == "ok"
        assert len(records) == 1


def test_load_session_duplicate_chat_set_id_skipped():
    """Duplicate chat_set_id in different files are skipped."""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir)

        (path / "chat1.json").write_text(json.dumps({
            "chat_set_id": "cs-001",
            "session_id": "session-123",
            "set_number": 1,
            "user_text": "First"
        }))
        (path / "chat2.json").write_text(json.dumps({
            "chat_set_id": "cs-001",  # Duplicate
            "session_id": "session-123",
            "set_number": 2,
            "user_text": "Second"
        }))

        records, reason = load_session(path)

        assert reason == "ok"
        assert len(records) == 1
        assert records[0]["chat_set_id"] == "cs-001"
        assert records[0]["set_number"] == 1  # First one kept


if __name__ == "__main__":
    pytest.main([__file__, "-v"])