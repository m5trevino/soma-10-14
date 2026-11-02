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
    """Rename this session's downloaded files into chronological order."""
    raw = dest / session
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
        if target == path or target.exists():
            continue
        path.rename(target)
        renamed += 1
    return renamed


def sync_once(dest: Path, only: str | None = None) -> None:
    sessions = [only] if only else _list_sessions()
    if not sessions:
        print("  no sessions found on the engine", file=sys.stderr)
        return

    for session in sessions:
        before = set(p.name for p in (dest / session).glob("*.txt")) if (dest / session).is_dir() else set()
        if not _rsync(f"{session}/", dest / session):
            continue
        after = set(p.name for p in (dest / session).glob("*.txt"))
        new = len(after - before)
        moved = organise(session, dest)
        if new or moved:
            print(f"  {session}: {new} new, {moved} renamed")


def main() -> int:
    ap = argparse.ArgumentParser(description="Pull PEA files into a local archive")
    ap.add_argument("--dest", default=str(DEFAULT_DEST))
    ap.add_argument("--session", default=None)
    ap.add_argument("--watch", action="store_true",
                    help="keep syncing in a loop")
    ap.add_argument("--interval", type=int, default=30)
    args = ap.parse_args()

    dest = Path(args.dest).expanduser()
    dest.mkdir(parents=True, exist_ok=True)

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
    total = sum(1 for _ in dest.rglob("*.txt"))
    print(f"\n{dest}  ({total} files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
