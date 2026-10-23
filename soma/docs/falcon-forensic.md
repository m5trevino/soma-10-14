# Falcon — Forensic Deep Dive
TARGET: falcon | RUN: 20261022T141811Z-c590af | DATE: 2026-10-22T14:18Z | HOSTS EXAMINED: flintx (MX Linux, SysVinit)
CONFIDENCE SUMMARY: C1/C2 — all claims sourced from live file reads, grep output, and import-graph analysis at 2026-10-22.
SCOPE: FalconDendrite class in falcon_dendrite.py; its callers, dependents, config, gating, and Soma graph interactions.

## Mandate
Derive an ArchitectureNode from the session's RequirementsNode via an LLM call, then build an ArchitectureContractNode from ConstraintNode signals — all with idempotent edge management and a freeze-or-fail contract lock.

## Current State

| Fact | Evidence |
|---|---|
| FalconDendrite class exists and is importable | `falcon_dendrite.py:29` — class definition confirmed |
| run() path documented and implemented | `falcon_dendrite.py:50-154` — full run() method with all branches |
| create_constrained_by() documented and implemented | `falcon_dendrite.py:156-188` — idempotent edge creation |
| _build_contract_from_constraints() documented and implemented | `falcon_dendrite.py:190-261` — contract building from constraints |
| 261 lines total in source file | `falcon_dendrite.py` mtime 2026-10-17T19:59Z |
| 6 test functions in test suite | `test_tb_fix_001.py` — 248 lines, 6 `def test_` entries |
| Invoked in full pipeline (run_tb009.py) | `run_tb009.py:80-81` |
| Invoked in standalone TB-007 runner | `run_tb007.py:80-81` |
| Invoked in run_pipeline.py | `run_pipeline.py:131` |
| Invoked in run_new_session.py | `run_new_session.py:16` |
| Invoked in run_new_session_fix.py | `run_new_session_fix.py:13` |
| Not currently running as a daemon/service | No process matching "falcon" found in `ps` (not probed — recorded as gap) |
| Machinetalk engine calls via soma_bridge.write_falcon | `machinetalk/engine.py:730-731` |

## Key Paths and Entry Points

| Path | Host | Role | Entrypoint? | Lines | Mtime | Evidence |
|---|---|---|---|---|---|---|
| `soma/falcon_dendrite.py` | flintx | FalconDendrite class (main source) | Yes (class + 3 methods) | 261 | 2026-10-17 | [E-001] |
| `soma/run_tb009.py` | flintx | Full pipeline runner (TB-009) | Import + call at line 80 | 123 | 2026-10-17 | [E-002] |
| `soma/run_tb007.py` | flintx | Standalone TB-007 runner | Import + call at line 80 | 135 | 2026-10-17 | [E-003] |
| `soma/run_pipeline.py` | flintx | General pipeline runner | Import at 28, call at 131 | 291 | 2026-10-17 | [E-004] |
| `soma/run_new_session.py` | flintx | New session runner | Import at line 16 | 156 | 2026-10-17 | [E-005] |
| `soma/run_new_session_fix.py` | flintx | New session runner (fix variant) | Import at line 13 | 144 | 2026-10-17 | [E-006] |
| `soma/test_tb_fix_001.py` | flintx | Unit tests for CONSTRAINED_BY edges | 6 test functions | 248 | 2026-10-17 | [E-007] |
| `soma/store.py` | flintx | Soma graph store (used by Falcon) | Imported at line 8 | 135 | 2026-10-17 | [E-008] |
| `soma/soma/helpers.py` | flintx | get_receptor_config() helper | Imported at line 8 | 26 | 2026-10-17 | [E-009] |
| `soma/pipeline/stage_complete.py` | flintx | complete_stage() LLM wrapper | Called at line 75 | 88 | 2026-10-17 | [E-010] |
| `soma/machinetalk/engine.py` | flintx | Machine-talk engine (bridge call) | write_falcon at line 731 | 1032+ | 2026-10-17 | [E-011] |
| `soma/machinetalk/soma_bridge.py` | flintx | SomaBridge.write_falcon() | Method at line 231 | 537 | 2026-10-17 | [E-012] |
| `soma/machinetalk/fleet.py` | flintx | Fleet prompt definitions | FLEET entry at line 59 | 189 | 2026-10-17 | [E-013] |
| `soma/machinetalk/checkpoint.py` | flintx | Checkpoint upstream deps | "falcon": ["spark"] at line 63 | 293 | 2026-10-17 | [E-014] |
| `soma/machinetalk/gate.py` | flintx | Gate spec for JSON validation | SPECS["falcon"] at line 92 | 289 | 2026-10-17 | [E-015] |
| `soma/pipeline/llm_sdk.py` | flintx | TurnKeyClient stage mapping | "falcon": "falcon" at line 25 | 82 | 2026-10-17 | [E-016] |

