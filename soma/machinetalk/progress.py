"""Clean table-based progress output for Stage 1 ingestion.

After each chatset finishes → print header → divider → table → divider.
After all chatsets → summary.

No spinners, no interleaved logs, no live dashboard.
"""
from __future__ import annotations


# ── Primitives ──────────────────────────────────────────────────────────

_DIVIDER = ("■□■□■□■□■□■□■□■■□■□■□■□■□■□■□■■□■□■□■□■□■□■□"
            "■■□■□■□■□■□■□■□■■□■□■□■□■□■□■□■■□■□■□■□■□■□■□"
            "■■□■□■□■□■□■□■□■■□■□■□■□■□■□■□■■□■□■□■□■□■□■□■")

_STAGE_LABELS = {
    "distiller": "DISTILLER",
    "introbeaver": "INTRO-BEAVER",
    "planbeaver": "PLAN-BEAVER",
    "outrobeaver": "OUTRO-BEAVER",
}

# Step aliases: what the user sees
_STEP_LABELS = {
    "distiller":    ("ALPHA", "Receptor",      "DISTILLER"),
    "introbeaver":  ("BRAVO", "Classifier",    "INTRO-BEAVER"),
    "planbeaver":   ("CHARLIE", "Integrator",  "PLAN-BEAVER"),
    "outrobeaver":  ("EDWARD", "Retrograde",   "OUTRO-BEAVER"),
}

_STAGE_ORDER = ["distiller", "introbeaver", "planbeaver", "outrobeaver"]

_COL_HEADERS = [
    "",
    "CHARACTERS IN",
    "CHARACTERS OUT",
    "SIGNALS-INTRO-BEAVER",
    "TASKS-PLAN-BEAVER",
    "OUTCOME-OUTRO-BEAVER",
    "MODEL-USED",
]

# Fixed column widths matching the user's spec exactly
_COL_WIDTHS = [15, 15, 16, 20, 19, 20, 40]


# ── Helpers ─────────────────────────────────────────────────────────────

def _clean_model(model: str, gateway_map: dict | None = None) -> str:
    """Format model display name using gateway map when available.

    With gateway map: look up gateway for model_id, format as ``model_name-gateway``.
    Without gateway map (or model missing): fall back to uppercased name.

    Examples (with map):
        ``inclusionai/ling-3.0-flash`` (novita) → ``ling-3.0-flash-novita``
        ``nvidia/nemotron-3.5:free`` (openrouter) → ``nemotron-3.5-openrouter``
        ``gpt-4o`` (openai) → ``gpt-4o-openai``

    Examples (without map / fallback):
        ``inclusionai/ling-3.0-flash`` → ``LING-3.0-FLASH (INCLUSIONAI)``
    """
    if not model:
        return ""
    if gateway_map and model in gateway_map:
        gw = gateway_map[model]
        # Strip provider prefix (everything before /)
        name = model.split("/", 1)[1] if "/" in model else model
        # Strip tag at :
        name = name.split(":", 1)[0]
        return f"{name}-{gw}"
    # Fallback — uppercase model name with provider/tag
    parts = model.split("/", 1)
    provider = parts[0].upper() if len(parts) > 1 else None
    model_part = parts[1] if len(parts) > 1 else parts[0]
    mp = model_part.split(":", 1)
    name = mp[0].strip()
    tag = mp[1].strip() if len(mp) > 1 else None
    suffix = tag.upper() if tag else (provider if provider else None)
    if suffix:
        return f"{name.upper()} ({suffix})"
    return name.upper()


def _cell(text: str, width: int, align: str = "left") -> str:
    """Format one cell within its column."""
    text = str(text) if text is not None else ""
    if align == "right":
        return f"{text:>{width}}"
    return f"{text:<{width}}"


def _fmt_number(n) -> str:
    """Format an integer with commas for display."""
    if n is None or n == "":
        return ""
    try:
        return f"{int(n):,}"
    except (ValueError, TypeError):
        return str(n)


def _top_line(widths: list[int]) -> str:
    """Top border: ╔══╦══╦═╗"""
    parts = []
    for i, w in enumerate(widths):
        sep = "╦" if i < len(widths) - 1 else "╗"
        parts.append("=" * w + sep)
    return "╔" + "".join(parts)


def _bottom_line(widths: list[int]) -> str:
    """Bottom border: ╚══╩══╩═╝"""
    parts = []
    for i, w in enumerate(widths):
        sep = "╩" if i < len(widths) - 1 else "╝"
        parts.append("=" * w + sep)
    return "╚" + "".join(parts)


def _hsep(widths: list[int]) -> str:
    """Header/body separator: ╠══╬══╬═╣"""
    parts = []
    for i, w in enumerate(widths):
        sep = "╬" if i < len(widths) - 1 else "╣"
        parts.append("=" * w + sep)
    return "╠" + "".join(parts)


def _row(cells: list[str], widths: list[int]) -> str:
    """One data row."""
    parts = []
    for i, (c, w) in enumerate(zip(cells, widths)):
        parts.append(_cell(c, w) + "║")
    return "║" + "".join(parts)


