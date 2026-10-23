# Discovery Notes: spark

TARGET: spark
RUN ID: 20261022T123742Z-7187da
DATE: 2026-10-22T12:37:42Z
HOST: flintx

## Target lock

TARGET: spark
SLUG: spark
RUN ID: 20261022T123742Z-7187da
SCOPE: Derives a RequirementsNode from a SessionAnchor/StrategicBlueprint via an LLM call.
EXCLUDED: every other component; sibling components are interfaces only.

## Inventory summary

- Root: `/home/flintx/soma-10-14/soma` exists, 181 files at depth 3.
- Entry point: `spark_dendrite.py` — 100 lines, mtime 2026-10-18T01:40:17Z.
- Configs: none declared.
- Datastores: `workspaces/` declared in registry but does not exist on disk.
- Git: directory is not a repository (no `.git` at project root level for soma subdir).
- Newest file in root: `docs/integrator-forensic.md` (2026-10-22T05:36Z).
- Entry point is the fourth-newest Python module (after run_engine.py, machinetalk/engine.py, interactive.py).

## Entry points

| Path | Host | Lines | Mtime | Role |
|---|---|---|---|---|
| `spark_dendrite.py` | flintx | 100 | 2026-10-18T01:40:17Z | Main module [E-001] |
| `run_pipeline.py:27,124` | flintx | — | 2026-10-21T19:46Z | Import + instantiation [E-002] |
| `run_tb007.py:18,74` | flintx | — | — | Import + standalone runner call [E-003] |
| `machinetalk/engine.py:99,729` | flintx | — | 2026-10-21T19:43Z | Build stage registration + SomaBridge write [E-004] |
| `machinetalk/soma_bridge.py:14,206` | flintx | — | — | SomaBridge.write_spark mapping [E-005] |
| `machine-talk/tb-008-spark.md` | flintx | 80 | — | MachineTalk prompt spec [E-006] |

## Runtime state

- No process running that directly invokes spark (not a standalone daemon).
- Spark is invoked as a stage within two orchestration paths:
  1. `run_pipeline.py` — `InteractiveRunner.run()` → `SparkDendrite(...).run(session_id)` [E-002]
  2. `machinetalk/engine.py` — `run_stages_2_4()` → `_run_build_stage("spark", ...)` → SomaBridge.write_spark [E-004]
- Neither path was probed live (no `python3 run_pipeline.py` or `python3 run_engine.py` executed during this run).

## Data stores

- `workspaces/` at `/home/flintx/soma-10-14/soma/workspaces`: does **not exist** on disk. Registry declares it as a datastore; inventory confirms `exists=False`.
- `soma.json` at `/home/flintx/soma-10-14/soma/output/soma.json`: exists (mtime 2026-10-21T20:03Z), contains the Soma graph store including RequirementsNode data. [E-007]

## Configuration and invariants

- Default instruction: `_DEFAULT_SPARK_INSTRUCTION` (lines 15-20 of spark_dendrite.py) — a system prompt asking for `{"requirement_text": str, "source_blueprint_id": str}` JSON. [E-001]
- `get_receptor_config(self._soma, "spark")` at line 58 queries `ReceptorConfig` nodes by `name` or `stage` key. If found, its `instruction_body` overrides the default. [E-001]
- `stage_name = "spark"` — hardcoded on line 34. [E-001]
- `complete_stage()` from `pipeline.stage_complete.py` — handles LLM call, JSON extraction, and metrics. [E-008]
- `turn-key-profiles/soma-current.json` — TurnKey profile used by TurnKeyClient; spark maps to `"spark"` in `_STAGE_MAP` at line 24 of `llm_sdk.py`. [E-009]
- `machine-talk/tb-008-spark.md` — MachineTalk prompt spec with full output schema (SPARK_SPECIFICATION, FR-NNN, NFR-NNN, scout_signal, etc.). [E-006]

## Cross-component edges

