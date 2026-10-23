#!/usr/bin/env bash
# Sync the codebase into soma-grok/ for Grok web UI upload.
# Run this after making CLI changes: bash sync-to-grok.sh

set -euo pipefail

SRC="/home/flintx/soma-10-14"
DEST="/home/flintx/soma-grok"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
SUMMARY="/home/flintx/soma-grok-sync-$TIMESTAMP.txt"

# Patterns rsync should ignore (never sync these)
EXCLUDES=(
  --exclude='node_modules'
  --exclude='__pycache__'
  --exclude='.pytest_cache'
  --exclude='*.egg-info'
  --exclude='.venv'
  --exclude='venv'
  --exclude='.git'
  --exclude='.gitignore'
  --exclude='*.log'
  --exclude='distiller.log'
  --exclude='introbeaver.log'
  --exclude='outrobeaver.log'
  --exclude='planbeaver.log'
  --exclude='2026*'
  --exclude='data/*.json'
  --exclude='soma_queue*.json'
  --exclude='.dashboard_port'
  --exclude='soma-grok/'
  --exclude='.trevino-*.json'
  --exclude='output/'
  --exclude='.specstory/'
)

# 1. Snapshot files currently in soma-grok/
declare -A OLD_FILES
if [ -d "$DEST" ]; then
  while IFS= read -r -d '' f; do
    rel="${f#$DEST/}"
    OLD_FILES["$rel"]=1
  done < <(find "$DEST" -type f -print0 2>/dev/null)
fi

# 2. Clean out soma-grok/
echo "==> Cleaning $DEST ..."
rm -rf "${DEST:?}"/*
rm -rf "${DEST:?}"/.[!.]* 2>/dev/null || true

# 3. Copy fresh from source
echo "==> Copying source files ..."
rsync -a "${EXCLUDES[@]}" "$SRC/" "$DEST/"

# 4. Snapshot files now in soma-grok/
declare -A NEW_FILES
while IFS= read -r -d '' f; do
  rel="${f#$DEST/}"
  NEW_FILES["$rel"]=1
done < <(find "$DEST" -type f -print0 2>/dev/null)

# 5. Compare and produce summary
ADDED=0
UPDATED=0
REMOVED=0
UNCHANGED=0

{
  echo "=== soma-grok sync summary ==="
  echo "Date: $(date)"
  echo ""

  # Added / Updated
  ADDED_FILES=()
  UPDATED_FILES=()
  for f in "${!NEW_FILES[@]}"; do
    if [ -z "${OLD_FILES[$f]+x}" ]; then
      ADDED_FILES+=("$f")
    else
      UPDATED_FILES+=("$f")
    fi
  done

  # Removed
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

  echo "---"
  echo "Total files in soma-grok/: $(find "$DEST" -type f | wc -l)"
  echo "Added: ${#ADDED_FILES[@]} | Updated: ${#UPDATED_FILES[@]} | Removed: ${#REMOVED_FILES[@]}"
} | tee "$SUMMARY"

TOTAL=$(find "$DEST" -type f | wc -l)
echo ""
echo "==> Touching all files to today's date..."
find "$DEST" -type f -exec touch -d "today" {} +
echo ""
echo "==> Done. $TOTAL files synced to soma-grok/"
echo "==> Summary saved to: $SUMMARY"
