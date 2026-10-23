# Soma Session Picker — Forensic Deep Dive
TARGET: soma-session-picker | RUN: 20261022T102813Z-496d3c | DATE: 2026-10-22 | HOSTS EXAMINED: flintx
CONFIDENCE SUMMARY: runtime state C1; code paths C2; live data C1; docs C3 and contradicted by code | SCOPE: the FastAPI backend, React UI, launch script, and JSON/SQLite stores reachable from `/home/flintx/soma-10-14/soma-session-picker`

## Mandate
The Soma Session Picker is a local FastAPI and React browser over the chat-session vault that turns a persisted favorites list into a JSON queue for Soma.

## Current State

Neither service is running. At 2026-10-22T10:28Z, `ps` found no uvicorn, vite, or picker process [E-001]; `ss -lntp` found no listener on 8001 or 5174 [E-002][E-053]; `curl http://127.0.0.1:8001/api/health` returned connection refused [E-003]; and both launcher logs under `/tmp` are absent [E-004].

The backend is importable and complete. On flintx at 2026-10-22T10:31Z, loading `main` under `backend/venv/bin/python` succeeded and exposed 12 API routes plus FastAPI docs and the static mount [E-005]. The venv is Python 3.11.2 with fastapi 0.115.0, uvicorn 0.30.6, aiosqlite 0.20.0, and python-dotenv 1.0.1 [E-006]. The source was last edited 2026-10-21T19:21:35Z, after the last compiled bytecode at 2026-10-21T18:59:30Z, so no Python process refreshed the bytecode after the last source edit [E-005][E-056].

The live data is present and large. `vault.db` is a 2.2 GB SQLite file with `sessions` at 6015 rows and `dev_sessions` at 4792 rows [E-037][E-038]. The session vault contains 4792 directories, 4792 `session.json` files, and 73 `*.meta.json` caches [E-042]. On flintx at 2026-10-22T10:32Z, an in-process call to the list builder produced a 4792-row cache in 3.0 seconds, but the HTTP response defaults to 500 rows [E-040]. In the same probe, filter options returned 12 providers, 29 domains, and 9 models with scores from 0 to 406158 [E-041].

Several artifacts are stale or inert. `backend/vault.db` is a zero-byte file [E-046]. `backend/data/soma_queue.json` and `data/soma_queue.json` predate the current source by three days [E-045][E-056]. The frontend `dist` build is dated 2026-10-20T05:12:03Z and contains the current launch string [E-047]. There are no tests, no README, and no `AGENTS.md` inside the root [E-051], and the directory is not a git repository [E-052].

The newest verified timestamp in this run is the queue file at `/home/flintx/soma-10-14/data/soma_queue.json`, mtime 2026-10-22T03:03:42Z, whose keys are not produced by this backend [E-045][E-021].

All mtimes in this report are UTC; the raw inventory artifacts preserve the host's local `-0700` strings [E-056].

## Key Paths and Entry Points