| From | To | Mechanism | Evidence |
|---|---|---|---|
| `spark_dendrite.py` | `store.Soma` | import + `create_node("RequirementsNode", ...)` [E-001] |
| `spark_dendrite.py` | `soma.helpers.get_receptor_config` | import + query ReceptorConfig nodes [E-001] |
| `spark_dendrite.py` | `pipeline.stage_complete.complete_stage` | import + `complete_stage(llm, stage_name, instruction_body, payload)` [E-008] |
| `spark_dendrite.py` | `llm_client.call(stage, messages)` | runtime call (expects `call` method) [E-010] |
| `machinetalk/engine.py` | `spark_dendrite.py` | **does not import** engine runs spark via MachineTalk client, not via SparkDendrite class [E-004] |
| `machinetalk/engine.py` | `machinetalk.soma_bridge.SomaBridge.write_spark` | `self._bridge.write_spark(build, gate, rec.model, latency)` [E-004] |
| `machinetalk/soma_bridge.py` | `Soma.create_node("RequirementsNode", ...)` | bridge writes to the Soma graph store [E-005] |
| `run_pipeline.py` | `spark_dendrite.SparkDendrite` | `SparkDendrite(self._soma, self._llm, None).run(self._session_id)` [E-002] |
| `run_tb007.py` | `spark_dendrite.SparkDendrite` | `SparkDendrite(soma, llm, rotator).run(session_id)` — but rotator is passed, not None [E-003] |
| `machine-talk/tb-008-spark.md` | `machinetalk/client.py` | MachineTalk spec used by the client for the "spark" stage [E-006, E-011] |
| `pipeline/llm_sdk.py` | `turnkey.sdk` | TurnKeyClient wraps TurnKey SDK `run_stage("spark", messages)` [E-009] |

## Instructions and recency

| Doc | Mtime | Authority Rank |
|---|---|---|
| `spark_dendrite.py` (docstring TB-DEND-021) | 2026-10-18T01:40:17Z | C2 — current source code [E-001] |
| `machine-talk/tb-008-spark.md` | — (mtime not captured) | C3 — prompt spec [E-006] |
| `machinetalk/soma_bridge.py` mapping table | 2026-10-21T19:43Z | C2 — current source [E-005] |
| `run_pipeline.py` docstring | 2026-10-21T19:46Z | C2 — current orchestrator [E-002] |

## Conflicts

CONFLICT C-01
  claim A: `spark_dendrite.py` calls `llm.call(stage, messages)` [E-010]
  claim B: `TurnKeyClient` only defines `chat()`, not `call()` [E-012]
  resolution: both-live (the code has the call on line 35 of stage_complete.py, but the runtime class lacks the method)
  impact: SPARK will FAIL at runtime with AttributeError when invoked through complete_stage() with a TurnKeyClient. This affects run_pipeline.py and run_tb007.py paths that pass real LLM clients. The machinetalk/engine.py path bypasses SparkDendrite entirely and uses MachineTalk client + SomaBridge.write_spark, which is unaffected.

CONFLICT C-02
  claim A: `spark_dendrite.py` expects `{"requirement_text": str, "source_blueprint_id": str}` [E-001]
  claim B: `machine-talk/tb-008-spark.md` defines full SPARK_SPECIFICATION schema with FR-NNN, NFR-NNN, data_requirements, critical_user_flows, gap_analysis, scout_signal [E-006]
  resolution: both-live (different specs, different callers)
  impact: SparkDendrite expects a minimal JSON but the MachineTalk spec requires a comprehensive specification. The SomaBridge.write_spark method (line 206) extracts `functional_requirements` from the parsed gate output, suggesting the bridge expects the full spec. There is a structural mismatch between what SparkDendrite produces and what the MachineTalk spec emits.

CONFLICT C-03
  claim A: `run_pipeline.py` passes `None` as third arg: `SparkDendrite(self._soma, self._llm, None)` [E-002]
  claim B: `run_tb007.py` passes `rotator`: `SparkDendrite(soma, llm, rotator)` [E-003]
  resolution: both-live (two different runner scripts)
  impact: The third constructor argument is never used in SparkDendrite (only `self._soma` and `self._llm` are stored). The rotator parameter is dead code in SparkDendrite but may be used by sibling stages.

## Unknowns and boundary gaps

U-01: No test file exists for spark. No `test_spark_dendrite.py` found. The stage is the only dendrite in the pipeline with zero test coverage. Evidence needed: a tracer-bullet test that instantiates SparkDendrite with a mock LLM and a session with a StrategicBlueprintNode, then asserts RequirementsNode creation.

U-02: `stage_complete.py` calls `llm.call(stage, messages)` but `TurnKeyClient` only defines `chat()`. This is a confirmed runtime error when SparkDendrite is used with a real LLM client through the `complete_stage()` path. Evidence needed: either (a) a `.call()` wrapper was added to TurnKeyClient in an uncommitted version, or (b) the code path has never been exercised live and the stage_complete path is dead code for spark.

