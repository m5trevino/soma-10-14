# Discovery Notes — soma

## Target lock
TARGET: soma
SLUG: soma
RUN ID: 20261022T095652Z-3411e1
BASE DIR: /home/flintx/soma-10-14
HOST: flintx
STARTED: 2026-10-22T09:56:52Z
SCOPE: Local Soma / MachineTalk engine — launcher, session loading, pipeline orchestrator, Soma graph store, stage bridge.
EXCLUDED: every other registry target (picker, turn-key SDK internals, ai-engine, chat-log stores, invariants).

## Inventory summary
- Roots: `/home/flintx/soma-10-14/soma` (177 files depth 3), `/home/flintx/soma-10-14` (337 files depth 3) [E-001].
- Not a git repository: `git rev-parse --is-inside-work-tree` → "fatal: not a git repository" [E-002]. Dating therefore uses mtimes only.
- Newest verified source files (UTC mtimes): `soma/run_engine.py` 2026-10-22T02:46:35Z, `soma/machinetalk/engine.py` 2026-10-22T02:43:59Z, `soma/interactive.py` 2026-10-22T02:36:45Z, `run_sessions.py` 2026-10-22T02:16:01Z [E-003].
- Output root `soma/output/` contains `checkpoints/` (16 files), `stage1/` (3 session dirs, 158 files), `artifacts/`, `skip_vault/`, `logs/`, `soma.json` (420,111 bytes, mtime 2026-10-21T20:03) [E-004][E-005].
- No `stage2`, `stage3`, `stage4`, or `codebase` directories exist under `soma/output` [E-004].
- `soma/workspaces/` exists but contains only `test-session`; inventory script reported it absent (path check discrepancy) [E-004].

## Entry points
| path | role | lines | mtime (UTC) | evidence |
|---|---|---|---|---|
| `run.sh` | bash launcher; inserts `turn-key`+`soma` on PYTHONPATH; `--source`/`--queue` → `soma/run_engine.py`, else `run_sessions.py` | 19 | 2026-10-18T09:43:04Z | E-006 |
| `run_sessions.py` | session batch launcher, picker, profile selection, subprocess to engine | 1329 | 2026-10-22T02:16:01Z | E-007 |
| `soma/run_engine.py` | canonical engine entry; argparse `--source/--queue/--profile/--out/--debug/--workers/--port/--soma-only/--max-chatsets` | 269 | 2026-10-22T02:46:35Z | E-008 |
| `soma/machinetalk/engine.py` | 4-stage orchestrator | 1025 | 2026-10-22T02:43:59Z | E-009 |
| `soma/machinetalk/client.py` | TurnKey adapter; only model-call surface | 182 | 2026-10-17T19:18Z | E-010 |
| `soma/machinetalk/source.py` | session/chatset loader | 172 | 2026-10-18T13:49Z | E-011 |
| `soma/store.py` | JSON-backed graph store | 135 | 2026-10-18T02:56:57Z | E-012 |
| `soma/machinetalk/soma_bridge.py` | stage artifacts → graph nodes/edges | 538 | 2026-10-18T13:49Z | E-013 |
| `soma/machinetalk/gate.py` | Python response gate | 290 | 2026-10-14T12:15Z | E-014 |
| `soma/machinetalk/checkpoint.py` | per-session checkpoint store | 266 | 2026-10-15T18:14Z | E-015 |
| `run_dashboard.py` | standalone dashboard launcher | ~150 | 2026-10-17T18:00Z | E-016 |

Import check with the launcher's PYTHONPATH (`turn-key:soma`): `turnkey` resolves to `/home/flintx/.local/lib/python3.11/site-packages/turnkey/__init__.py`; `machinetalk.engine`, `machinetalk.client`, `store` resolve inside the project. `import machinetalk.engine` succeeds [E-017].

