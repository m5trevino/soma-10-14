# Discovery Notes: soma-session-picker

TARGET: soma-session-picker
SLUG: soma-session-picker
RUN: 20261022T102813Z-496d3c
PASS: 1 (discovery)
STARTED: 2026-10-22T10:28:13Z
ANALYST: Droid (DeepSeek V4.1 Flash)

## Target lock

- Canonical target: soma-session-picker
- Scope sentence: FastAPI + Vite web UI for browsing chat sessions, maintaining favorites, and exporting a queue consumed by Soma.
- Excluded: every other component; `soma`, `turn-key`, `ai-engine`, and all stage modules were not opened for internals.
- Local roots examined: `/home/flintx/soma-10-14/soma-session-picker`
- Remote roots examined: none registered (`01-inventory.json` remote = {})
- Probe window: 2026-10-22T10:28Z to 2026-10-22T10:40Z

## Inventory summary

| Root | Host | Exists | Files (depth 3) | Newest file | Newest mtime |
|---|---|---:|---:|---|---|
| `/home/flintx/soma-10-14/soma-session-picker` | flintx | yes | 23 (excluding node_modules/venv bodies) | `backend/main.py` | 2026-10-21T19:21:35Z |
| `/home/flintx/soma-10-14/soma-session-picker/frontend/dist` | flintx | yes | 3 | `dist/assets/index-*.js` | 2026-10-20T05:12:03Z |
| `/media/storage/graphdb/session_site/vault.db` | flintx | yes | 1 file | DB file | mtime 2026-10-16T13:28:49Z |
| `/media/storage/dendritic123/chat-logs/sessions` | flintx | yes | 4792 session dirs | `waypoint.walker.script.online/` | 2026-10-21T17:24Z |

- Repository state (git HEAD, branch, dirty): not a git repository; `git -C . rev-parse --show-toplevel` and `git -C /home/flintx/soma-10-14 rev-parse --show-toplevel` both returned "not a git repository" [E-052].
- Archives or mirrors discovered: none inside the root.
- Inventory artifacts: `01-inventory.txt`, `01-inventory.json`.
- Python runtime: `backend/venv/bin/python` 3.11.2; fastapi 0.115.0, uvicorn 0.30.6, aiosqlite 0.20.0, python-dotenv 1.0.1 [E-006].

## Entry points

| Path | Host | Role | Lines | Mtime | Evidence |
|---|---|---|---:|---|---|
| `start.sh` | flintx | launcher; kills 8001/5174, creates venv, runs uvicorn and vite | 77 | 2026-10-18T03:39:36Z | [E-028] |
| `backend/main.py` | flintx | FastAPI app, all routes, queue/profile/export writers | 671 | 2026-10-21T19:21:35Z | [E-005] |
| `backend/db.py` | flintx | aiosqlite connection factory and DATABASE_PATH resolution | 34 | 2026-10-18T03:33:08Z | [E-027] |
| `frontend/src/App.jsx` | flintx | React UI state, API calls, favorites, export | 689 | 2026-10-19T19:44:51Z | [E-030] |
| `frontend/dist/index.html` | flintx | built UI served by FastAPI at `/` when present | 1 | 2026-10-20T05:12:03Z | [E-047] |

- Confirmed executable/importable surfaces: `backend/main.py` imports cleanly under `backend/venv/bin/python`; `main.app.routes` enumerated 12 API routes plus static/docs routes [E-005].
- Launch scripts and actual exec targets: `start.sh:32` runs `python3 -m uvicorn main:app --host 0.0.0.0 --port 8001` after `cd backend`; `start.sh:49` runs `npx vite --host 0.0.0.0 --port 5174` [E-028].
- Entry points named in docs but absent: `/api/filter-options` (DOCUMENTATION.md:299) has no route; `backend/data/soma_sessions.db` (DOCUMENTATION.md:685) does not exist.
- No test files, README, AGENTS.md, or CLAUDE.md exist inside the root [E-051].

## Runtime state

