#!/usr/bin/env bash
# Launcher for the Soma engine.
# Usage:
#   ./run.sh                        # Launch web picker → run pipeline (default)
#   ./run.sh --queue file.json      # Use existing queue, skip picker
#   ./run.sh --source /path         # Direct mode (legacy)
#   ./run.sh --dashboard            # Dashboard only
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
export PYTHONPATH="$DIR/turn-key:$DIR/soma:${PYTHONPATH:-}"

# If any legacy run_engine.py flags are passed, forward directly
if [[ "$1" == "--source" || "$1" == "--queue" ]]; then
  cd "$DIR/soma"
  exec python3 run_engine.py "$@"
fi

cd "$DIR"
exec python3 run_sessions.py "$@"
