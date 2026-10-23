"""Unit tests for ReceptorDendrite (TB-TK-REPLACE-001).

Verifies:
  - Node existence validation (raises ValueError for missing nodes)
  - Accurate character-level compression metrics
  - Deterministic whitespace stripping
  - Output dict shape (ReceptorOutput dataclass fields)
  - Edge cases: empty text, all-whitespace text, single line
"""
import sys
import tempfile
from pathlib import Path
from typing import Any

import pytest

# Ensure the soma/ directory is importable
_SOMA_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SOMA_DIR))

from store import Soma
from pipeline.receptor_dendrite import ReceptorDendrite, ReceptorOutput, strip_raw


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def empty_soma() -> Soma:
    """Soma instance backed by a temp file that is cleaned up after the test."""
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
        path = tmp.name
    try:
        return Soma(path=path)
    finally:
        Path(path).unlink(missing_ok=True)


@pytest.fixture
def populated_soma(empty_soma: Soma) -> Soma:
    """Soma pre-loaded with a single ChatSet node."""
    empty_soma.create_node("ChatSet", {
        "id": "sess01:1",
        "session_id": "sess01",
        "set_number": 1,
        "user_text": "Build a CLI tool.\n\n\n\n\nRun it now.",
        "assistant_text": "Here is the tool.\n\n\n\n\nDone.\n\n\n\n\nThanks.",
    })
    return empty_soma


@pytest.fixture
def empty_text_soma(empty_soma: Soma) -> Soma:
    """ChatSet with empty user + assistant text."""
    empty_soma.create_node("ChatSet", {
        "id": "sess_empty:1",
        "session_id": "sess_empty",
        "set_number": 1,
        "user_text": "",
        "assistant_text": "",
    })
    return empty_soma


# ---------------------------------------------------------------------------
# Tests: strip_raw (pure function, no Soma dependency)
# ---------------------------------------------------------------------------

class TestStripRaw:
    """Deterministic whitespace-cleaning function tests."""

    def test_preserves_single_line(self) -> None:
        assert strip_raw("hello world") == "hello world"

    def test_strips_trailing_space_on_lines(self) -> None:
        result = strip_raw("hello   \nworld  \n")
        assert result == "hello\nworld"

    def test_collapse_excessive_blank_lines(self) -> None:
        raw = "line1\n\n\n\n\nline2"
        assert strip_raw(raw) == "line1\n\nline2"

    def test_strips_leading_trailing_blank_space(self) -> None:
        raw = "\n\n\nhello\n\n\n"
        assert strip_raw(raw) == "hello"

    def test_handles_empty_string(self) -> None:
        assert strip_raw("") == ""

    def test_handles_whitespace_only(self) -> None:
        assert strip_raw("   \n\n  \n  ") == ""

    def test_preserves_normal_multiline(self) -> None:
        raw = "first\n\nsecond\n\nthird"
        assert strip_raw(raw) == raw

    def test_collapse_preserves_double_blank(self) -> None:
        """Exactly 3 blank lines → 2."""
        assert strip_raw("a\n\n\n\nb") == "a\n\nb"

    def test_does_not_touch_2_consecutive_blanks(self) -> None:
        """3 newlines (2 blank lines) is fine — only 4+ collapsed."""
        assert strip_raw("a\n\n\nb") == "a\n\n\nb"

    def test_utf8_content_preserved(self) -> None:
        raw = "日本語\n\n\n\nテスト"
        assert strip_raw(raw) == "日本語\n\nテスト"


# ---------------------------------------------------------------------------
# Tests: Node existence validation
# ---------------------------------------------------------------------------

class TestNodeValidation:
    """ReceptorDendrite raises ValueError when ChatSet is missing."""

    def test_missing_chatset_raises_valueerror(self, populated_soma: Soma) -> None:
        dendrite = ReceptorDendrite(populated_soma)
        with pytest.raises(ValueError, match="not found"):
            dendrite.run("nonexistent:99")

    def test_valid_chatset_does_not_raise(self, populated_soma: Soma) -> None:
        dendrite = ReceptorDendrite(populated_soma)
        # Should not raise
        out = dendrite.run("sess01:1")
        assert out is not None


# ---------------------------------------------------------------------------
# Tests: Compression metrics accuracy
# ---------------------------------------------------------------------------