| Path | Host | Role | Entrypoint? | Lines | Mtime | Evidence |
|---|---|---|---:|---:|---|---|
| `start.sh` | flintx | kills ports 8001/5174, creates venv, installs requirements, starts uvicorn and vite | yes | 77 | 2026-10-18T03:39:36Z | [E-028] |
| `backend/main.py` | flintx | FastAPI app; all routes; queue, profile, launch, export readers/writers | yes | 671 | 2026-10-21T19:21:35Z | [E-005] |
| `backend/db.py` | flintx | aiosqlite connection and `DATABASE_PATH` resolution | yes | 34 | 2026-10-18T03:33:08Z | [E-027] |
| `backend/.env` | flintx | `DATABASE_PATH`, `SESSIONS_PATH`, `QUEUE_OUTPUT_PATH` | no | 4 | 2026-10-18T03:32:03Z | [E-007] |
| `frontend/src/App.jsx` | flintx | UI state, fetches, favorites, export and launch actions | yes | 689 | 2026-10-19T19:44:51Z | [E-030] |
| `frontend/src/components/FilterBar.jsx` | flintx | search/filter/sort controls | no | 145 | 2026-10-18T09:52Z | [E-034] |
| `frontend/src/components/SessionTable.jsx` | flintx | session rows, selection, favorite stars | no | 114 | 2026-10-18T08:53Z | [E-035] |
| `frontend/src/components/SessionMetaPanel.jsx` | flintx | metadata detail sidebar | no | 238 | 2026-10-18T08:52Z | [E-036] |
| `frontend/dist/index.html` | flintx | built UI mounted by FastAPI at `/` | yes | 1 | 2026-10-20T05:12:03Z | [E-026][E-047] |
| `data/soma_queue.json` | flintx | effective `QUEUE_OUTPUT_PATH` from `.env` | no | 6 | 2026-10-18T08:47:29Z | [E-045] |
| `backend/data/soma_queue.json` | flintx | unused queue copy | no | 5 | 2026-10-18T17:15:44Z | [E-045] |
| `/home/flintx/soma-10-14/data/soma_queue.json` | flintx | hard-coded second queue write target | no | 1787 bytes | 2026-10-22T03:03:42Z | [E-045] |
| `/media/storage/graphdb/session_site/vault.db` | flintx | SQLite source for list and filters | no | 2.2 GB | 2026-10-16T13:28:49Z | [E-037] |
| `/home/flintx/soma-10-14/soma/turn-key-profiles/soma-current.json` | flintx | profile read by `/api/profile` | no | 2803 bytes | 2026-10-21T04:08Z | [E-008] |

`start.sh:32` runs `python3 -m uvicorn main:app --host 0.0.0.0 --port 8001` after `cd backend`; `start.sh:49` runs `npx vite --host 0.0.0.0 --port 5174` [E-028]. Both services bind all interfaces. The launcher also kills whatever holds either port before starting [E-028].

## Architecture and Data Flow

Context, target centered. Solid arrows are code-verified; `?` marks an interface observed only through its artifact.

```text
                         Browser (React/Vite :5174)
                                   |
                                   | HTTP /api/*, Vite proxy -> :8001  [E-029][E-030]
                                   v
                    +------------------------------+
                    |  FastAPI backend             |
                    |  backend/main.py             |
                    +------------------------------+
                      |      |       |        |
        SELECT        |      | read  | write  | import
        sessions /    |      | session| *.meta | soma.machinetalk
        dev_sessions  |      | .json | .json  | .session_metadata
                      v      v       v        v
                 vault.db  session vault   session vault   [E-009][E-011]
                 [E-014]   [E-011]         [E-020]
                      |
                      | read profile
                      v
        soma/turn-key-profiles/soma-current.json  [E-008][E-017]

       writes on POST /api/select:
         QUEUE_OUTPUT_PATH = picker/data/soma_queue.json   [E-021]
         /home/flintx/soma-10-14/data/soma_queue.json      [E-021]
                      |
                      | same path also holds runner keys  [E-045]
                      v
                 Soma runner  ?  (internals not opened)
```

Execution flow, including failure branches.

```text
GET /api/sessions
  _full_cache empty?
    -> _build_meta_cache: SELECT session_id,date,provider,model,domain,
       sub_domain,project_context,topics FROM sessions      [E-014]
    -> _build_full_cache: SELECT * FROM dev_sessions
       ORDER BY total_score DESC                            [E-014]
    -> per row: read session.json, count *.json chatsets    [E-011][E-013]
  -> substring filters, equality filters, sort key, slice[:limit] [E-018]
  -> JSON {sessions, total=len(slice)}                      [E-018]

GET /api/session/{id}/metadata
  _resolve_path -> directory exists? --no--> 404            [E-020]
  {session_id}.meta.json exists? --yes--> return cache      [E-012]
  import session_metadata -> extract_session_metadata(dir)  [E-009]
     success -> write {session_id}.meta.json -> return      [E-020]
     exception -> 500                                       [E-020]

POST /api/select   (UI "Export N Favorites")
  body {"selected":[...],"count":N,"timestamp":...}         [E-033]
  session_ids = body.get("session_ids", []) -> []            [E-055]
  write QUEUE_OUTPUT_PATH with selected=[], count=0         [E-021]
  write /home/flintx/soma-10-14/data/soma_queue.json
    (overwrites runner keys if present)                     [E-021][E-045]

POST /api/launch
  validate json_path:str, mode:str, count:non-negative int  [E-024]
  any error -> 400; else write soma_launch.json             [E-024]
```

