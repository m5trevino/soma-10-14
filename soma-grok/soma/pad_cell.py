"""TB-001: Exact-width cell padder."""
from __future__ import annotations


def pad_cell(text: str, width: int, align: str) -> str:
    """Return a string of exactly *width* characters.

    *align* is ``'left'`` or ``'right'``.

    Raises
    ------
    ValueError
        If text contains a tab or newline, if text is longer than width,
        or if *align* is not one of the recognised values.
    """
    if align not in ("left", "right"):
        raise ValueError(f"align must be 'left' or 'right', got {align!r}")

    if "\t" in text or "\n" in text:
        raise ValueError("text must not contain a tab or newline")

    if len(text) > width:
        raise ValueError(f"text length {len(text)} exceeds width {width}")

    if align == "left":
        return text.ljust(width)
    # right
    return text.rjust(width)