- Process inspection command: `ps -eo pid,lstart,etimes,cmd | rg -i 'uvicorn|main:app|vite|soma-session-picker'` on flintx at 2026-10-22T10:28Z [E-001].
- Matching processes (PID, elapsed, command): none. The only python/node processes were glances, guake, blueman, fusermount, multiclip.
- Listening sockets: `ss -lntp` showed no listener on 8001 or 5174 [E-002].
- HTTP probes: `curl -sS -m 5 http://127.0.0.1:8001/api/health` returned connection refused (curl exit 7, HTTP 000) at 2026-10-22T10:28Z [E-003].
- Service units: local SysVinit is irrelevant here; no unit named soma-session-picker was found, and no `systemctl` command was run on flintx.
- Queue/state files and mtimes:
  - `data/soma_queue.json` 2026-10-18T08:47:29Z, 119 bytes, keys `selected/count/timestamp` [E-045].
  - `backend/data/soma_queue.json` 2026-10-18T17:15:44Z, 67 bytes, keys `selected/count/timestamp` [E-045].
  - `/home/flintx/soma-10-14/data/soma_queue.json` 2026-10-22T03:03:42Z, 1787 bytes, keys `selected/count/running/started_at/profile/finished_at/exit_code` [E-045].
  - `/home/flintx/.soma_queue.json` absent [E-045].
- Last log lines: `/tmp/soma-picker-backend.log` and `/tmp/soma-picker-frontend.log` do not exist [E-004].
- Evidence of last execution: `backend/__pycache__/main.cpython-311.pyc` mtime 2026-10-21T18:59:30Z predates `main.py` mtime 2026-10-21T19:21:35Z, so the running code was not re-imported after the last source edit [E-005].
- `backend/vault.db` exists but is a zero-byte file, mtime 2026-10-21T04:53:46Z [E-046].

## Data stores

| Store | Host | Engine | Schema summary | Rows | Newest record | Access | Evidence |
|---|---|---|---|---|---:|---|---|---|
| `/media/storage/graphdb/session_site/vault.db` | flintx | SQLite 3.40.1 | `sessions`, `dev_sessions`, `chat_anchors`, `session_metadata`, `chat_set_metadata`, FTS5 tables | sessions 6015; dev_sessions 4792 | `sessions.date` max 2026-06-22 | read-only (`sqlite3 -readonly`) | [E-037][E-038] |
| `/media/storage/dendritic123/chat-logs/sessions` | flintx | filesystem | 4792 dirs, 4792 `session.json`, 73 `*.meta.json` | 4792 dirs | dir mtime 2026-10-21T17:24Z | read-only | [E-042] |
| `data/soma_queue.json` | flintx | JSON | picker queue format (`selected/count/timestamp`) | 1 selected | 2026-10-18T08:47:29Z | read | [E-045] |
| `backend/data/soma_queue.json` | flintx | JSON | picker queue format | 0 selected | 2026-10-18T17:15:44Z | read | [E-045] |
| `/home/flintx/soma-10-14/data/soma_queue.json` | flintx | JSON | runner-extended queue (`running/started_at/profile/finished_at/exit_code`) | 18 selected | 2026-10-22T03:03:42Z | read | [E-045] |
| `/home/flintx/soma-10-14/session-picker-json/` | flintx | filesystem | UI export artifacts | 1 file, 18 sessions | 2026-10-21T18:35:56Z | read | [E-050] |

- Tables actually queried by the target: `sessions` in `_build_meta_cache` and `session_counts`; `dev_sessions` in `_build_full_cache` and score-range query [E-014][E-019].
- ID namespace mismatch: only 3051 `dev_sessions.session_id` values join `sessions.session_id` exactly; 3935 match by tail segment [E-039]. `_build_meta_cache` stores both exact and tail keys, so 3935 of 4792 rows receive metadata at runtime [E-040].
- Stores present but unused by this target: `chat_anchors`, `session_metadata`, `chat_set_metadata`, FTS tables; `backend/vault.db` (empty).
- Locked or unreadable stores: none encountered; DB was opened read-only.

## Configuration and invariants

