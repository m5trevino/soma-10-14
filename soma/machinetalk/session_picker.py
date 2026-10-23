#!/usr/bin/env python3
"""Interactive session picker — curses UI for selecting sessions to process.

Usage:
    python -m soma.machinetalk.session_picker
    python soma/machinetalk/session_picker.py
    python run_sessions.py                    # via launcher
    
Features:
- Arrow keys to navigate sessions
- Space bar to add/remove from selection
- Enter to commit selection and return to caller
- Sort by: name, provider, chat_sets, characters, anchor/domain
- Reverse sort with R key
- Search/filter with / key (substring match)
- Shows metadata: title, sets, chars, provider, domain/anchor
- Reads from /media/storage/dendritic123/chat-logs/sessions/
- Also indexes SearchMonkey III vault.db if available

Returns selected SessionInfo objects as a JSON list of paths to stdout
and a Python list to the caller.
"""
import curses
import json
import os
import re
import sqlite3
import sys
from pathlib import Path
from collections import defaultdict
from typing import Optional


# ── Session root paths ────────────────────────────────────────────────────

SESSIONS_PATH = Path("/media/storage/dendritic123/chat-logs/sessions")
SEARCHMONKEY_DB = Path("/media/storage/dendritic123/searchmonkey-iii/backend/vault.db")


class SessionInfo:
    """Metadata about a single session."""
    __slots__ = [
        "id", "path", "title", "provider", "chat_sets", "characters",
        "anchors", "domain", "sub_domain", "dev_score", "total_sets"
    ]

    def __init__(self, session_id: str, path: Path):
        self.id = session_id
        self.path = str(path)
        self.title = None
        self.provider = None
        self.chat_sets = 0
        self.characters = 0
        self.anchors = []
        self.domain = None
        self.sub_domain = None
        self.dev_score = 0
        self.total_sets = 0
        self._load_metadata()

    def _load_metadata(self):
        """Load metadata from session.json and scan JSONL files."""
        session_dir = Path(self.path)

        # Try session.json first
        session_json = session_dir / "session.json"
        if session_dir.exists() and session_json.exists():
            try:
                with open(session_json) as f:
                    data = json.load(f)
                self.title = data.get("title") or data.get("name")
                self.total_sets = data.get("total_sets", 0)
            except (json.JSONDecodeError, OSError):
                pass

        # Count chat sets and characters from JSON files
        if session_dir.is_dir():
            json_files = sorted(
                [f for f in session_dir.iterdir() if f.suffix == ".json"],
                key=lambda f: f.name
            )
            for json_file in json_files:
                if json_file.name == "session.json":
                    continue
                try:
                    with open(json_file) as f:
                        data = json.load(f)
                    self.chat_sets += 1
                    for key in ("user_text", "assistant_text", "text", "content"):
                        if key in data and isinstance(data[key], str):
                            self.characters += len(data[key])
                except (json.JSONDecodeError, OSError):
                    pass

        # Extract provider from session ID
        if not self.provider:
            if "@" in self.id:
                self.provider = "gmail"
            elif "claude_web" in self.id:
                self.provider = "claude"
            elif "grok_web" in self.id:
                self.provider = "grok"
            elif "cursor" in self.id:
                self.provider = "cursor"
            else:
                self.provider = "unknown"

        # Use total_sets from session.json if we counted fewer
        if self.total_sets and self.total_sets > self.chat_sets:
            self.chat_sets = self.total_sets

    def display_name(self) -> str:
        """Return a display-friendly name for this session."""
        if self.title:
            return self.title
        # Clean up the session ID for display
        name = self.id
        # Remove date prefix if present
        if len(name) > 8 and name[:2].isdigit() and name[2] in "._-":
            name = name[3:]
        # Replace dots with spaces for readability
        name = name.replace(".", " ").replace("_", " ")
        return name[:80]


def _load_searchmonkey_db():
    """Load session metadata from SearchMonkey III vault.db if available."""
    meta = {}
    if not SEARCHMONKEY_DB.exists():
        return meta
    try:
        conn = sqlite3.connect(str(SEARCHMONKEY_DB))
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT session_id, domain, sub_domain FROM sessions")
        for row in cur.fetchall():
            meta[row["session_id"]] = {
                "domain": row.get("domain"),
                "sub_domain": row.get("sub_domain"),
            }
        conn.close()
    except Exception:
        pass
    return meta


def scan_sessions() -> list:
    """Scan all sessions from disk and return SessionInfo objects."""
    if not SESSIONS_PATH.exists():
        return []

    # Load SearchMonkey metadata (fast cache)
    sm_meta = _load_searchmonkey_db()

    sessions = []
    for session_dir in sorted(SESSIONS_PATH.iterdir()):
        if session_dir.is_dir():
            try:
                session = SessionInfo(session_dir.name, session_dir)
                # Overlay SearchMonkey metadata
                if session.id in sm_meta:
                    session.domain = sm_meta[session.id].get("domain")
                    session.sub_domain = sm_meta[session.id].get("sub_domain")
                sessions.append(session)
            except Exception:
                continue
    return sessions


