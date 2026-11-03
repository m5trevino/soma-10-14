#!/usr/bin/env python3
"""Pull PEA session files from the engine into a local, ordered archive.

Every model call writes one PEA file on the engine containing the verbatim
request and response. This pulls them down and renames each one so a plain
`ls` puts them in the order they happened, with the stage and outcome visible
in the name.

Local layout:

    ~/pea-sessions/<session>/<YYYYMMDD-HHMMSS>-<NN>-<stage>-<OK|FAIL>.txt

The sequence number is the file's chronological position inside that session,
so ordering survives two calls landing in the same second.

The stage comes from the PEA body itself ("MACHINE TALK — TB-001: DISTILLER"),
not from the engine's metadata, so it works for files written before stage
labelling existed.

Usage:
    python3 tools/pea_sync.py                 # sync everything, once
    python3 tools/pea_sync.py --watch         # keep syncing
    python3 tools/pea_sync.py --session NAME  # one session only
    python3 tools/pea_sync.py --dest DIR
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import datetime as _datetime
import time
from pathlib import Path

REMOTE = "engine"
REMOTE_ROOT = "/root/hetzner/ai-engine/pea_sessions"
DEFAULT_DEST = Path.home() / "pea-sessions"

# "=== MACHINE TALK — TB-001: DISTILLER ===" appears in the system prompt of
# the raw request body, so every PEA file carries its own stage label.
_STAGE_RE = re.compile(r"TB-\d{3}:\s*([A-Z][A-Z\-]+)")
_STATUS_RE = re.compile(r"^STATUS:\s+(\w+)", re.MULTILINE)
_TIMESTAMP_RE = re.compile(r"^TIMESTAMP:\s+(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})",
                           re.MULTILINE)


def _rsync(remote_sub: str, local: Path) -> bool:
    """Copy one remote path down. Returns False when the source is missing."""
    local.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        ["rsync", "-a", "--ignore-existing",
         "-e", "ssh -o BatchMode=yes -o ConnectTimeout=10",
         f"{REMOTE}:{REMOTE_ROOT}/{remote_sub}", str(local) + "/"],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        return True
    if "No such file" in (result.stderr or ""):
        return False
    print(f"  rsync failed: {result.stderr.strip()[:200]}", file=sys.stderr)
    return False


def _list_sessions() -> list[str]:
    out = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
         REMOTE, f"ls -1 {REMOTE_ROOT}"],
        capture_output=True, text=True,
    )
    if out.returncode != 0:
        return []
    return [line.strip() for line in out.stdout.splitlines() if line.strip()]


def _stage_of(text: str) -> str:
    m = _STAGE_RE.search(text)
    if not m:
        return "unknown"
    label = m.group(1).strip().lower().replace("-", "")
    return {
        "distiller": "distiller",
        "introbeaver": "introbeaver",
        "planbeaver": "planbeaver",
        "outrobeaver": "outrobeaver",
        "nexus": "nexus",
        "spark": "spark",
        "falcon": "falcon",
        "eagle": "eagle",
        "drafter": "drafter",
        "scout": "scout",
        "oc": "oc",
        "olc": "olc",
    }.get(label, label)


def _stamp_and_status(text: str, fallback: Path) -> tuple[str, str]:
    ts = _TIMESTAMP_RE.search(text)
    stamp = ts.group(1).replace("-", "").replace(":", "").replace(" ", "-") if ts else ""
    if not stamp:
        stamp = fallback.stem.split("-")[0] if "-" in fallback.stem else "00000000-000000"
    status = "OK"
    st = _STATUS_RE.search(text)
    if st:
        status = "OK" if st.group(1).upper() == "SUCCESS" else "FAIL"
    return stamp, status


def organise(session: str, dest: Path) -> int:
    """Rename one session directory's files into chronological order."""
    return organise_dir(dest / session)