| Key / rule | Source path:line | Default | Effective value (redacted if secret) | Enforced in code? |
|---|---|---|---|---|
| `DATABASE_PATH` | `backend/.env:1`, `backend/db.py:8-19` | `./vault.db` | `/media/storage/graphdb/session_site/vault.db` | yes when `main.py` is imported from `backend/` and `load_dotenv()` runs |
| `SESSIONS_PATH` | `backend/.env:2`, `backend/main.py:30-33` | `/media/storage/dendritic123/chat-logs/sessions` | same | yes |
| `QUEUE_OUTPUT_PATH` | `backend/.env:3`, `backend/main.py:34-37` | `~/.soma_queue.json` | `/home/flintx/soma-10-14/soma-session-picker/data/soma_queue.json` | yes |
| hard-coded second queue path | `backend/main.py:531-534`, `backend/main.py:553-556` | none | `/home/flintx/soma-10-14/data/soma_queue.json` | yes |
| launch output path | `backend/main.py:578` | none | `/home/flintx/soma-10-14/data/soma_launch.json` | yes; file absent at probe time |
| profile path | `backend/main.py:41-44` | none | `/home/flintx/soma-10-14/soma/turn-key-profiles/soma-current.json` | read-only; exists [E-008] |
| CORS origin | `backend/main.py:84-90` | none | `http://localhost:5174` | yes |
| bind address | `start.sh:32`, `start.sh:49` | none | `0.0.0.0` for both services | yes |
| cache lifetime | `backend/main.py:367-369` | process lifetime | never invalidated after first build | yes |
| request limit | `backend/main.py:361`, `backend/main.py:429` | 500 | caller-supplied; no upper bound | yes |
| launch validation | `backend/main.py:613-623` | none | `count` must be non-negative int | yes; rejects `mode=all` from UI [E-032] |

- Config precedence observed: `os.environ` first; `main.py:19-20` `load_dotenv()` searches from the process cwd; `db.py:11-15` additionally looks for `<root>/.env`, which does not exist [E-027]. Effective config was confirmed by importing `main` from `backend/` [E-005].
- Environment variables read (names only): `DATABASE_PATH`, `SESSIONS_PATH`, `QUEUE_OUTPUT_PATH`.
- Profiles / model decks: `/api/profile` returns `name` and `deck[]` reduced to `{modelId, provider}` [E-017]. Live file has `name: ""` and at least four cards [E-054].
- Hard gates and validation rules: `/api/launch` validates types/values [E-024]; `/api/sessions/load` requires a path and rejects missing/invalid JSON [E-016]; metadata endpoint requires an existing session directory [E-020].
- Invariants documented but not enforced: DOCUMENTATION.md claims no database dependency (line 18) and lists endpoints/params that are absent (lines 248-251, 299-311) [E-048].
- Cache invalidation: none. `.meta.json` is trusted whenever present [E-012]; `_full_cache` is built once [E-014].

## Cross-component edges

| Direction | Counterpart | Mechanism | Payload / contract | Evidence |
|---|---|---|---|---|
| target → soma | `soma.machinetalk.session_metadata` | Python import, with `spec_from_file_location` fallback | `extract_session_metadata(session_dir: str \| Path) -> dict` | [E-009] |
| target → filesystem | session vault | read `session.json`, count `*.json` chatsets | title/total_sets/total_session_chars/models_used/chatset count | [E-011][E-013] |
| target → filesystem | session vault | write `{session_id}.meta.json` on metadata request | full extraction dict | [E-020] |
| target → filesystem | `QUEUE_OUTPUT_PATH` | JSON write on POST `/api/select` and `/api/select-with-metadata` | `{selected, count, timestamp}` | [E-021] |
| target → filesystem | `/home/flintx/soma-10-14/data/soma_queue.json` | JSON write on the same POSTs | same payload; overwrites any runner fields | [E-021][E-045] |
| target → filesystem | `/home/flintx/soma-10-14/data/soma_launch.json` | JSON write on POST `/api/launch` | `{json_path, mode, count, timestamp}` | [E-024] |
| target → filesystem | `<base>/session-picker-json/export_*.json` | file write on GET `/api/select/export` | current queue JSON | [E-025] |
| target → turn-key profile | `soma/turn-key-profiles/soma-current.json` | file read | profile name + deck model IDs/providers | [E-017] |
| target → SQLite | `vault.db` | `aiosqlite` SELECT only | sessions/dev_sessions rows | [E-014][E-019] |
| browser → target | FastAPI | `/api/*` via Vite proxy `http://localhost:8001` | JSON | [E-030][E-047] |
| target → Soma runner | queue file | file contract only; runner internals not opened | session IDs | [E-045] |

- Edges observed in code but not observed at runtime: every HTTP write path; the services were not running.
- Edges observed at runtime but not found in code: the runner-shaped keys in `/home/flintx/soma-10-14/data/soma_queue.json` are not produced by `backend/main.py` [E-045].
- Boundary gaps (sibling internals deliberately not opened): `soma/machinetalk/session_metadata.py` body; Soma runner queue reader/writer; turn-key deck semantics.

