"""Unit tests for TB-004 — Beat state word."""
import pytest
from state_word import state_word, format_elapsed


class TestStateWord:
    """Beat state word tests."""

    # ── WORKING path ────────────────────────────────────────────────

    def test_open_beat_age_2_returns_working(self):
        assert state_word(phase_open=True, beat_age_seconds=2, finished_ok=False) == "WORKING"

    def test_open_beat_age_89_returns_working(self):
        """Upper boundary of WORKING zone."""
        assert state_word(phase_open=True, beat_age_seconds=89, finished_ok=False) == "WORKING"

    def test_open_beat_age_0_returns_working(self):
        """Zero age is fresh."""
        assert state_word(phase_open=True, beat_age_seconds=0, finished_ok=False) == "WORKING"

    # ── KILL path (open + beat expired) ─────────────────────────────

    def test_open_beat_age_90_returns_kill(self):
        """Lower boundary of KILL zone — open + exactly 90."""
        assert state_word(phase_open=True, beat_age_seconds=90, finished_ok=False) == "KILL"

    def test_open_beat_age_120_returns_kill(self):
        assert state_word(phase_open=True, beat_age_seconds=120, finished_ok=False) == "KILL"

    def test_open_beat_age_91_returns_kill(self):
        assert state_word(phase_open=True, beat_age_seconds=91, finished_ok=False) == "KILL"

    # ── KILL path (finished not ok) ─────────────────────────────────

    def test_finished_not_ok_returns_kill(self):
        assert state_word(phase_open=False, beat_age_seconds=0, finished_ok=False) == "KILL"

    def test_finished_not_ok_age_50_returns_kill(self):
        assert state_word(phase_open=False, beat_age_seconds=50, finished_ok=False) == "KILL"

    # ── NEXT path (finished ok) ─────────────────────────────────────

    def test_finished_ok_returns_next(self):
        assert state_word(phase_open=False, beat_age_seconds=0, finished_ok=True) == "NEXT"

    def test_finished_ok_open_returns_next(self):
        """finished_ok=truth overrides phase_open."""
        assert state_word(phase_open=True, beat_age_seconds=0, finished_ok=True) == "NEXT"

    def test_finished_ok_large_age_returns_next(self):
        assert state_word(phase_open=True, beat_age_seconds=3600, finished_ok=True) == "NEXT"

    # ── format_elapsed ──────────────────────────────────────────────

    def test_14_seconds(self):
        assert format_elapsed(14) == "00:14"

    def test_121_seconds(self):
        assert format_elapsed(121) == "02:01"

    def test_zero_seconds(self):
        assert format_elapsed(0) == "00:00"

    def test_60_seconds(self):
        assert format_elapsed(60) == "01:00"

    def test_3599_seconds(self):
        assert format_elapsed(3599) == "59:59"

    def test_3600_seconds(self):
        assert format_elapsed(3600) == "60:00"

    def test_60000_seconds(self):
        assert format_elapsed(60000) == "1000:00"
