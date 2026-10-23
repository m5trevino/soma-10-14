# soma — Forensic Deep Dive
TARGET: soma | RUN: 20261022T095652Z-3411e1 | DATE: 2026-10-22 | HOSTS EXAMINED: flintx (local), ubuntu-8gb-hel1-1 (`[remote]`, read-only SSH)
CONFIDENCE SUMMARY: 15 C1 (live command/file reads), 19 C2 (static source/config), 1 C3 (target-local doc) | SCOPE: local Soma / MachineTalk engine — launcher, session loader, pipeline orchestrator, Soma graph store, stage bridge

## Mandate
Soma turns selected chat-log sessions into a resumable four-stage model pipeline and mirrors each stage's accepted output into one JSON property graph at `soma/output/soma.json`.

## Current State
The engine is not running on flintx. `ps -eo pid,ppid,etimes,cmd | rg 'run_sessions|run_engine|soma|dashboard'` returned no matching process, and `ss -lntp` showed no listener on 9876, 9877, 9878, 8001, or 5174 at 2026-10-22T09:56:59Z [E-018].

The newest verified activity is 2026-10-21T20:03Z: `soma.json`, the checkpoints, the queue files, and the pipeline logs all carry that mtime. The last log line is OUTROBEAVER `DONE` for session `25-11-20-multiclip.2.0.feature.overhaul` chatset 2, `tokens=28704 ms=14539 model=apodex/apodex-1.1-mini verdict=RED` [E-020].

Importability is intact on the current source tree: with `PYTHONPATH=turn-key:soma`, `machinetalk.engine` and `store` import from the project and `turnkey` imports from `/home/flintx/.local/lib/python3.11/site-packages/turnkey/__init__.py` [E-017]. `pytest soma/test_run_engine_soma_only.py` passed 6 tests at 2026-10-22T09:59Z [E-022].

The persisted graph is inconsistent with the pipeline's own write path: 997 nodes but 1 edge (`CONTAINS`), distributed as `ChatSet 788`, `TaskNode 133`, `ReceptorLog 60`, `SessionAnchor 16` [E-005]. Edges are written but not reloaded (C-04).

Stage 2–4 have left no output: `soma/output` contains `checkpoints/`, `stage1/`, `artifacts/`, `skip_vault/`, `logs/`, and `soma.json` only — no `stage2`, `stage3`, `stage4`, or `codebase` directory [E-004]. Every inspected checkpoint has `session_stages: {}` [E-025].

Thirteen checkpoints are frozen mid-stage-1 (every ChatSet at `distiller: RUNNING`), for example `250602-1389` with 90 chatsets and `26-01-12-peacock.project.timeline.revealed` with 303 chatsets [E-025]. Two sessions have partial terminal state: `260622-2403` has cs1 `planbeaver RUNNING`, cs2 `planbeaver BLOCKED`, cs3 `distiller FAILED`; `25-11-20-multiclip.2.0.feature.overhaul` has cs1 `distiller FAILED` and cs2 fully `DONE` [E-025].

The remote model service is live but does not host this component: `peacock-engine` is `active`, its `WorkingDirectory=/root/hetzner/ai-engine`, `GET http://127.0.0.1:3099/health` returns `PEACOCK_ENGINE_V3` `ONLINE`, and `/root/hetzner/ai-engine/soma` does not exist [E-023].

The project is not a git repository [E-002], so no commit-level provenance exists; mtimes are the only dating signal.

## Key Paths and Entry Points
The bounded inventory scanned both roots: 177 files at depth 3 under `soma/` and 337 under the project root [E-001]; every mtime below comes from the package listing [E-003].

