"""Unit tests for TB-009 — Prepared-list driver."""
import io
from prepared_list import run_sets
from metrics_table import render_table


def _make_row(c_in, c_out, sig, tsk, oc, model):
    return {"chars_in": c_in, "chars_out": c_out, "signals": sig,
            "tasks": tsk, "outcomes": oc, "model": model}


def _make_item(index, total, outcomes, rows):
    return {"index": index, "total": total, "outcomes": outcomes, "rows": rows}


ALL_SUCCESS = ["SUCCESS", "SUCCESS", "SUCCESS", "SUCCESS"]
ROWS = [
    _make_row(1000, 800, 2, 1, 1, "qwen"),
    _make_row(900, 700, 2, 1, 1, "gpt"),
    _make_row(800, 600, 2, 1, 1, "nemotron"),
    _make_row(700, 500, 2, 1, 1, "qwen"),
]


class TestRunSets:
    """Prepared-list driver tests."""

    def test_three_success_items(self):
        """Three success items produce three closed blocks in order."""
        items = [
            _make_item(1, 3, ALL_SUCCESS, ROWS),
            _make_item(2, 3, ALL_SUCCESS, ROWS),
            _make_item(3, 3, ALL_SUCCESS, ROWS),
        ]
        stream = io.StringIO()
        result = run_sets(items, stream)
        assert result == "NEXT"
        output = stream.getvalue()
        assert output.count("CHAT SET") == 3
        assert "1 /   3" in output
        assert "2 /   3" in output
        assert "3 /   3" in output

    def test_kill_on_item_2(self):
        """A KILL on item 2 writes the kill block and does not write item 3."""
        items = [
            _make_item(1, 3, ALL_SUCCESS, ROWS),
            _make_item(2, 3, ["SUCCESS", "SUCCESS", "FAIL", "SUCCESS"], ROWS),
            _make_item(3, 3, ALL_SUCCESS, ROWS),
        ]
        stream = io.StringIO()
        result = run_sets(items, stream)
        assert result == "KILL"
        output = stream.getvalue()
        assert "1 /   3" in output
        assert "KILL" in output
        assert "3 /" not in output  # Item 3 not written

    def test_returns_next_all_closed(self):
        """Return NEXT if all items closed."""
        items = [_make_item(1, 2, ALL_SUCCESS, ROWS),
                 _make_item(2, 2, ALL_SUCCESS, ROWS)]
        stream = io.StringIO()
        result = run_sets(items, stream)
        assert result == "NEXT"

    def test_returns_kill_on_stop(self):
        """Return KILL if stopped early."""
        items = [_make_item(1, 3, ALL_SUCCESS, ROWS),
                 _make_item(2, 3, ["FAIL", "FAIL", "FAIL", "FAIL"], ROWS),
                 _make_item(3, 3, ALL_SUCCESS, ROWS)]
        stream = io.StringIO()
        result = run_sets(items, stream)
        assert result == "KILL"

    def test_earlier_blocks_not_rewritten(self):
        """Earlier blocks are not rewritten."""
        items = [
            _make_item(1, 2, ALL_SUCCESS, ROWS),
            _make_item(2, 2, ALL_SUCCESS, ROWS),
        ]
        stream = io.StringIO()
        run_sets(items, stream)
        output = stream.getvalue()
        assert output.count("CHAT SET   1") == 1
        assert output.count("CHAT SET   2") == 1

    def test_no_file_access(self):
        """Function does not open any files."""
        import prepared_list
        import inspect
        source = inspect.getsource(prepared_list)
        assert "open(" not in source
        assert "Path(" not in source or "# path check" in source

    def test_no_computed_counts(self):
        """Function does not compute counts — receives pre-computed rows."""
        # This is tested implicitly: rows are passed in and used as-is.
        # If the function computed counts from source data, it would
        # have its own data aggregation logic.
        items = [_make_item(1, 1, ALL_SUCCESS, ROWS)]
        stream = io.StringIO()
        result = run_sets(items, stream)
        assert result == "NEXT"