## Instructions and recency

| Document | Path | Host | Mtime | Authority rank | What it claims |
|---|---|---|---:|---|---|
| `DOCUMENTATION.md` | `/home/flintx/soma-10-14/soma-session-picker/DOCUMENTATION.md` | flintx | 2026-10-18T09:18:38Z | 4 (target-local doc) | no DB dependency; `/api/filter-options`; `meta_*` params; queue at `data/soma_queue.json` |
| `INTEGRATION_GUIDE.md` | `/home/flintx/soma-10-14/soma-session-picker/INTEGRATION_GUIDE.md` | flintx | 2026-10-18T09:19:41Z | 4 (target-local doc) | export writes `/home/flintx/soma-10-14/data/soma_queue.json`; cached meta named `NNNNN.meta.json` |
| project README | `/home/flintx/soma-10-14/README.md` | flintx | 2026-10-14T19:19Z | 5 (top-level design doc) | describes Soma runner only; does not mention the picker |
| code | `backend/main.py`, `frontend/src/App.jsx` | flintx | 2026-10-21, 2026-10-19 | 2 (runtime source) | authoritative for behavior |
| live data | `vault.db`, session vault, queue JSON | flintx | 2026-10-22T10:28Z probe | 1 (live state) | authoritative for current state |

- Newest authoritative instruction: none newer than the code; docs predate the last `main.py` edit by 3 days.
- Superseded instructions: DOCUMENTATION.md "no database dependency" and `/api/filter-options`; INTEGRATION_GUIDE cache filename.
- Instructions that contradict code: see Conflicts.
- Archived/chat-log evidence (lowest rank): none used.

## Conflicts

### CONFLICT C-01

- claim A: "no database dependency" and "reads everything from session.json ... on disk" | source: `DOCUMENTATION.md:18`, `DOCUMENTATION.md:30` | mtime: 2026-10-18T09:18:38Z
- claim B: every list and filter request queries SQLite `sessions`/`dev_sessions`; DATABASE_PATH points to a 2.2 GB vault.db | source: `backend/main.py:205-208`, `backend/main.py:234-237`, `backend/.env:1` | mtime: 2026-10-21T19:21:35Z
- resolution: B
- basis: live import + read-only DB query returned 6015/4792 rows [E-038]
- impact on report: the picker is DB-backed; disk reads are supplementary.

### CONFLICT C-02

- claim A: queue is written to `data/soma_queue.json` under the picker | source: `DOCUMENTATION.md:26`, `DOCUMENTATION.md:201`, `backend/.env:3` | mtime: 2026-10-18
- claim B: queue is written to `/home/flintx/soma-10-14/data/soma_queue.json` | source: `backend/main.py:531-534`, `INTEGRATION_GUIDE.md:18-19` | mtime: 2026-10-21
- claim C: default is `~/.soma_queue.json` | source: `backend/main.py:34-37` | mtime: 2026-10-21
- resolution: both-live
- basis: each POST writes `QUEUE_OUTPUT_PATH` and then the hard-coded `soma-10-14/data` path; the effective env path is the picker `data/` file [E-005][E-021]
- impact on report: two files are written per selection; `backend/data/soma_queue.json` is dead.

### CONFLICT C-03

- claim A: endpoints `/api/filter-options` and query params `meta_sub_domain`, `meta_sentiment`, `meta_topics`, `meta_project_context` exist | source: `DOCUMENTATION.md:248-251`, `DOCUMENTATION.md:299-311` | mtime: 2026-10-18
- claim B: route table has no `/api/filter-options`; `get_sessions` accepts only `search, domain, provider, model, min_score, max_score, min_sets, sort, order, limit` | source: `backend/main.py:350-362`, live `main.app.routes` [E-005] | mtime: 2026-10-21
- resolution: B
- basis: imported app route enumeration
- impact on report: documented metadata filtering is unavailable.

### CONFLICT C-04

- claim A: cached metadata files are per-chatset `NNNNN.meta.json` next to chatsets | source: `INTEGRATION_GUIDE.md:310`, `DOCUMENTATION.md:358` | mtime: 2026-10-18
- claim B: cache path is `{session_id}.meta.json` inside the session dir | source: `backend/main.py:137`, `backend/main.py:507` | mtime: 2026-10-21
- resolution: B
- basis: 73 live caches are named `{dir}.meta.json` and the sampled file resolves by the code's lookup [E-044]
- impact on report: cache naming and invalidation follow the code.