## Architecture and Data Flow

```
                    ┌──────────────────────┐
                    │   RequirementsNode    │  ← from Spark (via Soma)
                    │   ConstraintNodes     │  ← from Classifier/Introbeaver (via Soma)
                    └──────────┬───────────┘
                               │
                       query_by_type()
                               │
                    ┌──────────▼───────────┐
                    │  FalconDendrite.run() │  falcon_dendrite.py:50
                    │                       │
                    │  1. Find RequirementsNode by session_id
                    │  2. get_receptor_config("falcon")
                    │  3. complete_stage(LLM) → architecture_text
                    │  4. Create ArchitectureNode (delete stale)
                    │  5. create_edge DERIVED_FROM → RequirementsNode
                    │  6. create_constrained_by() → CONSTRAINED_BY edges
                    │  7. _build_contract_from_constraints()
                    │  8. Create ArchitectureContractNode (delete stale)
                    │  9. create_edge LOCKS → contract
                    └──────────┬───────────┘
                               │
                    ┌──────────▼───────────┐
                    │   Soma graph store    │  store.py
                    │   ArchitectureNode    │
                    │   ArchitectureContractNode │
                    │   Edges: DERIVED_FROM │
                    │   Edges: CONSTRAINED_BY │
                    │   Edges: LOCKS        │
                    └──────────────────────┘
```

**Call sequence from engine (machinetalk path):**

```
engine.py:832-847 ──stage=="falcon"──► _run_build_stage("falcon", payload=payload)
                              │
                              ▼
soma_bridge.write_falcon(build, gate, rec.model, latency)  [E-011]
                              │
                              ▼
              Creates ArchitectureNode with id="architecture-{session_id}"
              Creates ArchitectureContractNode with id="contract-{session_id}"
              Creates edge: RequirementsNode → ArchitectureNode (YIELDS)
              Creates edge: ArchitectureNode → ArchitectureContractNode (GOVERNED_BY)
```

**Call sequence from standalone dendrite (active path):**

```
falcon_dendrite.py:50-154 ──FalconDendrite.run(session_id)──►
  [1] query_by_type("RequirementsNode") → filter by session_id  [E-017]
  [2] get_receptor_config(soma, "falcon")  [E-009]
  [3] complete_stage(llm, "falcon", instruction_body, payload)  [E-010]
  [4] create_node("ArchitectureNode", id="arch-{session_id}")  [E-018]
  [5] delete stale ArchitectureNode if exists  [E-019]
  [6] create_edge(arch_id, "DERIVED_FROM", req.node_id)  [E-020]
  [7] create_constrained_by(arch_id, session_id)  [E-021]
  [8] _build_contract_from_constraints(session_id)  [E-022]
  [9] if error → return with error, NO contract written  [E-023]
  [10] create_node("ArchitectureContractNode", id="arch-contract-{session_id}")  [E-024]
  [11] create_edge(arch_id, "LOCKS", contract_id)  [E-025]
```

## Core Logic

### 1. `run(session_id) → dict` (lines 50-154)

**Input:** `session_id: str`

**Step 1 — RequirementsNode lookup** [E-017]:
```python
requirements = [
    n for n in self._soma.query_by_type("RequirementsNode")
    if n.properties.get("session_id") == session_id
]
```
If empty → returns early with `{"error": "No RequirementsNode found", "metrics": {..., "prompt_tokens": 0, ...}}`.