# ── Sort functions ─────────────────────────────────────────────────────────

def sort_key_provider(item, reverse=False):
    return (item.provider, item.display_name())

def sort_key_name(item, reverse=False):
    return item.display_name()

def sort_key_sets(item, reverse=True):
    return (item.chat_sets, item.display_name())

def sort_key_chars(item, reverse=True):
    return (item.characters, item.display_name())

def sort_key_anchor(item, reverse=False):
    return (item.domain or "", item.sub_domain or "", item.display_name())

SORT_FUNCTIONS = {
    "name": sort_key_name,
    "provider": sort_key_provider,
    "sets": sort_key_sets,
    "chars": sort_key_chars,
    "anchor": sort_key_anchor,
}

SORT_NAMES = {
    "name": "Name",
    "provider": "Provider",
    "sets": "Chat Sets",
    "chars": "Characters",
    "anchor": "Anchor/Domain",
}


# ── Curses UI ─────────────────────────────────────────────────────────────

def _short_name(name: str, max_len: int = 50) -> str:
    """Truncate a name to fit the display."""
    if not name:
        return "?"
    if len(name) > max_len:
        return name[:max_len - 3] + "..."
    return name


def run_session_picker(sort_by: str = "name") -> list[str] | None:
    """Main curses UI for session selection.

    Args:
        sort_by: Initial sort key (name, provider, sets, chars, anchor)

    Returns:
        list of selected session paths, or None if user cancels.
    """
    sessions = scan_sessions()

    if not sessions:
        print("No sessions found!")
        return []

    current_sort = sort_by
    sort_reversed = False
    search_filter = ""
    search_re = None

    def sort_sessions():
        nonlocal sessions
        key_fn = SORT_FUNCTIONS[current_sort]
        sessions.sort(key=lambda s: key_fn(s, sort_reversed))

    sort_sessions()

    selected = set()  # set of display indices into current sorted list

    def draw(stdscr, scroll_off, hover_idx):
        stdscr.erase()
        H, W = stdscr.getmaxyx()

        # Title
        stdscr.attron(curses.A_BOLD)
        stdscr.addstr(0, 0, "  SOMA SESSION PICKER".ljust(W - 1))
        stdscr.attroff(curses.A_BOLD)

        # Instructions row
        stdscr.addstr(1, 0, f"  Sort: {SORT_NAMES[current_sort]}{' (REV)' if sort_reversed else ''}  |  "
                           f"Selected: {len(selected)}/{len(sessions)}  |  "
                           f"Filter: {'ON' if search_filter else 'OFF'}".ljust(W - 1)[:W-1])

        # Key hints
        hints = "↑↓Nav  SpaceSel  EnterDone  RRev  N/P/S/C/A ChangeSort  /Search  ESC Quit"
        stdscr.addstr(2, 0, hints.ljust(W - 1)[:W-1])

        if search_filter:
            stdscr.addstr(3, 0, f"  Match: \"{search_filter}\"".ljust(W - 1)[:W-1])

        # Separator
        stdscr.addstr(4, 0, ("─" * (W - 1))[:W-1])

        # Session list
        visible = H - 6
        start = scroll_off
        if start < 0:
            start = 0
        if start > len(sessions) - visible:
            start = max(0, len(sessions) - visible)

        for i in range(visible):
            idx = start + i
            if idx >= len(sessions):
                break

            row = 5 + i
            s = sessions[idx]
            marker = "[+]" if idx in selected else "[ ]"
            name = _short_name(s.title or s.id)
            meta = f" {s.chat_sets}s  {s.characters:>10,}c  {s.provider}"
            if s.domain:
                meta += f"  ▸ {s.domain}"
            line = f"  {marker} {name}{meta}"

            # Truncate to width
            if len(line) > W - 1:
                line = line[:W - 1]

            try:
                if idx == hover_idx:
                    stdscr.attron(curses.A_REVERSE | curses.A_BOLD)
                stdscr.addstr(row, 0, line)
                stdscr.attroff(curses.A_REVERSE | curses.A_BOLD)
            except curses.error:
                pass

        # Status bar
        if sessions:
            show_idx = min(start, len(sessions) - 1)
            status = f"  {start + 1}-{min(start + visible, len(sessions))}/{len(sessions)}  │  " \
                     f"{_short_name(sessions[show_idx].id)}"
        else:
            status = "  No sessions"
        stdscr.addstr(H - 1, 0, status.ljust(W - 1)[:W-1])

        stdscr.refresh()

    # ── Main loop ───────────────────────────────────────────────────────
    stdscr = curses.initscr()
    curses.noecho()
    curses.cbreak()
    stdscr.keypad(True)
    stdscr.timeout(-1)  # blocking

    scroll_off = 0
    hover_idx = 0
    search_input = ""
    search_mode = False

    try:
        while True:
            draw(stdscr, scroll_off, hover_idx)
            key = stdscr.getch()

            if key == 27:  # ESC
                return None

            if search_mode:
                if key in (10, 13, 27):  # Enter or ESC ends search
                    if key != 27:
                        search_filter = search_input
                        if search_filter:
                            search_re = re.compile(re.escape(search_filter), re.IGNORECASE)
                    else:
                        search_input = ""
                    search_mode = False
                    scroll_off = 0
                    hover_idx = 0
                    continue
                elif key in (curses.KEY_BACKSPACE, 127, 8):
                    search_input = search_input[:-1]
                elif 32 <= key <= 126:
                    search_input += chr(key)
                continue

            # Filtering: only show sessions matching search_re
            if search_re:
                visible_indices = [
                    i for i, s in enumerate(sessions)
                    if search_re.search(s.title or s.id) or
                       search_re.search(s.domain or "") or
                       search_re.search(s.provider)
                ]
            else:
                visible_indices = list(range(len(sessions)))

            if not visible_indices:
                continue

            # Keep hover_idx within visible indices
            if hover_idx not in visible_indices:
                hover_idx = visible_indices[0]

            if key == curses.KEY_UP:
                vi = visible_indices.index(hover_idx)
                if vi > 0:
                    hover_idx = visible_indices[vi - 1]
                    if hover_idx < scroll_off:
                        scroll_off = hover_idx

            elif key == curses.KEY_DOWN:
                vi = visible_indices.index(hover_idx)
                if vi < len(visible_indices) - 1:
                    hover_idx = visible_indices[vi + 1]
                    min_scroll = hover_idx - (stdscr.getmaxyx()[0] - 7)
                    if hover_idx >= scroll_off + (stdscr.getmaxyx()[0] - 7):
                        scroll_off = max(scroll_off, min_scroll)

            elif key == ord(' '):
                if hover_idx in selected:
                    selected.discard(hover_idx)
                else:
                    selected.add(hover_idx)

            elif key == curses.KEY_ENTER or key == 10 or key == 13:
                if selected:
                    return [sessions[i].path for i in sorted(selected)]
                else:
                    return [s.path for s in sessions]

            elif key == ord('r') or key == ord('R'):
                sort_reversed = not sort_reversed
                sort_sessions()
                selected = set()  # reset selection on re-sort
                scroll_off = 0
                hover_idx = 0

            elif key == ord('n') or key == ord('N'):
                current_sort = "name"
                sort_reversed = False
                sort_sessions()
                selected = set()
                scroll_off = 0
                hover_idx = 0

            elif key == ord('p') or key == ord('P'):
                current_sort = "provider"
                sort_reversed = False
                sort_sessions()
                selected = set()
                scroll_off = 0
                hover_idx = 0

            elif key == ord('s') or key == ord('S'):
                current_sort = "sets"
                sort_reversed = True
                sort_sessions()
                selected = set()
                scroll_off = 0
                hover_idx = 0

            elif key == ord('c') or key == ord('C'):
                current_sort = "chars"
                sort_reversed = True
                sort_sessions()
                selected = set()
                scroll_off = 0
                hover_idx = 0

            elif key == ord('a') or key == ord('A'):
                current_sort = "anchor"
                sort_reversed = False
                sort_sessions()
                selected = set()
                scroll_off = 0
                hover_idx = 0

            elif key == ord('/'):
                search_mode = True
                search_input = ""

    finally:
        curses.nocbreak()
        stdscr.keypad(False)
        curses.echo()
        curses.endwin()


