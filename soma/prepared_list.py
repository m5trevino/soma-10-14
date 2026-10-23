"""TB-009: Prepared-list driver — Walk a prepared list and append one block per item.

Stop on first KILL. Return NEXT if all closed, KILL if stopped.
"""
from __future__ import annotations

import io

from state_word import state_word
from closed_set import write_closed_set
from kill_block import write_kill_set


def run_sets(items: list[dict], stream: io.TextIOBase) -> str:
    """Walk a prepared list and append one block per item.

    Parameters
    ----------
    items : list[dict]
        Each dict has keys:
        - 'index' (int): 1-based set index
        - 'total' (int): total sets
        - 'outcomes' (list[str]): outcome for each of 4 stages
        - 'rows' (list[dict]): row data for the table
    stream : io.TextIOBase
        Output stream.

    Returns
    -------
    str
        'NEXT' if all items closed successfully, 'KILL' if stopped early.
    """
    STAGE_NAMES = ["DISTILLER", "INTRO-BEAVER", "PLAN-BEAVER", "OUTRO-BEAVER"]

    for item in items:
        idx = item["index"]
        total = item["total"]
        outcomes = item["outcomes"]

        # Check beat age on each item to decide
        # The beat_age is derived from the state of outcomes
        # If any outcome is FAIL, it's a kill situation
        # If all are SUCCESS, check beat (use 0 since this is pre-computed)
        beat_age = 0
        finished_outcomes: list[tuple[str, str]] = []
        failed_name = ""

        # Determine which stages finished and what state_word says
        # For pre-computed items, we know outcomes already
        all_success = all(o == "SUCCESS" for o in outcomes)
        first_fail_idx = None
        for i, o in enumerate(outcomes):
            if o != "SUCCESS":
                first_fail_idx = i
                break
            finished_outcomes.append((STAGE_NAMES[i], o))

        if first_fail_idx is not None:
            # Kill situation
            failed_name = STAGE_NAMES[first_fail_idx]
            # Add finished outcomes up to the failed stage
            finished_outcomes = [(STAGE_NAMES[i], outcomes[i]) for i in range(first_fail_idx)]
            # Write kill block
            write_kill_set(idx, total, finished_outcomes, failed_name, 90, stream)
            return "KILL"

        if not all_success:
            # Non-success outcome — treat as kill
            if first_fail_idx is None:
                # Shouldn't happen: not all_success implies a failure was found
                return "KILL"
            failed_name = STAGE_NAMES[first_fail_idx]
            finished_outcomes = [(STAGE_NAMES[i], outcomes[i]) for i in range(first_fail_idx)]
            write_kill_set(idx, total, finished_outcomes, failed_name, 90, stream)
            return "KILL"

        # All SUCCESS — write closed set
        write_closed_set(idx, total, outcomes, item["rows"], stream)

    return "NEXT"