def organise_dir(raw: Path) -> int:
    """Rename a directory's PEA files into chronological order."""
    if not raw.is_dir():
        return 0

    # Order by the timestamp recorded inside the file, not by mtime: rsync
    # preserves mtime, but the content timestamp is what the run actually
    # happened at, and the two disagree after a copy.
    entries: list[tuple[str, Path, str, str]] = []
    for path in raw.iterdir():
        if not path.is_file() or path.suffix != ".txt":
            continue
        try:
            text = path.read_text(errors="ignore")
        except OSError:
            continue
        stage = _stage_of(text)
        stamp, status = _stamp_and_status(text, path)
        entries.append((stamp, path, stage, status))

    entries.sort(key=lambda e: (e[0], e[1].name))

    renamed = 0
    for seq, (stamp, path, stage, status) in enumerate(entries, start=1):
        target = raw / f"{stamp}-{seq:02d}-{stage}-{status}.txt"
        if target == path:
            continue
        # Two files must never share a name. The sequence number makes this
        # unique within a run, but a re-sync can meet a name that already
        # exists, and silently skipping that file would leave it under its
        # raw remote name. Advance the sequence instead.
        n = seq
        while target.exists() and target != path:
            n += 1
            target = raw / f"{stamp}-{n:03d}-{stage}-{status}.txt"
        path.rename(target)
        renamed += 1
    return renamed


def _split_run(name: str) -> tuple[str, str]:
    """Split an engine PEA directory name into (run_id, session).

    A newer engine names a run "<YYYYMMDD-HHMMSS>--<session>". An older one
    names only the session, so the run has to be recovered per file from the
    timestamp inside it. Directories without a separator are returned with an
    empty run id and filed by `_run_of_file`.
    """
    if "--" in name:
        run_id, _, session = name.partition("--")
        return run_id, session
    return "", name


# Two files this far apart cannot belong to the same pipeline run. A run is a
# single invocation over a queue; ten minutes of silence inside one means the
# operator started another.
RUN_GAP = 600.0


def _file_epoch(path: Path) -> float | None:
    """Epoch seconds for a PEA file, from its content stamp or its mtime."""
    try:
        text = path.read_text(errors="ignore")
    except OSError:
        return None
    stamp, _ = _stamp_and_status(text, path)
    try:
        return _datetime.datetime.strptime(stamp, "%Y%m%d-%H%M%S").timestamp()
    except (ValueError, TypeError):
        pass
    try:
        return path.stat().st_mtime
    except OSError:
        return None


def group_runs(paths: list[Path]) -> list[list[Path]]:
    """Split one session's files into pipeline runs by time gaps.

    The engine files by chat-log session, so a session directory holds every
    run that ever touched that log. Recovering runs from the files
    themselves is the only option when the remote naming is old.
    """
    stamped = [(t, p) for p in paths for t in [_file_epoch(p)] if t is not None]
    stamped.sort(key=lambda x: (x[0], x[1].name))
    runs: list[list[Path]] = []
    cur: list[Path] = []
    prev: float | None = None
    for t, path in stamped:
        if prev is not None and t - prev > RUN_GAP and cur:
            runs.append(cur)
            cur = []
        cur.append(path)
        prev = t
    if cur:
        runs.append(cur)
    return runs