def save_queue(paths: list[str], output_path: str = "data/queue.json"):
    """Save selected session paths to a JSON queue file."""
    from pathlib import Path as _Path
    _Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    data = {
        "selected": paths,
        "count": len(paths),
        "timestamp": __import__("datetime").datetime.utcnow().isoformat() + "Z",
    }
    with open(output_path, "w") as f:
        json.dump(data, f, indent=2)
    return data


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="SOMA Session Picker")
    parser.add_argument("--sort", default="name",
                        choices=["name", "provider", "sets", "chars", "anchor"],
                        help="Initial sort mode")
    parser.add_argument("--queue", default="data/queue.json",
                        help="Output queue file path")
    args = parser.parse_args()

    print(f"Starting session picker (sort={args.sort})...")
    print("Full-screen curses UI. Make sure your terminal is big enough.\n")

    paths = run_session_picker(sort_by=args.sort)
    if paths:
        data = save_queue(paths, args.queue)
        print(f"\n✓ Selected {data['count']} sessions")
        print(f"✓ Queue saved to {args.queue}")
        print("\nSession paths:")
        for p in paths:
            print(f"  {p}")
        print(f"\nRun pipeline: pipeline run --debug /tmp/soma_debug --source {paths[0]}")
    else:
        print("No sessions selected.")