### CONFLICT C-05

- claim A: `timestamp` is an epoch-like integer (`1234567890`) | source: `DOCUMENTATION.md:378`, `DOCUMENTATION.md:570` | mtime: 2026-10-18
- claim B: `timestamp` is `asyncio.get_event_loop().time()`, a monotonic float | source: `backend/main.py:524`, `backend/main.py:546`, `backend/main.py:630` | mtime: 2026-10-21
- resolution: B
- basis: live picker-format files contain values such as `211636.864513157` [E-045]
- impact on report: consumers cannot treat the value as wall-clock time.

### CONFLICT C-06

- claim A: the UI "Export" also writes `data/soma_queue.json` and the export is the file Soma consumes | source: `DOCUMENTATION.md:195-201`, `INTEGRATION_GUIDE.md:9-21` | mtime: 2026-10-18
- claim B: the UI downloads a browser Blob and separately POSTs `/api/select`; no server export file is involved in that button | source: `frontend/src/App.jsx:291-345` | mtime: 2026-10-19
- resolution: both-live
- basis: export performs a client download and a queue write; the server-side `/api/select/export` route is never called by the UI [E-030][E-033][E-025]
- impact on report: two distinct export mechanisms exist; only one is wired to the UI.

### CONFLICT C-07

- claim A: sessions have a `title` shown in the table | source: `DOCUMENTATION.md:269`, `frontend/src/components/SessionTable.jsx:103` | mtime: 2026-10-18
- claim B: `title` resolves from `session.json.title` or `.name`; live `session.json` has neither, so all 4792 rows return `title=""` | source: `backend/main.py:179`, live cache count [E-040] | mtime: 2026-10-21
- resolution: B
- basis: sampled `session.json` keys and in-process full-cache count (0 titles)
- impact on report: the Title column renders `—` for every row.

### CONFLICT C-08

- claim A: `data/soma_queue.json` holds only `{selected,count,timestamp}` | source: `DOCUMENTATION.md:563-571`, `INTEGRATION_GUIDE.md:18-20` | mtime: 2026-10-18
- claim B: live `/home/flintx/soma-10-14/data/soma_queue.json` also holds `running,started_at,profile,finished_at,exit_code` | source: live file [E-045] | mtime: 2026-10-22T03:03:42Z
- resolution: unresolved (second writer)
- basis: `backend/main.py` never writes those keys; the writer is outside this target's code
- impact on report: the picker and the Soma runner share one mutable path with incompatible payloads.

### CONFLICT C-09

- claim A: `/api/select` accepts `{session_ids: [...]}` | source: `backend/main.py:520`, `DOCUMENTATION.md:368-370` | mtime: 2026-10-21
- claim B: the UI posts `{selected: [...], count, timestamp}` | source: `frontend/src/App.jsx:317-327` | mtime: 2026-10-19
- resolution: both-live, incompatible
- basis: backend reads `request.get("session_ids", [])`, so a UI export writes `selected: []` while the downloaded file keeps the favorites [E-055]
- impact on report: the UI export clears the queue file instead of populating it.

## Unknowns and boundary gaps

### U-01

- Unknown: which cwd and environment the backend used on its last real run.
- Why it matters: `load_dotenv()` is cwd-dependent; a run from outside `backend/` leaves `DATABASE_PATH` unset and would create/use `./vault.db` (the zero-byte file).
- Evidence that would close it: preserved `/tmp/soma-picker-backend.log`, a process env dump, or shell history for the launch.
- Command or path not run (and why): no live process exists; `ps e` cannot recover a dead process env.

### U-02

- Unknown: which component writes the runner keys into `/home/flintx/soma-10-14/data/soma_queue.json`.
- Why it matters: the picker can overwrite run state (`running`, `exit_code`) with a three-key payload at any selection.
- Evidence that would close it: Soma runner source or a write trace; this target's scope excludes sibling internals.
- Command or path not run (and why): `soma/` runner files were not opened by scope fence.

### U-03

- Unknown: whether a picker POST during an active Soma run truncates runner state.
- Why it matters: destructive race on a shared state file.
- Evidence that would close it: instrumented POST while a run is active, or code read of the runner's read/write order.
- Command or path not run (and why): writes are forbidden by the read-only rule.

### U-04