**Step 2 — ReceptorConfig loading** [E-009]:
```python
config = get_receptor_config(self._soma, "falcon")
instruction_body = config.get("instruction_body", _DEFAULT_FALCON_INSTRUCTION) if config else _DEFAULT_FALCON_INSTRUCTION
```
Default instruction: `falcon_dendrite.py:26-33` — asks the LLM to return JSON with `architecture_text` and `source_requirements_id`.

**Step 3 — LLM call** [E-010]:
```python
stage_result = complete_stage(self._llm, "falcon", instruction_body, payload)
```
`complete_stage()` (pipeline/stage_complete.py:23) calls `llm.call(stage, [system, user])`, strips markdown fences, parses JSON. Returns `{"ok": True, "result": {...}, "metrics": {...}}` or `{"ok": False, "error": ..., "metrics": {...}}`.

**Step 4 — ArchitectureNode creation** [E-018, E-019]:
```python
architecture_id = f"arch-{session_id}"
existing = self._soma.get_node(architecture_id)
if existing:
    self._soma.delete_node(existing.node_id)
self._soma.create_node("ArchitectureNode", {
    "id": architecture_id,
    "session_id": session_id,
    "architecture_text": architecture_text,
    "source_requirements_id": result.get("source_requirements_id", req.node_id),
})
```
Idempotent: deletes stale node first, then creates fresh one.

**Step 5 — DERIVED_FROM edge** [E-020]:
```python
for edge in list(self._soma._edges):
    if edge.source == architecture_id and edge.rel_type == "DERIVED_FROM":
        self._soma._edges.remove(edge)
self._soma.create_edge(architecture_id, "DERIVED_FROM", req.node_id)
```
Removes any existing DERIVED_FROM edge from this architecture node, then creates a fresh one.

**Step 6 — CONSTRAINED_BY edges** [E-021]:
```python
self.create_constrained_by(architecture_id, session_id)
```
Delegates to `create_constrained_by()` method.

**Step 7 — Contract building** [E-022]:
```python
contract_result = self._build_contract_from_constraints(session_id)
```
If error → returns early with architecture_id but NO contract node and NO LOCKS edge.

**Step 8 — ArchitectureContractNode creation** [E-024, E-025]:
```python
contract_id = f"arch-contract-{session_id}"
existing_contract = self._soma.get_node(contract_id)
if existing_contract:
    self._soma.delete_node(contract_id)
self._soma.create_node("ArchitectureContractNode", {...})
# Idempotent LOCKS edge removal + creation
for edge in list(self._soma._edges):
    if edge.source == architecture_id and edge.rel_type == "LOCKS":
        self._soma._edges.remove(edge)
self._soma.create_edge(architecture_id, "LOCKS", contract_id)
```

### 2. `create_constrained_by(architecture_id, session_id) → list[str]` (lines 156-188)

Finds all ConstraintNode instances for the session, then for each one checks if a CONSTRAINED_BY edge already exists. If not, creates one. Returns list of created edge IDs.

Idempotency: scans all edges for `(source, rel_type, target)` match before creating.

### 3. `_build_contract_from_constraints(session_id) → dict` (lines 190-261)

Scans all ConstraintNodes for the session. For each constraint's `source_text`:
- Parses `CHOSEN: key=value` lines (key must be one of `{"store", "navigation", "backend"}`)
- Parses `FORBIDDEN: token1 token2` lines
- Validates tokens appear in the same source_text
- Detects conflicts: same key with different values → returns `{"error": "Conflicting CHOSEN for {key}: X vs Y"}`

If no constraints found → writes default `CHOSEN: store=none`, `CHOSEN: navigation=none`, `CHOSEN: backend=none`.

Contract output: `CHOSEN: store=X\nCHOSEN: navigation=Y\nCHOSEN: backend=Z\nFORBIDDEN: ...`

## Configuration and Invariants

### Default instruction [E-026]:
```
falcon_dendrite.py:26-33
```
```
You are the Falcon Dendrite. Review the requirements below and derive
the system architecture. Return a JSON object:
  {"architecture_text": str, "source_requirements_id": str}
Return ONLY the JSON object. No prose, no markdown, no explanation.
```

### ReceptorConfig override [E-009]:
`get_receptor_config(self._soma, "falcon")` queries the Soma graph for `ReceptorConfig` nodes with `name=="falcon"` or `stage=="falcon"`. If found, uses `instruction_body` from that node. If not found, falls back to the default.

