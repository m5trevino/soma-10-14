"""Unit tests for TB-011 — Crystallize status block."""
import io
from crystallize import write_crystallize


def _make_stage(name, outcome, verified=0, failed=0):
    return {
        "name": name,
        "outcome": outcome,
        "count_verified": verified,
        "count_failed": failed,
    }


class TestWriteCrystallize:
    """Crystallize status block tests."""

    def test_success_list(self):
        """One success list — all stages complete."""
        stages = [
            _make_stage("BLUEPRINT", "SUCCESS", verified=10, failed=0),
            _make_stage("MONOLITH", "SUCCESS", verified=8, failed=0),
            _make_stage("SLICE", "SUCCESS", verified=6, failed=0),
            _make_stage("HARDEN", "SUCCESS", verified=16, failed=1),
            _make_stage("EXECUTE", "SUCCESS", verified=4, failed=0),
            _make_stage("GATE", "SUCCESS", verified=16, failed=1),
            _make_stage("PUBLISH", "SUCCESS", verified=3, failed=0),
        ]
        stream = io.StringIO()
        result = write_crystallize(stages, stream)
        assert "STATE  NEXT  published 7. failed slot stays unwritten." in result
        assert "-[PUBLISH]- Running. . . . . . . -[SUCCESS]-" in result

    def test_fail_on_gate(self):
        """List that fails on GATE — PUBLISH absent."""
        stages = [
            _make_stage("BLUEPRINT", "SUCCESS", verified=10, failed=0),
            _make_stage("MONOLITH", "SUCCESS", verified=8, failed=0),
            _make_stage("GATE", "FAIL"),
            _make_stage("PUBLISH", "SUCCESS", verified=3, failed=0),
        ]
        stream = io.StringIO()
        result = write_crystallize(stages, stream)
        assert "STATE  KILL  stage=GATE. Nothing published after the failure." in result
        assert "-[PUBLISH]" not in result

    def test_no_set_frames(self):
        """Must not print a chat set header."""
        stages = [_make_stage("BLUEPRINT", "SUCCESS", verified=5, failed=0)]
        stream = io.StringIO()
        write_crystallize(stages, stream)
        output = stream.getvalue()
        assert "CHAT SET" not in output

    def test_does_not_publish_files(self):
        """Must not publish files."""
        import crystallize, inspect
        source = inspect.getsource(crystallize)
        assert "open(" not in source
        assert "write(" not in source.replace("stream.write", "")

    def test_only_runs_when_invoked(self):
        """Must not clear the screen."""
        stages = [_make_stage("BLUEPRINT", "SUCCESS", verified=5, failed=0)]
        stream = io.StringIO()
        write_crystallize(stages, stream)
        output = stream.getvalue()
        assert "\033[2J" not in output
        assert "\033[H" not in output

    def test_success_dot_count_is_7(self):
        """Each status line uses 7 dots."""
        stages = [_make_stage("GATE", "SUCCESS", verified=16, failed=1)]
        stream = io.StringIO()
        write_crystallize(stages, stream)
        output = stream.getvalue()
        line = [l for l in output.splitlines() if "-[GATE]-" in l][0]
        # Pattern: "-[GATE]- Running. . . . . . . -[SUCCESS]-"
        assert "-[SUCCESS]-" in line
        assert "Running. . . . . . . -[SUCCESS]-" in line

    def test_running_uses_cr(self):
        """A running stage uses the same carriage-return status line."""
        stages = [_make_stage("BLUEPRINT", None)]
        stream = io.StringIO()
        write_crystallize(stages, stream)
        output = stream.getvalue()
        assert "\r" in output

    def test_fail_stops_block(self):
        """Later stage names are not printed on fail."""
        stages = [
            _make_stage("SLICE", "SUCCESS", verified=2, failed=0),
            _make_stage("HARDEN", "FAIL"),
            _make_stage("EXECUTE", "SUCCESS", verified=1, failed=0),
        ]
        stream = io.StringIO()
        result = write_crystallize(stages, stream)
        assert "-[EXECUTE]" not in result