| path | host | role | entrypoint? | lines | mtime (UTC) | evidence |
|---|---|---|---|---|---|---|
| `run.sh` | flintx | launcher; dispatches `--source`/`--queue` to `soma/run_engine.py`, else `run_sessions.py`; sets `PYTHONPATH=turn-key:soma` | yes | 19 | 2026-10-18T09:43:04Z | E-006 |
| `run_sessions.py` | flintx | interactive launcher, picker, profile/worker selection, spawns engine | yes | 1329 | 2026-10-22T02:16:01Z | E-007 |
| `soma/run_engine.py` | flintx | canonical engine CLI; queue/source load, dashboard thread, `--soma-only` | yes | 269 | 2026-10-22T02:46:35Z | E-008 |
| `soma/machinetalk/engine.py` | flintx | stage orchestration, checkpoints, artifacts, Soma writes | yes (imported) | 1025 | 2026-10-22T02:43:59Z | E-009 |
| `soma/machinetalk/client.py` | flintx | TurnKey adapter; the only model-call surface | yes (imported) | 182 | 2026-10-17T19:18Z | E-010 |
| `soma/machinetalk/source.py` | flintx | session and ChatSet loader, canonical hash | yes (imported) | 172 | 2026-10-18T13:49Z | E-011 |
| `soma/machinetalk/gate.py` | flintx | per-stage response validation | no | 290 | 2026-10-14T12:15Z | E-014 |
| `soma/machinetalk/checkpoint.py` | flintx | per-session checkpoint store | no | 266 | 2026-10-15T18:14Z | E-015 |
| `soma/machinetalk/soma_bridge.py` | flintx | stage output to graph node/edge translation | no | 538 | 2026-10-18T13:49Z | E-013 |
| `soma/store.py` | flintx | JSON-backed graph store | yes (imported) | 135 | 2026-10-18T02:56:57Z | E-012 |
| `soma/machinetalk/invariants.py` | flintx | four hard-coded invariant rules | no | 66 | 2026-10-14T12:15Z | E-029 |
| `run_dashboard.py` | flintx | standalone dashboard launcher (port 9877 constant) | yes | 156 | 2026-10-17T18:00Z | E-016 |
| `soma/machinetalk/debug_dashboard.py` | flintx | HTTP dashboard and JSONL event writer | yes (imported) | 1216 | 2026-10-21T14:30Z | E-033 |
| `soma/turn-key-profiles/soma-current.json` | flintx | model deck + pipeline settings | config | — | 2026-10-21T04:08Z | E-026 |
| `soma/machine-talk/tb-*.md` | flintx | system prompts for 12 stages | config | — | 2026-10-14T12:15Z | E-034 |
| `soma/output/checkpoints/*.checkpoint.json` | flintx | resume state | datastore | 16 files | 2026-10-21T20:03Z | E-025 |
| `soma/output/soma.json` | flintx | graph output | datastore | 420,111 B | 2026-10-21T20:03Z | E-005 |

`--soma-only` is a second, narrower entry inside the same CLI: it loads the first session and first ChatSet, writes `SessionAnchor`, `ChatSet`, and `ReceptorLog`, then exits without calling the beavers or stages 2–4 (`soma/run_engine.py:135-265`) [E-008].

## Architecture and Data Flow

```text
                    +-----------------------------------------------+
                    |  run.sh                                        |
                    |    --source/--queue --> soma/run_engine.py      |
                    |    default ------------> run_sessions.py       |
                    +----------------+------------------------------+
                                     | subprocess.run (argv, cwd=root)
                                     v
+---------------------+     +-----------------------------------------+
| soma-session-picker |     | run_engine.py                           |
|  bash start.sh      |---->|  load_source() -> [Session] -> [ChatSet]|
|  :5174 (pick)       | env |  EngineClient(profile)                  |
|  writes queue JSON  |     |  start_dashboard(port=9877)  [thread]   |
+---------------------+     |  engine.run(...)                        |
        ^                   +----+-------------------+----------------+
        | SESSIONS_PATH          |                   |
        | QUEUE_OUTPUT_PATH      v                   v
+-------+----------+     +--------------+    +---------------------+
| /media/storage/  |     | machinetalk/ |    | soma/output/        |
| dendritic123/    |     | engine.py    |--->| checkpoints/        |
| chat-logs/       |     |  stage 1 x4  |    | stage1..4/*.md      |
| sessions/        |     |  stages 2-4  |    | artifacts/*.json    |
+------------------+     +------+-------+    | soma.json           |
                                |            | run_manifest.md     |
                                | client.py  +---------------------+
                                v
                     +-----------------------+
                     | turnkey SDK (installed)|
                     |  run_stage(name, msgs) |
                     +-----------+-----------+
                                 | HTTP (not executed this run)
                                 v
                     +-----------------------+
                     | engine.save-aichats.com|
                     | :3099  [remote]        |
                     +-----------------------+
```

Unverified edge: the HTTP request body and response handling inside the SDK are not inspected (U-01), so the hop from `client.py` to the remote service is labeled `?` for payload shape.

