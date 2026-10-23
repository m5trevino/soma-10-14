"""Unit tests for TB-010 — Ingest close summary."""
import io
from ingest_close import write_ingest_close


class TestWriteIngestClose:
    """Ingest close summary tests."""

    def test_done_with_no_fail(self):
        stream = io.StringIO()
        stats = {"done": 54, "total": 54, "fail": 0,
                 "chars_in": 45654, "chars_out": 14402,
                 "signals": 44, "tasks": 18, "outcomes": 12}
        write_ingest_close(stats, stream)
        output = stream.getvalue()
        lines = output.splitlines()
        assert lines[0] == "INGEST  NEXT  54/54 closed"
        assert lines[1] == "sets 54   fail 0"
        assert "chars in" in lines[2]
        assert "45,654" in lines[2]
        assert "14,402" in lines[2]
        assert lines[3] == "signals 44   tasks 18   outcomes 12"
        assert lines[4] == "STATE  NEXT  phase=INGEST done. Waiting."

    def test_done_with_fail(self):
        stream = io.StringIO()
        stats = {"done": 54, "total": 54, "fail": 1,
                 "chars_in": 45654, "chars_out": 14402,
                 "signals": 44, "tasks": 18, "outcomes": 12}
        write_ingest_close(stats, stream)
        output = stream.getvalue()
        lines = output.splitlines()
        assert lines[4] == "STATE  KILL  phase=INGEST failed. Waiting."

    def test_no_row_bodies(self):
        """Must not print row bodies."""
        stream = io.StringIO()
        stats = {"done": 1, "total": 1, "fail": 0,
                 "chars_in": 100, "chars_out": 50,
                 "signals": 1, "tasks": 1, "outcomes": 1}
        write_ingest_close(stats, stream)
        output = stream.getvalue()
        assert "┌" not in output
        assert "│" not in output
        assert "─" not in output

    def test_does_not_start_later_phase(self):
        """Function is purely informational — no phase logic."""
        import ingest_close, inspect
        source = inspect.getsource(ingest_close)
        assert "phase=" not in source or "phase=INGEST" in source
