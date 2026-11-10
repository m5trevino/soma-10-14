#!/usr/bin/env bash
# Publish PEA manifests to the directory Caddy serves.
#
# Why this exists: the engine writes manifests to
#   /root/hetzner/ai-engine/pea_sessions/manifests/
# but Caddy serves /pea/ from
#   /srv/pea-manifests
# and /root is mode 700, so the `caddy` user cannot read the source directly.
# That is the lockdown working as intended, not a bug to route around.
#
# This copies across the permission boundary rather than widening it.
set -euo pipefail

SRC="/root/hetzner/ai-engine/pea_sessions/manifests"
DST="/srv/pea-manifests"

[ -d "$SRC" ] || exit 0
mkdir -p "$DST"

# Publish manifests with the server's filesystem layout removed.
#
# The engine's own copy keeps "dir" and "path" because it is a local record.
# The published copy must not: those fields are an absolute-path map of the
# host, and /pea/ is world-readable. The viewer only needs "file" and
# "created" -- it reconstructs the remote path from REMOTE_ROOT itself.
for f in "$SRC"/*-manifest.json; do
    [ -e "$f" ] || continue
    python3 - "$f" "$DST/$(basename "$f")" <<'PY'
import json, sys, os
src, dst = sys.argv[1], sys.argv[2]
with open(src, encoding="utf-8") as fh:
    data = json.load(fh)
files = []
for entry in data.get("files") or []:
    if not isinstance(entry, dict):
        continue
    # The viewer groups files into runs by "dir" (pea_viewer.py:135,287), so
    # the basename is required. The absolute path is not: it is an
    # unauthenticated map of the host, and the viewer rebuilds the remote path
    # from REMOTE_ROOT. Publish the basename only.
    dir_name = (entry.get("dir") or "").rstrip("/").split("/")[-1]
    files.append({
        "file": entry.get("file", ""),
        "dir": dir_name,
        "created": entry.get("created", ""),
    })
out = {
    "day": data.get("day", ""),
    "updated": data.get("updated", ""),
    "count": len(files),
    "files": files,
}
tmp = dst + ".tmp"
with open(tmp, "w", encoding="utf-8") as fh:
    json.dump(out, fh, indent=2)
os.replace(tmp, dst)
PY
done

chmod 644 "$DST"/*-manifest.json 2>/dev/null || true
chown root:root "$DST"/*-manifest.json 2>/dev/null || true

# Drop manifests older than 30 days so the directory does not grow forever.
find "$DST" -name '*-manifest.json' -mtime +30 -delete 2>/dev/null || true
