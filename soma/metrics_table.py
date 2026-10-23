"""TB-005: Four-row metrics table — UTF-8 box drawing.

Columns (7): blank, CHARACTERS IN, CHARACTERS OUT,
             SIGNALS-INTRO-BEAVER, TASKS-PLAN-BEAVER,
             OUTCOME-OUTRO-BEAVER, MODEL-USED

Column inner widths: 14, 15, 16, 22, 19, 22, 13
Total inner width: 121
Total line length: 123 (1 border + 121 content + 1 border)

Every line must be exactly the same length.
Only exactly four data rows accepted.
"""
from __future__ import annotations

from format_count_cell import format_count_cell

# ── Column definitions ────────────────────────────────────────────────

_HEADERS = [
    "",
    "CHARACTERS IN",
    "CHARACTERS OUT",
    "SIGNALS-INTRO-BEAVER",
    "TASKS-PLAN-BEAVER",
    "OUTCOME-OUTRO-BEAVER",
    "MODEL-USED",
]

_WIDTHS = [14, 15, 16, 22, 19, 22, 13]
_TOTAL_WIDTH = sum(_WIDTHS)  # 121

# Column boundary positions (character offset after each column)
_BOUNDARIES: list[int] = []
_pos = 0
for _w in _WIDTHS[:-1]:
    _pos += _w
    _BOUNDARIES.append(_pos)  # [14, 29, 45, 67, 86, 108]


def render_table(rows: list[dict]) -> str:
    """Render a 7-column box table for exactly four data rows.

    Parameters
    ----------
    rows : list[dict]
        Exactly 4 row dicts with keys:
        'chars_in' (int), 'chars_out' (int), 'signals' (int),
        'tasks' (int), 'outcomes' (int), 'model' (str).

    Returns
    -------
    str
        The complete table string (7 lines, no trailing newline).

    Raises
    ------
    ValueError
        If rows is not exactly 4, or any row is missing or malformed.
    """
    if not isinstance(rows, list):
        raise ValueError(f"rows must be a list, got {type(rows).__name__}")

    if len(rows) != 4:
        raise ValueError(f"render_table expects exactly 4 rows, got {len(rows)}")

    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"row {i} must be a dict, got {type(row).__name__}")
        for key in ("chars_in", "chars_out", "signals", "tasks", "outcomes", "model"):
            if key not in row:
                raise ValueError(f"row {i} missing key {key!r}")

    # ── helpers ──────────────────────────────────────────────────────

    def _left(line_type: str) -> str:
        return {"top": "┌", "line": "│", "sep": "├"}[line_type]

    def _right(line_type: str) -> str:
        return {"top": "┐", "line": "│", "sep": "┤"}[line_type]

    def _content_top() -> str:
        return "─" * _TOTAL_WIDTH

    def _content_sep() -> str:
        chars = ["─"] * _TOTAL_WIDTH
        for bp in _BOUNDARIES:
            chars[bp] = "┼"
        return "".join(chars)

    def _content_header() -> str:
        return "".join(h.ljust(w) for h, w in zip(_HEADERS, _WIDTHS))

    def _content_data(row: dict) -> str:
        parts: list[str] = [
            " " * _WIDTHS[0],
            format_count_cell(row["chars_in"], _WIDTHS[1]),
            format_count_cell(row["chars_out"], _WIDTHS[2]),
            str(row["signals"]).ljust(_WIDTHS[3]),
            str(row["tasks"]).ljust(_WIDTHS[4]),
            str(row["outcomes"]).ljust(_WIDTHS[5]),
            str(row["model"]).ljust(_WIDTHS[6]),
        ]
        return "".join(parts)

    # ── build 7 lines ────────────────────────────────────────────────

    lines = [
        _left("top") + _content_top() + _right("top"),
        _left("line") + _content_header() + _right("line"),
        _left("sep") + _content_sep() + _right("sep"),
        *[_left("line") + _content_data(r) + _right("line") for r in rows],
    ]

    # Verify all lines equal length
    lens = {len(l) for l in lines}
    if len(lens) != 1:
        raise RuntimeError(f"Unequal line lengths: {lens}")

    return "\n".join(lines)
