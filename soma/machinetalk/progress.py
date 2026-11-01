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
    "STAGE",
    "CHARS IN",
    "CHARS OUT",
    "STATUS",
    "SIGNALS",
    "TASKS",
    "OUTCOME",
    "MODEL",
]

# Fixed column widths matching the user's spec exactly
_COL_WIDTHS = [15, 12, 12, 22, 10, 10, 10, 34]


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

def _chars_out(sd: dict) -> str:
    """Characters the stage produced.

    The store keeps the verbatim response for the distiller, so its output
    size is measurable. Beavers only keep a token count, and tokens are not
    characters, so the cell stays blank rather than showing a number that
    means something else.
    """
    raw = sd.get("raw_response")
    if isinstance(raw, str) and raw:
        return _fmt_number(len(raw))
    out = sd.get("chars_out")
    if isinstance(out, (int, float)) and out:
        return _fmt_number(int(out))
    return ""


def _status_cell(sd: dict | None) -> str:
    """One unambiguous status word, including why a stage did not run."""
    if sd is None:
        return "NOT RUN"
    status = (sd.get("status") or "PENDING").upper()
    if status == "SKIPPED":
        reason = (sd.get("skip_reason") or "").strip()
        return f"SKIP {reason}" if reason else "SKIP"
    if status in ("FAILED", "BLOCKED"):
        errs = sd.get("errors")
        if isinstance(errs, str) and errs.strip():
            return f"{status} {errs.strip()[:14]}"
        return status
    if status == "DONE":
        verdict = str(sd.get("verdict") or "").strip()
        if verdict.lower() in ("true", "1", "yes"):
            # The stage ran and decided there was nothing to keep.
            return "DONE (NO SIGNAL)"
        return "DONE"
    return status


def _stage_counts(sd: dict | None) -> tuple[str, str, str]:
    """Signal / task / outcome counts from the stored payload, if present."""
    if not sd:
        return "", "", ""
    parsed = sd.get("payload")
    if not isinstance(parsed, dict):
        raw = sd.get("raw_response")
        if isinstance(raw, str) and raw.strip().startswith("{"):
            try:
                import json as _json
                parsed = _json.loads(raw)
            except Exception:
                parsed = None
    if not isinstance(parsed, dict):
        return "", "", ""

    body = unwrap_payload(parsed)

    def _n(*keys: str) -> str:
        total = 0
        found = False
        for key in keys:
            val = body.get(key)
            if isinstance(val, list):
                total += len(val)
                found = True
        return str(total) if found else ""

    return (_n("directives", "preferences", "questions", "confirmations"),
            _n("tasks", "plan_items", "files"),
            _n("outcomes", "deliverables", "lessons"))


def _find_key(obj, key: str):
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        for v in obj.values():
            r = _find_key(v, key)
            if r is not None:
                return r
    elif isinstance(obj, list):
        for v in obj:
            r = _find_key(v, key)
            if r is not None:
                return r
    return None


