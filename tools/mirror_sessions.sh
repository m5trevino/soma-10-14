#!/usr/bin/env bash
# Mirror the sessions root into a working copy (distinct name, not "sessions").
#
# The mirror is disposable: re-running this re-syncs from source and prunes
# anything not in source (including the consolidated/ subdir the consolidator
# writes). Consolidate into a *separate* target, or re-mirror before you need
# to re-run consolidation from scratch.
set -euo pipefail

SRC="${1:-/media/storage/dendritic123/chat-logs/sessions}"
DST="${2:-/media/storage/dendritic123/chat-logs/lineage}"

if [ ! -d "$SRC" ]; then
    echo "source not found: $SRC" >&2
    exit 1
fi

mkdir -p "$DST"
rsync -a --delete "$SRC/" "$DST/"
echo "mirrored $SRC -> $DST"
