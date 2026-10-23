# Spark — Forensic Deep Dive

TARGET: spark | RUN: 20261022T123742Z-7187da | DATE: 2026-10-22T12:37:42Z | HOSTS EXAMINED: flintx
CONFIDENCE SUMMARY: C2 (static source analysis; no live execution of spark stages). One C1 finding: confirmed TurnKeyClient lacks .call() method.
SCOPE: Derives a RequirementsNode from a SessionAnchor/StrategicBlueprint via an LLM call.

## Mandate

Spark is a Stage-2 dendrite that calls an LLM to derive a RequirementsNode from the session's StrategicBlueprintNode.

## Current State

Two code paths exist for spark, producing structurally different outputs:

1. **Legacy dendrite path** — `spark_dendrite.py` (100 lines, mtime 2026-10-18T01:40:17Z) implements `SparkDendrite.run(session_id)`. Called by `run_pipeline.py` and `run_tb007.py`. Expects minimal JSON `{"requirement_text": str, "source_blueprint_id": str}`.
2. **MachineTalk pipeline path** — `machinetalk/engine.py` invokes the MachineTalk client for stage "spark" via `_run_build_stage("spark", ...)`. Uses `machine-talk/tb-008-spark.md` as the prompt spec. Produces a full SPARK_SPECIFICATION output. Writes via `SomaBridge.write_spark()`.

No process runs spark independently. The `workspaces/` datastore does not exist on disk. The only persisted graph output is `output/soma.json` (mtime 2026-10-21T20:03Z).

**Critical finding**: The legacy dendrite path contains a confirmed runtime bug — `stage_complete.py` calls `llm.call()` but `TurnKeyClient` only defines `chat()`. This causes `AttributeError` at runtime when `SparkDendrite` is used with a real LLM client.

## Key Paths and Entry Points

| Path | Host | Role | Entrypoint? | Lines | Mtime | Evidence |
|---|---|---|---|---|---|---|
| `spark_dendrite.py` | flintx | Main class + run() | Yes | 100 | 2026-10-18T01:40:17Z | [E-001] |
| `run_pipeline.py` | flintx | Pipeline orchestrator | Yes | 291 | 2026-10-21T19:46Z | [E-002] |
| `run_tb007.py` | flintx | Standalone TB-007 runner | Yes | 132 | — | [E-003] |
| `machinetalk/engine.py` | flintx | Build-stage orchestrator | Yes | 1000+ | 2026-10-21T19:43Z | [E-004] |
| `machinetalk/soma_bridge.py` | flintx | SomaBridge.write_spark() | Yes | 537 | 2026-10-21T19:43Z | [E-005] |
| `pipeline/stage_complete.py` | flintx | LLM call orchestration | Yes | 88 | — | [E-008] |
| `machine-talk/tb-008-spark.md` | flintx | Prompt spec | No | 80 | — | [E-006] |
| `pipeline/llm_sdk.py` | flintx | TurnKeyClient._STAGE_MAP | No | 82 | — | [E-009] |
| `soma/helpers.py` | flintx | get_receptor_config() | No | 26 | — | [E-001] |
| `store.py` | flintx | Soma graph store | No | 135 | — | [E-001] |
| `output/soma.json` | flintx | Persisted graph store | No | — | 2026-10-21T20:03Z | [E-007] |

## Architecture and Data Flow

```
                    ┌─────────────────────────────┐
                    │   Legacy Dendrite Path       │
                    │   run_pipeline.py /          │
                    │   run_tb007.py               │
                    └──────────┬──────────────────┘
                               │ SparkDendrite(soma, llm, None).run()
                               ▼
                    ┌─────────────────────────────┐
                    │   spark_dendrite.py          │
                    │   1. query_by_type("StrategicBlueprintNode") │
                    │   2. get_receptor_config(soma, "spark")     │
                    │   3. complete_stage(llm, "spark", ...)     │
                    │   4. create_node("RequirementsNode", ...)  │
                    │   5. create_edge(DERIVED_FROM)             │
                    └──────────┬──────────────────┘
                               │
                               ▼
                    ┌─────────────────────────────┐
                    │   stage_complete.py          │
                    │   llm.call(stage, messages)  │  ← BUG: .call() missing on TurnKeyClient
                    │   JSON parse + metrics       │
                    └──────────┬──────────────────┘
                               │
                               ▼
                    ┌─────────────────────────────┐
                    │   TurnKeyClient              │
                    │   .call() → AttributeError   │
                    │   .chat() exists but unused  │
                    └─────────────────────────────┘

                    ┌─────────────────────────────┐
                    │   MachineTalk Pipeline Path  │
                    │   machinetalk/engine.py      │
                    │   run_stages_2_4()           │
                    │   _run_build_stage("spark")  │
                    └──────────┬──────────────────┘
                               │ MachineTalk client + tb-008-spark.md
                               ▼
                    ┌─────────────────────────────┐
                    │   MachineTalk Client         │
                    │   stage="spark"              │
                    │   payload: nexus_output      │
                    │   → full SPARK_SPECIFICATION │
                    └──────────┬──────────────────┘
                               │ gate.parsed (full spec JSON)
                               ▼
                    ┌─────────────────────────────┐
                    │   SomaBridge.write_spark()   │
                    │   Extracts functional_reqs   │
                    │   → RequirementsNode         │
                    │   → edge blueprint→require  │
                    └─────────────────────────────┘
```