- Unknown: why only 73 of 4792 sessions have `.meta.json`.
- Why it matters: metadata panels for the rest trigger on-demand extraction and a write into the session dir.
- Evidence that would close it: access logs or a count of sessions visited in the UI.
- Command or path not run (and why): no logs exist.

### U-05

- Unknown: why `sessions` (6015) and `dev_sessions` (4792) have different ID namespaces and row counts.
- Why it matters: 857 list rows have no metadata even after tail matching; filter dropdowns are built from a different table than the list.
- Evidence that would close it: the ingestion scripts for both tables.
- Command or path not run (and why): ingestion code is outside the target root.

### U-06

- Unknown: whether `frontend/dist` matches `frontend/src` byte-for-byte in behavior.
- Why it matters: FastAPI serves `dist` at `/`; the dev server serves `src`.
- Evidence that would close it: rebuild and compare, or inspect the bundle for each string.
- Probe result: `dist` mtime 2026-10-20T05:12:03Z is later than `App.jsx` 2026-10-19T19:44:51Z; bundle contains "Launch submitted" [E-047].

### U-07

- Unknown: side effects of `soma.machinetalk.session_metadata.extract_session_metadata`.
- Why it matters: the target calls it on the request path and then writes the returned dict itself.
- Evidence that would close it: read the sibling module; excluded by scope.
- Command or path not run (and why): sibling internals intentionally not opened.

### U-08

- Unknown: whether `GET /api/sessions/load?path=` is reachable from non-local networks in practice.
- Why it matters: it reads any file as JSON and the backend binds `0.0.0.0` with no auth.
- Evidence that would close it: host firewall and listener state during a run.
- Command or path not run (and why): service not running; no firewall changes attempted.

### U-09

- Unknown: whether `mode=all` launch ever succeeded against the current backend.
- Why it matters: the UI omits `count` for that mode, while the backend requires an integer.
- Evidence that would close it: a request log or a live POST.
- Command or path not run (and why): POST writes `soma_launch.json`; read-only rule.

### U-10

- Unknown: whether any picker-generated queue file currently contains a UI selection.
- Why it matters: the current UI posts the wrong key, so a fresh export would write an empty selection.
- Evidence that would close it: a live export POST, or a queue file whose `timestamp` matches a UI action.
- Command or path not run (and why): POST writes are forbidden; existing files predate the code's last edit.

## Evidence index

Mirror of `03-evidence-index.tsv`.

