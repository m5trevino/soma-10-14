"""Unit tests for TB-005 — Four-row metrics table."""
import pytest
from metrics_table import render_table

# ── golden reference ──────────────────────────────────────────────────
# Columns: blank(14) | CHARS IN(15) | CHARS OUT(16) | SIGNALS-INTRO-BEAVER(22) |
#          TASKS-PLAN-BEAVER(19) | OUTCOME-OUTRO-BEAVER(22) | MODEL-USED(13)
# Row order: DISTILLER, INTRO-BEAVER, PLAN-BEAVER, OUTRO-BEAVER

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
    _make_row(5000, 3000, 4, 2, 1, "qwen-30b"),
    _make_row(3000, 2500, 3, 1, 1, "gpt-oss"),
    _make_row(2500, 2000, 3, 2, 1, "nemotron"),
    _make_row(2000, 1500, 4, 1, 1, "qwen-30b"),
]


class TestRenderTable:
    """Four-row metrics table tests."""

    def test_line_count_is_7(self):
        """7 lines: top, header, separator, 4 data, bottom."""
        table = render_table(ROWS)
        lines = table.split("\n")
        assert len(lines) == 7, f"Expected 7 lines, got {len(lines)}"

    def test_all_lines_same_length(self):
        """Every line must be the same length."""
        table = render_table(ROWS)
        lines = table.split("\n")
        lengths = {len(l) for l in lines}
        assert len(lengths) == 1, f"Line lengths not equal: {lengths}"

    def test_line_length_is_123(self):
        """2 borders + 1+inner+1 for each of 7 cols:
        1 + (1+14+1) + (1+15+1) + (1+16+1) + (1+22+1) + (1+19+1) + (1+22+1) + (1+13+1) + 1 = 123
        """
        table = render_table(ROWS)
        lines = table.split("\n")
        assert len(lines[0]) == 123, f"Expected 123 chars, got {len(lines[0])}"

    def test_top_border(self):
        table = render_table(ROWS)
        lines = table.split("\n")
        assert lines[0].startswith("┌")
        assert lines[0].endswith("┐")
        assert "─" in lines[0]

    def test_last_data_row(self):
        """Line 6 is the 4th data row (OUTRO-BEAVER), no bottom border."""
        table = render_table(ROWS)
        lines = table.split("\n")
        assert lines[6].startswith("│")
        assert lines[6].endswith("│")
        assert "qwen-30b" in lines[6]

    def test_header_line(self):
        table = render_table(ROWS)
        lines = table.split("\n")
        header = lines[1]
        assert "│" in header
        assert "CHARACTERS IN" in header
        assert "CHARACTERS OUT" in header
        assert "SIGNALS-INTRO-BEAVER" in header
        assert "TASKS-PLAN-BEAVER" in header
        assert "OUTCOME-OUTRO-BEAVER" in header
        assert "MODEL-USED" in header

    def test_separator_line(self):
        table = render_table(ROWS)
        lines = table.split("\n")
        sep = lines[2]
        assert sep.startswith("├")
        assert sep.endswith("┤")
        assert "┼" in sep

    def test_data_rows_present(self):
        table = render_table(ROWS)
        assert "5,000" in table
        assert "3,000" in table

    def test_fifth_row_raises(self):
        with pytest.raises(ValueError, match="exactly 4"):
            render_table(ROWS + [_make_row(0, 0, 0, 0, 0, "x")])

    def test_missing_row_raises(self):
        with pytest.raises(ValueError, match="exactly 4"):
            render_table(ROWS[:3])

    def test_missing_key_raises(self):
        bad = list(ROWS)
        del bad[0]["chars_in"]
        with pytest.raises(ValueError, match="missing"):
            render_table(bad)

    def test_non_list_raises(self):
        with pytest.raises(ValueError, match="list"):
            render_table("not a list")  # type: ignore