## Runtime state
- `ps -eo pid,ppid,etimes,cmd | rg 'run_sessions|run_engine|soma|dashboard'` on flintx at 2026-10-22T09:56:59Z: **no matching process**. The engine is not running [E-018].
- `ss -lntp` on flintx at 2026-10-22T09:56:59Z: nothing listening on 9876, 9877, 9878, 8001, or 5174 [E-018][E-019].
- `.dashboard_port` contains `9878` (mtime 2026-10-21T20:03) [E-019].
- Last pipeline logs stop at 2026-10-22 03:03:27 local (2026-10-21T20:03:27Z). Final line: OUTROBEAVER DONE, `tokens=28704 ms=14539 model=apodex/apodex-1.1-mini verdict=RED` [E-020].
- Preceding logs show `DISTILLER/INTROBEAVER/PLANBEAVER … already DONE (resume)` and an OUTROBEAVER START with no completion line in the 030237 log [E-020].
- Queue: `data/queue.json` and `data/soma_queue.json` both mtime 2026-10-21T20:03, `selected` holds absolute chat-log session paths [E-021].
- `data/.last_queue` = `/home/flintx/soma-10-14/session-picker-json/soma_favorites_2026-10-2.json`; `data/.last_profile` = `/home/flintx/soma-10-14/turn-key-profile/pro-name_2026-10-21T21-06-14.json`; `data/.last_workers` = `1` [E-021].
- Test evidence: `python3 -m pytest soma/test_run_engine_soma_only.py -q` → 6 passed in 0.05s (2026-10-22T09:59Z) [E-022].
- Remote probe (`ssh engine`, 2026-10-22T09:57:25Z): host `ubuntu-8gb-hel1-1`; `peacock-engine` active; `WorkingDirectory=/root/hetzner/ai-engine`; `GET http://127.0.0.1:3099/health` → `{"status":"ONLINE","system":"PEACOCK_ENGINE_V3","version":"3.0.0",...}`; `ls -d /root/hetzner/ai-engine/soma` → absent [E-023].
- Local DNS `engine.save-aichats.com` → 204.168.184.49; `tailscale status` shows `ubuntu-8gb-hel1-1` at 100.87.51.23, active, direct 204.168.184.49:41641; `curl -m 8 http://engine.save-aichats.com:3099/health` → HTTP 200, remote_ip 204.168.184.49, 0.529s [E-024].