### Sequence: Legacy Dendrite Path (run_pipeline.py)

```
run_pipeline.py:124
  └─> SparkDendrite(soma, TurnKeyClient, None).run(session_id)
       └─> query_by_type("StrategicBlueprintNode") ──→ blueprint node
       └─> get_receptor_config(soma, "spark") ──→ instruction_body (or fallback)
       └─> complete_stage(llm, "spark", instruction_body, blueprint_text)
            └─> llm.call("spark", [{"system": instruction}, {"user": blueprint}])  ✗ AttributeError
       └─> (unreachable) create_node("RequirementsNode", ...)
       └─> (unreachable) create_edge("DERIVED_FROM")
```

### Sequence: MachineTalk Pipeline Path (engine.py)

```
engine.py:run_stages_2_4()
  └─> order = ["nexus", "spark", "falcon", ...]
  └─> stage == "spark"
       └─> _run_build_stage("spark", payload={"plan_context", "nexus_output"})
            └─> MachineTalk client.run_stage("spark", messages)
            └─> gate.verdict = DONE
            └─> SomaBridge.write_spark(build, gate.parsed, model, latency)
                 └─> Extracts gate.parsed["functional_requirements"]
                 └─> create_node("RequirementsNode", {id, session_id, requirement_text, model_id, latency_ms})
                 └─> create_edge(blueprint → requirement)
```

## Core Logic

### SparkDendrite.run() (spark_dendrite.py:30-100)

1. **Timestamp start** — `time.monotonic()` at line 32.
2. **Query StrategicBlueprintNode** — `self._soma.query_by_type("StrategicBlueprintNode")` filtered by `session_id` (lines 36-39). If none found, returns early with `{"error": "No StrategicBlueprintNode found"}` and metrics (lines 40-52).
3. **Load blueprint text** — Extracts `blueprint.properties["blueprint_text"]` (line 55).
4. **Load config** — `get_receptor_config(self._soma, "spark")` queries `ReceptorConfig` nodes by `name` or `stage` key. Falls back to `_DEFAULT_SPARK_INSTRUCTION` (lines 58-62). [E-001]
5. **Call complete_stage** — `complete_stage(self._llm, "spark", instruction_body, payload)` at line 65. This is where the path breaks. [E-010]
6. **Parse result** — Expects `result["requirement_text"]`. Falls back to `payload` if empty (lines 78-80).
7. **Write RequirementsNode** — Deletes any existing `req-{session_id}` node, creates fresh one with `id`, `session_id`, `requirement_text`, `source_blueprint_id`. [E-001]
8. **Create lineage edge** — `create_edge(requirements_id, "DERIVED_FROM", blueprint.id)` at line 94. [E-001]

### SomaBridge.write_spark() (soma_bridge.py:206-229)

The MachineTalk pipeline path uses a completely different write pattern:

1. **Extract functional_requirements** — `gate.parsed["functional_requirements"]` — joins list items with newlines (lines 211-217).
2. **Create RequirementsNode** — uses `requirements-{session_id}` as id (note: `run_pipeline.py` uses `req-{session_id}` — **different id scheme**). Properties include `model_id` and `latency_ms` (absent in legacy path). [E-005]
3. **Create edge** — `blueprint-{session_id} --YIELDS--> requirements-{session_id}` (legacy path uses `DERIVED_FROM`). [E-005]

## Configuration and Invariants