```text
queue/source JSON
   |
   v
load_source()  soma/machinetalk/source.py:152-171
   |  Session{chatsets[]}, ChatSet{raw_chat_set, hash}
   v
Engine.run()  soma/machinetalk/engine.py:976-1025
   |
   +--> run_stage1()  soma/machinetalk/engine.py:536-656
   |       | jobs = chatsets not fully DONE        (skip resume)
   |       | ThreadPoolExecutor(workers)
   |       v
   |    run_chatset()  soma/machinetalk/engine.py:479-532
   |       | write SessionAnchor + ChatSet -> soma
   |       | for stage in distiller,introbeaver,planbeaver,outrobeaver
   |       |    payload = raw_chat_set + static extras      <-- no upstream output
   |       v
   |    _run_chatset_stage()  soma/machinetalk/engine.py:297-477
   |       | checkpoint RUNNING
   |       | client.call_stage -> gate.validate
   |       | write stage1 .md + artifacts/<id>/<stage>.json
   |       | write debug JSONL event
   |       +-- DONE/SKIPPED -> cs_mark + Soma nodes + _persist
   |       +-- BLOCKED      -> cs_mark BLOCKED
   |       +-- FAILED       -> cs_mark FAILED
   |       v
   |    if any chatset failed -> run() returns 1  (stages 2-4 skipped)
   v
run_stages_2_4()  soma/machinetalk/engine.py:797-945
   | nexus -> spark -> falcon -> eagle -> drafter -> scout -> oc -> olc
   | each: _run_build_stage -> artifact + Soma node
   | oc REWORK -> checkpoint BLOCKED, return False
   | olc DONE -> _write_codebase() -> codebase/<build>/ + VerifiedNode
   v
run_manifest.md
```