## Core Logic

**Startup.** Importing `main` calls `load_dotenv()` before reading configuration [E-010]. The lifespan handler opens the database and runs `SELECT 1`; a bad `DATABASE_PATH` fails startup, not the first request [E-010]. CORS allows only `http://localhost:5174` [E-010]. If `frontend/dist` exists, it is mounted at `/` [E-026].

**List construction.** `_build_meta_cache` selects eight columns from `sessions` and indexes each row by full `session_id` and, when different, by its trailing path segment [E-014]. `_build_full_cache` selects all columns from `dev_sessions` ordered by `total_score DESC`, then calls `_build_full_session` for each row [E-014]. That function resolves the directory by basename under `SESSIONS_PATH`, reads `session.json`, and counts non-`session.json` JSON files as chatsets [E-011]. It builds a 25-key row and takes `title` from `session.json.title` or `.name` [E-013].

The two tables do not share a namespace. Only 3051 `dev_sessions.session_id` values match `sessions.session_id` exactly; 3935 match when compared by tail segment [E-039]. The meta cache therefore serves 3935 of 4792 rows, and the remainder return empty `provider`, `model`, `date`, `domain`, `sub_domain`, `topics`, and `project_context` [E-040]. Live `session.json` files contain no `title` or `name`; every row returned `title=""`, so the table's Title column renders `—` for all 4792 rows [E-040][E-043][E-035].

Measured on flintx at 2026-10-22T10:32Z, a cold list build costs 3.0 seconds for 4792 rows; the cache is held for the process lifetime and rebuilt only on restart [E-040][E-014]. The Refresh button calls the same endpoint but cannot invalidate the cache [E-018].

**Filtering and sorting.** `get_sessions` filters in Python over the in-memory cache: substring search across session_id/title/domain/topics/dir name, exact domain, normalized provider, exact model, minimum score, maximum score, minimum chat-set count [E-018]. Provider normalization strips spaces and hyphens and lowercases, so `claude_web`, `claudeweb`, and `Claude Web` collapse to one filter bucket [E-015]. Sort keys are score, sets, date, name, functions, provider, and domain; the UI exposes all seven [E-018][E-034].

The response `total` is computed after `results[:limit]`, so it reports the size of the returned page, not the number of matches [E-018]. The default limit is 500; the live cache has 4792 rows, so a default request reports `total: 500` [E-040].

**Filter options.** `session_counts` reads three distinct lists and a score range from the database, not from the cache [E-019]. Providers are deduplicated by normalized form; domains and models are passed through raw, which is why both `education` and `educational` appear [E-019][E-041].

**Metadata on click.** The UI requests `/api/session/{encoded session_id}/metadata` and expects a dict with `metadata` sub-dicts of value-count maps, `anchors`, and `tool_calls` [E-030][E-036]. The backend resolves the directory, returns `{session_id}.meta.json` if present without checking its age, and otherwise imports `soma.machinetalk.session_metadata`, calls `extract_session_metadata(session_dir)`, and writes the returned dict as `{meta.session_id}.meta.json` [E-012][E-020]. The sampled live cache has exactly the keys the UI reads: `session_id`, `provider`, `total_sets`, `total_session_chars`, `file_count`, `anchors`, `tool_calls`, `metadata`, `json_file_list` [E-044].

The write is inside the request path. A read-only session directory or a full disk turns a metadata view into HTTP 500 [E-020]. The UI never sends a cache-busting parameter, so a stale cache remains authoritative [E-012].

**Favorites and export.** Favorites live only in browser `localStorage` under `soma_favorites`; they are not stored in SQLite or in the queue [E-031]. Opening the favorites panel fetches metadata for every favorite [E-030].

The Export button does two independent things [E-033]. First it downloads a browser-generated array of session objects. Second it POSTs `{selected: [...], count, timestamp}` to `/api/select` [E-033]. The backend reads `request.get("session_ids", [])`, a key the UI never sends, so the POST always resolves to an empty list and the queue is written with `selected: []` and `count: 0` [E-055][E-021].