# ── Session Header ──────────────────────────────────────────────────────

def session_header(session_id: str, total_sets: int) -> str:
    """Session header block."""
    h_top = ("┏◚◚◚◚◚◚◚◚◚◚◚◚◚◚◚◚◚◚◚◚◚◚◚◚◚◚◚◚◚"
             "◚◚◚◚◚◚◚◚◚◚◚◚◚◚◚◚◚◚◚◚◚◚◚┓")
    h_bot = ("┗◛◛◛◛◛◛◛◛◛◛◛◛◛◛◛◛◛◛◛◛◛◛◛◛◛◛◛◛◛"
             "◛◛◛◛◛◛◛◛◛◛◛◛◛◛◛◛◛◛◛◛◛◛◛┛")
    lines = [
        h_top,
        session_id,
        h_bot,
        "",
        "                    ▛▝▝▝▝▝▝▝▝▝▝▝▝▝▝▝▝▝▝▝▝ ▜",
        f"                         {total_sets} CHAT SETS",
        "                    ▙ ▖▖▖▖▖▖▖▖▖▖▖▖▖▖▖▖▖▖▖▖▟",
        "",
    ]
    return "\n".join(lines)


# ── Chatset Table ───────────────────────────────────────────────────────

def chatset_table(set_num: int, total: int, stages: dict,
                  gateway_map: dict | None = None) -> str:
    """Render the full table for one completed chatset.

    ``stages``: dict keyed by stage name, values are checkpoint dicts:
      status, verdict, model, tokens, artifact, errors, etc.
    ``gateway_map``: optional model_id → gateway lookup map for _clean_model.
    """
    rows: list[list[str]] = []

    for sname in _STAGE_ORDER:
        sd = stages.get(sname)
        label = _STAGE_LABELS.get(sname, sname.upper())

        if sd is None:
            rows.append([label, "SKIPPED", "", "", "", "", ""])
            continue

        status = sd.get("status", "PENDING")
        model = sd.get("model") or ""
        verdict = sd.get("verdict") or ""
        chars_in = sd.get("chars_in")
        tokens = sd.get("tokens")

        if sname == "distiller":
            if status == "SKIPPED":
                col = [label, "SKIPPED", "", "", "", "", _clean_model(model, gateway_map)]
            else:
                col = [label, "", "", "", "", "", _clean_model(model, gateway_map)]
                if chars_in is not None and chars_in > 0:
                    col[1] = _fmt_number(chars_in)
        elif sname == "introbeaver":
            if status == "SKIPPED":
                col = [label, "", "", "SKIPPED", "", "", _clean_model(model, gateway_map)]
            elif status in ("FAILED", "BLOCKED"):
                col = [label, "", "", "FAILED", "", "", _clean_model(model, gateway_map)]
            else:
                col = [label, "", _fmt_number(tokens) if tokens else "",
                       verdict if verdict else "", "", "", _clean_model(model, gateway_map)]
        elif sname == "planbeaver":
            if status == "SKIPPED":
                col = [label, "", "", "", "SKIPPED", "", _clean_model(model, gateway_map)]
            elif status in ("FAILED", "BLOCKED"):
                col = [label, "", "", "", "FAILED", "", _clean_model(model, gateway_map)]
            else:
                col = [label, "", _fmt_number(tokens) if tokens else "",
                       "", verdict if verdict else "", "", _clean_model(model, gateway_map)]
        else:
            # outrobeaver
            if status == "SKIPPED":
                col = [label, "", "", "", "", "SKIPPED", _clean_model(model, gateway_map)]
            elif status in ("FAILED", "BLOCKED"):
                col = [label, "", "", "", "", "FAILED", _clean_model(model, gateway_map)]
            else:
                col = [label, "", _fmt_number(tokens) if tokens else "",
                       "", "", verdict if verdict else "PARTIAL", _clean_model(model, gateway_map)]

        rows.append(col)

    # Build lines using fixed column widths
    lines: list[str] = []

    marker_text = f"CHAT SET {set_num}/{total}"
    marker_side = "█" * 7
    lines.append(f"\n{marker_side}   {marker_text}   {marker_side}")
    lines.append("")

    lines.append(_top_line(_COL_WIDTHS))
    lines.append(_row(_COL_HEADERS, _COL_WIDTHS))
    lines.append(_hsep(_COL_WIDTHS))
    for r in rows:
        lines.append(_row(r, _COL_WIDTHS))
    lines.append(_row([""] * len(_COL_HEADERS), _COL_WIDTHS))
    lines.append(_bottom_line(_COL_WIDTHS))
    lines.append("")

    return "\n".join(lines)


# ── Summary ─────────────────────────────────────────────────────────────

def session_summary(done: int, failed: int, skipped: int, total: int) -> str:
    """Final summary block."""
    top = "╔══════════•⊱✦⊰•══════════╗"
    bot = "╚══════════•⊱✦⊰•══════════╝"
    line = f"   DONE: {done}  FAILED: {failed}  SKIPPED: {skipped}  TOTAL: {total}"
    return f"\n{top}\n{line}\n{bot}\n"