## Core Logic
1. **Launch.** `run.sh` prepends `turn-key` and `soma` to `PYTHONPATH`; with `--source` or `--queue` it `cd`s into `soma/` and `exec`s `run_engine.py`, otherwise it `exec`s `run_sessions.py` (`run.sh:9-19`) [E-006].
2. **Launcher path.** `run_sessions.py` resolves a profile (`soma/turn-key-profiles/soma-current.json` first, then `*profile*.json`), resolves the queue, chooses workers (default 1 from state, 2 if unset), and starts a dashboard process on 9877 (`run_sessions.py:60-82`, `run_sessions.py:341-357`) [E-007][E-027][E-032].
3. **Queue write.** The launcher writes the same object to `data/soma_queue.json` and `data/queue.json` with `selected`, `count`, `running`, `started_at`, `profile`, then invokes `run_engine.py --queue <soma_queue.json> --profile … --debug /tmp/soma_debug --out soma/output --port 9877 --workers N [--max-chatsets N]` with a 36000 s timeout (`run_sessions.py:262-314`) [E-007].
4. **Load.** `run_engine.load_queue()` reads `selected` and resolves each entry against `/media/storage/dendritic123/chat-logs/sessions`, falling back to the raw path; `load_source()` then returns sessions oldest-first by session id (`soma/run_engine.py:51-76`, `soma/machinetalk/source.py:152-171`) [E-008][E-011].
5. **ChatSet assembly.** For each `set_number`, chunk files are sorted by their numeric chunk index, `user_text` and `assistant_text` are concatenated, and the canonical `raw_chat_set` is `[{"role":"USER",…},{"role":"AGENT",…}]` (empty roles dropped); `chatset_hash_for(raw)` produces the sha256 used by gates (`soma/machinetalk/source.py:80-120`) [E-011].
6. **Engine construction.** `Engine.__init__` creates `CheckpointStore(out)`, `Manifest(out)`, `StageLogger`, and `AtomicSoma(out/soma.json)` wrapped in `SomaBridge` (`soma/machinetalk/engine.py:154-175`) [E-009].
7. **Stage-1 scheduling.** `run_stage1` skips chatsets whose `outrobeaver` is `DONE`/`SKIPPED` unless `force`, applies `max_chatsets`, and submits one job per ChatSet to `ThreadPoolExecutor(max_workers=workers)` (`soma/machinetalk/engine.py:536-595`) [E-009].
8. **Per-ChatSet writes.** Before any model call, `run_chatset` writes/rewrites `SessionAnchor` and `ChatSet` into Soma and persists (`soma/machinetalk/engine.py:489-498`) [E-009][E-013].
9. **Stage-1 calls.** The four stages run in fixed order. Each receives `{"session_id", "timestamp_utc", "raw_chat_set"}` plus static extras: planbeaver gets empty `codebase_context`/`invariant_rules`, outrobeaver gets `final_artifact_state` derived by regex over the transcript. Only the distiller gets the readable transcript as `chunk` (`soma/machinetalk/engine.py:287-295`, `503-523`) [E-009].
10. **Call and gate.** `EngineClient.call_stage` loads the system prompt via `fleet.load_system_prompt(stage, strip_injection=True)`, assembles the user message, makes one `sdk.run_stage(mapped, messages)` call, and validates the raw text with `gate.validate` (`soma/machinetalk/client.py:137-181`, `soma/machinetalk/fleet.py:94-170`) [E-010][E-014].
11. **Gate rules.** Each stage has required keys, a verdict key, and optionally a hash-echo key. Distiller `skip=true` clears errors (clean skip); `introbeaver NO_INTENT` is also a skip; verdicts in `block_tokens` (e.g. planbeaver `BLOCKED`/`INVALID_PLAN`, outrobeaver `GHOST_SESSION`, drafter `BROKEN_DRAFT`) become BLOCKED; scout is text and must start with `### SCOUT VIOLATION REPORT:` and end with `SCOUT REVIEW COMPLETE. VERDICT: <token>` (`soma/machinetalk/gate.py:79-108`, `169-290`) [E-014].
12. **Durability.** Before the call the stage is marked `RUNNING`; on pass the checkpoint stores verdict, model, tokens, chars, latency, artifact path, and full raw response/system/user text; artifacts are written to `stage1/<session>/<n>_<stage>.md` and `artifacts/<session:set>/<stage>.json` (`soma/machinetalk/engine.py:317-320`, `415-445`; `soma/machinetalk/report.py:146-163`) [E-009][E-015].
13. **Soma writes.** On pass, distiller writes `ReceptorLog` + `PROCESSED_BY`; introbeaver writes `IntentNode` + `YIELDS`; planbeaver writes one `TaskNode` per plan file; outrobeaver writes `OutcomeNode` (`soma/machinetalk/engine.py:446-455`; `soma/machinetalk/soma_bridge.py:82-160`) [E-009][E-013].
14. **Failure.** A hard-block verdict marks `BLOCKED`; anything else marks `FAILED`. `run_stage1` returns false if any chatset failed or crashed, and `run()` returns 1 immediately, so stages 2–4 never start (`soma/machinetalk/engine.py:457-477`, `599-615`, `990-993`) [E-009].
15. **Build unit.** One session yields build id = session id; multiple sessions yield `project-<id>-<id>…`, and `_merged_raw` concatenates all chatsets chronologically, deduplicating by hash (`soma/machinetalk/engine.py:660-670`, `987-988`) [E-009].
16. **Stages 2–4.** Fixed order `nexus, spark, falcon, eagle, drafter, scout, oc, olc`. Each stage reads earlier artifacts from `artifacts/<build>/<stage>.json`; missing upstream aborts the build with a printed reason (`soma/machinetalk/engine.py:797-879`) [E-009].
17. **Scout rules.** The engine instantiates `InvariantRegistry()` with no path, so the four hard-coded rules INV-001..004 are used, filtered by file extension (`soma/machinetalk/engine.py:871-879`; `soma/machinetalk/invariants.py:13-66`) [E-029].
18. **OC and OLC.** OC reads draft + scout; a `REWORK` verdict marks the stage BLOCKED and returns false. OLC reads OC decision + scout violations, and on success `_write_codebase` writes `olc_output.hardened_files` (or the drafter files as fallback) under `codebase/<build>/` after rejecting empty or `..` paths, then writes `VerifiedNode` records (`soma/machinetalk/engine.py:901-969`; `soma/machinetalk/soma_bridge.py:522-537`) [E-009][E-013].
19. **Dashboard event bug.** In `run_stage1`'s completion loop, the summary event uses `sid, n` at `soma/machinetalk/engine.py:624` before `sid, n` are assigned at `soma/machinetalk/engine.py:642`, so that write raises `NameError` and is swallowed by `except Exception: pass`; only the per-stage event written inside `_run_chatset_stage` reaches the JSONL (`soma/machinetalk/engine.py:617-639`) [E-009].
20. **Store defect.** `AtomicSoma._persist` serializes edges with key `relationship`; `Soma._load` reads `edata["rel_type"]` inside a bare `try/except`, so a reload drops every edge and keeps the nodes loaded before the exception (`soma/machinetalk/engine.py:75-92`; `soma/store.py:38-56`, `58-73`) [E-009][E-012]. The live file's 1 edge against 997 nodes matches this path [E-005].

