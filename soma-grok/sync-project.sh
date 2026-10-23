#!/usr/bin/env bash
# sync-project.sh — Sync a codebase into a "clean" copy for web-UI LLM contexts.
#
# Usage:
#   bash sync-project.sh <source-dir> <dest-dir>
#
# Example:
#   bash sync-project.sh ~/my-project ~/my-project/my-project-grok
#
# Produces:
#   - Clean copy in dest-dir (excludes noise)
#   - Summary file: sync-YYYYMMDD_HHMMSS.txt

set -euo pipefail

if [ $# -lt 2 ]; then
  echo "Usage: bash sync-project.sh <source-dir> <dest-dir>"
  echo "  Cleans dest-dir and copies source with noise excluded."
  echo "  Shows added/updated/removed files. Saves a summary."
  exit 1
fi

SRC="$(cd "$1" && pwd)"
DEST="$2"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
SUMMARY="$(dirname "$DEST")/sync-$TIMESTAMP.txt"

# ── Noise to exclude ──────────────────────────────────────────────
EXCLUDES=(
  --exclude='node_modules'
  --exclude='__pycache__'
  --exclude='.pytest_cache'
  --exclude='*.egg-info'
  --exclude='.venv'
  --exclude='venv'
  --exclude='env/'
  --exclude='.git'
  --exclude='.gitignore'
  --exclude='.DS_Store'
  --exclude='*.log'
  --exclude='*.tmp'
  --exclude='*.swp'
  --exclude='*.swo'
  --exclude='dist/'
  --exclude='build/'
  --exclude='.next/'
  --exclude='*.pyc'
  --exclude='__pycache__'
  --exclude='.mypy_cache'
  --exclude='.ruff_cache'
  --exclude='coverage/'
  --exclude='.tox/'
  --exclude='.coverage'
  --exclude='.eslintcache'
  --exclude='*.lock'          # npm lock, poetry lock, etc.
  --exclude='package-lock.json'
  --exclude='yarn.lock'
  --exclude='poetry.lock'
  --exclude='Gemfile.lock'
  --exclude='.specstory/'
  --exclude='output/'
  --exclude='soma-grok/'      # prevent nested copies
  --exclude='*-*-sync-*.txt'  # skip old summaries
)

# ── 1. Snapshot existing files ────────────────────────────────────
declare -A OLD_FILES
if [ -d "$DEST" ]; then
  while IFS= read -r -d '' f; do
    rel="${f#$DEST/}"
    OLD_FILES["$rel"]=1
  done < <(find "$DEST" -type f -print0 2>/dev/null)
fi

# ── 2. Clean dest ─────────────────────────────────────────────────
echo "==> Cleaning $DEST ..."
rm -rf "${DEST:?}"/*
rm -rf "${DEST:?}"/.[!.]* 2>/dev/null || true

# ── 3. Copy from source ──────────────────────────────────────────
echo "==> Copying from $SRC ..."
rsync -a "${EXCLUDES[@]}" "$SRC/" "$DEST/"

# ── 4. Snapshot new files ─────────────────────────────────────────
declare -A NEW_FILES
while IFS= read -r -d '' f; do
  rel="${f#$DEST/}"
  NEW_FILES["$rel"]=1
done < <(find "$DEST" -type f -print0 2>/dev/null)

# ── 5. Diff and summary ──────────────────────────────────────────
{
  echo "=== sync-project summary ==="
  echo "Source: $SRC"
  echo "Dest:   $DEST"
  echo "Date:   $(date)"
  echo ""

  ADDED_FILES=()
  UPDATED_FILES=()
  for f in "${!NEW_FILES[@]}"; do
    if [ -z "${OLD_FILES[$f]+x}" ]; then
      ADDED_FILES+=("$f")
    else
      UPDATED_FILES+=("$f")
    fi
  done

  REMOVED_FILES=()
  for f in "${!OLD_FILES[@]}"; do
    if [ -z "${NEW_FILES[$f]+x}" ]; then
      REMOVED_FILES+=("$f")
    fi
  done

  if [ ${#ADDED_FILES[@]} -gt 0 ]; then
    echo "--- ADDED (${#ADDED_FILES[@]}) ---"
    printf '%s\n' "${ADDED_FILES[@]}" | sort
    echo ""
  fi

  if [ ${#UPDATED_FILES[@]} -gt 0 ]; then
    echo "--- UPDATED (${#UPDATED_FILES[@]}) ---"
    printf '%s\n' "${UPDATED_FILES[@]}" | sort
    echo ""
  fi

  if [ ${#REMOVED_FILES[@]} -gt 0 ]; then
    echo "--- REMOVED (${#REMOVED_FILES[@]}) ---"
    printf '%s\n' "${REMOVED_FILES[@]}" | sort
    echo ""
  fi

  TOTAL=$(find "$DEST" -type f | wc -l)
  echo "---"
  echo "Total files: $TOTAL"
  echo "Added: ${#ADDED_FILES[@]} | Updated: ${#UPDATED_FILES[@]} | Removed: ${#REMOVED_FILES[@]}"
} | tee "$SUMMARY"

TOTAL=$(find "$DEST" -type f | wc -l)
echo ""
echo "==> Done. $TOTAL files in $DEST"
echo "==> Summary: $SUMMARY"
