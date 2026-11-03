#!/usr/bin/env python3
"""SOMA board — a four-tile control panel for the Soma launchers.

Each tile starts one service in its own terminal window. The window owns the
process: closing the window stops the service. The board keeps no state, so it
can be closed at any moment without affecting anything it launched. The lamps
are live port checks, so they stay honest even for services started by hand.

The PEA sync strip below the tiles is deliberately not a fifth tile: it is a
background rsync loop with no window and no service manager, so it gets a
status line instead. It reads the pid file the loop's starter writes, falls
back to scanning /proc, and starts the loop detached when asked.

Keys:
    arrows / tab   move between tiles and the sync strip
    space / enter  launch the focused tile, or start the sync when focused
    1 2 3 4        launch a specific tile
    p              start the PEA sync
    q              quit the board (does not stop anything)

Usage:
    soma                 open the board
    soma --check         print service status and exit
    soma --dry           open the board but never spawn windows
"""
from __future__ import annotations

import os
import shlex
import shutil
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from rich.text import Text
from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Grid
from textual.widgets import Static

SOMA_DIR = Path(__file__).resolve().parent
PICKER_DIR = SOMA_DIR / "soma-session-picker"
TURNKEY_DIR = Path("/home/flintx/turn-key")

# PEA log browser (tools/pea_viewer.py). Read-only: pea_sync.py owns syncing.
PEA_LOG_PORT = 5199
# The manifest viewer picks the next free port if this one is busy, so the
# board probes the preferred one and falls back to whatever the process says.
PEA_MANIFEST_PORT = 9893

PEACOCK_DIR = Path.home() / "peacock"

# PEA sync now runs the repo's own puller, which fetches every session into
# ~/pea-sessions/<session>/ and renames each file so the order is chronological
# and the name carries the stage and outcome. The old rsync loop only mirrored
# raw files and left them unlabelled.
PEA_TOOL = SOMA_DIR / "tools" / "pea_sync.py"
TUI_DIR = Path("/home/flintx/peacock-engine-tui-core")
PEA_DEST = Path.home() / "pea-sessions"
SYNC_SCRIPT = PEA_TOOL
SYNC_PIDFILE = Path.home() / ".pea-sync.pid"
SYNC_MIRROR = PEA_DEST

BONE = "#e9e4d7"
DIM = "#8d9aa4"
FAINT = "#5f6a77"
AMBER = "#f2a93b"
AMBER_HI = "#ffd28c"
GREEN = "#4ade80"


# ── probes ───────────────────────────────────────────────────────────────

def port_open(port: Optional[int], timeout: float = 0.15) -> bool:
    if not port:
        return False
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            return sock.connect_ex(("127.0.0.1", port)) == 0
    except OSError:
        return False


def dashboard_port() -> int:
    try:
        return int((SOMA_DIR / ".dashboard_port").read_text().strip())
    except (OSError, ValueError):
        return 9877


# ── PEA sync probe ───────────────────────────────────────────────────────
#
# pea-sync.sh is a bare `while true` rsync loop. It writes no pid file of its
# own, so we honour the one its starter leaves behind, verify the pid is still
# the script (guarding against pid reuse), and fall back to a /proc scan for
# copies started without one. Negative scans are cached so a running loop that
# predates the pid file does not cost a /proc walk every second.

_SYNC_SCAN_TTL = 5.0
_sync_scan_cache = {"at": 0.0, "pid": None}


def _proc_cmdline(pid: int) -> str:
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return ""
    return raw.replace(b"\x00", b" ").decode("utf-8", "replace")