## Configuration and Invariants
- **Profile.** `soma/turn-key-profiles/soma-current.json` defines a 9-card deck (`deepseek-v4-pro` on ollama, `nvidia/nemotron-3.5-lightning:free` on openrouter, `inclusionai/ling-3.1-flash` and `zai-org/glm-4.6v` on novita, `qwen/qwen3.6-plus:free` on xkiro, `nemotron-3-nano:30b-cloud`, `apodex/apodex-1.1-mini`, `kimi-k2.7-code:cloud`, `cohere/north-mini-code`) and 12 stage entries, all `useDeck: true`; `pipeline` sets `mode: sequential`, `workers: 1`, `timeout: 180`, `maxRetries: 10` [E-026].
- **Precedence.** The launcher probes `soma/turn-key-profiles/soma-current.json`, then `soma/turn-key-profiles/*profile*.json`, then project-root `soma-current.json` and `*profile*.json` (`run_sessions.py:60-82`) [E-027]. The interactive UI instead lists `<base>/turn-key-profile/*.json` from `_get_base_dir()` plus the legacy directory (`run_sessions.py:621-644`) [E-028]. Runtime state on disk points at `/home/flintx/soma-10-14/turn-key-profile/pro-name_2026-10-21T21-06-14.json` as last used [E-021].
- **Paths and ports.** Engine defaults: `--out /tmp/soma_out`, `--debug /tmp/soma_debug`, `--workers 2`, `--port 9876` (`soma/run_engine.py:84-92`). The launcher overrides output to `soma/output` and port to 9877 (`run_sessions.py:45-54`, `288-299`) [E-007].
- **Environment.** The engine reads one variable, `HETZNER_OUTPUT_LOG`; when set it appends `<ISO> <output_path>` after a run (`soma/run_engine.py:32-48`) [E-008]. No other `os.environ` read exists on the engine path.
- **Stage contracts.** Prompt bodies for all 12 stages exist on disk under `soma/machine-talk/` (`tb-001`…`tb-014` plus `tb-002-pipeline-protocol.md` and `tb-003-system-base.md`) [E-034]. Required keys per stage: distiller `chatset_hash`,`skip`; introbeaver `introbeaver_output`; planbeaver `planbeaver_output`; outrobeaver `outrobeaver_output`; nexus `plan_hash_verification`,`blueprints`; spark `plan_hash_verification`,`functional_requirements`; falcon `plan_hash_verification`,`component_architecture`; eagle `file_tree`,`skeleton_blocks`; drafter `draft_artifact`; oc `oc_decision`; olc `olc_output` (`soma/machinetalk/gate.py:79-99`) [E-014].
- **Hash enforcement.** Hash echo is a warning, not an error: `missing_hash_echo` and `hash_mismatch` are appended to warnings and the gate can still pass (`soma/machinetalk/gate.py:186-198`) [E-014].
- **Checkpoint invariants.** One file per session at `<out>/checkpoints/<session_id>.checkpoint.json`, atomic replace via `tempfile.mkstemp` + `os.replace`, statuses `PENDING RUNNING DONE FAILED SKIPPED BLOCKED` (`soma/machinetalk/checkpoint.py:76-130`) [E-015].
- **Documented-only invariants.** The checkpoint docstring says FAILED means "all retry models exhausted" (`soma/machinetalk/checkpoint.py:20-27`), but the engine writes FAILED after a single call, and the client performs no retry loop (`soma/machinetalk/engine.py:467-476`; `soma/machinetalk/client.py:137-162`) [E-015][E-009][E-010]. The gate docstring's rotation claim is likewise not enforced in this package (`soma/machinetalk/gate.py:8-12`) [E-014].
- **Graph contract.** Node type is a free-form string passed to `Soma.create_node`; there is no schema or enum. Edge relation is a free-form string passed to `create_edge` (`soma/store.py:75-106`) [E-012].
- **Graph property defect.** `write_chatset` stores `chatset_hash` as the text after ":" in `session:set`, i.e. the set number; live nodes show `"chatset_hash": "1"` (`soma/machinetalk/soma_bridge.py:69-77`) [E-013][E-005].

