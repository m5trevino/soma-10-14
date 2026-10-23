"""Unit tests for pad_cell (TB-001)."""
import pytest
from pad_cell import pad_cell


class TestPadCell:
    """Exact-width cell padder tests."""

    def test_distiller_left(self):
        result = pad_cell("DISTILLER", 14, "left")
        assert result == "DISTILLER     "
        assert len(result) == 14

    def test_intro_beaver_left(self):
        result = pad_cell("INTRO-BEAVER", 14, "left")
        assert result == "INTRO-BEAVER  "
        assert len(result) == 14

    def test_plan_beaver_left(self):
        result = pad_cell("PLAN-BEAVER", 14, "left")
        assert result == "PLAN-BEAVER   "
        assert len(result) == 14

    def test_outro_beaver_left(self):
        result = pad_cell("OUTRO-BEAVER", 14, "left")
        assert result == "OUTRO-BEAVER  "
        assert len(result) == 14

    def test_empty_left(self):
        result = pad_cell("", 14, "left")
        assert result == "              "
        assert len(result) == 14

    def test_tab_raises(self):
        with pytest.raises(ValueError, match="tab or newline"):
            pad_cell("hello\tworld", 14, "left")

    def test_newline_raises(self):
        with pytest.raises(ValueError, match="tab or newline"):
            pad_cell("hello\nworld", 14, "left")

    def test_overflow_raises(self):
        with pytest.raises(ValueError, match="exceeds width"):
            pad_cell("TOOLONG", 5, "left")

    def test_return_length_always_width(self):
        for text, width, align in [
            ("hi", 10, "left"),
            ("hi", 10, "right"),
            ("", 5, "left"),
            ("", 5, "right"),
            ("abc", 3, "left"),
            ("abc", 3, "right"),
        ]:
            result = pad_cell(text, width, align)
            assert len(result) == width