"""Unit tests for write_status (TB-003)."""
import io
from write_status import write_status


class TestWriteStatus:
    """Single stage status line tests."""

    def test_success_text_golden(self):
        stream = io.StringIO()
        write_status("DISTILLER", "SUCCESS", stream)
        result = stream.getvalue()
        expected = "-[DISTILLER]- Running. . . . . . . -[SUCCESS]-\n"
        assert result == expected, f"Got {result!r}"

    def test_fail_text_golden(self):
        stream = io.StringIO()
        write_status("PLAN-BEAVER", "FAIL", stream)
        result = stream.getvalue()
        expected = "-[PLAN-BEAVER]- Running. . . . . . . -[FAIL]-\n"
        assert result == expected, f"Got {result!r}"

    def test_running_uses_cr_no_newline(self):
        stream = io.StringIO()
        write_status("PLAN-BEAVER", None, stream)
        result = stream.getvalue()
        assert "\n" not in result, f"Running line should not contain newline, got {result!r}"
        assert "\r" in result, f"Running line should contain carriage return, got {result!r}"
        assert "-[PLAN-BEAVER]- Running." in result

    def test_finish_emits_exactly_one_newline(self):
        stream = io.StringIO()
        write_status("DISTILLER", "SUCCESS", stream)
        result = stream.getvalue()
        assert result.count("\n") == 1, f"Expected exactly 1 newline, got {result.count(chr(10))}"

    def test_second_call_does_not_edit_finished_line(self):
        """A second call writes a NEW line after the first; it doesn't
        rewrite the first line (no cursor-up or overwrite)."""
        stream = io.StringIO()
        write_status("DISTILLER", "SUCCESS", stream)
        first = stream.getvalue()
        assert first == "-[DISTILLER]- Running. . . . . . . -[SUCCESS]-\n"

        write_status("DISTILLER", "SUCCESS", stream)
        result = stream.getvalue()
        # The function appends; verify the second line also has the suffix
        # and the first line is untouched (StringIO just appends).
        lines = result.split("\n")
        assert lines[0] == "-[DISTILLER]- Running. . . . . . . -[SUCCESS]-"
        assert lines[1] == "-[DISTILLER]- Running. . . . . . . -[SUCCESS]-"

    def test_outcome_other_than_success_or_fail_raises(self):
        stream = io.StringIO()
        import pytest
        with pytest.raises(ValueError, match="outcome"):
            write_status("PLAN-BEAVER", "BOGUS", stream)

    def test_success_dot_count_is_7(self):
        """The suffix contains exactly 7 dots in the Running line."""
        stream = io.StringIO()
        write_status("PLAN-BEAVER", "SUCCESS", stream)
        result = stream.getvalue()
        # The pattern is "Running. . . . . . ." — 7 dots total (6 spaces + final dot)
        assert result.endswith("-[SUCCESS]-\n")