## Dependencies and Cross-Component Connections
**Verified**
- **Launcher to engine:** `subprocess.run` of `soma/run_engine.py` with queue, profile, debug, out, port, workers, optional max-chatsets; `cwd` is the project root, timeout 36000 s (`run_sessions.py:288-314`) [E-007].
- **Engine to turnkey SDK:** `from turnkey.profile_integration import initialize_sdk_with_profile`; `sdk.run_stage(mapped_stage, messages)`; stage names map through `_STAGE_MAP`, e.g. `classifier→introbeaver`, `retrograde→outrobeaver`, `axon_hillock→oc`, `myelinator→olc` (`soma/machinetalk/client.py:15-36`, `86-100`) [E-010].
- **Engine to chat logs:** directory read of `session.json` and numbered chatset JSON under the queue paths; the loader hard-codes no root but the launcher and `load_queue` use `/media/storage/dendritic123/chat-logs/sessions` (`soma/machinetalk/source.py:123-171`; `soma/run_engine.py:64`) [E-011][E-008].
- **Engine to Soma store:** in-process `create_node`/`create_edge` through `SomaBridge`, persisted by `AtomicSoma` on every stage completion (`soma/machinetalk/engine.py:446-455`, `725-746`) [E-009][E-013].
- **Launcher to picker:** `bash soma-session-picker/start.sh` with `SESSIONS_PATH=/media/storage/dendritic123/chat-logs/sessions` and `QUEUE_OUTPUT_PATH=<project>/data/soma_queue.json`; polls `http://localhost:5174` for 30 s (`run_sessions.py:472-515`) [E-031].
- **Launcher to dashboard:** `Popen([python, run_dashboard.py, --no-open, --port, 9877])`; the engine additionally starts an in-process HTTP server on the same port and runs `fuser -k <port>/tcp` first (`run_sessions.py:341-357`; `soma/machinetalk/debug_dashboard.py:108-113`) [E-032][E-033].
- **Engine to remote model service:** the turnkey SDK resolves `engineUrl` from the profile or defaults to the host `engine.save-aichats.com` on port 3099; DNS resolves to 204.168.184.49 and `GET /health` returns 200 in 0.529 s from flintx (`/home/flintx/.local/lib/python3.11/site-packages/turnkey/profile_integration.py:75`; `/home/flintx/.local/lib/python3.11/site-packages/turnkey/sdk.py:37`) [E-030][E-024].
- **Remote ai-engine:** `peacock-engine` active on ubuntu-8gb-hel1-1, health `ONLINE`, and no `soma` directory under `/root/hetzner/ai-engine` [E-023].

**Inferred, not executed**
- The exact HTTP request the SDK issues to `:3099` during `run_stage` (U-01). The only default-URL evidence is the SDK constant and the profile's absent `engineUrl`.
- That a healthy `:3099` implies stage calls would succeed. No model call was made in this run by design (read-only rule; a stage call writes to the remote service).

## Known Gaps and Uncertainties

### G-01 SDK internals (U-01)
Rotation, retry, and key selection inside `run_stage` are outside this target. The profile declares `maxRetries: 10` [E-026], while soma records one attempt [E-010], so failure semantics depend on which layer retries. Close by running target `turn-key` and reading `sdk.py:run_stage`.

### G-02 Edge loss (C-04)
Edges written by the engine cannot be reloaded because of the `relationship`/`rel_type` mismatch [E-009][E-012]. Any consumer of `soma.json` sees a node-only graph [E-005]. Close by writing one node and edge into a scratch store and reloading it, or by reconciling the two serializers.

### G-03 Dashboard process collision (C-02, C-03)
The launcher's dashboard and the engine's in-process dashboard both target 9877, and the engine runs `fuser -k` on that port before binding [E-032][E-033]. `run_dashboard.py` ignores `--port` and writes `.dashboard_port=9878` [E-016][E-019]. The URL printed by the launcher is therefore not necessarily the URL served. Close with a single controlled launch and `ss` before and after.

### G-04 Unchained stage-1 calls (C-01)
The fleet docstring and `cli-manifest.json` describe predecessor-to-successor inputs, while the engine sends only the raw ChatSet plus static extras [E-009]. Beaver outputs are produced from raw text, not from the distiller's extraction, which matches checkpoints where distiller is FAILED while introbeaver and outrobeaver are DONE [E-025]. Close by inspecting the payload section of one `stage1/<session>/<n>_introbeaver.md`.