def sync_once(dest: Path, only: str | None = None) -> None:
    sessions = [only] if only else _list_sessions()
    if not sessions:
        print("  no sessions found on the engine", file=sys.stderr)
        return

    for session in sessions:
        run_id, chat_session = _split_run(session)
        # Group by run first, then by chat session inside the run. A run
        # directory answers "what did this pipeline run do"; a session
        # directory alone answers nothing, because every run wrote into it.
        if run_id:
            # Newer engine: the remote directory name already identifies one
            # run. File it flat, "<run>--<session>", so every run directory
            # sits at the same level whether it was named by the engine or
            # reconstructed from timestamps.
            target = dest / f"{run_id}--{chat_session}"
            before = set(p.name for p in target.glob("*.txt")) if target.is_dir() else set()
            if not _rsync(f"{session}/", target):
                continue
            after = set(p.name for p in target.glob("*.txt"))
            new = len(after - before)
            moved = organise_dir(target)
            label = f"{run_id}/{chat_session}"
            if new or moved:
                print(f"  {label}: {new} new, {moved} renamed")
            continue

        # Older engine: the remote directory holds every run of this session.
        # Stage into a holding area, then split by time gap into run dirs.
        #
        # The holding area is emptied every pass, so "new" cannot be measured
        # from it. Filed files are also renamed into chronological order, so
        # their names no longer match the remote ones. Each run directory
        # therefore records the remote names it consumed in .sources, and a
        # pass counts only files whose remote name appears in none of them.
        # Without that index every pass re-pulls and re-files the whole
        # session forever.
        holding = dest / ".incoming" / chat_session
        if not _rsync(f"{session}/", holding):
            continue

        already: set[str] = set()
        for d in dest.iterdir():
            if not d.is_dir() or not d.name.endswith(f"--{chat_session}"):
                continue
            idx = d / ".sources"
            if idx.is_file():
                already.update(idx.read_text().split())
        incoming = sorted(holding.glob("*.txt"))
        fresh = [p for p in incoming if p.name not in already]
        new = len(fresh)

        runs = group_runs(incoming)
        filed = 0
        for run in runs:
            first = min(_file_epoch(p) or 0.0 for p in run)
            tag = _datetime.datetime.fromtimestamp(first).strftime("%Y%m%d-%H%M%S")
            run_dir = dest / f"{tag}--{chat_session}"
            run_dir.mkdir(parents=True, exist_ok=True)
            # Record the remote names this run consumed before renaming them.
            idx = run_dir / ".sources"
            seen = set(idx.read_text().split()) if idx.is_file() else set()
            seen.update(p.name for p in run)
            idx.write_text("\n".join(sorted(seen)) + "\n")
            for f in run:
                run_dir.joinpath(f.name).unlink(missing_ok=True)
                f.rename(run_dir / f.name)
            organise_dir(run_dir)
            filed += len(run)
        try:
            holding.rmdir()
        except OSError:
            pass
        if new or filed:
            print(f"  {chat_session}: {new} new, {len(runs)} run(s), "
                  f"{filed} filed")


def _colour_enabled() -> bool:
    """Colour only on a terminal, and only when NO_COLOR is unset."""
    import os
    if os.environ.get("NO_COLOR") is not None:
        return False
    return sys.stdout.isatty()


class _C:
    """ANSI codes, blanked when colour is off so widths stay correct."""
    RESET = BOLD = DIM = DIR = FILE = GREEN = RED = ""
    if _colour_enabled():
        RESET = "\033[0m"
        BOLD = "\033[1m"
        DIM = "\033[2m"
        DIR = "\033[1;36m"     # bold cyan: run directories
        FILE = ""              # plain: log files
        GREEN = "\033[32m"
        RED = "\033[31m"


def _online(timeout: int = 8) -> tuple[bool, str]:
    """Whether the engine host answers SSH right now."""
    try:
        r = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", f"ConnectTimeout={timeout}",
             REMOTE, "true"],
            capture_output=True, text=True, timeout=timeout + 4)
        if r.returncode == 0:
            return True, "online"
        err = (r.stderr or "").strip().splitlines()
        last = err[-1] if err else "unreachable"
        return False, (last.rsplit(": ", 1)[-1] or last)[:48]
    except subprocess.TimeoutExpired:
        return False, "timeout"
    except Exception as exc:
        return False, type(exc).__name__


def _human_age(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.0f}s ago"
    if seconds < 3600:
        return f"{seconds / 60:.0f}m ago"
    if seconds < 86400:
        return f"{seconds / 3600:.1f}h ago"
    return f"{seconds / 86400:.1f}d ago"