U-03: The machinetalk/engine.py path uses the MachineTalk client to run "spark" as a build stage (line 830 of engine.py), not the SparkDendrite Python class. This means two entirely different code paths exist for "spark":
  1. The legacy dendrite path (SparkDendrite class) — called by run_pipeline.py and run_tb007.py
  2. The MachineTalk pipeline path (machine-talk prompt spec + client.run_stage) — called by machinetalk/engine.py
  These two paths produce structurally different outputs (minimal JSON vs. full SPARK_SPECIFICATION) that write to slightly different RequirementsNode property sets. Evidence needed: confirmation that the MachineTalk pipeline is the active production path and the SparkDendrite class is legacy/deprecated.

U-04: `workspaces/` directory is declared as a datastore in the registry but does not exist. Evidence needed: determine if this is intentional (no workspace persistence) or an omission from a previous cleanup.

U-05: The `run_engine.py` file (line 142 comment) explicitly states it "does NOT call stages 2-4 (nexus, spark, falcon, drafter, scout, oc, olc)." Evidence needed: confirm the current production runner path — is it `run_pipeline.py`, `run_engine.py`, or the machinetalk engine?

## Evidence index

| ID | host | kind | locator | captured_at | proves | confidence |
|---|---|---|---|---|---|---|
| E-001 | flintx | file | spark_dendrite.py | 2026-10-22T12:37Z | SparkDendrite class, run() path, RequirementsNode creation, DERIVED_FROM edge | C2 |
| E-002 | flintx | file | run_pipeline.py:27,124 | 2026-10-22T12:37Z | InteractiveRunner invokes SparkDendrite with TurnKeyClient and None rotator | C2 |
| E-003 | flintx | file | run_tb007.py:18,74 | 2026-10-22T12:37Z | Standalone runner invokes SparkDendrite with rotator | C2 |
| E-004 | flintx | file | machinetalk/engine.py:99,729,824-830 | 2026-10-22T12:37Z | Engine registers "spark" as stage2, calls _run_build_stage, calls SomaBridge.write_spark | C2 |
| E-005 | flintx | file | machinetalk/soma_bridge.py:14,206-229 | 2026-10-22T12:37Z | SomaBridge.write_spark maps gate.parsed to RequirementsNode | C2 |
| E-006 | flintx | file | machine-talk/tb-008-spark.md | 2026-10-22T12:37Z | MachineTalk prompt spec: full SPARK_SPECIFICATION output schema | C2 |
| E-007 | flintx | file | output/soma.json mtime | 2026-10-22T12:37Z | Soma graph persisted with current data | C2 |
| E-008 | flintx | file | pipeline/stage_complete.py:20-88 | 2026-10-22T12:37Z | complete_stage() orchestrates LLM call, JSON extraction, metrics | C2 |
| E-009 | flintx | file | pipeline/llm_sdk.py:21-30,24 | 2026-10-22T12:37Z | _STAGE_MAP maps "spark" → "spark" | C2 |
| E-010 | flintx | file | pipeline/stage_complete.py:35 | 2026-10-22T12:37Z | Calls llm.call(stage, messages) — expects .call() method | C2 |
| E-011 | flintx | file | machinetalk/client.py:25 | 2026-10-22T12:37Z | client.py maps "spark" → "spark" stage name | C2 |
| E-012 | flintx | command | python3 -c "from pipeline.llm_sdk import TurnKeyClient; print(hasattr(c, 'call'), hasattr(c, 'chat'))" | 2026-10-22T12:37Z | TurnKeyClient has chat but NOT call — confirmed AttributeError risk | C1 |

## Report plan

Sections:
1. Mandate — one sentence from E-001
2. Current State — two paths, two outputs, mtime from E-001/E-004
3. Key Paths and Entry Points — table from E-001 through E-012
4. Architecture and Data Flow — ASCII context diagram, sequence for both paths
5. Core Logic — SparkDendrite.run() full path, MachineTalk path via engine.py
6. Configuration and Invariants — default instruction, config override, stage maps
7. Dependencies and Cross-Component Connections — table from cross-component edges
8. Known Gaps — U-01 through U-05, C-01 through C-03
9. Evidence Log — full index above