Each queue write also writes the same payload to `/home/flintx/soma-10-14/data/soma_queue.json` [E-021]. That file currently carries runner state (`running`, `started_at`, `profile`, `finished_at`, `exit_code`) that this backend never emits, so the next UI export would replace runner state with a three-key empty selection [E-045].

`save_selected_with_metadata` repeats the same request-key mismatch and then writes one cache per selected session [E-022]. No UI code calls this route [E-030].

**Queue timestamp.** All three write paths use `asyncio.get_event_loop().time()`, a monotonic float, not wall-clock epoch seconds [E-021][E-022][E-024]. Existing picker-format files contain values such as `211636.864513157` [E-045].

**Launch.** The Start panel requires a JSON path, a mode (`all`, `one`, `few`), and a count for `few` [E-030]. The request body sets `count` to `undefined` when mode is `all`; `JSON.stringify` drops the key, and the backend rejects the request because `count` is not an int [E-032][E-024]. The launcher therefore cannot start an "All sessions" run against this backend. `one` and `few` send an integer and pass validation [E-032][E-024]. A successful launch writes `/home/flintx/soma-10-14/data/soma_launch.json`; that file was absent at probe time [E-024].

**Profile.** `/api/profile` reads `soma-current.json`, returns `name` and a reduced `deck` of `{modelId, provider}` [E-017]. The live file has an empty name and at least four model cards, so the Start panel displays "Unnamed" [E-054].

**Export route.** `GET /api/select/export` reads the effective queue file, writes a timestamped copy under `<base>/session-picker-json/`, and returns the same JSON [E-025]. Because `data/.base_path` is absent, the resolved directory is `/home/flintx/soma-10-14/session-picker-json`; it holds one 18-session export [E-050][E-023]. No UI code calls this route [E-030].

**Arbitrary path read.** `GET /api/sessions/load?path=` resolves any user-supplied path, requires it to be a file, parses it as JSON, and returns its session-shaped contents [E-016]. The server binds `0.0.0.0` and has no authentication [E-028][E-010]. The endpoint is reachable to anyone who can reach port 8001; it discloses file contents that parse as JSON.

## Configuration and Invariants

| Key / rule | Source | Default | Effective value | Enforced? |
|---|---|---|---|---|
| `DATABASE_PATH` | `backend/.env:1`, `backend/db.py:8-19` | `./vault.db` | `/media/storage/graphdb/session_site/vault.db` | yes, only if dotenv ran |
| `SESSIONS_PATH` | `backend/.env:2`, `backend/main.py:30-33` | `/media/storage/dendritic123/chat-logs/sessions` | same | yes |
| `QUEUE_OUTPUT_PATH` | `backend/.env:3`, `backend/main.py:34-37` | `~/.soma_queue.json` | `/home/flintx/soma-10-14/soma-session-picker/data/soma_queue.json` | yes |
| hard-coded queue | `backend/main.py:531-534`, `backend/main.py:553-556` | none | `/home/flintx/soma-10-14/data/soma_queue.json` | yes |
| profile path | `backend/main.py:41-44` | none | `/home/flintx/soma-10-14/soma/turn-key-profiles/soma-current.json` | yes |
| launch output | `backend/main.py:578` | none | `/home/flintx/soma-10-14/data/soma_launch.json` | yes |
| CORS origin | `backend/main.py:84-90` | none | `http://localhost:5174` | yes |
| bind address | `start.sh:32`, `start.sh:49` | none | `0.0.0.0` | yes |
| page limit | `backend/main.py:361`, `backend/main.py:429` | 500 | caller-supplied, no upper bound | yes |
| launch count | `backend/main.py:613-623` | none | non-negative integer | yes |
| cache invalidation | `backend/main.py:367-369`, `backend/main.py:497-499` | process lifetime | none | no invalidation path |
| `.meta.json` freshness | `backend/main.py:129-143` | trust any file | no mtime comparison | no |

Precedence is `os.environ` first, then `load_dotenv()` [E-010]. `backend/main.py:19-20` loads dotenv from the process cwd, so `start.sh`'s `cd "$BACKEND_DIR"` is what makes `backend/.env` effective [E-028]. `backend/db.py` independently looks for `<project>/.env`, which does not exist, and falls back to `./vault.db` [E-027][E-046]. A backend started from any other directory therefore has no `DATABASE_PATH` and no `SESSIONS_PATH` override, and will use or create the empty `backend/vault.db` [E-046].