| ID | Host | Kind | Locator | Captured at | Proves | Confidence |
|---|---|---|---|---|---|---|
| E-001 | flintx | runtime | `ps -eo pid,lstart,etimes,cmd` filtered | 2026-10-22T10:28Z | no picker/uvicorn/vite process | C1 |
| E-002 | flintx | runtime | `ss -lntp` filtered 8001/5174 | 2026-10-22T10:28Z | no listeners | C1 |
| E-003 | flintx | runtime | `curl http://127.0.0.1:8001/api/health` | 2026-10-22T10:28Z | connection refused | C1 |
| E-004 | flintx | runtime | `ls /tmp/soma-picker-*.log` | 2026-10-22T10:28Z | logs absent | C1 |
| E-005 | flintx | runtime | import `backend/main.py` under venv | 2026-10-22T10:31Z | routes, effective config, import works | C1 |
| E-006 | flintx | runtime | `backend/venv/bin/python --version`, `pip list` | 2026-10-22T10:31Z | Python 3.11.2 and package versions | C1 |
| E-007 | flintx | config | `backend/.env:1-3` | 2026-10-22T10:29Z | three env keys and path values | C2 |
| E-008 | flintx | config | `backend/main.py:41-44` | 2026-10-22T10:29Z | profile path under soma | C2 |
| E-009 | flintx | code | `backend/main.py:50-69` | 2026-10-22T10:31Z | lazy import + file fallback of session_metadata | C2 |
| E-010 | flintx | code | `backend/main.py:75-90` | 2026-10-22T10:29Z | lifespan SELECT 1, app version, CORS | C2 |
| E-011 | flintx | code | `backend/main.py:106-126` | 2026-10-22T10:29Z | session path resolution and chatset counting | C2 |
| E-012 | flintx | code | `backend/main.py:129-143` | 2026-10-22T10:29Z | cached `.meta.json` lookup, no freshness check | C2 |
| E-013 | flintx | code | `backend/main.py:146-185` | 2026-10-22T10:29Z | row composition and title fallback | C2 |
| E-014 | flintx | code | `backend/main.py:196-240` | 2026-10-22T10:29Z | cache SQL and one-time build | C2 |
| E-015 | flintx | code | `backend/main.py:245-254` | 2026-10-22T10:29Z | provider normalization | C2 |
| E-016 | flintx | code | `backend/main.py:260-312` | 2026-10-22T10:29Z | arbitrary-path JSON read endpoint | C2 |
| E-017 | flintx | code | `backend/main.py:315-347` | 2026-10-22T10:29Z | health and profile endpoints | C2 |
| E-018 | flintx | code | `backend/main.py:350-433` | 2026-10-22T10:29Z | filter/sort/limit and post-limit `total` | C2 |
| E-019 | flintx | code | `backend/main.py:436-479` | 2026-10-22T10:29Z | counts queries and score range | C2 |
| E-020 | flintx | code | `backend/main.py:482-514` | 2026-10-22T10:29Z | metadata endpoint writes cache file | C2 |
| E-021 | flintx | code | `backend/main.py:517-536` | 2026-10-22T10:29Z | select writes two queue paths | C2 |
| E-022 | flintx | code | `backend/main.py:539-575` | 2026-10-22T10:29Z | select-with-metadata writes queues and caches | C2 |
| E-023 | flintx | code | `backend/main.py:578-598` | 2026-10-22T10:29Z | launch path and export dir resolution | C2 |
| E-024 | flintx | code | `backend/main.py:601-637` | 2026-10-22T10:29Z | launch validation and write | C2 |
| E-025 | flintx | code | `backend/main.py:640-661` | 2026-10-22T10:29Z | server-side export write | C2 |
| E-026 | flintx | code | `backend/main.py:664-670` | 2026-10-22T10:31Z | static mount of dist | C2 |
| E-027 | flintx | code | `backend/db.py:8-27` | 2026-10-22T10:29Z | DB path resolution and root `.env` lookup | C2 |
| E-028 | flintx | code | `start.sh:8-9`, `start.sh:26-32`, `start.sh:48-49` | 2026-10-22T10:29Z | ports, binds, launch commands | C2 |
| E-029 | flintx | code | `frontend/src/App.jsx:9` | 2026-10-22T10:29Z | API base `/api` | C2 |
| E-030 | flintx | code | `frontend/src/App.jsx:74-144` | 2026-10-22T10:29Z | fetch calls for counts/profile/sessions/metadata | C2 |
| E-031 | flintx | code | `frontend/src/App.jsx:20-25`, `frontend/src/App.jsx:68-70` | 2026-10-22T10:29Z | favorites in localStorage | C2 |
| E-032 | flintx | code | `frontend/src/App.jsx:255-279` | 2026-10-22T10:29Z | launch payload omits count for mode all | C2 |
| E-033 | flintx | code | `frontend/src/App.jsx:291-345` | 2026-10-22T10:29Z | client-side export plus POST /api/select | C2 |
| E-034 | flintx | code | `frontend/src/components/FilterBar.jsx:100-131` | 2026-10-22T10:29Z | sort/limit controls | C2 |
| E-035 | flintx | code | `frontend/src/components/SessionTable.jsx:40-104` | 2026-10-22T10:29Z | table columns and title rendering | C2 |
| E-036 | flintx | code | `frontend/src/components/SessionMetaPanel.jsx:39-46` | 2026-10-22T10:29Z | metadata dict shape expected by UI | C2 |
| E-037 | flintx | data | `sqlite3 -readonly ... '.schema'` on vault.db | 2026-10-22T10:30Z | table schemas | C1 |
| E-038 | flintx | data | `sqlite3 -readonly` COUNT queries | 2026-10-22T10:30Z | sessions 6015; dev_sessions 4792 | C1 |
| E-039 | flintx | data | `sqlite3 -readonly` join/tail queries | 2026-10-22T10:30Z | 3051 exact / 3935 tail matches | C1 |
| E-040 | flintx | runtime | in-process `_build_full_cache()` and `get_sessions()` | 2026-10-22T10:32Z | 4792 cache, 500 returned, 0 titles, 3935 providers | C1 |
| E-041 | flintx | runtime | in-process `session_counts()` | 2026-10-22T10:32Z | 12 providers, 29 domains, 9 models, score 0..406158 | C1 |
| E-042 | flintx | data | `find`/`ls` over sessions root | 2026-10-22T10:30Z | 4792 dirs, 4792 session.json, 73 meta | C1 |
| E-043 | flintx | data | `session.json` sample | 2026-10-22T10:30Z | no title/name; has session_id/provider/sets/chars/models_used | C1 |
| E-044 | flintx | data | `*.meta.json` sample and lookup check | 2026-10-22T10:32Z | cache keys and filename match code | C1 |
| E-045 | flintx | data | queue files `ls` + JSON keys | 2026-10-22T10:30Z | three queue paths, mtimes, runner keys | C1 |
| E-046 | flintx | data | `ls -la backend/vault.db`, `file` | 2026-10-22T10:29Z | zero-byte DB | C1 |
| E-047 | flintx | data | `ls frontend/dist`, `rg` bundle | 2026-10-22T10:31Z | build mtime and bundled launch string | C1 |
| E-048 | flintx | doc | `DOCUMENTATION.md:18`, `:30`, `:248-251`, `:299-311`, `:358`, `:563-571` | 2026-10-22T10:29Z | stale claims | C3 |
| E-049 | flintx | doc | `INTEGRATION_GUIDE.md:18-21`, `:293`, `:310` | 2026-10-22T10:29Z | queue path and cache naming claims | C3 |
| E-050 | flintx | data | `ls /home/flintx/soma-10-14/session-picker-json` | 2026-10-22T10:31Z | one 18-session export, `.base_path` absent | C1 |
| E-051 | flintx | data | `find` for tests/README/AGENTS | 2026-10-22T10:33Z | no tests or local instructions | C1 |
| E-052 | flintx | runtime | `git rev-parse --show-toplevel` | 2026-10-22T10:33Z | not a git repository | C1 |
| E-053 | flintx | runtime | `ss -lntp` full output | 2026-10-22T10:33Z | no 800x/5174 listener | C1 |
| E-054 | flintx | data | `head -c 700 soma-current.json` | 2026-10-22T10:31Z | profile name empty, deck cards present | C1 |
| E-055 | flintx | code | `frontend/src/App.jsx:317-327` + `backend/main.py:520` | 2026-10-22T10:35Z | UI posts `selected`; backend reads `session_ids`, so export posts an empty selection | C2 |
| E-056 | flintx | data | `find . -maxdepth 3 -type f -printf '%TY-%Tm-%Td %TH:%TM:%TS %p\n'` and `ls -la backend/__pycache__` | 2026-10-22T10:33Z | file mtimes: main.py 19:21:35Z, main pyc 18:59:30Z, docs 2026-10-18, dist 2026-10-20T05:12:03Z | C1 |

