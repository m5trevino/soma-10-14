#!/usr/bin/env python3
"""PEA manifest viewer — watch the engine write logs, pull any one on demand.

Reads the daily manifest the engine publishes at
https://herbert.save-aichats.com/pea/<date>-manifest.json, lists what has been
written today, and pulls a chosen file to this machine with scp when you press
its button.

Nothing is downloaded automatically. A file sits on the server until you ask
for it; when you do, it is saved into the local session directory so pressing
the button again re-reads the saved copy instead of transferring it twice.

Usage:
    python3 tools/pea_manifest_view.py            # serve and open a browser
    python3 tools/pea_manifest_view.py --no-open  # serve only
    python3 tools/pea_manifest_view.py --port 9880
"""
from __future__ import annotations

import argparse
import json
import subprocess
import threading
import time
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

MANIFEST_BASE = "https://herbert.save-aichats.com/pea"
REMOTE = "engine"
LOCAL_ROOT = Path.home() / "pea-sessions"
DEFAULT_PORT = 9880
CACHE = 5.0

_lock = threading.Lock()
_cache: dict[str, tuple[float, list[dict], str]] = {}


def fetch_manifest(day: str) -> tuple[list[dict], str]:
    """Files for one day. Cached briefly so the page can poll cheaply."""
    now = time.monotonic()
    with _lock:
        hit = _cache.get(day)
        if hit and now - hit[0] < CACHE:
            return hit[1], hit[2]
    url = f"{MANIFEST_BASE}/{day}-manifest.json"
    try:
        with urllib.request.urlopen(url, timeout=15) as r:
            body = json.loads(r.read().decode("utf-8"))
        files = body.get("files") or []
        err = ""
    except Exception as exc:
        files, err = [], f"{type(exc).__name__}: {exc}"
    with _lock:
        _cache[day] = (now, files, err)
    return files, err


def session_dir(path: str) -> Path:
    """Local directory mirroring the remote one, named after it."""
    return LOCAL_ROOT / Path(path).parent.name


def local_copy(entry: dict) -> Path:
    return session_dir(entry["path"]) / entry["file"]


