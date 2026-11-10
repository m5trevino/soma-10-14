#!/usr/bin/env python3
"""Interactive launcher for the session consolidator — zero CLI flags.

Hardcodes the source/db/target paths, discovers every conversation chain,
prints a numbered menu, and routes a selection to either a dry-run preview or
a physical write. The operator never types a path or a flag.

Usage:
    python3 tools/run_consolidator.py
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import consolidate_chains as cc

# ── Hardcoded paths — the operator never types these. ──────────────────────
ROOT = Path("/media/storage/dendritic123/chat-logs/sessions")
DB = Path("/media/storage/graphdb/session_site/vault.db")
TARGET = Path("/media/storage/dendritic123/chat-logs/lineage")
# The Soma queue the engine's load_queue() reads. Same path the legacy
# session picker (soma-session-picker /api/select) writes to.
QUEUE_PATH = Path("/home/flintx/soma-10-14/data/soma_queue.json")


def export_to_soma_json(paths: list[str], queue_path: Path = QUEUE_PATH) -> dict:
    """Write selected session paths to the Soma queue JSON.

    Mirrors the legacy session picker's /api/select schema exactly:
    {"selected": [...], "count": N, "timestamp": <float>}.
    """
    queue_data = {
        "selected": list(paths),
        "count": len(paths),
        "timestamp": time.time(),
    }
    queue_path.parent.mkdir(parents=True, exist_ok=True)
    with open(queue_path, "w") as f:
        json.dump(queue_data, f, indent=2)
    return queue_data


def discover() -> list[cc.Chain]:
    """Resolve every conversation chain from the source + vault DB."""
    return cc.resolve_chains(ROOT, DB)


def _truncate(text: str, width: int) -> str:
    if len(text) <= width:
        return text
    return text[: max(0, width - 1)] + "…"


def render_menu(chains: list[cc.Chain], out) -> None:
    """Print the numbered chain table: [index] name  sessions  chunks."""
    cols = shutil.get_terminal_size((80, 24)).columns
    name_width = max(20, cols - 32)
    print(f"  {'#':>4}  {'CHAIN':<{name_width}}  {'SESSIONS':>8}  {'CHUNKS':>8}", file=out)
    print("  " + "─" * (name_width + 26), file=out)
    for i, chain in enumerate(chains, 1):
        name = _truncate(chain.key, name_width)
        print(f"  {i:>4}  {name:<{name_width}}  "
              f"{len(chain.members):>8}  {chain.total_chunks:>8}", file=out)
    print(file=out)


def _ask_mode(input_fn, out) -> bool | None:
    """True → dry-run, False → execute, None → abort back to the menu."""
    while True:
        mode = input_fn("Dry run (preview) or Execute (write)? [d/e]: ").strip().lower()
        if mode == "d":
            return True
        if mode == "e":
            return False
        if mode == "q":
            return None
        print("  invalid — enter 'd' or 'e'", file=out)


def _execute(chains: list[cc.Chain], dry_run: bool, out) -> None:
    exported: list[str] = []
    for chain in chains:
        if dry_run:
            emitted, dropped = cc.dedup_chain(ROOT, chain.members)
            print(f"[dry-run] {chain.key}", file=out)
            print(f"  members ({len(chain.members)}): {', '.join(chain.members)}", file=out)
            print(f"  would emit {len(emitted)} chunks, drop {len(dropped)}", file=out)
        else:
            result = cc.consolidate_chain(ROOT, TARGET, chain)
            print(f"{result['key']}: emitted {result['emitted']} chunks, "
                  f"dropped {result['dropped']} → {result['output_dir']}", file=out)
            exported.append(result["output_dir"])
    if not dry_run and exported:
        export_to_soma_json(exported)
        print(f"queue: {len(exported)} selected → {QUEUE_PATH}", file=out)


def run(chains: list[cc.Chain], input_fn=input, out=None) -> None:
    """Main interactive loop. ``input_fn``/``out`` are injectable for tests."""
    out = out or sys.stdout
    while True:
        render_menu(chains, out)
        choice = input_fn("Select an index, 'a' for all, 'q' to quit: ").strip().lower()

        if choice == "q":
            print("bye", file=out)
            return

        if choice == "a":
            selected = chains
        elif choice.isdigit():
            idx = int(choice)
            if not 1 <= idx <= len(chains):
                print(f"  invalid — index out of range (1-{len(chains)})", file=out)
                continue
            selected = [chains[idx - 1]]
        else:
            print("  invalid — enter an index, 'a', or 'q'", file=out)
            continue

        dry_run = _ask_mode(input_fn, out)
        if dry_run is None:
            continue  # back to the menu
        _execute(selected, dry_run, out)


def main() -> int:
    chains = discover()
    if not chains:
        print("no chains found", file=sys.stderr)
        return 1
    run(chains)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
