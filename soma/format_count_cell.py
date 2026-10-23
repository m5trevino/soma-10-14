"""TB-002: Comma count cell."""
from __future__ import annotations


def format_count_cell(n: int, width: int, trail: int = 5) -> str:
    """Format one non-negative integer into a fixed-width count cell.

    The number is formatted with a thousands separator and right-aligned
    in ``(width - trail)`` characters, followed by exactly *trail* spaces.

    Parameters
    ----------
    n : int
        Non-negative integer (0 ≤ n ≤ 99999).
    width : int
        Total cell width.
    trail : int
        Number of trailing spaces (default 5).

    Returns
    -------
    str
        Formatted cell string of exactly *width* characters.

    Raises
    ------
    ValueError
        If *n* is negative, greater than 99999, or *trail* is non-positive.
    """
    if trail < 1:
        raise ValueError(f"trail must be at least 1, got {trail}")

    if not isinstance(n, int) or isinstance(n, bool):
        raise ValueError(f"n must be an integer, got {type(n).__name__}")

    if n < 0:
        raise ValueError(f"n must be non-negative, got {n}")

    if n > 99999:
        raise ValueError(f"n must not exceed 99999, got {n}")

    number_str = f"{n:,}"
    align_width = width - trail
    if len(number_str) > align_width:
        raise ValueError(
            f"formatted number '{number_str}' ({len(number_str)} chars) "
            f"exceeds alignment width {align_width}"
        )

    return number_str.rjust(align_width) + " " * trail