def _is_sync_pid(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return "pea-sync" in _proc_cmdline(pid)


def _scan_for_sync() -> Optional[int]:
    now = time.monotonic()
    if now - _sync_scan_cache["at"] < _SYNC_SCAN_TTL:
        cached = _sync_scan_cache["pid"]
        # Re-validate: a cached pid that has since died must not read as
        # running just because the TTL has not elapsed.
        if cached is None or _is_sync_pid(cached):
            return cached

    found: Optional[int] = None
    try:
        names = os.listdir("/proc")
    except OSError:
        names = []
    me = os.getpid()
    for name in names:
        if not name.isdigit():
            continue
        pid = int(name)
        if pid == me:
            continue
        if "pea-sync" in _proc_cmdline(pid):
            found = pid
            break

    _sync_scan_cache["at"] = now
    _sync_scan_cache["pid"] = found
    return found


def sync_pid() -> Optional[int]:
    try:
        pid = int(SYNC_PIDFILE.read_text().strip())
    except (OSError, ValueError):
        pid = None
    if pid and _is_sync_pid(pid):
        return pid
    return _scan_for_sync()


def _proc_age(pid: int) -> Optional[float]:
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
        uptime = float(Path("/proc/uptime").read_text().split()[0])
    except (OSError, ValueError, IndexError):
        return None
    try:
        after_comm = stat.rsplit(")", 1)[1].split()
        start_ticks = int(after_comm[19])  # field 22 of /proc/<pid>/stat
    except (IndexError, ValueError):
        return None
    hz = os.sysconf("SC_CLK_TCK") or 100
    return max(0.0, uptime - start_ticks / hz)


def format_age(seconds: Optional[float]) -> str:
    if seconds is None:
        return ""
    total = int(seconds)
    if total < 60:
        return "<1m"
    minutes = total // 60
    hours, minutes = divmod(minutes, 60)
    days, hours = divmod(hours, 24)
    if days:
        return f"{days}d {hours:02d}h"
    if hours:
        return f"{hours}h {minutes:02d}m"
    return f"{minutes}m"


# ── tile definitions ─────────────────────────────────────────────────────

@dataclass(frozen=True)
class Spec:
    key: str
    title: str
    target: str
    short: str
    hint: str
    cwd: Path
    command: str
    probe: Optional[Callable[[], bool]] = None
    url: Optional[Callable[[], Optional[str]]] = None


SPECS: list[Spec] = [
    Spec(
        key="picker",
        title="Session Picker",
        target="browser · port 5174",
        short="5174",
        hint="close the window to stop",
        cwd=PICKER_DIR,
        command="bash ./start-fg.sh",
        probe=lambda: port_open(5174) and port_open(8001),
        url=lambda: "http://localhost:5174",
    ),
    Spec(
        key="turnkey",
        title="Turn Key Builder",
        target="browser · port 5173",
        short="5173",
        hint="close the window to stop",
        cwd=TURNKEY_DIR,
        command="./launcher.sh fg",
        probe=lambda: port_open(5173),
        url=lambda: "http://127.0.0.1:5173",
    ),
    Spec(
        key="dashboard",
        title="Debug Dashboard",
        target="browser · port 9877+",
        short="9877+",
        hint="ctrl+c or close to stop",
        cwd=SOMA_DIR,
        command="python3 run_dashboard.py",
        probe=lambda: port_open(dashboard_port()),
        url=lambda: f"http://127.0.0.1:{dashboard_port()}",
    ),
    Spec(
        key="tui",
        title="Engine TUI",
        target="terminal · opentui",
        short="tui",
        hint="q to quit",
        cwd=TUI_DIR,
        command="./start.sh",
        probe=None,
        url=None,
    ),
    Spec(
        key="soma",
        title="Run Soma",
        target="terminal · ./run.sh",
        short="./run.sh",
        hint="exits when the run finishes",
        cwd=SOMA_DIR,
        command="./run.sh",
        probe=None,
        url=None,
    ),
    Spec(
        key="pealogs",
        title="PEA Manifests",
        target="browser · port 9893",
        short="9893",
        hint="read or download one, or all",
        cwd=SOMA_DIR,
        command="python3 tools/pea_viewer.py",
        probe=lambda: port_open(PEA_MANIFEST_PORT),
        url=lambda: f"http://127.0.0.1:{PEA_MANIFEST_PORT}",
    ),
]

BY_KEY = {spec.key: spec for spec in SPECS}


# ── window launching ─────────────────────────────────────────────────────

def terminal_argv(title: str, inner: str) -> Optional[list[str]]:
    """Build an argv for the first terminal emulator we can find."""
    argv = ["bash", "-lc", inner]
    if shutil.which("alacritty"):
        return ["alacritty", "-t", title, "-e", *argv]
    if shutil.which("kitty"):
        return ["kitty", "-T", title, *argv]
    if shutil.which("xfce4-terminal"):
        return ["xfce4-terminal", "--title", title, "-x", *argv]
    if shutil.which("x-terminal-emulator"):
        return ["x-terminal-emulator", "-T", title, "-e", *argv]
    if shutil.which("xterm"):
        return ["xterm", "-T", title, "-e", *argv]
    return None


def window_inner(spec: Spec) -> str:
    """Command body run inside the new window.

    Holds the window open on exit so a crash is readable instead of a window
    that flashes and disappears.
    """
    body = f"cd {shlex.quote(str(spec.cwd))} && {spec.command}"
    return (
        f"{body}; rc=$?; echo; "
        f"printf '[exit %s] Press Enter to close this window. ' \"$rc\"; read -r _"
    )


# ── widgets ──────────────────────────────────────────────────────────────

class Tile(Static):
    can_focus = True

    def __init__(self, spec: Spec) -> None:
        super().__init__(id=f"tile-{spec.key}")
        self.spec = spec
        self.running = False

    def on_mount(self) -> None:
        self._draw()

    def set_running(self, running: bool) -> None:
        if running == self.running:
            return
        self.running = running
        self.set_class(running, "running")
        self._draw()

    def _target(self) -> str:
        try:
            width = self.content_size.width
        except Exception:
            width = 0
        if not width:
            width = 40
        return self.spec.target if width >= 32 else self.spec.short

    def _draw(self) -> None:
        text = Text()
        text.append(self.spec.title.upper(), style=f"bold {BONE}")
        text.append("\n")

        if self.running:
            text.append("● ", style=GREEN)
            text.append("running", style=GREEN)
        elif self.spec.probe is None:
            text.append("○ ", style=FAINT)
            text.append("idle", style=FAINT)
        else:
            text.append("○ ", style=FAINT)
            text.append("off", style=FAINT)

        text.append("   ", style=FAINT)
        text.append(self._target(), style=DIM)
        text.append("\n")

        label = "OPEN TAB" if (self.running and self.spec.url) else "LAUNCH"
        text.append(f" {label} ", style=f"bold {AMBER_HI} on #1b242d")
        self.update(text)

    def on_resize(self, event: events.Resize) -> None:
        self._draw()

    def on_click(self, event: events.Click) -> None:
        event.stop()
        self.focus()
        app = self.app
        if isinstance(app, SomaBoard):
            app.launch(self)


class SyncStrip(Static):
    """Status and switch for the PEA delivery loop.

    Not a tile: the loop has no window of its own, so there is nothing to own
    its lifetime and nothing to close. It runs detached once started.
    """

    can_focus = True

    def __init__(self) -> None:
        super().__init__(id="sync")
        self.running = False
        self.pid: Optional[int] = None
        self.age = ""

    def on_mount(self) -> None:
        self._draw()

    def set_state(self, running: bool, pid: Optional[int], age: str) -> None:
        if (running, pid, age) == (self.running, self.pid, self.age):
            return
        self.running, self.pid, self.age = running, pid, age
        self.set_class(running, "running")
        self._draw()

    def _draw(self) -> None:
        width = self.size.width or 100
        text = Text()
        text.append(" PEA SYNC", style=f"bold {BONE}")
        text.append("   ", style=FAINT)

        if self.running:
            text.append("● ", style=GREEN)
            text.append("running", style=GREEN)
            if self.pid:
                text.append(f"   pid {self.pid}", style=DIM)
            if self.age:
                text.append(f"   up {self.age}", style=DIM)
        else:
            text.append("○ ", style=FAINT)
            text.append("off", style=FAINT)
            text.append("   press p to start", style=AMBER)

        if width >= 76:
            text.append("   ", style=FAINT)
            text.append("~/peacock/pea_sessions", style=FAINT)

        self.update(text)

    def on_resize(self, event: events.Resize) -> None:
        self._draw()

    def on_click(self, event: events.Click) -> None:
        event.stop()
        self.focus()
        app = self.app
        if isinstance(app, SomaBoard):
            app.start_sync()


# ── app ──────────────────────────────────────────────────────────────────

class SomaBoard(App):
    # Tile grid geometry is derived from SPECS in compose().
    # It used to be hardcoded to 2x2, which silently clipped the fifth tile:
    # the "soma" engine tile (run_sessions.py) was composed but off-screen,
    # so the board showed four tiles and the main app could not be launched.
    _COLS = 2

    CSS = """
    Screen {
        background: #080c10;
        color: #d7dee5;
    }

    #top {
        height: 2;
        padding: 0 2;
        content-align: left middle;
        background: #141b22;
        border-bottom: solid #2a3642;
    }

    #grid {
        layout: grid;
        grid-gutter: 1 2;
        padding: 0 2;
        height: 1fr;
    }

    #sync {
        height: 2;
        padding: 0 2;
        content-align: left middle;
        background: #0c1116;
        border-top: solid #2a3642;
    }

    #sync:focus {
        background: #1b242d;
    }

    #bar {
        height: 2;
        padding: 0 2;
        content-align: left middle;
        background: #141b22;
    }

    Tile {
        background: #141b22;
        border: round #2a3642;
        padding: 0 2;
        content-align: left middle;
        height: 100%;
        width: 100%;
    }

    Tile:focus {
        background: #1b242d;
        border: round #f2a93b;
    }

    Tile.running {
        border: round #4ade80;
    }

    Tile.running:focus {
        border: round #ffd28c;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "quit", priority=True),
        Binding("space", "launch_focused", "launch", priority=True),
        Binding("enter", "launch_focused", "launch", priority=True),
        Binding("right", "focus_tile(1)", "next", priority=True),
        Binding("down", "focus_tile(1)", "next", priority=True),
        Binding("left", "focus_tile(-1)", "prev", priority=True),
        Binding("up", "focus_tile(-1)", "prev", priority=True),
        Binding("1", "launch_key('picker')", "", priority=True),
        Binding("2", "launch_key('turnkey')", "", priority=True),
        Binding("3", "launch_key('dashboard')", "", priority=True),
        Binding("4", "launch_key('soma')", "", priority=True),
        Binding("5", "launch_key('pealogs')", "", priority=True),
        Binding("p", "start_sync", "pea sync", priority=True),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.notice = ""
        self.notice_at = 0.0
        self.states: dict[str, bool] = {}

    def compose(self) -> ComposeResult:
        yield Static(self._header_text(), id="top")
        with Grid(id="grid"):
            for spec in SPECS:
                yield Tile(spec)
        yield SyncStrip()
        yield Static(self._bar_text(), id="bar")

    def on_mount(self) -> None:
        # Size the tile grid to the tile count. A fixed 2x2 grid composed all
        # five tiles but clipped the last one off-screen, which hid the Soma
        # engine tile (run_sessions.py) entirely.
        rows = max(1, -(-len(SPECS) // self._COLS))
        try:
            grid = self.query_one("#grid", Grid)
            grid.styles.grid_size_columns = self._COLS
            grid.styles.grid_size_rows = rows
        except Exception:
            pass

        tiles = list(self.query(Tile))
        if tiles:
            self.set_focus(tiles[0])
        self.refresh_states()
        self.set_interval(1.0, self.refresh_states)

    # ── rendering ──

    @staticmethod
    def _header_text() -> Text:
        """The banner, tinted purple→green across the art, then the subtitle."""
        text = Text()
        try:
            from banner import ART, TAGLINE, gradient_hex
        except ImportError:
            ART, TAGLINE = (), ""

        if ART:
            width = max(len(line) for line in ART)
            for line in ART:
                for col, ch in enumerate(line):
                    if ch == " ":
                        text.append(ch)
                        continue
                    text.append(ch, style=gradient_hex(col, width))
                text.append("\n")
            text.append("\n")
            text.append(TAGLINE, style=FAINT)
            text.append("\n\n")

        text.append("SOMA", style=f"bold {BONE}")
        text.append("   machine room launcher", style=DIM)
        return text

    def _bar_text(self) -> Text:
        text = Text()
        text.append(" ←→↑↓ move   space launch   click a tile   q quit", style=DIM)
        text.append("\n")

        fresh_notice = self.notice and (time.monotonic() - self.notice_at) < 5.0
        if fresh_notice:
            text.append(f" {self.notice}", style=AMBER)
            return text

        focused = self.focused
        if isinstance(focused, Tile):
            text.append(f" {focused.spec.hint}", style=FAINT)
        elif isinstance(focused, SyncStrip):
            if focused.running:
                text.append(" PEA delivery loop is running detached", style=FAINT)
            else:
                text.append(" start the PEA delivery loop", style=FAINT)
        else:
            text.append(" stop a service by closing its window", style=FAINT)
        return text

    def _refresh_bar(self) -> None:
        try:
            self.query_one("#bar", Static).update(self._bar_text())
        except Exception:
            pass

    def notice_line(self, message: str) -> None:
        self.notice = message
        self.notice_at = time.monotonic()
        self._refresh_bar()

    # ── state ──

    def is_running(self, spec: Spec) -> bool:
        if spec.probe is None:
            return False
        try:
            return bool(spec.probe())
        except Exception:
            return False

    def refresh_states(self) -> None:
        for spec in SPECS:
            running = self.is_running(spec)
            self.states[spec.key] = running
            try:
                tile = self.query_one(f"#tile-{spec.key}", Tile)
            except Exception:
                continue
            tile.set_running(running)

        pid = sync_pid()
        try:
            strip = self.query_one("#sync", SyncStrip)
        except Exception:
            strip = None
        if strip is not None:
            age = format_age(_proc_age(pid)) if pid else ""
            strip.set_state(bool(pid), pid, age)

        self._refresh_bar()

    # ── actions ──

    def _focus_order(self) -> list:
        items: list = list(self.query(Tile))
        try:
            items.append(self.query_one("#sync", SyncStrip))
        except Exception:
            pass
        return items

    def action_focus_tile(self, delta: int) -> None:
        items = self._focus_order()
        if not items:
            return
        focused = self.focused
        try:
            index = items.index(focused)  # type: ignore[arg-type]
        except ValueError:
            index = 0
        self.set_focus(items[(index + delta) % len(items)])

    def action_launch_focused(self) -> None:
        focused = self.focused
        if isinstance(focused, Tile):
            self.launch(focused)
        elif isinstance(focused, SyncStrip):
            self.start_sync()

    def action_start_sync(self) -> None:
        self.start_sync()

    def start_sync(self) -> None:
        if os.environ.get("SOMA_TUI_DRY"):
            self.notice_line("dry run: would start the PEA sync")
            return

        pid = sync_pid()
        if pid:
            self.notice_line(f"PEA sync already running · pid {pid}")
            return

        if not SYNC_SCRIPT.exists():
            self.notice_line(f"missing {SYNC_SCRIPT}")
            return

        try:
            proc = subprocess.Popen(
                [sys.executable, str(SYNC_SCRIPT), "--watch",
                 "--dest", str(PEA_DEST)],
                cwd=str(SOMA_DIR),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except OSError as exc:
            self.notice_line(f"start failed: {exc}")
            return

        # The loop does not write its own pid file; the documented stop command
        # reads this one, so keep it truthful.
        try:
            SYNC_PIDFILE.parent.mkdir(parents=True, exist_ok=True)
            SYNC_PIDFILE.write_text(f"{proc.pid}\n")
        except OSError:
            pass

        self.notice_line(f"PEA sync started · pid {proc.pid}")
        _sync_scan_cache["pid"] = proc.pid
        _sync_scan_cache["at"] = time.monotonic()
        self.refresh_states()

    def action_launch_key(self, key: str) -> None:
        spec = BY_KEY.get(key)
        if spec is None:
            return
        try:
            tile = self.query_one(f"#tile-{spec.key}", Tile)
        except Exception:
            return
        self.launch(tile)

    def launch(self, tile: Tile) -> None:
        spec = tile.spec

        if os.environ.get("SOMA_TUI_DRY"):
            self.notice_line(f"dry run: would open {spec.title}")
            return

        # Already up: bring the page back instead of starting a second copy.
        if self.is_running(spec):
            url = spec.url() if spec.url else None
            if url:
                webbrowser.open(url)
                self.notice_line(f"already running · opened {url}")
            else:
                self.notice_line(f"{spec.title} is already running")
            return

        argv = terminal_argv(f"SOMA · {spec.title}", window_inner(spec))
        if argv is None:
            self.notice_line("no terminal emulator found")
            return

        try:
            subprocess.Popen(
                argv,
                start_new_session=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError as exc:
            self.notice_line(f"launch failed: {exc}")
            return

        self.notice_line(f"launched {spec.title}")

        if spec.url is not None and spec.probe is not None:
            threading.Thread(
                target=self._open_when_ready,
                args=(spec,),
                daemon=True,
            ).start()

    def _open_when_ready(self, spec: Spec) -> None:
        deadline = time.monotonic() + 40.0
        while time.monotonic() < deadline:
            try:
                if spec.probe is not None and spec.probe():
                    url = spec.url() if spec.url else None
                    if url:
                        webbrowser.open(url)
                        self._notify_threadsafe(f"opened {url}")
                    return
            except Exception:
                pass
            time.sleep(0.5)
        self._notify_threadsafe(f"{spec.title}: did not come up within 40s")

    def _notify_threadsafe(self, message: str) -> None:
        try:
            self.call_from_thread(self.notice_line, message)
        except Exception:
            pass


# ── entry point ──────────────────────────────────────────────────────────

def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        prog="soma",
        description="SOMA machine room launcher",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="print the detected state of each service and exit",
    )
    parser.add_argument(
        "--dry",
        action="store_true",
        help="open the board but never spawn windows",
    )
    args = parser.parse_args()

    if args.dry:
        os.environ["SOMA_TUI_DRY"] = "1"

    if args.check:
        for spec in SPECS:
            if spec.probe is None:
                state = "n/a"
            else:
                state = "running" if spec.probe() else "off"
            print(f"{spec.key:<10} {state:<8} {spec.target}")

        pid = sync_pid()
        if pid:
            age = format_age(_proc_age(pid))
            detail = f"pid {pid}" + (f" up {age}" if age else "")
            print(f"{'sync':<10} {'running':<8} {detail}")
        else:
            print(f"{'sync':<10} {'off':<8} {SYNC_MIRROR}")
        return

    SomaBoard().run()


if __name__ == "__main__":
    main()