def status_report(dest: Path, limit: int | None = None,
                  check_online: bool = True) -> None:
    """Newest-first view of what is on disk and whether the engine is up.

    Directories are bold and coloured, the files inside them are plain, so
    the eye lands on run boundaries first and detail second.
    """
    runs = sorted((d for d in dest.iterdir()
                   if d.is_dir() and d.name != ".incoming"),
                  key=lambda d: d.name, reverse=True)
    if not runs:
        print(f"  {_C.DIM}no runs in {dest}{_C.RESET}")
        return

    # How many rows fit: one for the header, one per dir, one per file.
    if limit is None:
        try:
            limit = max(10, shutil.get_terminal_size().lines - 6)
        except OSError:
            limit = 40

    newest = max((p.stat().st_mtime for d in runs for p in d.glob("*.txt")),
                 default=None)

    if check_online:
        up, why = _online()
        state = (f"{_C.GREEN}● online{_C.RESET}" if up
                 else f"{_C.RED}● offline{_C.RESET} {_C.DIM}({why}){_C.RESET}")
    else:
        state = f"{_C.DIM}● unchecked{_C.RESET}"

    total = sum(1 for d in runs for _ in d.glob("*.txt"))
    print()
    print(f"  {_C.BOLD}PEA archive{_C.RESET}  {dest}")
    print(f"  engine  {REMOTE}:{REMOTE_ROOT}  {state}")
    print(f"  {len(runs)} runs · {total} files"
          + (f" · last sync {_human_age(time.time() - newest)}"
             if newest else ""))
    print(f"  {_C.DIM}{'─' * 72}{_C.RESET}")

    rows = 0
    for d in runs:
        if rows >= limit:
            print(f"  {_C.DIM}… {len(runs) - runs.index(d)} more run(s){_C.RESET}")
            break
        files = sorted(d.glob("*.txt"), key=lambda p: p.name, reverse=True)
        # Newest activity in this run, for runs that are still filling.
        age = ""
        if files:
            newest_here = max(p.stat().st_mtime for p in files)
            age = f"  {_C.DIM}{_human_age(time.time() - newest_here)}{_C.RESET}"
        print(f"  {_C.DIR}{d.name}/{_C.RESET}"
              f"  {_C.DIM}{len(files)} file(s){_C.RESET}{age}")
        rows += 1
        shown = 0
        for f in files:
            if rows >= limit:
                print(f"    {_C.DIM}… {len(files) - shown} more file(s){_C.RESET}")
                rows += 1
                break
            ok = f.name.endswith("-OK.txt")
            mark = (f"{_C.GREEN}OK{_C.RESET}" if ok
                    else f"{_C.RED}FAIL{_C.RESET}")
            print(f"    {_C.FILE}{f.name}{_C.RESET}  {mark}")
            rows += 1
            shown += 1
    print()


def main() -> int:
    ap = argparse.ArgumentParser(description="Pull PEA files into a local archive")
    ap.add_argument("--dest", default=str(DEFAULT_DEST))
    ap.add_argument("--session", default=None)
    ap.add_argument("--watch", action="store_true",
                    help="keep syncing in a loop")
    ap.add_argument("--interval", type=int, default=30)
    ap.add_argument("--status", action="store_true",
                    help="show what is on disk, newest first, and exit")
    ap.add_argument("--last", type=int, default=None,
                    help="with --status: how many rows to show")
    args = ap.parse_args()

    dest = Path(args.dest).expanduser()
    dest.mkdir(parents=True, exist_ok=True)

    if args.status:
        status_report(dest, limit=args.last)
        return 0

    if args.watch:
        print(f"watching {REMOTE}:{REMOTE_ROOT} -> {dest} every {args.interval}s")
        try:
            while True:
                sync_once(dest, args.session)
                time.sleep(args.interval)
        except KeyboardInterrupt:
            print("\nstopped")
            return 0

    sync_once(dest, args.session)
    status_report(dest, limit=args.last)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
