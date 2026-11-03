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


PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>PEA manifests</title>
<style>
 :root { color-scheme: dark; }
 body { background:#0b0d12; color:#d8dbe2; font:14px/1.5 ui-monospace,monospace;
        margin:0; padding:18px 22px; }
 h1 { font-size:15px; font-weight:600; margin:0 0 2px; color:#7fd1e0; }
 .sub { color:#6b7280; font-size:12px; margin-bottom:14px; }
 .bar { display:flex; gap:10px; align-items:center; margin-bottom:12px; }
 input[type=date] { background:#151922; color:#d8dbe2; border:1px solid #262c38;
        border-radius:5px; padding:4px 7px; font:inherit; }
 button { background:#151922; color:#8fd3e6; border:1px solid #2b3444;
        border-radius:5px; padding:4px 11px; font:inherit; cursor:pointer; }
 button:hover { border-color:#3f6f80; color:#bfeaf5; }
 button:disabled { opacity:.45; cursor:default; }
 .dot { width:8px; height:8px; border-radius:50%; display:inline-block; }
 table { width:100%; border-collapse:collapse; }
 th { text-align:left; font-weight:600; color:#8a93a3; font-size:11px;
      text-transform:uppercase; letter-spacing:.06em; padding:6px 8px;
      border-bottom:1px solid #222836; }
 td { padding:6px 8px; border-bottom:1px solid #171c26; vertical-align:top; }
 tr:hover td { background:#10141c; }
 .f { color:#e2e6ee; }
 .ok { color:#3ddc84; } .fail { color:#ff5f6d; }
 .when { color:#6b7280; }
 .st { font-size:12px; }
 .err { color:#ff8a8a; background:#1d1114; border:1px solid #3a1d22;
        padding:8px 10px; border-radius:5px; margin-bottom:12px; }
 .empty { color:#5b6472; padding:24px 2px; }
 .all { background:#16281f; color:#7fe0a0; border-color:#2c5140; }
 .all:hover { border-color:#3f7a5c; color:#b6f5cc; }
 .prog { margin:10px 0 14px; }
 .track { height:5px; background:#151922; border:1px solid #222836;
          border-radius:3px; overflow:hidden; }
 .fill { height:100%; width:0; background:#3f7a5c; transition:width .25s; }
 .pmeta { color:#8a93a3; font-size:12px; margin-top:5px; }
 .jlog { background:#0d1016; border:1px solid #1b2029; border-radius:5px;
         margin-top:8px; padding:8px 10px; max-height:190px; overflow:auto;
         font-size:12px; color:#8892a3; white-space:pre-wrap; }
</style></head><body>
<h1>PEA manifests</h1>
<div class="sub" id="sub">reading&hellip;</div>
<div class="bar">
  <label>day <input type="date" id="day"></label>
  <button id="refresh">refresh</button>
  <button id="all" class="all">download all</button>
  <span class="st" id="state"></span>
</div>
<div class="prog">
  <div class="track"><div class="fill" id="fill"></div></div>
  <div class="pmeta" id="pmeta">idle</div>
  <div class="jlog" id="jlog" hidden></div>
</div>
<div id="err"></div>
<table><thead><tr>
  <th style="width:46%">file</th><th style="width:16%">stage</th>
  <th style="width:16%">created</th><th style="width:22%"></th>
</tr></thead><tbody id="rows"></tbody></table>
<div class="empty" id="empty" hidden>no files written today yet</div>
<script>
const dayEl = document.getElementById('day');
const rowsEl = document.getElementById('rows');
const stateEl = document.getElementById('state');
const subEl = document.getElementById('sub');
const errEl = document.getElementById('err');
const emptyEl = document.getElementById('empty');

const today = new Date().toISOString().slice(0,10);
dayEl.value = today;

function stageOf(f){
  const m = f.replace(/^.*?-([a-z]+)-(SUCCESS|FAIL)\\.txt$/, '$1');
  return m === f ? '—' : m;
}
function okOf(f){ return f.endsWith('SUCCESS.txt'); }

async function load(){
  const day = dayEl.value || today;
  stateEl.textContent = '·';
  try {
    const r = await fetch('/api/manifest?day=' + encodeURIComponent(day));
    const d = await r.json();
    errEl.innerHTML = d.error ? '<div class="err">' + d.error + '</div>' : '';
    subEl.textContent = d.files.length + ' file' + (d.files.length===1?'':'s')
      + ' · ' + (d.count||0) + ' recorded · updated ' + (d.updated || '—')
      + ' · source ' + d.source;
    rowsEl.innerHTML = '';
    emptyEl.hidden = d.files.length > 0;
    currentFiles = d.files;
    for (const e of d.files.slice().reverse()){
      const tr = document.createElement('tr');
      const ok = okOf(e.file);
      tr.innerHTML =
        '<td class="f">' + e.file + '</td>' +
        '<td>' + stageOf(e.file) + '</td>' +
        '<td class="when">' + (e.created||'').replace('T',' ').replace('Z','') + '</td>' +
        '<td></td>';
      const cell = tr.lastElementChild;
      const b = document.createElement('button');
      b.textContent = 'read';
      b.onclick = () => read(e, b, cell);
      cell.appendChild(b);
      rowsEl.appendChild(tr);
    }
    stateEl.textContent = 'live';
  } catch (x) {
    stateEl.textContent = 'error';
    errEl.innerHTML = '<div class="err">' + x + '</div>';
  }
}

async function read(e, btn, cell){
  btn.disabled = true;
  cell.innerHTML = '<span class="st">pulling…</span>';
  try {
    const r = await fetch('/api/pull', {method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({path:e.path, file:e.file, dir:e.dir})});
    const d = await r.json();
    if (d.ok){
      cell.innerHTML = '<span class="st ok">' + d.note + '</span> ' +
        '<a href="/file?p=' + encodeURIComponent(d.local) +
        '" target="_blank" style="color:#8fd3e6">open</a>';
    } else {
      cell.innerHTML = '<span class="st fail">' + d.note + '</span>';
      btn.disabled = false; cell.appendChild(btn);
    }
  } catch (x) {
    cell.innerHTML = '<span class="st fail">' + x + '</span>';
    btn.disabled = false; cell.appendChild(btn);
  }
}

document.getElementById('refresh').onclick = load;
dayEl.onchange = load;

// ── bulk download ──────────────────────────────────────────────────
const allBtn = document.getElementById('all');
const fillEl = document.getElementById('fill');
const pmetaEl = document.getElementById('pmeta');
const jlogEl = document.getElementById('jlog');
let currentFiles = [];

allBtn.onclick = async () => {
  if (!currentFiles.length) return;
  allBtn.disabled = true;
  pmetaEl.textContent = 'sending command…';
  jlogEl.hidden = false; jlogEl.textContent = '';
  try {
    const r = await fetch('/api/pull-all', {method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({files: currentFiles})});
    const d = await r.json();
    if (!d.ok) { pmetaEl.textContent = d.note || 'could not start'; allBtn.disabled = false; }
  } catch (x) {
    pmetaEl.textContent = String(x); allBtn.disabled = false;
  }
};

async function pollJob(){
  try {
    const r = await fetch('/api/job');
    const j = await r.json();
    if (j.phase === 'idle'){ return; }
    const pct = j.total ? Math.round(100 * j.done / j.total) : 0;
    fillEl.style.width = pct + '%';
    fillEl.style.background = j.phase === 'complete' && !j.failed
      ? '#3ddc84' : (j.failed ? '#c2503d' : '#3f7a5c');
    const bits = [];
    if (j.running) bits.push('running');
    else bits.push('complete');
    bits.push(j.done + '/' + j.total + ' saved');
    if (j.failed) bits.push(j.failed + ' failed');
    if (j.current) bits.push('→ ' + j.current);
    if (j.started) bits.push('start ' + j.started);
    if (j.finished) bits.push('end ' + j.finished);
    pmetaEl.textContent = bits.join(' · ');
    if (j.log && j.log.length){
      jlogEl.textContent = j.log.join('\\n');
      jlogEl.scrollTop = jlogEl.scrollHeight;
    }
    allBtn.disabled = j.running;
    if (!j.running) allBtn.disabled = false;
  } catch (_) {}
}
setInterval(pollJob, 800);
pollJob();

document.getElementById('refresh').onclick = load;
load();
setInterval(load, 5000);
</script></body></html>
"""


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
            self._send(200, PAGE.encode(), "text/html; charset=utf-8")
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
