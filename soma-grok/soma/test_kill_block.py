"""Unit tests for TB-007 — Kill block."""
import io
from kill_block import write_kill_set


OUTCOMES = [("DISTILLER", "SUCCESS"), ("INTRO-BEAVER", "SUCCESS"), ("PLAN-BEAVER", "FAIL")]


class TestWriteKillSet:
    """Kill block tests."""

    def test_first_line_kill_header(self):
        stream = io.StringIO()
        write_kill_set(7, 54, OUTCOMES, "PLAN-BEAVER", 90, stream)
        output = stream.getvalue()
        lines = output.splitlines()
        assert lines[0] == "CHAT SET 7/54  KILL"

    def test_finished_stages_print_fail(self):
        stream = io.StringIO()
        write_kill_set(7, 54, OUTCOMES, "PLAN-BEAVER", 90, stream)
        output = stream.getvalue()
        assert "-[DISTILLER]- Running. . . . . . . -[SUCCESS]-" in output
        assert "-[INTRO-BEAVER]- Running. . . . . . . -[SUCCESS]-" in output
        assert "-[PLAN-BEAVER]- Running. . . . . . . -[FAIL]-" in output

    def test_reason_line(self):
        stream = io.StringIO()
        write_kill_set(7, 54, OUTCOMES, "PLAN-BEAVER", 90, stream)
        output = stream.getvalue()
        assert "REASON no beat for 01:30" in output
        assert "Kill it. Later sets did not start." in output

    def test_no_table_present(self):
        """No box table characters in kill block."""
        stream = io.StringIO()
        write_kill_set(7, 54, OUTCOMES, "PLAN-BEAVER", 90, stream)
        output = stream.getvalue()
        assert "┌" not in output
        assert "└" not in output
        assert "│" not in output
        assert "─" not in output

    def test_no_further_set_header(self):
        """Only one CHAT SET header."""
        stream = io.StringIO()
        write_kill_set(7, 54, OUTCOMES, "PLAN-BEAVER", 90, stream)
        output = stream.getvalue()
        assert output.count("CHAT SET") == 1

    def test_no_screen_clear(self):
        stream = io.StringIO()
        write_kill_set(7, 54, OUTCOMES, "PLAN-BEAVER", 90, stream)
        output = stream.getvalue()
        assert "\033[2J" not in output
        assert "\033[H" not in output

    def test_age_90_formats_as_01_30(self):
        stream = io.StringIO()
        write_kill_set(1, 54, [], "DISTILLER", 90, stream)
        output = stream.getvalue()
        assert "01:30" in output

    def test_age_zero_formats_as_00_00(self):
        stream = io.StringIO()
        write_kill_set(1, 54, [], "DISTILLER", 0, stream)
        output = stream.getvalue()
        assert "00:00" in output

    def test_empty_finished_outcomes(self):
        """No finished stages — only header and reason."""
        stream = io.StringIO()
        write_kill_set(1, 54, [], "DISTILLER", 120, stream)
        output = stream.getvalue()
        lines = output.splitlines()
        assert lines[0] == "CHAT SET 1/54  KILL"
        assert "no beat for 02:00" in output
        assert "DISTILLER" not in lines[1] if len(lines) > 1 else True