def pull(entry: dict) -> tuple[bool, str]:
    """Copy one file down, unless it is already here.

    The transfer is a plain scp of the exact path the manifest recorded, so
    nothing is re-derived and the bytes are identical to the server's.
    """
    target = local_copy(entry)
    if target.exists() and target.stat().st_size > 0:
        return True, "already saved"
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        res = subprocess.run(
            ["scp", "-q", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
             f"{REMOTE}:{entry['path']}", str(target)],
            capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        return False, "scp timed out"
    if res.returncode != 0:
        return False, (res.stderr or "scp failed").strip()[:200]
    return True, "downloaded"


# ── bulk job ────────────────────────────────────────────────────────────
#
# One button downloads every file for the selected day. The job runs in a
# background thread and reports each phase, so the page can show the command
# being sent, which file is in flight, and the completion, rather than going
# quiet for the length of the transfer.

_job_lock = threading.Lock()
_job: dict = {"running": False, "phase": "idle", "total": 0, "done": 0,
              "failed": 0, "current": "", "log": [], "started": "",
              "finished": ""}


def _job_reset(total: int) -> None:
    with _job_lock:
        _job.update({"running": True, "phase": "starting", "total": total,
                     "done": 0, "failed": 0, "current": "", "log": [],
                     "started": time.strftime("%H:%M:%S"), "finished": ""})


def _job_note(msg: str) -> None:
    with _job_lock:
        _job["log"].append(f"{time.strftime('%H:%M:%S')}  {msg}")
        del _job["log"][:-200]


def _job_update(**kw) -> None:
    with _job_lock:
        _job.update(kw)


def _bulk(files: list[dict]) -> None:
    """Transfer every listed file, one scp per file, reporting as it goes."""
    _job_reset(len(files))
    _job_update(phase="sending")
    _job_note(f"scp {REMOTE}:<path> {LOCAL_ROOT}/<session>/")
    _job_note(f"{len(files)} file(s) queued")

    for i, entry in enumerate(files, start=1):
        name = entry.get("file", "?")
        _job_update(current=name, done=i - 1)
        _job_note(f"[{i}/{len(files)}] {name}")
        ok, note = pull(entry)
        with _job_lock:
            if ok:
                _job["done"] += 1
            else:
                _job["failed"] += 1
            _job["log"].append(f"        {note}")

    with _job_lock:
        _job.update({"running": False, "phase": "complete",
                     "current": "", "finished": time.strftime("%H:%M:%S")})
        _job["log"].append(
            f"{time.strftime('%H:%M:%S')}  complete: {_job['done']} saved, "
            f"{_job['failed']} failed")


def start_bulk(files: list[dict]) -> bool:
    with _job_lock:
        if _job["running"]:
            return False
    threading.Thread(target=_bulk, args=(files,), daemon=True).start()
    return True


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, obj: dict) -> None:
        self._send(code, json.dumps(obj).encode(), "application/json")

    def do_GET(self):
        u = urlparse(self.path)
        if u.path in ("/", "/index.html"):
            # The page lives in its own file so the hardware styling can be
            # edited without touching the server logic.
            page = Path(__file__).with_name("pea_view.html")
            if page.is_file():
                self._send(200, page.read_bytes(), "text/html; charset=utf-8")
            else:
                self._send(500, b"pea_view.html missing beside the server",
                           "text/plain; charset=utf-8")
            return
        if u.path == "/api/manifest":
            day = (parse_qs(u.query).get("day") or [""])[0]
            if not day:
                from datetime import date
                day = date.today().isoformat()
            files, err = fetch_manifest(day)
            self._json(200, {"files": files, "error": err, "count": len(files),
                             "day": day, "source": MANIFEST_BASE})
            return
        if u.path == "/api/job":
            with _job_lock:
                self._json(200, dict(_job))
            return
        if u.path == "/file":
            raw = (parse_qs(u.query).get("p") or [""])[0]
            p = Path(raw)
            if p.is_file() and LOCAL_ROOT in p.parents:
                self._send(200, p.read_bytes(), "text/plain; charset=utf-8")
                return
            self._json(404, {"ok": False})
            return
        self._json(404, {"ok": False})

    def do_POST(self):
        route = urlparse(self.path).path
        if route not in ("/api/pull", "/api/pull-all"):
            self._json(404, {"ok": False})
            return
        try:
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            self._json(400, {"ok": False, "note": "bad request"})
            return

        if route == "/api/pull-all":
            files = [f for f in (body.get("files") or []) if f.get("path")]
            if not files:
                self._json(200, {"ok": False, "note": "nothing to download"})
                return
            started = start_bulk(files)
            self._json(200, {
                "ok": started,
                "note": "" if started else "a download is already running",
                "count": len(files),
            })
            return

        entry = body
        ok, note = pull(entry)
        self._json(200, {"ok": ok, "note": note,
                         "local": str(local_copy(entry))})


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--no-open", action="store_true")
    a = ap.parse_args()

    LOCAL_ROOT.mkdir(parents=True, exist_ok=True)
    # A fixed port collides with whatever else is already listening. Bind the
    # requested one if free, otherwise take the next free port.
    port = a.port
    for candidate in range(a.port, a.port + 40):
        try:
            srv = ThreadingHTTPServer(("127.0.0.1", candidate), Handler)
            port = candidate
            break
        except OSError:
            continue
    else:
        print(f"  no free port in {a.port}-{a.port + 39}", file=__import__("sys").stderr)
        return 1
    url = f"http://127.0.0.1:{port}/"
    print(f"  PEA manifest viewer  {url}")
    print(f"  source   {MANIFEST_BASE}")
    print(f"  saving   {LOCAL_ROOT}/<session>/")
    if not a.no_open:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n  stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
