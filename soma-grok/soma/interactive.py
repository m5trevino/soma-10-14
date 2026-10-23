#!/usr/bin/env python3
"""Interactive launcher for the Soma engine.

Opens the web-based session picker in your browser, lets you select sessions,
then runs them via run_engine.py --queue.
"""
from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

QUEUE_PATH = Path("/home/flintx/soma-10-14/data/soma_queue.json")
FRONTEND_URL = "http://localhost:5174"
BACKEND_URL = "http://localhost:8001"


def wait_for_picker(timeout: int = 60) -> bool:
    """Wait for the Soma Session Picker to be available."""
    for _ in range(timeout * 2):
        try:
            urllib.request.urlopen(f"{BACKEND_URL}/api/health", timeout=0.5)
            return True
        except Exception:
            time.sleep(0.5)
    return False


def open_picker():
    """Open the session picker in the default browser."""
    if wait_for_picker():
        print(f"\n  Soma Session Picker ready: {FRONTEND_URL}")
        print(f"  Select sessions, then click 'Export selected'\n")
        try:
            system = platform.system()
            if system == "Darwin":
                subprocess.Popen(["open", FRONTEND_URL])
            elif system == "Windows":
                os.startfile(FRONTEND_URL)
            else:
                subprocess.Popen(["xdg-open", FRONTEND_URL])
        except Exception:
            print(f"  Could not auto-open browser. Visit: {FRONTEND_URL}")
    else:
        print(f"  Picker not available. Is it running?")
        print(f"  Start it with: cd /home/flintx/soma-10-14/soma-session-picker && bash start.sh")
        print(f"  Or visit: {FRONTEND_URL}")


def load_selected() -> list[str]:
    """Load selected session IDs from the queue file."""
    if not QUEUE_PATH.exists():
        print("No queue file found. Did you export sessions from the picker?")
        return []
    with open(QUEUE_PATH) as f:
        data = json.load(f)
    return data.get("selected", [])


def main() -> int:
    print("═══════════════════════════════════════")
    print("  Soma Interactive Launcher")
    print("═══════════════════════════════════════\n")

    # Check if queue already exists (from a previous picker run)
    if QUEUE_PATH.exists():
        try:
            with open(QUEUE_PATH) as f:
                old_data = json.load(f)
            old_count = old_data.get("count", 0)
            if old_count > 0:
                print(f"Found existing queue: {old_count} sessions")
                while True:
                    resp = input("  Use existing queue? (y/n): ").strip().lower()
                    if resp in ("y", "n"):
                        break
                if resp == "y":
                    sessions = load_selected()
                    print(f"\nRunning {len(sessions)} sessions from queue...")
                    return run_engine(sessions)
        except (json.JSONDecodeError, OSError):
            pass

    print("Step 1: Open session picker in your browser")
    print("───────────────────────────────────────────")
    open_picker()

    # Wait for user to select and export
    print("\nWaiting for you to select and export sessions from the picker...")
    print("(Ctrl+C to cancel)\n")
    try:
        for _ in range(120):  # wait up to 60 seconds
            time.sleep(0.5)
            if QUEUE_PATH.exists():
                try:
                    with open(QUEUE_PATH) as f:
                        data = json.load(f)
                    if data.get("count", 0) > 0:
                        print("✓ Queue received!\n")
                        return run_engine(data["selected"])
                except (json.JSONDecodeError, OSError):
                    pass
    except KeyboardInterrupt:
        print("\nCancelled.")
        return 0

    print("Timed out waiting for queue.")
    return 1


def run_engine(session_ids: list[str]) -> int:
    """Run run_engine.py with the selected sessions."""
    if not session_ids:
        print("No sessions selected. Nothing to run.")
        return 0

    # Find a profile
    pkg = Path(__file__).resolve().parent.parent
    profiles = []
    for p in pkg.glob("**/*profile*.json"):
        profiles.append(p)
    for p in pkg.glob("**/soma-current.json"):
        if p not in profiles:
            profiles.append(p)

    if not profiles:
        print("No profile found. Create one first.")
        return 1

    profile = profiles[0]
    print(f"Profile: {profile.name}")

    cmd = [
        sys.executable, "run_engine.py",
        "--queue", str(QUEUE_PATH),
        "--profile", str(profile),
    ]
    print(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=str(Path(__file__).parent))
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
