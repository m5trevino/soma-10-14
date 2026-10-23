"""Unit tests for TB-006 — Closed set block."""
import io
import pytest
from closed_set import write_closed_set
from metrics_table import render_table


def _make_row(chars_in, chars_out, signals, tasks, outcomes, model):
    return {
        "chars_in": chars_in,
        "chars_out": chars_out,
        "signals": signals,
        "tasks": tasks,
        "outcomes": outcomes,
        "model": model,
    }

ROWS = [
    _make_row(4000, 1500, 5, 2, 1, "qwen-30b"),
    _make_row(3500, 1200, 4, 2, 1, "gpt-oss"),
    _make_row(3000, 1000, 3, 1, 0, "nemotron"),
    _make_row(2154, 402, 2, 1, 1, "qwen-30b"),
]
OUTCOMES_SUCCESS = ["SUCCESS", "SUCCESS", "SUCCESS", "SUCCESS"]
OUTCOMES_MIXED = ["SUCCESS", "SUCCESS", "FAIL", "SUCCESS"]


class TestWriteClosedSet:
    """Closed set block tests."""

    def test_first_line_header(self):
        stream = io.StringIO()
        write_closed_set(1, 54, OUTCOMES_SUCCESS, ROWS, stream)
        output = stream.getvalue()
        assert output.startswith("CHAT SET   1 /  54  NEXT")

    def test_four_status_lines(self):
        stream = io.StringIO()
        write_closed_set(1, 54, OUTCOMES_SUCCESS, ROWS, stream)
        output = stream.getvalue()
        lines = output.splitlines()
        # Line 1 is header, lines 2-5 are status lines
        assert len(lines) >= 5
        assert "-[DISTILLER]-" in lines[1]
        assert "-[INTRO-BEAVER]-" in lines[2]
        assert "-[PLAN-BEAVER]-" in lines[3]
        assert "-[OUTRO-BEAVER]-" in lines[4]

    def test_table_appears_for_all_success(self):
        stream = io.StringIO()
        write_closed_set(1, 54, OUTCOMES_SUCCESS, ROWS, stream)
        output = stream.getvalue()
        # render_table returns a table — check for box chars
        assert "│" in output
        assert "─" in output
        assert "┌" in output

    def test_table_absent_for_fail(self):
        stream = io.StringIO()
        write_closed_set(1, 54, OUTCOMES_MIXED, ROWS, stream)
        output = stream.getvalue()
        assert "┌" not in output
        assert "│" not in output

    def test_last_line_summary(self):
        stream = io.StringIO()
        write_closed_set(1, 54, OUTCOMES_SUCCESS, ROWS, stream)
        output = stream.getvalue()
        lines = output.splitlines()
        last_line = lines[-1]
        # Chars from golden counts (comma-formatted)
        assert "12,654" in last_line
        assert "4,102" in last_line
        assert "signals 14" in last_line
        assert "tasks 6" in last_line
        assert "outcomes 3" in last_line

    def test_block_ends_with_newline(self):
        stream = io.StringIO()
        write_closed_set(1, 54, OUTCOMES_SUCCESS, ROWS, stream)
        output = stream.getvalue()
        assert output.endswith("\n")

    def test_does_not_reach_function_for_other_sets(self):
        """Function doesn't loop sets — just writes one block."""
        stream = io.StringIO()
        # Called once, should only write one block
        write_closed_set(1, 54, OUTCOMES_SUCCESS, ROWS, stream)
        # Count how many "CHAT SET" headers appear
        output = stream.getvalue()
        assert output.count("CHAT SET") == 1

    def test_does_not_clear_screen(self):
        """No ANSI escape sequences for clearing."""
        stream = io.StringIO()
        write_closed_set(1, 54, OUTCOMES_SUCCESS, ROWS, stream)
        output = stream.getvalue()
        assert "\033[2J" not in output
        assert "\033[H" not in output

    def test_does_not_print_chat_text(self):
        """No raw chat content in output."""
        stream = io.StringIO()
        write_closed_set(1, 54, OUTCOMES_SUCCESS, ROWS, stream)
        output = stream.getvalue()
        assert "GOD DAMN" not in output
        assert "AIGHT" not in output