### G-05 No stage-2–4 evidence (U-02)
There is no `stage2/3/4`, `codebase`, or `session_stages` output anywhere under `soma/output` [E-004][E-025]. The build pipeline is code-complete but operationally unproven on this host. Close by scanning `/tmp/soma_out`, archives, and `soma-grok/` for matching artifacts.

### G-06 Stale RUNNING states (U-03)
Thirteen checkpoints freeze at `distiller: RUNNING` (every ChatSet in the file) [E-025]. Resume logic trusts `DONE`/`SKIPPED` and will re-run these chatsets, but the cause (SIGKILL versus crash) is unknown. Close with system logs around 2026-10-18T10:18Z.

### G-07 Stale and wrong graph metadata (C-07, C-08)
The launcher guide names stage files that do not exist, and `ChatSet.chatset_hash` in the graph is the set number [E-035][E-013]. Doc-driven debugging will look in the wrong module, and hash-based verification of graph nodes is impossible. Close by regenerating the guide from the live import graph and fixing the bridge property.

### G-08 Unexamined boundaries (U-05, U-06, U-07)
The picker's actual queue write path, whether `--soma-only` ever ran against the live output tree, and whether `soma-grok/` is an archive or a live duplicate are outside this target. Each could explain duplicate or missing output. Close with a picker-scoped run, a shell-history search, and an import/reference scan of `soma-grok/`.

### G-09 Boundary gap: SDK payload shape
The request body sent to `engine.save-aichats.com` on port 3099 and the response envelope (`choices[0].message.content`, `usage.*`) are consumed at `soma/machinetalk/client.py:103-115` but produced inside the SDK [E-010]. Treat the shape as an interface assumption until `turn-key` is examined separately.

