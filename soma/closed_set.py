"""TB-006: Closed set block — Append one finished set block.

Table appears only when all four outcomes are SUCCESS.
"""
from __future__ import annotations

import io

from pad_cell import pad_cell
from format_count_cell import format_count_cell
from write_status import write_status
from metrics_table import render_table
from state_word import state_word


def write_closed_set(
    index: int,
    total: int,
    outcomes: list[str],
    rows: list[dict],
    stream: io.TextIOBase,
) -> None:
    """Append one finished set block.

    Parameters
    ----------
    index : int
        1-based set index.
    total : int
        Total number of sets.
    outcomes : list[str]
        Four outcome strings — 'SUCCESS' or 'FAIL'.
    rows : list[dict]
        Four row dicts with keys: chars_in, chars_out, signals,
        tasks, outcomes, model.
    stream : io.TextIOBase
        Output stream (e.g. sys.stdout).
    """
    # Line 1: set header
    header = (
        f"CHAT SET {pad_cell(str(index), 3, 'right')} "
        f"/ {pad_cell(str(total), 3, 'right')}  "
        "NEXT"
    )
    stream.write(header + "\n")

    # Lines 2-5: final status lines in stage order
    # Stages: DISTILLER, INTRO-BEAVER, PLAN-BEAVER, OUTRO-BEAVER
    stage_names = ["DISTILLER", "INTRO-BEAVER", "PLAN-BEAVER", "OUTRO-BEAVER"]
    for name, outcome in zip(stage_names, outcomes):
        write_status(name, outcome, stream)

    # Lines 6: table only when all SUCCESS
    if all(o == "SUCCESS" for o in outcomes):
        table = render_table(rows)
        stream.write(table + "\n")

    # Line N: summary line
    chars_in = sum(r["chars_in"] for r in rows)
    chars_out = sum(r["chars_out"] for r in rows)
    signals = sum(r["signals"] for r in rows)
    tasks = sum(r["tasks"] for r in rows)
    outcomes_count = sum(r["outcomes"] for r in rows)
    model = rows[-1]["model"]

    summary = (
        f"chars {format_count_cell(chars_in, 15)}"
        f"-> {format_count_cell(chars_out, 15)}"
        f"   signals {signals}   tasks {tasks}   outcomes {outcomes_count}   model {model}"
    )
    stream.write(summary + "\n")
