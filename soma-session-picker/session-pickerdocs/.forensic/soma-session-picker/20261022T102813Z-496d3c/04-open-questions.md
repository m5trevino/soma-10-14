# Open Questions: soma-session-picker

RUN: 20261022T102813Z-496d3c

### U-01

- Unknown: which cwd and environment the backend used on its last real run.
- Why it matters: `load_dotenv()` is cwd-dependent; a run outside `backend/` leaves `DATABASE_PATH` unset and falls back to `./vault.db`, the zero-byte file in the repo.
- Evidence that would close it: preserved `/tmp/soma-picker-backend.log`, process env dump, or shell history.
- Not run: no live process; environment of a dead process cannot be recovered.

### U-02

- Unknown: which component writes `running`, `started_at`, `profile`, `finished_at`, `exit_code` into `/home/flintx/soma-10-14/data/soma_queue.json`.
- Why it matters: the picker overwrites that file with a three-key payload on every selection save.
- Evidence that would close it: Soma runner source or a write trace.
- Not run: sibling component internals excluded by scope fence.

### U-03

- Unknown: whether a picker POST during an active Soma run truncates runner state.
- Why it matters: shared mutable state file with incompatible payloads.
- Evidence that would close it: instrumented POST during a run, or runner read/write order.
- Not run: writes are forbidden by the read-only rule.

### U-04

- Unknown: why only 73 of 4792 sessions have a cached `.meta.json`.
- Why it matters: the remaining sessions trigger extraction and a write into the session directory on first click.
- Evidence that would close it: request logs or UI visit history.
- Not run: launcher logs absent.

### U-05

- Unknown: why `sessions` (6015) and `dev_sessions` (4792) have different ID namespaces and counts.
- Why it matters: list rows and filter options come from different tables; 857 rows lack metadata.
- Evidence that would close it: ingestion scripts for both tables.
- Not run: ingestion code lives outside the target root.

### U-06

- Unknown: whether `frontend/dist` matches the current `frontend/src`.
- Why it matters: FastAPI serves `dist` at `/`; the dev server serves `src`.
- Evidence that would close it: a reproducible rebuild and comparison.
- Probe: dist mtime is newer than `App.jsx`; bundle contains "Launch submitted".

### U-07

- Unknown: side effects of `soma.machinetalk.session_metadata.extract_session_metadata`.
- Why it matters: invoked on the request path before the target writes the returned dict.
- Evidence that would close it: read the sibling module.
- Not run: excluded by scope fence.

### U-08

- Unknown: whether `GET /api/sessions/load?path=` is reachable from non-local networks in practice.
- Why it matters: reads any file as JSON; backend binds `0.0.0.0` with no authentication.
- Evidence that would close it: host firewall rules and listener state during a run.
- Not run: service not running; no firewall changes attempted.

### U-09

- Unknown: whether `mode=all` launch ever succeeded against the current backend.
- Why it matters: UI omits `count` for that mode while backend rejects a missing count.
- Evidence that would close it: request log or live POST.
- Not run: POST writes `soma_launch.json`; read-only rule.
