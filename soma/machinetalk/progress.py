"""Clean table-based progress output for Stage 1 ingestion.

While a stage runs → one live line, rewritten in place with a spinning
character and elapsed seconds, frozen with a single newline when it ends.
After each chatset finishes → print header → divider → table → divider.
After all chatsets → summary.

No interleaved logs, no live dashboard.
"""
from __future__ import annotations

import sys
import threading
import time


# ── Primitives ──────────────────────────────────────────────────────────

# ANSI styling for the dressed-up stage output. Always emitted so the
# launcher's terminal (which re-prints captured lines) still renders it.
_C_RESET = "\033[0m"
_C_BOLD = "\033[1m"
_C_DIM = "\033[2m"
_C_CYAN = "\033[36m"
_C_GREEN = "\033[32m"
_C_YELLOW = "\033[33m"

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


# ── Live stage line ─────────────────────────────────────────────────────
#
# Exactly one running stage owns the terminal line. The owner rewrites that
# line in place with a carriage return (spinner glyph + elapsed seconds) and
# freezes it with a single newline when the stage returns. Stage 1 runs on
# several worker threads, so extra spinners stay silent rather than fighting
# for the line, and ordinary output is queued until the line is free.

_SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
_SPINNER_TICK = 0.1
_FROZEN_GLYPH = "✓"

_io_lock = threading.RLock()
_active_line: "_LiveLine | None" = None
_deferred: list[tuple[tuple, dict]] = []


class _LiveLine:
    """One spinner line, owned by at most one stage at a time."""

    def __init__(self, label: str) -> None:
        self.label = label
        self._started = time.monotonic()
        self._stop = threading.Event()
        self._thread: "threading.Thread | None" = None
        self._owns = False
        self._width = 0

    def open(self) -> None:
        global _active_line
        with _io_lock:
            self._owns = _active_line is None
            if self._owns:
                _active_line = self
        if not self._owns:
            return
        self._thread = threading.Thread(
            target=self._spin, daemon=True, name="stage-spinner")
        self._thread.start()

    def _spin(self) -> None:
        frames = _SPINNER_FRAMES
        idx = 0
        while True:
            self._draw(frames[idx % len(frames)])
            idx += 1
            if self._stop.wait(_SPINNER_TICK):
                return

    def _elapsed(self) -> int:
        return int(time.monotonic() - self._started)

    def _draw(self, glyph: str) -> None:
        body = f"  {glyph} {self.label}... {self._elapsed()}s"
        padding = " " * max(0, self._width - len(body))
        self._width = len(body)
        with _io_lock:
            sys.stdout.write("\r" + body + padding)
            sys.stdout.flush()

    def close(self) -> None:
        global _active_line
        self._stop.set()
        if self._thread is not None:
            self._thread.join()
        if not self._owns:
            return
        # Freeze the final elapsed value on the same line, then end the line.
        self._draw(_FROZEN_GLYPH)
        with _io_lock:
            sys.stdout.write("\n")
            sys.stdout.flush()
            if _active_line is self:
                _active_line = None
        _flush_deferred()


def _flush_deferred() -> None:
    """Print output queued while a spinner owned the line."""
    while True:
        with _io_lock:
            if _active_line is not None or not _deferred:
                return
            args, kwargs = _deferred.pop(0)
            print(*args, **kwargs)


def emit(*args, **kwargs) -> None:
    """Print normally, or queue while a stage spinner owns the line."""
    with _io_lock:
        if _active_line is not None:
            _deferred.append((args, kwargs))
            return
        print(*args, **kwargs)


def spin(label: str, fn, *args, **kwargs):
    """Run ``fn`` behind a one-line spinner showing elapsed seconds."""
    line = _LiveLine(label)
    line.open()
    try:
        return fn(*args, **kwargs)
    finally:
        line.close()


# ── Distiller step display ──────────────────────────────────────────────
#
# The distiller's 11 processing steps (tb-001) all happen inside one LLM
# call, so there is no natural per-step signal to print. This shows each
# step on a ~30 s cadence (randomized durations) so the operator can see
# what the call is doing, then heartbeats until the call returns.