class TestCompressionMetrics:
    """Character-level metrics must be accurate."""

    def test_bytes_original_includes_both_texts(
        self, populated_soma: Soma
    ) -> None:
        dendrite = ReceptorDendrite(populated_soma)
        out = dendrite.run("sess01:1")

        raw_user = "Build a CLI tool.\n\n\n\n\nRun it now."
        raw_asst = "Here is the tool.\n\n\n\n\nDone.\n\n\n\n\nThanks."
        expected_original = (raw_user + raw_asst).encode("utf-8")

        assert out.bytes_original == len(expected_original)

    def test_bytes_cleaned_matches_cleaned_text(
        self, populated_soma: Soma
    ) -> None:
        dendrite = ReceptorDendrite(populated_soma)
        out = dendrite.run("sess01:1")

        assert out.bytes_cleaned == len(out.cleaned_text.encode("utf-8"))

    def test_whitespace_removed_is_positive_when_excess_blanks_present(
        self, populated_soma: Soma
    ) -> None:
        dendrite = ReceptorDendrite(populated_soma)
        out = dendrite.run("sess01:1")
        assert out.whitespace_removed > 0

    def test_compression_ratio_is_between_0_and_1(
        self, populated_soma: Soma
    ) -> None:
        dendrite = ReceptorDendrite(populated_soma)
        out = dendrite.run("sess01:1")
        assert 0.0 <= out.compression_ratio <= 1.0

    def test_empty_text_ratio_is_zero(
        self, empty_text_soma: Soma
    ) -> None:
        dendrite = ReceptorDendrite(empty_text_soma)
        out = dendrite.run("sess_empty:1")
        assert out.bytes_original == 0
        assert out.compression_ratio == 0.0
        assert out.cleaned_text == ""
        assert out.whitespace_removed == 0

    def test_whitespace_only_removed_fully(
        self, empty_soma: Soma
    ) -> None:
        """A ChatSet that is all whitespace should compress to 0."""
        empty_soma.create_node("ChatSet", {
            "id": "sess_ws:1",
            "session_id": "sess_ws",
            "set_number": 1,
            "user_text": "   \n\n  \n  \n",
            "assistant_text": "\t\t  \n  ",
        })
        dendrite = ReceptorDendrite(empty_soma)
        out = dendrite.run("sess_ws:1")
        assert out.cleaned_text == ""
        assert out.bytes_cleaned == 0
        assert out.compression_ratio == 0.0


# ---------------------------------------------------------------------------
# Tests: Output shape (ReceptorOutput dataclass)
# ---------------------------------------------------------------------------

class TestOutputShape:
    """ReceptorOutput must contain all required fields with correct types."""

    def test_all_fields_present(self, populated_soma: Soma) -> None:
        dendrite = ReceptorDendrite(populated_soma)
        out = dendrite.run("sess01:1")

        assert isinstance(out, ReceptorOutput)
        assert isinstance(out.chatset_id, str)
        assert isinstance(out.cleaned_text, str)
        assert isinstance(out.compression_ratio, float)
        assert isinstance(out.bytes_original, int)
        assert isinstance(out.bytes_cleaned, int)
        assert isinstance(out.whitespace_removed, int)
        assert isinstance(out.lines_original, int)
        assert isinstance(out.lines_cleaned, int)

    def test_chatset_id_matches_input(
        self, populated_soma: Soma
    ) -> None:
        dendrite = ReceptorDendrite(populated_soma)
        out = dendrite.run("sess01:1")
        assert out.chatset_id == "sess01:1"

    def test_lines_cleaned_lte_lines_original(
        self, populated_soma: Soma
    ) -> None:
        dendrite = ReceptorDendrite(populated_soma)
        out = dendrite.run("sess01:1")
        assert out.lines_cleaned <= out.lines_original

    def test_lines_original_counts_all_lines(self, populated_soma: Soma) -> None:
        """Original lines count includes both user and assistant text."""
        raw_user = "Build a CLI tool.\n\n\n\n\nRun it now."
        raw_asst = "Here is the tool.\n\n\n\n\nDone.\n\n\n\n\nThanks."
        expected_lines = len((raw_user + raw_asst).splitlines())

        dendrite = ReceptorDendrite(populated_soma)
        out = dendrite.run("sess01:1")
        assert out.lines_original == expected_lines


# ---------------------------------------------------------------------------
# Tests: Deterministic stripping
# ---------------------------------------------------------------------------

class TestDeterministicStripping:
    """Running strip_raw twice produces the same result (idempotent)."""

    def test_idempotent(self, populated_soma: Soma) -> None:
        dendrite = ReceptorDendrite(populated_soma)
        out1 = dendrite.run("sess01:1")
        out2 = dendrite.run("sess01:1")
        assert out1.cleaned_text == out2.cleaned_text

    def test_no_randomness(self, populated_soma: Soma) -> None:
        dendrite = ReceptorDendrite(populated_soma)
        results = [dendrite.run("sess01:1").cleaned_text for _ in range(10)]
        assert len(set(results)) == 1


# ---------------------------------------------------------------------------
# Tests: Convenience method
# ---------------------------------------------------------------------------

class TestGetCompressionRatio:
    """The get_compression_ratio shortcut works correctly."""

    def test_returns_float(self, populated_soma: Soma) -> None:
        dendrite = ReceptorDendrite(populated_soma)
        ratio = dendrite.get_compression_ratio("sess01:1")
        assert isinstance(ratio, float)
        assert 0.0 <= ratio <= 1.0

    def test_matches_full_run(self, populated_soma: Soma) -> None:
        dendrite = ReceptorDendrite(populated_soma)
        ratio = dendrite.get_compression_ratio("sess01:1")
        full = dendrite.run("sess01:1")
        assert ratio == full.compression_ratio