## Report plan

| Report section | Core claim | Evidence IDs | Diagram? |
|---|---|---|---|
| Mandate | DB-backed session browser whose only durable outputs are a queue JSON and cached metadata | E-014, E-021, E-033 | no |
| Current State | not running; code importable; DB and vault live; dist built | E-001..E-006, E-038, E-042, E-047 | no |
| Key Paths and Entry Points | 5 entry surfaces; ports 8001/5174; two queue paths | E-005, E-007, E-028, E-045 | no |
| Architecture and Data Flow | browser → FastAPI → aiosqlite/vault → queue; Vite proxy | E-009, E-014, E-021, E-030 | yes |
| Core Logic | cache build, filter/sort, metadata cache write, queue double write, UI request-key mismatch, launch validation | E-011..E-025, E-055 | yes |
| Configuration and Invariants | env keys, cwd-dependent dotenv, dual queue path, no cache invalidation | E-007, E-014, E-027, E-032 | no |
| Dependencies and Cross-Component Connections | soma.session_metadata import; profile read; queue shared with runner | E-009, E-017, E-045 | yes |
| Known Gaps and Uncertainties | G-01..G-10 from U-01..U-10 | U-01..U-10 | no |
| Evidence Log | all E rows | E-001..E-056 | no |

## Pass 1 gate

- [x] Target lock matches the request.
- [x] Entry point confirmed (`backend/main.py` imports; 12 routes).
- [x] Runtime state captured (not running; commands and timestamps recorded).
- [x] Every cross-component edge has a mechanism and evidence ID.
- [x] Every conflict resolved or marked unresolved (C-08 unresolved).
- [x] At least three actionable unknowns (U-01..U-10).
- [x] Evidence index has at least 10 rows with confidence classes (56 rows).
