"""TB-010: Ingest close summary — Append close summary after prepared list.

Then wait. Does not start another phase.
"""
from __future__ import annotations

import io

from format_count_cell import format_count_cell


def write_ingest_close(stats: dict, stream: io.TextIOBase) -> None:
    """Append the ingest close summary.

    Parameters
    ----------
    stats : dict
        Counts: done, total, fail, chars_in, chars_out,
        signals, tasks, outcomes.
    stream : io.TextIOBase
        Output stream.
    """
    done = stats["done"]
    total = stats["total"]
    fail = stats["fail"]
    chars_in = stats["chars_in"]
    chars_out = stats["chars_out"]
    signals = stats["signals"]
    tasks = stats["tasks"]
    outcomes = stats["outcomes"]

    # Line 1
    stream.write(f"INGEST  NEXT  {done}/{total} closed\n")

    # Line 2
    stream.write(f"sets {done}   fail {fail}\n")

    # Line 3
    stream.write(
        f"chars in {format_count_cell(chars_in, 15)}"
        f"   chars out {format_count_cell(chars_out, 16)}\n"
    )

    # Line 4
    stream.write(f"signals {signals}   tasks {tasks}   outcomes {outcomes}\n")

    # Line 5 — state depends on fail count
    if fail > 0:
        stream.write("STATE  KILL  phase=INGEST failed. Waiting.\n")
    else:
        stream.write("STATE  NEXT  phase=INGEST done. Waiting.\n")