The effective paths were verified by importing the app from `backend/`: `SESSIONS_PATH`, `QUEUE_OUTPUT_PATH`, and `db._database_path()` all matched `backend/.env` [E-005].

Documentation diverges from these invariants: it claims no database dependency, lists `/api/filter-options` and four `meta_*` parameters that do not exist, and documents a `data/soma_queue.json`-only queue [E-048][E-049]. The code is newer than both documents [E-005][E-048][E-056].

## Dependencies and Cross-Component Connections

| Direction | Counterpart | Mechanism | Payload / contract | Status |
|---|---|---|---|---|
| target -> soma | `soma.machinetalk.session_metadata` | Python import, with `spec_from_file_location` fallback to `soma/machinetalk/session_metadata.py` | `extract_session_metadata(session_dir) -> dict` | verified by import [E-009] |
| target -> vault | session directories | file reads of `session.json` and JSON chatset counts | title, sets, chars, models, chatset count | verified in code and live cache [E-011][E-013] |
| target -> vault | session directories | write `{session_id}.meta.json` | full extraction dict | verified in code; live samples exist [E-020][E-044] |
| target -> SQLite | `vault.db` | aiosqlite `SELECT` on `sessions` and `dev_sessions` | 6015 / 4792 rows | verified live [E-014][E-019][E-038] |
| target -> turn-key | `soma-current.json` | file read | profile name and deck model IDs/providers | verified live [E-017][E-054] |
| target -> Soma runner | `/home/flintx/soma-10-14/data/soma_queue.json` | file write of `{selected,count,timestamp}` | incompatible with runner keys in the same file | target side verified; consumer internals not opened [E-021][E-045] |
| browser -> target | FastAPI / Vite | `/api` fetches through the Vite proxy | JSON | verified in code [E-029][E-030] |
| target -> export dir | `session-picker-json/` | file write on `GET /api/select/export` | queue JSON copy | verified in code and artifact [E-025][E-050] |

Verified at runtime: the `soma.machinetalk.session_metadata` module resolves to `/home/flintx/soma-10-14/soma/machinetalk/session_metadata.py` and exposes `extract_session_metadata(session_dir)` [E-009]. Verified from the target side only: the queue path is written by this backend and also holds keys it does not produce [E-021][E-045].

Not verified: the Soma runner's read/write order on that queue file, and whether the runner tolerates the picker's three-key payload. Those require reading sibling code, which this run excluded.

Two contract mismatches cross the browser/backend boundary. The UI posts `selected` while the backend reads `session_ids` [E-055]. The UI omits `count` for mode `all` while the backend requires it [E-032][E-024]. Both are visible in current code and both block the intended Soma handoff.

## Known Gaps and Uncertainties

### G-01

- Unknown: the cwd and environment of the backend's last real run (U-01).
- Why it matters: a run outside `backend/` loses `DATABASE_PATH` and would serve the empty `backend/vault.db`.
- Evidence that would close it: launcher log, shell history, or a process environment capture.
- Current evidence: no process and no `/tmp/soma-picker-backend.log` [E-001][E-004][E-046].

### G-02

- Unknown: which component writes `running`, `started_at`, `profile`, `finished_at`, and `exit_code` into the shared queue file (U-02).
- Why it matters: the picker writes the same path with a smaller payload, so a UI export can remove run state.
- Evidence that would close it: Soma runner source or a write trace.
- Current evidence: the keys exist in the file and do not exist in `backend/main.py` [E-045][E-021].

### G-03

- Unknown: whether a picker POST during an active Soma run corrupts that run (U-03).
- Why it matters: shared mutable JSON with no lock, atomic replace, or merge.
- Evidence that would close it: instrumented POST during a run, or runner read/write order.
- Current evidence: both writes use plain `open(..., "w")` [E-021].

### G-04

- Unknown: why only 73 of 4792 sessions have a metadata cache (U-04).
- Why it matters: most first clicks invoke extraction and write into the vault.
- Evidence that would close it: request history or UI visit logs.
- Current evidence: 73 caches, no launcher logs [E-042][E-004].