_DISTILLER_STEPS = [
    "hashing input",
    "extracting heredocs, metadata, constraints",
    "stripping noise: greetings, apologies, fillers, fences",
    "checking for duplicate hashes",
    "last user statement = current goal",
    "classifying signals into graph data",
    "matching intent across turns",
    "logging noise purges + stats",
    "computing overall signal quality",
    "verdict: pass | skip | quarantine",
    "writing canonical payload",
]


class DistillerProgress:
    """Dressed-up step-by-step display for one distiller call."""

    def __init__(self, target: float = 30.0) -> None:
        self._target = max(1.0, float(target))
        self._stop = threading.Event()
        self._steps_done = threading.Event()
        self._thread: "threading.Thread | None" = None
        self._started = 0.0

    def start(self) -> None:
        self._started = time.monotonic()
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="distiller-steps")
        self._thread.start()

    def _run(self) -> None:
        import random

        n = len(_DISTILLER_STEPS)
        weights = [random.uniform(0.45, 1.55) for _ in range(n)]
        scale = self._target / sum(weights)
        width = max(len(s) for s in _DISTILLER_STEPS) + 2

        for i, (step, w) in enumerate(zip(_DISTILLER_STEPS, weights), start=1):
            dur = w * scale
            if self._stop.wait(dur):
                return
            dots = "." * max(3, width - len(step))
            with _io_lock:
                print(
                    f"  {_C_GREEN}✓{_C_RESET} "
                    f"{_C_DIM}[{i:02d}/{n}]{_C_RESET} "
                    f"{_C_CYAN}{step}{_C_RESET} {_C_DIM}{dots} {dur:>4.1f}s{_C_RESET}",
                    flush=True,
                )

        self._steps_done.set()

        # Steps are exhausted but the model may still be running.
        while not self._stop.wait(5.0):
            elapsed = time.monotonic() - self._started
            with _io_lock:
                print(
                    f"  {_C_DIM}… awaiting model response ({elapsed:.0f}s){_C_RESET}",
                    flush=True,
                )

    def finish(self) -> None:
        """Let the dressed-up output run through all steps, then stop."""
        self._steps_done.wait()
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=6.0)


# ── Distiller result summary ────────────────────────────────────────────

def _fmt_bytes(n) -> str:
    try:
        n = int(n)
    except (TypeError, ValueError):
        return "—"
    if n >= 1024:
        return f"{n / 1024:.1f}KB"
    return f"{n}B"


def distiller_summary(soma_path, parsed) -> str:
    """Render the SOMA DB path plus a few distiller processing stats."""
    parsed = parsed or {}

    def _count(key: str) -> int:
        v = parsed.get(key)
        if isinstance(v, (list, tuple)):
            return len(v)
        return int(v) if isinstance(v, int) else 0

    sigq = parsed.get("signal_quality")
    ns = parsed.get("noise_signature") or {}
    noise_b = ns.get("total_bytes_noise", 0)
    signal_b = ns.get("total_bytes_signal", 0)
    intent = str(parsed.get("intent") or "").strip()
    verdict = "SKIP" if parsed.get("skip") else "PASS"

    parts = [f"  {_C_BOLD}SOMA DB{_C_RESET}  {soma_path}"]
    if intent:
        parts.append(f"  {_C_BOLD}intent{_C_RESET}   {intent[:100]}")
    if isinstance(sigq, (int, float)):
        parts.append(
            f"  {_C_BOLD}signal quality{_C_RESET}  {sigq:.2f}   "
            f"{_C_DIM}noise {_fmt_bytes(noise_b)} / signal {_fmt_bytes(signal_b)}{_C_RESET}"
        )
    skip_reason = str(parsed.get("skip_reason") or "").strip()
    if skip_reason:
        parts.append(f"  {_C_BOLD}skip reason{_C_RESET}  {skip_reason}")
    parts.append(
        f"  {_C_BOLD}directives{_C_RESET} {_count('directives')}   "
        f"{_C_BOLD}constraints{_C_RESET} {_count('constraints')}   "
        f"{_C_BOLD}preferences{_C_RESET} {_count('preferences')}   "
        f"{_C_BOLD}questions{_C_RESET} {_count('questions')}   "
        f"{_C_BOLD}verdict{_C_RESET} {_C_GREEN if verdict == 'PASS' else _C_YELLOW}{verdict}{_C_RESET}"
    )
    return "\n".join(parts)