| Source | Key | Value/Role | Evidence |
|---|---|---|---|
| `spark_dendrite.py:15-20` | `_DEFAULT_SPARK_INSTRUCTION` | System prompt: `{"requirement_text": str, "source_blueprint_id": str}` | [E-001] |
| `spark_dendrite.py:34` | `stage_name` | Hardcoded `"spark"` | [E-001] |
| `soma/helpers.py:5-10` | `get_receptor_config()` | Queries `ReceptorConfig` by `name` or `stage` | [E-001] |
| `pipeline/llm_sdk.py:24` | `_STAGE_MAP["spark"]` | Maps to `"spark"` stage in TurnKey SDK | [E-009] |
| `machine-talk/tb-008-spark.md` | Prompt spec | Full SPARK_SPECIFICATION with FR-NNN, NFR-NNN, scout_signal, gap_analysis | [E-006] |
| `machinetalk/engine.py:99` | `GROUP_OF` | `"spark": "stage2"` | [E-004] |
| `machine-talk/tb-008-spark.md:75-77` | Violation penalties | Database schemas or markdown fences break the pipeline | [E-006] |

### Hard Gates

1. **JSON-only output** — Both the default instruction and the MachineTalk spec demand raw JSON. No prose, no markdown fences.
2. **StrategicBlueprintNode prerequisite** — Spark requires a `StrategicBlueprintNode` for the session (line 40 of spark_dendrite.py).
3. **Nexus upstream dependency** — The MachineTalk pipeline enforces: spark cannot run if nexus artifact is missing (line 827 of engine.py).
4. **Falcon upstream dependency** — Falcon cannot run if spark artifact is missing (line 834 of engine.py).

## Dependencies and Cross-Component Connections

### Upstream

| Component | Mechanism | Payload | Verified? |
|---|---|---|---|
| `Soma` (store.py) | `query_by_type("StrategicBlueprintNode")` | Nodes matching session_id | Yes [E-001] |
| `Soma` (store.py) | `get_node(requirements_id)` | Pre-existing RequirementsNode for overwrite | Yes [E-001] |
| `Soma` (store.py) | `create_node("RequirementsNode", ...)` | Requirement data | Yes [E-001] |
| `TurnKeyClient` | `.call(stage, messages)` | System prompt + blueprint text | **NO** — .call() missing [E-010, E-012] |
| `MachineTalk client` | `run_stage("spark", messages)` | Nexus output + plan context | Yes (engine.py path) [E-004] |
| `SomaBridge` | `write_spark(build, gate, model, latency)` | Parsed spec JSON | Yes (engine.py path) [E-005] |

### Downstream

| Component | Mechanism | Payload | Verified? |
|---|---|---|---|
| `Soma` (store.py) | `create_edge("DERIVED_FROM", blueprint.id)` | Lineage link | Yes [E-001] |
| `falcon_dendrite.py` | Reads `RequirementsNode` (via Soma query) | requirement_text | Yes (sibling dependency) |
| `SomaBridge.write_falcon()` | Edge `requirements-{id} --YIELDS--> architecture-{id}` | Contract link | Yes [E-005] |
| `scout_dendrite.py` | Queries `InvariantQueryNode` | Depends on drafter output, not directly on spark | Yes (sibling) |

## Known Gaps and Uncertainties

### G-01: Runtime AttributeError in complete_stage path
- **What is unknown**: `stage_complete.py:35` calls `llm.call(stage, messages)` but `TurnKeyClient` has no `.call()` method — only `.chat()`. A live execution test is required to confirm this always fails or if some code path has patched this.
- **Why it matters**: This breaks the entire legacy dendrite path for spark. `run_pipeline.py` and `run_tb007.py` both pass a `TurnKeyClient` that lacks `.call()`.
- **Evidence to close**: Run `python3 -c "from pipeline.llm_sdk import TurnKeyClient; from pipeline.stage_complete import complete_stage; c = TurnKeyClient(); complete_stage(c, 'spark', 'prompt', 'payload')"` or inspect TurnKeyClient's full MRO for inherited `.call()`.

### G-02: Zero test coverage
- **What is unknown**: No `test_spark_dendrite.py` exists. Spark is the only Stage-2 dendrite without unit tests.
- **Why it matters**: No automated verification of RequirementsNode creation, edge creation, error paths (no blueprint), or config override.
- **Evidence to close**: Create and run a test that instantiates SparkDendrite with a mock Soma + mock LLM, seeds a StrategicBlueprintNode, calls run(), and asserts node creation.