### G-05

- Unknown: why `sessions` and `dev_sessions` differ in count and ID namespace (U-05).
- Why it matters: 857 list rows have no metadata and filter lists come from a different table.
- Evidence that would close it: both ingestion scripts.
- Current evidence: 6015 vs 4792 rows; 3051 exact and 3935 tail matches [E-038][E-039][E-040].

### G-06

- Unknown: whether `frontend/dist` reflects `frontend/src` (U-06).
- Why it matters: the mounted build is what users get at `/`, while development uses the source.
- Evidence that would close it: rebuild and compare behavior.
- Current evidence: dist mtime is later than `App.jsx`; the bundle contains "Launch submitted" [E-047].

### G-07

- Unknown: side effects of `extract_session_metadata` (U-07).
- Why it matters: it runs before the target's own cache write, on a request path.
- Evidence that would close it: read the sibling module.
- Current evidence: only the import, signature, and returned dict shape were observed [E-009][E-044].

### G-08

- Unknown: actual network exposure of the unauthenticated read and write endpoints (U-08).
- Why it matters: `GET /api/sessions/load` reads arbitrary files and all POST routes write files.
- Evidence that would close it: firewall rules plus a live listener check.
- Current evidence: code binds `0.0.0.0`; service was not running during the probe [E-028][E-002].

### G-09

- Unknown: whether an "All sessions" launch ever succeeded (U-09).
- Why it matters: the current UI/backend contract always returns 400 for that mode.
- Evidence that would close it: request log or a live POST.
- Current evidence: `JSON.stringify` drops `undefined`, and the backend requires an int [E-032][E-024].

### G-10

- Unknown: whether any current picker queue file reflects a UI selection (U-10).
- Why it matters: the UI writes an empty selection due to the key mismatch.
- Evidence that would close it: a live export POST or a queue timestamp correlated with a UI action.
- Current evidence: picker-format files predate the last source edit; the newest queue file is runner-shaped [E-045][E-055].

## Evidence Log