def chatset_table(set_num: int, total: int, stages: dict,
                  gateway_map: dict | None = None) -> str:
    """Render the full table for one completed chatset.

    Every cell is either a measured character count or an explicit status.
    Tokens are deliberately absent: they vary by provider and do not describe
    how much text moved through the stage.

    ``stages``: dict keyed by stage name, values are checkpoint dicts
    (status, verdict, model, chars_in, raw_response, errors, ...).
    ``gateway_map``: optional model_id -> gateway lookup for _clean_model.
    """
    rows: list[list[str]] = []

    for sname in _STAGE_ORDER:
        sd = stages.get(sname)
        label = _STAGE_LABELS.get(sname, sname.upper())

        chars_in = ""
        if sd:
            ci = sd.get("chars_in")
            if isinstance(ci, (int, float)) and ci > 0:
                chars_in = _fmt_number(int(ci))

        signals, tasks, outcome = _stage_counts(sd)
        rows.append([
            label,
            chars_in,
            _chars_out(sd) if sd else "",
            _status_cell(sd),
            signals,
            tasks,
            outcome,
            _clean_model((sd or {}).get("model") or "", gateway_map),
        ])

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
    """Final per-session tally.

    ``done`` counts chatsets the distiller processed, ``skipped`` counts
    chatsets it judged signal-free, ``failed`` counts chatsets that errored.
    The three add up to ``total``.
    """
    accounted = done + failed + skipped
    lines = [
        "",
        "  ┌─ SESSION COMPLETE " + "─" * 34,
        f"  │  chatsets        {total}",
        f"  │  distilled       {done}",
        f"  │  skipped         {skipped}   (distiller found no signal)",
        f"  │  failed          {failed}",
        f"  │  accounted       {accounted}/{total}"
        + ("" if accounted == total else "   ← MISMATCH"),
        "  └" + "─" * 52,
        "",
    ]
    return "\n".join(lines)


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

        # Steps are exhausted but the model may still be running. Report once
        # at each 30 s mark, then every 60 s, so a long retry storm does not
        # bury the log in identical lines.
        last_reported = 0
        while not self._stop.wait(5.0):
            elapsed = time.monotonic() - self._started
            step = 30 if elapsed < 120 else 60
            if elapsed - last_reported < step:
                continue
            last_reported = elapsed
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


def unwrap_payload(parsed):
    """Return the distiller's own output object from a stored payload.

    The model returns ``{"_meta": {...}, "distiller_output": {...}}``. Every
    field of interest (skip, skip_reason, signal_quality, directives, ...)
    lives inside ``distiller_output``, so reading the envelope reports zeros.
    Payloads that are already flat pass through unchanged.
    """
    if not isinstance(parsed, dict):
        return {}
    inner = parsed.get("distiller_output")
    if isinstance(inner, dict):
        return inner
    return parsed


def _count_of(payload: dict, key: str) -> int:
    v = payload.get(key)
    if isinstance(v, (list, tuple)):
        return len(v)
    return int(v) if isinstance(v, int) else 0


def distiller_summary(soma_path, chars_in, parsed) -> str:
    """One block stating what the distiller actually decided.

    Every number here is either a character count taken from the source or a
    value read out of the model's own output object. Nothing is estimated.
    """
    payload = unwrap_payload(parsed)

    skip = bool(payload.get("skip"))
    skip_reason = str(payload.get("skip_reason") or "").strip()
    intent = str(payload.get("intent_anchor") or payload.get("intent") or "").strip()
    sigq = payload.get("signal_quality")

    counts = {k: _count_of(payload, k) for k in (
        "directives", "constraints", "preferences", "questions",
        "corrections", "confirmations", "artifacts")}

    if skip:
        decision = f"{_C_YELLOW}SKIPPED{_C_RESET}"
        if skip_reason:
            decision += f" {_C_DIM}({skip_reason}){_C_RESET}"
    else:
        decision = f"{_C_GREEN}PROCESSED{_C_RESET}"

    parts = [
        f"  {_C_BOLD}decision{_C_RESET}      {decision}",
    ]
    if isinstance(chars_in, int) and chars_in >= 0:
        parts.append(f"  {_C_BOLD}chars in{_C_RESET}     {chars_in:,}")
    if isinstance(sigq, (int, float)):
        parts.append(f"  {_C_BOLD}signal qual{_C_RESET}  {sigq:.2f}")
    if intent:
        parts.append(f"  {_C_BOLD}intent{_C_RESET}       {intent[:96]}")

    found = "  ".join(f"{k}={v}" for k, v in counts.items() if v)
    if found:
        parts.append(f"  {_C_BOLD}extracted{_C_RESET}    {found}")
    else:
        parts.append(f"  {_C_BOLD}extracted{_C_RESET}    {_C_DIM}nothing "
                     f"(all signal lists empty){_C_RESET}")

    parts.append(f"  {_C_BOLD}soma{_C_RESET}         {soma_path}")
    return "\n".join(parts)