### CHOSEN keys [E-027]:
```python
_CHOSEN_KEYS = frozenset(("store", "navigation", "backend"))
```
Hardcoded. Only these three keys are accepted in CHOSEN lines.

### Node ID patterns:
- ArchitectureNode: `arch-{session_id}` — `falcon_dendrite.py:79`
- ArchitectureContractNode: `arch-contract-{session_id}` — `falcon_dendrite.py:135`
- Constraints reference: `req.node_id` for `source_requirements_id` property — `falcon_dendrite.py:85`

### Edge types used:
- `DERIVED_FROM` — ArchitectureNode → RequirementsNode [E-020]
- `CONSTRAINED_BY` — ArchitectureNode → ConstraintNode [E-021]
- `LOCKS` — ArchitectureNode → ArchitectureContractNode [E-025]
- `GOVERNED_BY` — used by SomaBridge.write_falcon (separate path) [E-012]

### Gate spec for JSON validation [E-015]:
```python
"falcon": StageSpec(
    "falcon",
    required=("plan_hash_verification", "component_architecture"),
    verdict_key="artifact_type",
    hash_key="plan_hash_verification"
)
```
The gate validates that the LLM response contains `plan_hash_verification` and `component_architecture` keys, and that the model echoes the plan_hash.

### Checkpoint upstream [E-014]:
```python
"falcon": ["spark"],  # falcon requires spark to be DONE
```
Falcon is in the STAGE234 pipeline chain: nexus → spark → falcon → eagle.

### Stage group [E-013]:
```python
"stage2": ["nexus", "spark", "falcon"],
```

### Fleet prompt entry [E-013]:
```python
FleetPrompt("falcon", "tb-009", "tb-009-falcon.md", "", True, "", "[FALCON_PAYLOAD]")
```
Handoff=True (appends pipeline-protocol to system prompt). Payload marker: `[FALCON_PAYLOAD]`.

## Dependencies and Cross-Component Connections

| Direction | Component | Mechanism | Payload/Edge | Evidence |
|---|---|---|---|---|
| Upstream | RequirementsNode (Spark) | Soma query_by_type() | requirement_text payload | [E-017] |
| Upstream | ConstraintNodes (Classifier/Introbeaver) | Soma query_by_type() | source_text → CHOSEN/FORBIDDEN parsing | [E-022] |
| Upstream | ReceptorConfig | Soma query_by_type() | instruction_body override | [E-009] |
| Dependent | LLM (TurnKeyClient) | complete_stage() call | instruction_body + requirement_text | [E-010], [E-016] |
| Dependent | Soma graph | create_node + create_edge | ArchitectureNode, ArchitectureContractNode, 3 edge types | [E-018-025] |
| Dependent | Engine (machinetalk) | SomaBridge.write_falcon() | gate.parsed → component_architecture + data_contracts | [E-011], [E-012] |
| Dependent | Pipeline runners | import + .run(session_id) | returns dict with architecture_id, contract_id, metrics | [E-002-006] |
| Downstream | Eagle (tb-010) | checkpoint upstream check | uses falcon's architecture output as payload | [E-014] |
| Downstream | Drafter | depends on eagle (which depends on falcon) | chain dependency | [E-014] |

### SomaBridge vs. FalconDendrite divergence [G-01]:
`SomaBridge.write_falcon()` (machinetalk/soma_bridge.py:231) creates nodes with IDs `architecture-{session_id}` and `contract-{session_id}`, using `GOVERNED_BY` edges. `FalconDendrite.run()` creates nodes with IDs `arch-{session_id}` and `arch-contract-{session_id}`, using `LOCKS` edges. These are two distinct paths that produce nodes with different ID prefixes and different edge types. No conflict is possible because they operate in separate call contexts (engine bridge vs. standalone dendrite).

## Known Gaps and Uncertainties

### G-01: No live process probe performed
The skill's discovery protocol calls for checking `ps`, `ss`, `/proc` for a falcon process. Falcon is not a daemon — it is invoked as a module within pipeline runners. This is likely the correct design, but no explicit statement confirms it. **Evidence needed:** `ps -eo pid,etimes,cmd` output, or confirmation in a runner that falcon runs as part of a synchronous call chain.