| ID | Host | Kind | Locator | Captured at | Proves | Confidence |
|---|---|---|---|---|---|---|
| E-001 | flintx | runtime | `ps -eo pid,lstart,etimes,cmd` filtered for picker processes | 2026-10-22T10:28Z | no picker, uvicorn, or vite process is running | C1 |
| E-002 | flintx | runtime | `ss -lntp` filtered for 8001 and 5174 | 2026-10-22T10:28Z | no listeners on either service port | C1 |
| E-003 | flintx | runtime | `curl -sS -m 5 http://127.0.0.1:8001/api/health` | 2026-10-22T10:28Z | connection refused, HTTP 000 | C1 |
| E-004 | flintx | runtime | `ls /tmp/soma-picker-backend.log /tmp/soma-picker-frontend.log` | 2026-10-22T10:28Z | both launcher logs are absent | C1 |
| E-005 | flintx | runtime | import `backend/main.py` under `backend/venv/bin/python`; enumerate `app.routes` | 2026-10-22T10:31Z | app imports; 12 API routes; effective config paths | C1 |
| E-006 | flintx | runtime | `backend/venv/bin/python --version`; `pip list` | 2026-10-22T10:31Z | Python 3.11.2 and installed backend packages | C1 |
| E-007 | flintx | config | `backend/.env:1-3` | 2026-10-22T10:29Z | three environment keys and their path values | C2 |
| E-008 | flintx | config | `backend/main.py:41-44` | 2026-10-22T10:29Z | profile path resolves under `soma/turn-key-profiles` | C2 |
| E-009 | flintx | code | `backend/main.py:50-69` | 2026-10-22T10:31Z | lazy import of `soma.machinetalk.session_metadata` with file fallback | C2 |
| E-010 | flintx | code | `backend/main.py:75-90` | 2026-10-22T10:29Z | lifespan `SELECT 1`; version 0.3.0; CORS origin | C2 |
| E-011 | flintx | code | `backend/main.py:106-126` | 2026-10-22T10:29Z | session directory resolution and chatset counting | C2 |
| E-012 | flintx | code | `backend/main.py:129-143` | 2026-10-22T10:29Z | cached `.meta.json` lookup without freshness check | C2 |
| E-013 | flintx | code | `backend/main.py:146-185` | 2026-10-22T10:29Z | row composition; title from `session.json` title or name | C2 |
| E-014 | flintx | code | `backend/main.py:196-240` | 2026-10-22T10:29Z | meta-cache SQL and one-time full-cache build | C2 |
| E-015 | flintx | code | `backend/main.py:245-254` | 2026-10-22T10:29Z | provider normalization rule | C2 |
| E-016 | flintx | code | `backend/main.py:260-312` | 2026-10-22T10:29Z | arbitrary-path JSON read endpoint | C2 |
| E-017 | flintx | code | `backend/main.py:315-347` | 2026-10-22T10:29Z | health and profile response shapes | C2 |
| E-018 | flintx | code | `backend/main.py:350-433` | 2026-10-22T10:29Z | filters, sorting, limit slice, post-limit `total` | C2 |
| E-019 | flintx | code | `backend/main.py:436-479` | 2026-10-22T10:29Z | counts queries and score range | C2 |
| E-020 | flintx | code | `backend/main.py:482-514` | 2026-10-22T10:29Z | metadata endpoint writes `{session_id}.meta.json` | C2 |
| E-021 | flintx | code | `backend/main.py:517-536` | 2026-10-22T10:29Z | select writes two queue paths with a monotonic timestamp | C2 |
| E-022 | flintx | code | `backend/main.py:539-575` | 2026-10-22T10:29Z | select-with-metadata writes queues and per-session caches | C2 |
| E-023 | flintx | code | `backend/main.py:578-598` | 2026-10-22T10:29Z | launch path and export-dir resolution via `data/.base_path` | C2 |
| E-024 | flintx | code | `backend/main.py:601-637` | 2026-10-22T10:29Z | launch validation requires an integer count | C2 |
| E-025 | flintx | code | `backend/main.py:640-661` | 2026-10-22T10:29Z | server-side export writes a timestamped JSON copy | C2 |
| E-026 | flintx | code | `backend/main.py:664-670` | 2026-10-22T10:31Z | FastAPI mounts `frontend/dist` at `/` when present | C2 |
| E-027 | flintx | code | `backend/db.py:8-27` | 2026-10-22T10:29Z | `DATABASE_PATH` precedence and root `.env` lookup | C2 |
| E-028 | flintx | code | `start.sh:8-9`, `start.sh:26-32`, `start.sh:48-49` | 2026-10-22T10:29Z | ports, `cd backend`, uvicorn and vite on `0.0.0.0` | C2 |
| E-029 | flintx | code | `frontend/src/App.jsx:9` | 2026-10-22T10:29Z | API base is `/api` | C2 |
| E-030 | flintx | code | `frontend/src/App.jsx:74-144` | 2026-10-22T10:29Z | UI fetches counts, profile, sessions, and metadata | C2 |
| E-031 | flintx | code | `frontend/src/App.jsx:20-25`, `frontend/src/App.jsx:68-70` | 2026-10-22T10:29Z | favorites persist only in `localStorage` | C2 |
| E-032 | flintx | code | `frontend/src/App.jsx:255-279` | 2026-10-22T10:29Z | launch body omits `count` when mode is `all` | C2 |
| E-033 | flintx | code | `frontend/src/App.jsx:291-345` | 2026-10-22T10:29Z | export downloads a Blob and POSTs `/api/select` | C2 |
| E-034 | flintx | code | `frontend/src/components/FilterBar.jsx:100-131` | 2026-10-22T10:29Z | sort keys and limit options | C2 |
| E-035 | flintx | code | `frontend/src/components/SessionTable.jsx:40-104` | 2026-10-22T10:29Z | table columns and title rendering | C2 |
| E-036 | flintx | code | `frontend/src/components/SessionMetaPanel.jsx:39-46` | 2026-10-22T10:29Z | UI expects metadata as value-count maps | C2 |
| E-037 | flintx | data | `sqlite3 -readonly` schema dump on `/media/storage/graphdb/session_site/vault.db` | 2026-10-22T10:30Z | table schemas | C1 |
| E-038 | flintx | data | `sqlite3 -readonly` `COUNT(*)` on `sessions` and `dev_sessions` | 2026-10-22T10:30Z | 6015 and 4792 rows | C1 |
| E-039 | flintx | data | `sqlite3 -readonly` exact and tail-match joins | 2026-10-22T10:30Z | 3051 exact matches; 3935 tail matches | C1 |
| E-040 | flintx | runtime | in-process `_build_full_cache()` and `get_sessions()` | 2026-10-22T10:32Z | 4792 cached; 500 returned; 0 titles; 3935 providers | C1 |
| E-041 | flintx | runtime | in-process `session_counts()` | 2026-10-22T10:32Z | 12 providers, 29 domains, 9 models, score 0..406158 | C1 |
| E-042 | flintx | data | `find` and `ls` over the sessions root | 2026-10-22T10:30Z | 4792 dirs, 4792 `session.json`, 73 caches | C1 |
| E-043 | flintx | data | sampled `session.json` | 2026-10-22T10:30Z | no `title`/`name`; has provider, sets, chars, models | C1 |
| E-044 | flintx | data | sampled `permis.script.permissions.merging.meta.json` | 2026-10-22T10:32Z | cache keys match UI expectations and code filename | C1 |
| E-045 | flintx | data | `ls` and JSON key inspection of queue paths | 2026-10-22T10:30Z | two picker-format files; runner-extended file; default absent | C1 |
| E-046 | flintx | data | `ls -la backend/vault.db`; `file` | 2026-10-22T10:29Z | zero-byte SQLite placeholder | C1 |
| E-047 | flintx | data | `ls frontend/dist`; `rg` bundle for UI string | 2026-10-22T10:31Z | build mtime and bundled launch string | C1 |
| E-048 | flintx | doc | `DOCUMENTATION.md:18`, `DOCUMENTATION.md:30`, `DOCUMENTATION.md:248-251`, `DOCUMENTATION.md:299-311`, `DOCUMENTATION.md:358`, `DOCUMENTATION.md:563-571` | 2026-10-22T10:29Z | stale DB, endpoint, cache, and queue claims | C3 |
| E-049 | flintx | doc | `INTEGRATION_GUIDE.md:18-21`, `INTEGRATION_GUIDE.md:293`, `INTEGRATION_GUIDE.md:310` | 2026-10-22T10:29Z | queue-path and cache-filename claims | C3 |
| E-050 | flintx | data | `ls -la /home/flintx/soma-10-14/session-picker-json`; `data/.base_path` | 2026-10-22T10:31Z | one 18-session export; `.base_path` absent | C1 |
| E-051 | flintx | data | `find` for tests, README, `AGENTS.md`, `CLAUDE.md` | 2026-10-22T10:33Z | no tests or local instruction files | C1 |
| E-052 | flintx | runtime | `git rev-parse --show-toplevel` in root and parent | 2026-10-22T10:33Z | neither is a git repository | C1 |
| E-053 | flintx | runtime | full `ss -lntp` filtered for 800x and 5174 | 2026-10-22T10:33Z | no picker-related listener | C1 |
| E-054 | flintx | data | sampled `soma/turn-key-profiles/soma-current.json` | 2026-10-22T10:31Z | profile name empty; deck cards present | C1 |
| E-055 | flintx | code | `frontend/src/App.jsx:317-327` and `backend/main.py:520` | 2026-10-22T10:35Z | UI posts `selected`; backend reads `session_ids` | C2 |
| E-056 | flintx | data | `find` mtime listing and `ls -la backend/__pycache__` | 2026-10-22T10:33Z | file mtimes: main.py 19:21:35Z, pyc 18:59:30Z, docs 2026-10-18, dist 2026-10-20T05:12:03Z | C1 |

## Appendix: Run Artifacts

- Run directory: `.forensic/soma-session-picker/20261022T102813Z-496d3c/`
- Inventory: `01-inventory.txt`, `01-inventory.json`
- Discovery notes: `02-discovery-notes.md`
- Evidence index: `03-evidence-index.tsv`
- Open questions: `04-open-questions.md`
- No remote host is registered for this target; remote inventory is empty.
