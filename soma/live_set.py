"""TB-008: Live set line — Show the open set without redrawing closed sets.

Closed stages are appended as final lines.
Live stage is the carriage-return line.
No table while any stage is unfinished.
"""
from __future__ import annotations

import io

from write_status import write_status
from state_word import state_word


def write_live_set(
    index: int,
    total: int,
    done_outcomes: list[tuple[str, str]],
    live_name: str,
    beat_age_seconds: int,
    stream: io.TextIOBase,
) -> None:
    """Write the live set line and status.

    Parameters
    ----------
    index : int
        1-based set index.
    total : int
        Total number of sets.
    done_outcomes : list[tuple[str, str]]
        Pairs of (stage_name, outcome) for finished stages.
    live_name : str
        Name of the currently running stage.
    beat_age_seconds : int
        Seconds since last beat.
    stream : io.TextIOBase
        Output stream.
    """
    # Header depends on beat state
    sw = state_word(phase_open=True, beat_age_seconds=beat_age_seconds, finished_ok=False)

    if sw == "KILL":
        stream.write(f"CHAT SET {index}/{total}  KILL\n")
    else:
        stream.write(f"CHAT SET {index}/{total}  WORKING\n")

    # Closed stages: write final status lines (newline, not overwrite)
    for name, outcome in done_outcomes:
        write_status(name, outcome, stream)

    # Live stage: carriage-return line (no newline)
    write_status(live_name, None, stream)

    # Wait line: only if a later stage exists
    # Stages in order: DISTILLER, INTRO-BEAVER, PLAN-BEAVER, OUTRO-BEAVER
    STAGE_ORDER = ["DISTILLER", "INTRO-BEAVER", "PLAN-BEAVER", "OUTRO-BEAVER"]
    live_idx = STAGE_ORDER.index(live_name) if live_name in STAGE_ORDER else -1

    if sw == "WORKING" and live_idx < len(STAGE_ORDER) - 1:
        next_name = STAGE_ORDER[live_idx + 1]
        stream.write(f"\rNEXT   {next_name} waits. Do not kill.")
        stream.flush()