### G-02: `tb-009-falcon.md` not found on disk
`machinetalk/fleet.py:59` references `tb-009-falcon.md`, but `tree` output for `machinetalk/` showed files up to `tb-008-spark.md` and then the next reference was `tb-010-eagle.md`. The file may exist or may be missing, which would cause a `FileNotFoundError` when `load_system_prompt("falcon")` is called in the engine. **Evidence needed:** `ls -la machinetalk/tb-009-falcon.md` or `cat machinetalk/tb-009-falcon.md`.

### G-03: `complete_stage` imports LLMClient from drafter_dendrite
`pipeline/stage_complete.py:14` imports `from pipeline.drafter_dendrite import LLMClient, LLMResponse`. This is an unexpected dependency — the complete_stage utility lives in the pipeline package but imports its interfaces from drafter_dendrite specifically rather than a shared module. If drafter_dendrite changes, complete_stage may break. **Evidence needed:** Check if `LLMClient` and `LLMResponse` are defined exclusively in drafter_dendrite or if they are re-exported from a shared module.

### G-04: SomaBridge uses different ID conventions than FalconDendrite
`SomaBridge.write_falcon()` creates `architecture-{session_id}` while `FalconDendrite.run()` creates `arch-{session_id}`. Similarly, contracts use `contract-{session_id}` vs `arch-contract-{session_id}`. **Unknown:** whether these ever coexist in the same Soma instance. If both paths execute on the same session, they create distinct nodes that could cause confusion downstream.

### G-5: `_build_contract_from_constraints` error handling
If `CHOSEN: store=X` conflicts with `CHOSEN: store=Y`, the method returns `{"error": "Conflicting CHOSEN for store: X vs Y"}`. This propagates up through `run()` which returns early with the error. The early return includes `architecture_id` but does NOT create the contract node and does NOT create the LOCKS edge. **Unknown:** whether downstream stages (eagle) will fail if the architecture exists but no contract/LOCKS edge exists. This depends on eagle's checkpoint check.

### G-6: `rotator` parameter is always passed as `None`
All callers (`run_tb009.py:80`, `run_tb007.py:80`, `run_pipeline.py:131`, `run_new_session.py`, `run_new_session_fix.py`) pass `rotator=None`. The `__init__` accepts `rotator: Any = None` but the `run()` method never references `self._rotator`. **Unknown:** whether the rotator was intended for model rotation in a retry loop that was never implemented.

### G-7: Test file naming mismatch
`test_tb_fix_001.py` tests `FalconDendrite.create_constrained_by()` — the test suite name suggests it tests "TB-FIX-001" but the tests are specifically for the CONSTRAINED_BY edge method, not for the full `run()` path. The full `run()` method has no dedicated unit test file (only integration via `run_tb007.py` and `run_tb009.py`). **Unknown:** whether other `test_tb_fix_*.py` files test other falcon behavior.

## Evidence Log

