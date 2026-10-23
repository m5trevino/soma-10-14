"""TB-007: Kill block — Append a dead-set block and stop.

No table. No further set header.
"""
from __future__ import annotations

import io

from write_status import write_status
from state_word import format_elapsed


def write_kill_set(
    index: int,
    total: int,
    finished_outcomes: list[tuple[str, str]],
    failed_name: str,
    beat_age_seconds: int,
    stream: io.TextIOBase,
) -> None:
    """Append a dead-set block and stop. No table.

    Parameters
    ----------
    index : int
        1-based set index.
    total : int
        Total number of sets.
    finished_outcomes : list[tuple[str, str]]
        Pairs of (stage_name, outcome) for stages that finished
        before the kill. Outcome is 'SUCCESS' or 'FAIL'.
    failed_name : str
        Name of the stage that caused the kill.
    beat_age_seconds : int
        How many seconds ago the last beat was received.
    stream : io.TextIOBase
        Output stream (e.g. sys.stdout).
    """
    # Line 1: kill header
    stream.write(f"CHAT SET {index}/{total}  KILL\n")

    # Lines 2-N: finished stages with their outcomes
    for name, outcome in finished_outcomes:
        write_status(name, outcome, stream)

    # Line N+1: reason
    stream.write(
        f"REASON no beat for {format_elapsed(beat_age_seconds)}. "
        f"Kill it. Later sets did not start.\n"
    )