## Evidence Log
| ID | host | kind | locator | captured at | proves | confidence |
|---|---|---|---|---|---|---|
| E-001 | flintx | inventory | `.forensic/soma/20261022T095652Z-3411e1/01-inventory.txt` | 2026-10-22T09:56:53Z | roots, file counts, newest files, entrypoint heads | C1 |
| E-002 | flintx | command | `git -C /home/flintx/soma-10-14 rev-parse --is-inside-work-tree` | 2026-10-22T09:58Z | not a git work tree | C1 |
| E-003 | flintx | command | `find soma -maxdepth 2 -type f -name '*.py' -printf ...` | 2026-10-22T09:58Z | package sizes and mtimes | C1 |
| E-004 | flintx | command | `find soma/output -maxdepth 2 -type f/-type d` | 2026-10-22T09:58Z | output layout; no stage2-4 or codebase | C1 |
| E-005 | flintx | command | `python3 -c` parse of `soma/output/soma.json` | 2026-10-22T09:58Z | 997 nodes, 1 edge, type counts, chatset_hash="1" | C1 |
| E-006 | flintx | source | `run.sh:1-19` | 2026-10-22T09:58Z | launcher dispatch and PYTHONPATH | C2 |
| E-007 | flintx | source | `run_sessions.py:45-54,208-339,341-357,621-700,1231-1330` | 2026-10-22T09:58Z | constants, subprocess argv, dashboard start, profile discovery, CLI | C2 |
| E-008 | flintx | source | `soma/run_engine.py:23-128,135-269` | 2026-10-22T09:58Z | CLI, queue loader, dashboard thread, soma-only path | C2 |
| E-009 | flintx | source | `soma/machinetalk/engine.py:64-102,287-532,536-656,680-945,976-1025` | 2026-10-22T09:58Z | AtomicSoma, payloads, scheduling, checkpoints, Soma writes, stages 2-4 | C2 |
| E-010 | flintx | source | `soma/machinetalk/client.py:15-36,79-120,123-181` | 2026-10-22T09:58Z | stage map, single `run_stage`, no retry loop | C2 |
| E-011 | flintx | source | `soma/machinetalk/source.py:80-171` | 2026-10-22T09:58Z | ChatSet assembly, hashing, session discovery | C2 |
| E-012 | flintx | source | `soma/store.py:26-135` | 2026-10-22T09:58Z | JSON store; `rel_type` on load and persist | C2 |
| E-013 | flintx | source | `soma/machinetalk/soma_bridge.py:47-160,166-537` | 2026-10-22T09:58Z | node/edge creation per stage; wrong chatset_hash | C2 |
| E-014 | flintx | source | `soma/machinetalk/gate.py:79-108,169-290` | 2026-10-22T09:58Z | per-stage specs, validation, skip/block semantics | C2 |
| E-015 | flintx | source | `soma/machinetalk/checkpoint.py:1-130` | 2026-10-22T09:58Z | checkpoint schema, statuses, atomic write | C2 |
| E-016 | flintx | source | `run_dashboard.py:16-38,98-115` | 2026-10-22T09:58Z | port constant, no argparse, kill_port/find_port | C2 |
| E-017 | flintx | command | `PYTHONPATH=turn-key:soma python3 -c 'importlib.util.find_spec ...'` | 2026-10-22T09:58Z | import resolution and successful engine import | C1 |
| E-018 | flintx | command | `ps -eo pid,ppid,etimes,cmd \| rg ...`; `ss -lntp` | 2026-10-22T09:56:59Z | no process, no dashboard/listener ports | C1 |
| E-019 | flintx | command | `cat .dashboard_port`; `ss -lntp` | 2026-10-22T09:56:59Z | port file 9878; nothing listening | C1 |
| E-020 | flintx | logs | `20261022_030327_pipeline.log`, `20261022_030237_pipeline.log`, `20261022_030126_pipeline.log` tails | 2026-10-22T09:56:59Z | resume skips; OUTROBEAVER DONE verdict=RED | C1 |
| E-021 | flintx | files | `data/queue.json`, `data/soma_queue.json`, `data/.last_workers`, `data/.last_queue`, `data/.last_profile` | 2026-10-22T09:56:59Z | queue contents and last-used state | C1 |
| E-022 | flintx | command | `python3 -m pytest soma/test_run_engine_soma_only.py -q` | 2026-10-22T09:59Z | 6 tests pass | C1 |
| E-023 | flintx + remote | command | `ssh engine 'hostname; systemctl is-active peacock-engine; systemctl show ...; curl :3099/health; ls -d .../soma'` | 2026-10-22T09:57:25Z | remote identity, service active, health ONLINE, no soma dir `[remote]` | C1 |
| E-024 | flintx | command | `getent hosts engine.save-aichats.com`; `tailscale status`; `curl -m 8 /health` | 2026-10-22T09:59Z | DNS 204.168.184.49, direct tailscale path, HTTP 200 in 0.529 s | C1 |
| E-025 | flintx | data | `soma/output/checkpoints/*.checkpoint.json` (16 files) | 2026-10-22T09:58Z | RUNNING/FAILED/BLOCKED states; empty `session_stages` | C1 |
| E-026 | flintx | config | `soma/turn-key-profiles/soma-current.json` | 2026-10-22T09:58Z | 9-model deck, 12 stages, pipeline settings | C2 |
| E-027 | flintx | source | `run_sessions.py:60-82` | 2026-10-22T09:58Z | auto-detect profile order | C2 |
| E-028 | flintx | source | `run_sessions.py:589-644` | 2026-10-22T09:58Z | base dir, profile discovery, builder launch | C2 |
| E-029 | flintx | source | `soma/machinetalk/invariants.py:13-66`; `soma/machinetalk/engine.py:872-874` | 2026-10-22T09:58Z | four hard-coded rules; no path passed | C2 |
| E-030 | flintx | source | `/home/flintx/.local/lib/python3.11/site-packages/turnkey/profile_integration.py:7-75`; `/home/flintx/.local/lib/python3.11/site-packages/turnkey/sdk.py:37` | 2026-10-22T09:58Z | SDK import surface; default engine URL | C2 |
| E-031 | flintx | source | `run_sessions.py:472-515` | 2026-10-22T09:58Z | picker launch, env vars, readiness poll | C2 |
| E-032 | flintx | source | `run_sessions.py:341-357,288-299` | 2026-10-22T09:58Z | launcher dashboard on 9877; engine also gets port 9877 | C2 |
| E-033 | flintx | source | `soma/machinetalk/debug_dashboard.py:89-125,1199-1225` | 2026-10-22T09:58Z | `fuser -k` then bind; JSONL event append | C2 |
| E-034 | flintx | files | `soma/machine-talk/` prompt corpus | 2026-10-22T09:58Z | prompts exist; marker tails | C1 |
| E-035 | flintx | docs | `README.md`; `DROID-RESET.md`; `SESSION-LAUNCHER-GUIDE.md`; `MACHINE_TALK_SPEC.md`; `cli-manifest.json` | 2026-10-22T09:58Z | documented claims and mtimes; stale stage file map | C3 |
