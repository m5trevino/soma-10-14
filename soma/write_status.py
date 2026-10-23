"""TB-003: Single stage status line."""
from __future__ import annotations


# ── golden suffix strings ──────────────────────────────────────────────
_SUCCESS = "-[SUCCESS]-"
_FAIL = "-[FAIL]-"
_DOT_COUNT = 7

# ── internal helpers (pure) ────────────────────────────────────────────


def _success_suffix(name: str) -> str:
    """'-[NAME]- Running. . . . . . . -[SUCCESS]-'"""
    return f"-[{name}]- Running" + ". " * _DOT_COUNT + _SUCCESS


def _fail_suffix(name: str) -> str:
    """'-[NAME]- Running. . . . . . . -[FAIL]-'"""
    return f"-[{name}]- Running" + ". " * _DOT_COUNT + _FAIL


# ── public API ─────────────────────────────────────────────────────────


def write_status(name: str, outcome: str | None, stream: object) -> None:
    """Write one stage status line to *stream*.

    Parameters
    ----------
    name : str
        Stage name, e.g. ``'DISTILLER'``.
    outcome : str | None
        ``None`` means the stage is still running.
        ``'SUCCESS'`` or ``'FAIL'`` writes the final line.
        Any other value raises.
    stream : object
        Any object with a ``write`` method (``sys.stdout`` is common).

    Raises
    ------
    ValueError
        If *outcome* is neither ``None``, ``'SUCCESS'``, nor ``'FAIL'``.

    Notes
    -----
    * When *outcome* is ``None`` the line is rewritten in-place via
      carriage-return (``\\r``) so no newline is emitted.
    * When *outcome* is ``'SUCCESS'`` or ``'FAIL'`` the final line is
      written once with a trailing newline.
    * A second call with an outcome **does not** rewrite the finished
      line — the caller must guard against this.
    * This function never clears the screen, never moves the cursor
      up, and never prints a table or ``STATE`` line.
    """
    if outcome is None:
        # Still running — overwrite in place via carriage return.
        # The full line ends with the name so the next write covers it.
        line = f"-[{name}]- Running" + ". " * _DOT_COUNT + " "
        stream.write("\r" + line)
        stream.flush()
        return

    if outcome not in ("SUCCESS", "FAIL"):
        raise ValueError(
            f"outcome must be None, 'SUCCESS', or 'FAIL', got {outcome!r}"
        )

    # Finished — write exactly once with a newline.
    if outcome == "SUCCESS":
        line = _success_suffix(name)
    else:
        line = _fail_suffix(name)

    stream.write(line + "\n")
    stream.flush()