### G-03: Two conflicting output schemas
- **What is unknown**: SparkDendrite expects `{"requirement_text": str, "source_blueprint_id": str}` but the MachineTalk spec (tb-008-spark.md) produces a full SPARK_SPECIFICATION with FR-NNN, NFR-NNN, data_requirements, critical_user_flows, gap_analysis, and scout_signal.
- **Why it matters**: The SomaBridge.write_spark method expects `functional_requirements` (line 211 of soma_bridge.py), which only the MachineTalk spec produces. The legacy SparkDendrite produces `requirement_text` — a single field that the bridge does not read.
- **Evidence to close**: Verify which output schema is actually consumed in production by inspecting the most recent `output/soma.json` RequirementsNode properties.

### G-04: Two different node ID schemes
- **What is unknown**: SparkDendrite creates nodes with id `req-{session_id}` (line 82). SomaBridge.write_spark creates nodes with id `requirements-{session_id}` (line 219). These collide on the same session if both paths execute.
- **Why it matters**: The legacy path's `delete_node(requirements_id)` at line 84 deletes the legacy id but the bridge writes a different id. If both paths run on the same session, both nodes persist.
- **Evidence to close**: Check `output/soma.json` for coexisting `req-*` and `requirements-*` nodes.

### G-05: Unclear production runner
- **What is unknown**: `run_engine.py` explicitly states it "does NOT call stages 2-4" (line 142). But it is unclear which runner is the active production path — `run_pipeline.py`, `run_tb007.py`, or `machinetalk/engine.py`.
- **Why it matters**: Different runners execute different spark code paths with different schemas.
- **Evidence to close**: Check pipeline logs (`202610*.log` files in soma root) for which runner produces output.

### G-06: Third constructor parameter unused
- **What is unknown**: `SparkDendrite.__init__(self, soma, llm_client, rotator)` accepts a `rotator` parameter but never uses it. `run_pipeline.py` passes `None`; `run_tb007.py` passes a `_SimpleRotator`.
- **Why it matters**: Dead code; the parameter suggests historical use that was removed.
- **Evidence to close**: Confirm no historical code used `self._rotator` by checking git history.

## Evidence Log

| ID | host | kind | locator | captured at | proves | confidence |
|---|---|---|---|---|---|---|
| E-001 | flintx | file | spark_dendrite.py (all lines) | 2026-10-22T12:37Z | SparkDendrite class, run() path, RequirementsNode creation, DERIVED_FROM edge, default instruction | C2 |
| E-002 | flintx | file | run_pipeline.py:27,124 | 2026-10-22T12:37Z | InteractiveRunner invokes SparkDendrite with TurnKeyClient and None rotator | C2 |
| E-003 | flintx | file | run_tb007.py:18,74 | 2026-10-22T12:37Z | Standalone runner invokes SparkDendrite with rotator | C2 |
| E-004 | flintx | file | machinetalk/engine.py:99,729,824-830 | 2026-10-22T12:37Z | Engine registers "spark" as stage2, calls _run_build_stage, calls SomaBridge.write_spark | C2 |
| E-005 | flintx | file | machinetalk/soma_bridge.py:14,206-229 | 2026-10-22T12:37Z | SomaBridge.write_spark maps gate.parsed["functional_requirements"] to RequirementsNode | C2 |
| E-006 | flintx | file | machine-talk/tb-008-spark.md (all lines) | 2026-10-22T12:37Z | MachineTalk prompt spec: full SPARK_SPECIFICATION output schema | C2 |
| E-007 | flintx | file | output/soma.json (stat mtime) | 2026-10-22T12:37Z | Soma graph persisted with current data | C2 |
| E-008 | flintx | file | pipeline/stage_complete.py:20-88 | 2026-10-22T12:37Z | complete_stage() orchestrates LLM call, JSON extraction, metrics | C2 |
| E-009 | flintx | file | pipeline/llm_sdk.py:21-30,24 | 2026-10-22T12:37Z | _STAGE_MAP maps "spark" → "spark" | C2 |
| E-010 | flintx | file | pipeline/stage_complete.py:35 | 2026-10-22T12:37Z | Calls llm.call(stage, messages) — expects .call() method | C2 |
| E-011 | flintx | file | machinetalk/client.py:25 | 2026-10-22T12:37Z | client.py maps "spark" → "spark" stage name | C2 |
| E-012 | flintx | command | `python3 -c "..."` (hasattr check) | 2026-10-22T12:37Z | TurnKeyClient has chat but NOT call — confirmed AttributeError risk | C1 |
| E-013 | flintx | file | store.py:75-82 | 2026-10-22T12:37Z | Soma.create_node uses properties["id"] or uuid, auto-persists | C2 |
| E-014 | flintx | file | soma/helpers.py:5-10 | 2026-10-22T12:37Z | get_receptor_config queries ReceptorConfig by name or stage | C2 |