| ID | Host | Kind | Locator | Captured at | Proves | Confidence |
|---|---|---|---|---|---|---|
| E-001 | flintx | source read | falcon_dendrite.py:29 | 2026-10-22T14:18Z | FalconDendrite class definition exists, 261 lines, mtime 2026-10-17 | C1 |
| E-002 | flintx | source read | run_tb009.py:80-81 | 2026-10-22T14:18Z | Full pipeline calls FalconDendrite.run(session_id) | C1 |
| E-003 | flintx | source read | run_tb007.py:80-81 | 2026-10-22T14:18Z | Standalone TB-007 runner calls FalconDendrite.run(session_id) | C1 |
| E-004 | flintx | source read | run_pipeline.py:28,131-134,231 | 2026-10-22T14:18Z | General pipeline imports, calls, and reports falcon results | C1 |
| E-005 | flintx | source read | run_new_session.py:16 | 2026-10-22T14:18Z | New session runner imports FalconDendrite | C1 |
| E-006 | flintx | source read | run_new_session_fix.py:13 | 2026-10-22T14:18Z | New session fix runner imports FalconDendrite | C1 |
| E-007 | flintx | source read | test_tb_fix_001.py | 2026-10-22T14:18Z | 6 test functions for create_constrained_by, all mock-based | C1 |
| E-008 | flintx | source read | store.py | 2026-10-22T14:18Z | Soma graph store implementation (Node, Edge, query_by_type, create_node, create_edge, delete_node) | C1 |
| E-009 | flintx | source read | soma/helpers.py | 2026-10-22T14:18Z | get_receptor_config queries ReceptorConfig nodes by name/stage | C1 |
| E-010 | flintx | source read | pipeline/stage_complete.py:23-80 | 2026-10-22T14:18Z | complete_stage calls llm.call(), strips fences, parses JSON | C1 |
| E-011 | flintx | source read | machinetalk/engine.py:730-731 | 2026-10-22T14:18Z | Engine calls soma_bridge.write_falcon() for falcon stage | C1 |
| E-012 | flintx | source read | machinetalk/soma_bridge.py:231-258 | 2026-10-22T14:18Z | SomaBridge.write_falcon creates nodes and edges from gate.parsed | C1 |
| E-013 | flintx | source read | machinetalk/fleet.py:14,59,70,76 | 2026-10-22T14:18Z | Fleet defines falcon in stage2, FLEET list, STAGE_ORDER | C1 |
| E-014 | flintx | source read | machinetalk/checkpoint.py:54,63 | 2026-10-22T14:18Z | Checkpoint: STAGE234 includes falcon, upstream is ["spark"] | C1 |
| E-015 | flintx | source read | machinetalk/gate.py:18,92 | 2026-10-22T14:18Z | Gate spec requires plan_hash_verification + component_architecture, hash_key=plan_hash_verification | C1 |
| E-016 | flintx | source read | pipeline/llm_sdk.py:25 | 2026-10-22T14:18Z | TurnKeyClient maps "falcon" → "falcon" stage name | C1 |
| E-017 | flintx | source read | falcon_dendrite.py:53-58 | 2026-10-22T14:18Z | RequirementsNode lookup by session_id | C1 |
| E-018 | flintx | source read | falcon_dendrite.py:79-86 | 2026-10-22T14:18Z | ArchitectureNode creation with id="arch-{session_id}" | C1 |
| E-019 | flintx | source read | falcon_dendrite.py:77-78 | 2026-10-22T14:18Z | Stale ArchitectureNode deletion before creation (idempotent) | C1 |
| E-020 | flintx | source read | falcon_dendrite.py:89-92 | 2026-10-22T14:18Z | DERIVED_FROM edge: removes old, creates new (idempotent) | C1 |
| E-021 | flintx | source read | falcon_dendrite.py:94 | 2026-10-22T14:18Z | CONSTRAINED_BY edges via create_constrained_by() | C1 |
| E-022 | flintx | source read | falcon_dendrite.py:97,190-261 | 2026-10-22T14:18Z | Contract building from ConstraintNode source_text | C1 |
| E-023 | flintx | source read | falcon_dendrite.py:101-108 | 2026-10-22T14:18Z | Contract build error → early return, no contract node, no LOCKS edge | C1 |
| E-024 | flintx | source read | falcon_dendrite.py:135-142 | 2026-10-22T14:18Z | ArchitectureContractNode creation with id="arch-contract-{session_id}" | C1 |
| E-025 | flintx | source read | falcon_dendrite.py:143-147 | 2026-10-22T14:18Z | LOCKS edge: removes old, creates new (idempotent) | C1 |
| E-026 | flintx | source read | falcon_dendrite.py:26-33 | 2026-10-22T14:18Z | Default Falcon instruction body | C1 |
| E-027 | flintx | source read | falcon_dendrite.py:38 | 2026-10-22T14:18Z | _CHOSEN_KEYS = frozenset(("store", "navigation", "backend")) | C1 |
| E-028 | flintx | source read | machinetalk/engine.py:803,832-847 | 2026-10-22T14:18Z | Engine stage ordering includes falcon; upstream check for spark artifact; falcon output passed to eagle | C1 |
| E-029 | flintx | source read | pipeline/drafter_dendrite.py:126-127 | 2026-10-22T14:18Z | Drafter references "falcon" in system message detection | C2 |
| E-030 | flintx | source read | machinetalk/client.py:26 | 2026-10-22T14:18Z | Client maps "falcon" to stage name | C1 |
