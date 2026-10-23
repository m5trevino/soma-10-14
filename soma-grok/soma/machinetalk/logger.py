"""Stage logger: writes per-stage logs to CWD + output dir with clear labels.

Every stage start/work/complete/failure is logged to:
  - stdout (CLI notification)
  - CWD/<timestamp>_pipeline.log (master chronological log)
  - CWD/<stage>.log (per-stage append log)
  - <out>/logs/<stage>/<session>.log (per-session per-stage detail)

This ensures operators can watch live progress AND review historical
logs from any run, without hunting through subdirectories.
"""
from __future__ import annotations

import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

LOG_LOCK = threading.Lock()


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _label(status: str) -> str:
    labels = {
        "START": "[▶ START]",
        "WORK":  "[⟳ WORK] ",
        "DONE":  "[✓ DONE] ",
        "FAIL":  "[✗ FAIL] ",
        "BLOCK": "[⊘ BLOCK]",
        "SKIP":  "[≋ SKIP] ",
        "REDO":  "[↺ REDO] ",
        "INFO":  "[ℹ INFO] ",
    }
    return labels.get(status, f"[{status:7}]")


def _format_line(stage: str, status: str, msg: str) -> str:
    return f"{_ts()}  {_label(status)}  [{stage.upper():12}]  {msg}"


def _write_to(path: Path, line: str) -> None:
    with LOG_LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
            f.flush()


class StageLogger:
    """Thread-safe logger: console + cwd master log + per-stage logs."""

    def __init__(self, *, cwd: Path | None = None, out_dir: Path | None = None,
                 quiet: bool = False) -> None:
        self.cwd = Path(cwd or Path.cwd()).resolve()
        self.out_dir = Path(out_dir or self.cwd / "pipeline_out").resolve()
        self.quiet = quiet
        self._master_log = self.cwd / f"{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_pipeline.log"

    # -- public API --------------------------------------------------------

    def start(self, stage: str, *, session: str, chatset: int | None = None,
              model: str = "", detail: str = "") -> None:
        msg = f"session={session}"
        if chatset is not None:
            msg += f" chatset={chatset}"
        if model:
            msg += f" model={model}"
        if detail:
            msg += f" | {detail}"
        self._emit(stage, "START", msg)

    def work(self, stage: str, *, session: str, chatset: int | None = None,
             detail: str = "") -> None:
        msg = f"session={session}"
        if chatset is not None:
            msg += f" chatset={chatset}"
        if detail:
            msg += f" | {detail}"
        self._emit(stage, "WORK", msg)

    def done(self, stage: str, *, session: str, chatset: int | None = None,
             detail: str = "") -> None:
        msg = f"session={session}"
        if chatset is not None:
            msg += f" chatset={chatset}"
        if detail:
            msg += f" | {detail}"
        self._emit(stage, "DONE", msg)

    def fail(self, stage: str, *, session: str, chatset: int | None = None,
             detail: str = "") -> None:
        msg = f"session={session}"
        if chatset is not None:
            msg += f" chatset={chatset}"
        if detail:
            msg += f" | {detail}"
        self._emit(stage, "FAIL", msg)

    def block(self, stage: str, *, session: str, chatset: int | None = None,
              detail: str = "") -> None:
        msg = f"session={session}"
        if chatset is not None:
            msg += f" chatset={chatset}"
        if detail:
            msg += f" | {detail}"
        self._emit(stage, "BLOCK", msg)

    def skip(self, stage: str, *, session: str, chatset: int | None = None,
             detail: str = "") -> None:
        msg = f"session={session}"
        if chatset is not None:
            msg += f" chatset={chatset}"
        if detail:
            msg += f" | {detail}"
        self._emit(stage, "SKIP", msg)

    def redo(self, stage: str, *, session: str, detail: str = "") -> None:
        msg = f"session={session}"
        if detail:
            msg += f" | {detail}"
        self._emit(stage, "REDO", msg)

    def info(self, stage: str, msg: str) -> None:
        self._emit(stage, "INFO", msg)

    def banner(self, text: str) -> None:
        line = f"\n{'=' * 60}\n  {text}\n{'=' * 60}"
        if not self.quiet:
            print(line)
        _write_to(self._master_log, line)

    # -- internal ----------------------------------------------------------

    def _emit(self, stage: str, status: str, msg: str, session_id: str = "") -> None:
        line = _format_line(stage, status, msg)
        # Suppress console for Stage 1 — clean tables only
        stage1_stages = {"distiller", "introbeaver", "planbeaver", "outrobeaver"}
        should_print = not self.quiet and stage not in stage1_stages
        if should_print:
            print(line)
        _write_to(self._master_log, line)
        # Per-stage log in CWD
        stage_log = self.cwd / f"{stage.lower()}.log"
        _write_to(stage_log, line)
        # Per-session per-stage log in out_dir
        sid = session_id or (msg.split("session=")[1].split(" ")[0] if "session=" in msg else "unknown")
        session_log = self.out_dir / "logs" / stage.lower() / f"{sid}.log"
        _write_to(session_log, line)
