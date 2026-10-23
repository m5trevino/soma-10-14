"""TB-004: Beat state word — Turn age-of-last-beat into WORKING, NEXT, or KILL.

No printing. No sleeping. No knowledge of stage names.
"""
from __future__ import annotations


def state_word(phase_open: bool, beat_age_seconds: int, finished_ok: bool) -> str:
    """Turn age-of-last-beat into one of WORKING, NEXT, or KILL.

    Parameters
    ----------
    phase_open : bool
        ``True`` while the stage is still running.
    beat_age_seconds : int
        Seconds since last beat.
    finished_ok : bool
        ``True`` when the stage finished successfully.

    Returns
    -------
    str
        ``'WORKING'`` — stage is open and beat is fresh (< 90s).
        ``'NEXT'`` — stage finished successfully.
        ``'KILL'`` — stage finished badly OR beat aged past 90s while open.

    Raises
    ------
    ValueError
        If *finished_ok* is ``True`` and *phase_open* is ``True``
        (contradictory — but we treat finished_ok as the final truth).

    Notes
    -----
    * Beat threshold is exactly 90 seconds.
    * This function never sleeps or prints.
    * It does not know any stage names.
    """
    # finished_ok is the final truth — if the stage finished cleanly it's NEXT
    if finished_ok:
        return "NEXT"

    # Stage is not finished
    if not phase_open:
        # Finished but not ok
        return "KILL"

    # Phase is open, not finished — check beat age
    if beat_age_seconds >= 90:
        return "KILL"

    return "WORKING"


def format_elapsed(seconds: int) -> str:
    """Render an integer number of seconds as an MM:SS string.

    Parameters
    ----------
    seconds : int
        Non-negative integer number of seconds.

    Returns
    -------
    str
        Formatted string like ``'00:14'`` or ``'02:01'``.
    """
    minutes = seconds // 60
    secs = seconds % 60
    return f"{minutes:02d}:{secs:02d}"
