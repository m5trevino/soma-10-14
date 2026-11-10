# PEA manifest sync

## The problem

The PEA viewer shows nothing because two halves of the chain were never
connected:

```
engine writes  ->  /root/hetzner/ai-engine/pea_sessions/manifests/2026-11-04-manifest.json
                   (pea_trace.py:276 _append_manifest)

caddy serves   ->  /srv/pea-manifests/*          (Caddyfile, root * /srv/pea-manifests)

nothing copies between them.
```

`/root` is mode `700` and Caddy runs as user `caddy`, so pointing Caddy at the
source is not an option — verified blocked. That is the lockdown doing its job.

## The fix

A systemd timer copies the manifests across the permission boundary every
minute, leaving `/root` at `700`.

```bash
# on engine
scp -r /home/flintx/soma-10-14/deploy/* engine:/tmp/deploy/
ssh engine 'sudo install -m 755 /tmp/deploy/pea-manifest-sync.sh /usr/local/bin/'
ssh engine 'sudo install -m 644 /tmp/deploy/pea-manifest-sync.service /etc/systemd/system/'
ssh engine 'sudo install -m 644 /tmp/deploy/pea-manifest-sync.timer   /etc/systemd/system/'
ssh engine 'sudo systemctl daemon-reload'
ssh engine 'sudo systemctl enable --now pea-manifest-sync.timer'

# verify
ssh engine 'sudo systemctl start pea-manifest-sync.service'
ssh engine 'ls -la /srv/pea-manifests/'
```

Then confirm from here:

```bash
curl -s -o /dev/null -w '%{http_code}\n' \
  https://herbert.save-aichats.com/pea/2026-11-04-manifest.json
# expect 200
```

## Why not serve the whole PEA directory publicly

Considered and rejected. Three reasons:

1. **The log files carry `Authorization` headers.** All 283 files with one are
   currently masked (`Bearer sk-xt-...791b`), but that masking is a convention
   in the writer (`pea_trace.py`), not an enforced guarantee. A new provider
   that formats its headers differently puts a live key in a world-readable
   directory. 30 MB of cached-call payloads is not worth that surface.

2. **CORS is not access control.** `Access-Control-Allow-Origin` governs
   whether a *browser* may read a cross-origin response. It does not stop
   `curl`, a script, or a crawler. Publishing behind CORS is publishing.

3. **Authenticated pull already works.** `pea_viewer.py:_scp()` copies one
   file to `~/pea-sessions/` on demand over SSH with the user's key. That is
   the correct posture for a payload: fetch what you are looking at, with
   credentials, and nothing else.

The manifest is the one thing that must be public, because the viewer runs in
a browser and needs to know what exists before it can ask for a file.

## The published manifest is stripped

The engine's own manifest carries `dir` and `path` — absolute host paths:

```
"dir":  "/root/hetzner/ai-engine/pea_sessions/11-04-26-0327AM-app.enhancement.advice"
"path": "/root/hetzner/ai-engine/pea_sessions/.../11-04-26-0327AM-distiller-FAIL.txt"
```

`/pea/` is world-readable, so publishing that is publishing a filesystem map.
The sync script rewrites each entry to `{file, dir, created}` where `dir` is
the **basename only**. The viewer groups runs by that basename
(`pea_viewer.py:135,287`) and rebuilds the remote path from `REMOTE_ROOT`, so
nothing breaks.

## Why a timer and not a write inside the engine

Writing to `/srv` from `_append_manifest()` would work, but it ties the engine
to one deployment layout. A timer keeps the engine unaware of where its output
is published, survives an engine restart, and can be swapped for rsync or an
upload later without touching Python.

## Alternative if you ever leave /root at 700 by accident

If the timer is running but the viewer still 404s, check in this order:

1. `systemctl status pea-manifest-sync.timer` — is it active?
2. `journalctl -u pea-manifest-sync.service -n 20` — did the copy fail?
3. `ls -la /srv/pea-manifests/` — are files there and mode 644?
4. `curl -sI https://.../pea/<date>-manifest.json` — is Caddy serving?