## Data stores
- `soma/output/soma.json` — JSON graph (not SQLite; the inventory script's sqlite probe errored `file is not a database`). Parsed: 997 nodes, **1 edge**; node types `ChatSet: 788, TaskNode: 133, ReceptorLog: 60, SessionAnchor: 16`; the sole edge relationship is `CONTAINS` [E-005].
- `soma/output/checkpoints/<session_id>.checkpoint.json` — JSON per session. 16 files. Most carry every chatset at `distiller: RUNNING` (never completed), e.g. `250602-1389` 90 chatsets, `26-01-12-peacock…` 303 chatsets. Completed-ish records exist: `260622-2403` (cs1 DONE/DONE/RUNNING/PENDING, cs2 DONE/DONE/BLOCKED/DONE, cs3 FAILED/DONE/DONE/DONE) and `25-11-20-multiclip…` (cs1 FAILED/DONE/FAILED/DONE, cs2 all DONE). `session_stages` is `{}` in every file inspected → stages 2–4 were never marked [E-025].
- `soma/output/stage1/<session>/<n>_<stage>.md` — 158 markdown artifacts, three sessions [E-004].
- `soma/output/artifacts/<chatset_id>/<stage>.json` — parsed stage payloads keyed by `session:set` [E-004].
- Checkpoint schema (documented and matching code): `session_id`, `chatsets.{set}.{chatset_id,chatset_hash,chars,stages.{stage}.status}`, `session_stages`, `updated_at`; statuses `PENDING|RUNNING|DONE|FAILED|SKIPPED|BLOCKED` [E-015].
- No database connections anywhere in the target: `rg` over the package shows no `sqlite3` use in `soma/machinetalk/*`; the store is JSON-only [E-012][E-013].

## Configuration and invariants
- Profile: `soma/turn-key-profiles/soma-current.json` (2803 bytes, mtime 2026-10-21T04:08Z) — 9-card `deck` (ollama/openrouter/novita/xkiro), all 12 stages `useDeck: true`, `pipeline: {mode: sequential, workers: 1, timeout: 180, maxRetries: 10}` [E-026].
- Launcher auto-detect order: `soma/turn-key-profiles/soma-current.json` first, then `*profile*.json`, then project-root copies [E-027].
- Interactive launcher discovers profiles from `<base>/turn-key-profile/*.json` plus the legacy `soma/turn-key-profiles/*profile*.json`; base dir comes from `data/.base_path` [E-028].
- Runtime paths: `--out` default `/tmp/soma_out`; launcher overrides to `soma/output`; `--debug` default `/tmp/soma_debug`; launcher uses `DEBUG_DIR=/tmp/soma_debug`; ports 9876 (engine default), 9877 (launcher constant) [E-008][E-007].
- Stage→model mapping happens inside the turnkey SDK; `EngineClient.model_for()` always returns the literal `"turnkey"` [E-010].
- Gate contracts (enforced in code): per-stage required keys, verdict keys, hash echo key; distiller `skip=true` is a clean skip; `block_tokens` produce BLOCKED; scout is text with `### SCOUT VIOLATION REPORT:` head and `SCOUT REVIEW COMPLETE. VERDICT: <token>` tail [E-014].
- Invariants: `InvariantRegistry` holds four hard-coded rules (INV-001..004) and is instantiated with **no path** in the engine, so the SQLite/JSON override is never loaded [E-029][E-009].
- Config keys read by the engine from environment: `HETZNER_OUTPUT_LOG` only (append log of output path) [E-008].

## Cross-component edges
| direction | mechanism | payload | evidence |
|---|---|---|---|
| launcher → engine | `subprocess.run([sys.executable, soma/run_engine.py, --queue, --profile, --debug, --out, --port, --workers, (--max-chatsets)])`, cwd=project root, timeout 36000 s | queue path, profile path, output dir | E-007 |
| engine → turnkey SDK | `from turnkey.profile_integration import initialize_sdk_with_profile`; `sdk.run_stage(mapped_stage, messages)` | messages `[{system}, {user}]`, stage name mapped by `_STAGE_MAP` | E-010 |
| turnkey SDK → remote engine | HTTP to `engineUrl` or default `http://engine.save-aichats.com:3099` | model call (not executed in this run) | E-030 |
| engine → chat logs | `load_source()` reads `<sessions-root>/<session>/session.json` and `NNNNNN[.K].json`; launcher/queue hard-code `/media/storage/dendritic123/chat-logs/sessions` | session metadata + user/assistant text chunks | E-011, E-007 |
| engine → filesystem | `soma/output/checkpoints/`, `stage1/`, `stage2..4/`, `artifacts/`, `skip_vault/`, `logs/`, `codebase/`, `run_manifest.md`, `soma.json` | artifacts, checkpoints, graph | E-009, E-015 |
| launcher → picker | `bash soma-session-picker/start.sh` with `SESSIONS_PATH`, `QUEUE_OUTPUT_PATH`; polls `http://localhost:5174` | env + queue file | E-031 |
| launcher → dashboard procs | `Popen(run_dashboard.py --no-open --port 9877)`; engine separately starts `debug_dashboard.start_dashboard(port=9877)` in a thread | debug JSONL in `/tmp/soma_debug` | E-032, E-033 |
| engine → Soma store | `SomaBridge` → `Soma.create_node/create_edge` wrapped by `AtomicSoma` | node type + properties, edge rel_type | E-009, E-012, E-013 |

## Instructions and recency
| document | mtime | authority rank | claim |
|---|---|---|---|
| `README.md` | 2026-10-14 | 3 | `./run.sh --source … --profile …`; `pip install -e turn-key`; dashboard port 9876; "delete output dir" to force rerun |
| `DROID-RESET.md` | 2026-10-15 | 5 (historical intent) | dashboard is broken; describes `soma/machinetalk` layout; says `run_engine.py` must keep working |
| `soma/machine-talk/MACHINE_TALK_SPEC.md` | 2026-10-14 | 4 (protocol spec v2.0.0) | zero-inference protocol, hard gates fatal, chronology resolved |
| `SESSION-LAUNCHER-GUIDE.md` | 2026-10-21 | 3 | launcher flow; claims stage inputs are predecessor outputs; dashboard on 9877 |
| `soma/machine-talk/cli-manifest.json` | 2026-10-14 | 4 | stage list, input_source, output_artifact names; TB ids differ from `fleet.py` (manifest lists introbeaver=TB-001) |
| `soma/machine-talk/tb-*.md` | 2026-10-14 | 4 | stage prompts; tb-001 ends with `[RAW_CHAT_TRANSCRIPT]\n{chunk}` |

## Conflicts
```
CONFLICT C-01
  claim A: introbeaver consumes distiller output, planbeaver consumes introbeaver+raw, outrobeaver consumes planbeaver+extraction | source: soma/machinetalk/fleet.py:3-20, soma/machine-talk/cli-manifest.json | mtime: 2026-10-14
  claim B: every stage-1 call receives only {session_id, timestamp_utc, raw_chat_set} (+ static extras) | source: soma/machinetalk/engine.py:287-295, 503-523 | mtime: 2026-10-22T02:43Z
  resolution: B
  basis: executed call path builds payload in _beaver_payload; chunk is non-empty only for distiller
  impact: report states stage-1 beavers are independent, not chained
```
```
CONFLICT C-02
  claim A: launcher starts dashboard on 9877 and passes --port 9877 to the engine | source: run_sessions.py:52, 345-349, 288-299 | mtime: 2026-10-22T02:16Z
  claim B: engine calls start_dashboard(port=9877), which runs `fuser -k 9877/tcp` before binding | source: soma/machinetalk/debug_dashboard.py:108-113 | mtime: 2026-10-21T14:30Z
  resolution: both-live
  basis: code path is deterministic; the engine process kills the launcher's dashboard on the shared port
  impact: documented as a startup race, not a working two-dashboard design
```
```
CONFLICT C-03
  claim A: `run_dashboard.py --port N` selects the port | source: run_sessions.py:345-349 | mtime: 2026-10-22T02:16Z
  claim B: run_dashboard.py has no argparse; it ignores argv, uses PORT=9877, calls kill_port(9877), find_port(), write_port_file() | source: run_dashboard.py:16-38, 98-109 | mtime: 2026-10-17T18:00Z
  resolution: B
  basis: `.dashboard_port` = 9878 while the launcher asked for 9877
  impact: dashboard URL and .dashboard_port disagree with the printed URL
```
```
CONFLICT C-04
  claim A: edges persist under key `rel_type` | source: soma/store.py:66-69, 48-54 | mtime: 2026-10-18T02:56Z
  claim B: AtomicSoma persists edges under key `relationship` | source: soma/machinetalk/engine.py:84-87 | mtime: 2026-10-22T02:43Z
  resolution: both-live
  basis: store._load indexes `edata["rel_type"]` inside a bare `try/except`, so a file written by AtomicSoma raises KeyError and silently keeps only nodes
  impact: live soma.json has 997 nodes and 1 edge; edges written by the engine are lost on reload
```
```
CONFLICT C-05
  claim A: a failed gate "rotates to the next model and retries" | source: soma/machinetalk/gate.py:8-12 | mtime: 2026-10-14
  claim B: client performs exactly one `run_stage` call per stage and records `attempt=1` | source: soma/machinetalk/client.py:97-116, 155-162 | mtime: 2026-10-17T19:18Z
  resolution: B
  basis: no loop or second call exists in client.py; profile `maxRetries: 10` is consumed by the SDK, not by this adapter
  impact: retry/rotation behavior is attributed to the turnkey SDK boundary, not to soma
```
```
CONFLICT C-06
  claim A: checkpoint FAILED means "all retry models exhausted" | source: soma/machinetalk/checkpoint.py:20-27 | mtime: 2026-10-15
  claim B: FAILED is written after a single failed gate with `attempt=1` | source: soma/machinetalk/engine.py:467-476, client.py:155-162 | mtime: 2026-10-22T02:43Z
  resolution: B
  basis: engine marks FAILED on the one call result
  impact: state semantics documented as single-attempt failure
```
```
CONFLICT C-07
  claim A: launcher guide says stage 1 distiller is `soma/distiller_dendrite.py`, introbeaver `soma/introbeaver.py` | source: SESSION-LAUNCHER-GUIDE.md:330-340 | mtime: 2026-10-21
  claim B: those files do not exist; stage 1 is `machinetalk/engine.py` calling the model by stage name, prompt bodies in `soma/machine-talk/tb-*.md` | source: ls of soma/ (no distiller_dendrite.py / introbeaver.py), engine.py:503-523, fleet.py:38-66 | mtime: 2026-10-22T02:43Z
  resolution: B
  basis: directory listing and import graph
  impact: guide's file map is stale; report uses the live module map
```
```
CONFLICT C-08
  claim A: ChatSet.chatset_hash stores the chatset hash | source: soma/machinetalk/source.py:42, 106-118 | mtime: 2026-10-18T13:49Z
  claim B: bridge writes `chatset_hash` = the substring after ":" in `session:set` | source: soma/machinetalk/soma_bridge.py:76 | mtime: 2026-10-18T13:49Z
  resolution: both-live (loader is correct; graph property is wrong)
  basis: live soma.json sample `chatset_hash: "1"` with `chatset_id: "…:1"`
  impact: graph property cannot be used to verify a chatset hash
```

## Unknowns and boundary gaps
### U-01 SDK internals
What the installed turnkey SDK does between `initialize_sdk_with_profile` and the HTTP call (rotation, retry, key selection). Not opened: sibling component. Closing evidence: read `/home/flintx/.local/lib/python3.11/site-packages/turnkey/sdk.py:run_stage` under target `turn-key`.

### U-02 Stage 2–4 completion
Whether any stage 2–4 run ever succeeded. No `stage2/3/4` artifacts and no `session_stages` entries exist. Closing evidence: archived output dirs, `/tmp/soma_out`, or `soma-grok/` copies with matching mtimes.

### U-03 Stale RUNNING checkpoints
Why 11 checkpoint files are frozen at `distiller: RUNNING`. Closing evidence: journal/kernel log for 2026-10-18T10:18Z or a reproducer run.

### U-04 Stage-2 gate fit
Whether stage 2–4 gate specs match the output contract (nexus/spark/falcon require `plan_hash_verification`). Closing evidence: one captured stage-2 response or `soma/output/stage2/` artifacts.

### U-05 Picker queue path
Which queue file the picker writes in practice (`data/soma_queue.json` vs `soma-session-picker/backend/data/`). Closing evidence: backend source read under `soma-session-picker`, or a live picker run.

### U-06 soma-only history
Whether `--soma-only` was ever used against the live tree; its output shares `soma/output/soma.json` through the non-atomic store. Closing evidence: shell history or `SOMA-ONLY:` log lines.

### U-07 soma-grok status
Whether `soma-grok/` is an archive or a live duplicate. Its `run_sessions.py` mtime is newer (2026-10-21T19:37Z). Closing evidence: import/reference scan outside the archive.

### U-08 Remote latency
Real latency/throughput from flintx to the model engine per stage. Not measured to avoid a model call. Closing evidence: `run_manifest.md` with per-call latency.


## Evidence index
See `03-evidence-index.tsv`.

## Report plan
1. Mandate — E-006, E-008.
2. Current State — E-018, E-019, E-020, E-022, E-023, E-005.
3. Key Paths and Entry Points — E-001, E-003, E-006…E-016.
4. Architecture and Data Flow — E-007, E-010, E-029, E-030, E-031, E-032.
5. Core Logic — E-008, E-009, E-011, E-012, E-013, E-014, E-015, E-026.
6. Configuration and Invariants — E-026, E-027, E-028, E-029, E-014, E-015.
7. Dependencies and Cross-Component Connections — E-007, E-010, E-030, E-031, E-023, E-024.
8. Known Gaps and Uncertainties — U-01…U-08, C-01…C-08.
9. Evidence Log — all rows.
