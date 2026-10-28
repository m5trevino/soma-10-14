#!/usr/bin/env bash
# Launcher for the Soma engine.
# Usage:
#   ./run.sh                        # Launch web picker → run pipeline (default)
#   ./run.sh --queue file.json      # Use existing queue, skip picker
#   ./run.sh --source /path         # Direct mode (legacy)
#   ./run.sh --dashboard            # Dashboard only
#   ./run.sh --curses               # Interactive curses TUI (a-d, 1-8, 9, r, o, s, g)
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
export PYTHONPATH="$DIR/turn-key:$DIR/soma:${PYTHONPATH:-}"

# If curses launcher requested
for arg in "$@"; do
  case "$arg" in
    --curses)
      exec python3 "$DIR/soma/curses_launcher.py" "$@"
      ;;
    --source|--queue)
      cd "$DIR/soma"
      exec python3 run_engine.py "$@"
      ;;
  esac
done

cd "$DIR"
exec python3 run_sessions.py "$@"
