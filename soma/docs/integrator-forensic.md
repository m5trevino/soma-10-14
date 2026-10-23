# Integrator — Forensic Deep Dive

TARGET: integrator | RUN: 20261022T123201Z-e06851 | DATE: 2026-10-22T12:32Z | HOSTS EXAMINED: flintx (local)
CONFIDENCE SUMMARY: C1=14, C2=3, C3=2 | SCOPE: IntegratorDendrite module and its import graph
SCOPE: TB-TK-REPLACE-003 / PLAN-BEAVER stage — synthesises sequenced TaskNodes from classified signals. Duplicate module conflict between root and pipeline copies is resolved via import graph analysis.

## Mandate

Integrates classified signal nodes (produced by ClassifierDendrite) into TaskNode, RiskNode, DecisionNode, and StackNode records in the Soma graph with physical edges (REQUIRES_ACTION, INTRODUCES_RISK, ADDRESSES), producing idempotent output.

## Current State

Two copies of `integrator_dendrite.py` exist on disk, both live in distinct call paths:

| Copy | Path | Lines | Mtime | Live In |
|---|---|---|---|---|
| Root | `integrator_dendrite.py` | 574 | 2026-10-19T18:02 | `run_tb004.py`, `walk.py` |
| Pipeline | `pipeline/integrator_dendrite.py` | 578 | 2026-10-19T18:04 | `test_integrator_dendrite.py` |

They differ by approximately four logical lines: the root uses a `_console_handler` variable name and omits a `user_text` fetch; the pipeline uses `_ch`, includes the `user_text` fetch at line 259, and has an `import re` statement at line 269 that appears after the method body. These differences are cosmetic or dead-code artifacts — the `run()` method, node writers, validation logic, and edge linkage are functionally identical.

No standalone process or network port is associated with the integrator. It is imported as a module and invoked three ways:

1. **`run_tb004.py`** (direct runner) — imports root, runs `IntegratorDendrite.run(cs_id)` on an in-memory `Soma` after `ClassifierDendrite` populates signal edges [E-004]
2. **`walk.py`** (pipeline runner) — imports root, includes `("integrator", IntegratorDendrite)` in the `STAGE1` list [E-005]
3. **`machinetalk/engine.py`** (engine stage) — runs "planbeaver" as an LLM stage on raw chat sets, producing a different output contract (files + data contracts) via the TB-005 prompt [E-020]

The workspaces directory (`soma/workspaces`) does not exist on disk [E-023].

## Key Paths and Entry Points

| Path | Host | Role | Entrypoint? | Lines | Mtime | Evidence |
|---|---|---|---|---|---|---|
| `integrator_dendrite.py` | flintx | TB-TK-REPLACE-003 core | Yes | 574 | 2026-10-19T18:02 | [E-001] |
| `pipeline/integrator_dendrite.py` | flintx | TB-TK-REPLACE-003 core (duplicate) | Yes | 578 | 2026-10-19T18:04 | [E-002] |
| `test_integrator_dendrite.py` | flintx | Unit tests (558 lines, ~30 test methods) | No | 558 | 2026-10-19T00:43 | [E-003] |
| `run_tb004.py` | flintx | TB-004 Stage 1 runner | Import | 190 | — | [E-004] |
| `walk.py` | flintx | Pipeline orchestrator | Import | — | — | [E-005] |
| `machinetalk/soma_bridge.py` | flintx | Artifact-to-Soma bridge | Writes TaskNode | — | — | [E-013] |
| `machinetalk/engine.py` | flintx | "planbeaver" stage runner | Invokes LLM | — | — | [E-020] |
| `pipeline/drafter_dendrite.py` | flintx | LLMClient/LLMResponse/ MockLLMClient source | Import target | — | — | [E-015] |

## Architecture and Data Flow

### Context diagram

```text
                    ┌─────────────────────┐
                    │  ClassifierDendrite  │
                    │  (introbeaver/ALPHA) │
                    └──────────┬──────────┘
                               │ EXTRACTED_FROM edges on Soma
                               ▼
┌──────────────┐    ┌──────────────────────┐    ┌──────────────────────┐
│   ChatSet    │───▶│  IntegratorDendrite   │───▶│   Soma graph        │
│  (session)   │    │  (planbeaver/CHARLIE) │    │  TaskNode           │
└──────────────┘    └──────────────────────┘    │  RiskNode           │
                                                │  DecisionNode       │
                                                │  StackNode          │
                                                │  SessionNode        │
                                                └──────────────────────┘
                               │                          │
                               │ LLMClient.chat()         │ edges
                               │ (pipeline.drafter)       │
                               ▼                          ▼
                        ┌──────────────┐       ┌──────────────────┐
                        │ TurnKey      │       │ SomaBridge       │
                        │ / MockLLM    │       │ (writes artifact │
                        │              │       │  to JSON)        │
                        └──────────────┘       └──────────────────┘
```

### run() execution flow

```text
IntegratorDendrite.run(chat_set_id)
  │
  ├─ get_node(chat_set_id) → ChatSet? → error if missing
  │
  ├─ _collect_signal_ids(chat_set_id)
  │   └─ reads EXTRACTED_FROM edges, filters to 7 signal types
  │   └─ empty → _empty_result() → return
  │
  ├─ _build_signal_payload(signal_ids)
  │   └─ json.dumps([{id, type, source_text, confidence, rationale}])
  │
  ├─ _call_llm(chat_set_id, signal_payload)
  │   ├─ LLMClient.chat([{system, user}])
  │   ├─ strip markdown fences (re match)
  │   ├─ json.loads(content)
  │   └─ return {ok, result, metrics}
  │
  ├─ _write_task_nodes(tasks) → (all_ids, created_ids)
  │   └─ _validate_task() → _find_existing_task() → create_node("TaskNode")
  │
  ├─ _write_risk_nodes(risks) → (all_ids, created_ids)
  │   └─ _validate_risk() → _find_existing_risk() → create_node("RiskNode")
  │
  ├─ _write_decision_nodes(decisions) → (all_ids, created_ids)
  │   └─ _validate_decision() → _find_existing_decision() → create_node("DecisionNode")
  │
  ├─ _write_stack_nodes(stack) → (all_ids, created_ids)
  │   └─ _validate_stack_item() → _find_existing_stack() → create_node("StackNode")
  │
  └─ _create_linkage_edges(created_task_ids, created_risk_ids, signal_ids, ...)
      ├─ _ensure_session_node(session_id)
      ├─ REQUIRES_ACTION: SessionNode → TaskNode
      ├─ INTRODUCES_RISK: SessionNode → RiskNode
      └─ ADDRESSES: TaskNode → SignalNode
```

## Core Logic

### The `run()` method (`integrator_dendrite.py:130-197`) [E-016]

The public API accepts a `chat_set_id` string and returns a dict with four node-id lists and a metrics object. The execution path is:

1. **ChatSet validation** (line 140-142): Retrieves the node and confirms `node_type == "ChatSet"`. Returns `{"error": ...}` if not found or wrong type.

2. **Signal collection** (line 148): Calls `_collect_signal_ids()` [E-011], which reads all `EXTRACTED_FROM` edges from the ChatSet and filters targets to the seven signal node types: `IntentNode`, `DirectiveNode`, `ConstraintNode`, `QuestionNode`, `PreferenceNode`, `CorrectionNode`, `NoiseNode`.

3. **Signal payload assembly** (line 154): Calls `_build_signal_payload()` which serialises each signal node's `id`, `type`, `source_text`, `confidence`, and `rationale` into a JSON array.

4. **LLM synthesis call** (line 157): Calls `_call_llm()` which invokes `LLMClient.chat()` with a system prompt (the `_INTEGRATOR_INSTRUCTION` constant) and the signal payload as user content. Strips markdown code fences via regex, parses JSON. Returns `{ok, result, metrics}` or an error.

5. **Node writing** (lines 161-168): For each of the four output types (`tasks`, `risks`, `decisions`, `stack`), calls the corresponding `_write_*_nodes()` method. Each writer validates the input dict, checks idempotency via `_find_existing_*()`, creates the node, and returns `(all_ids, created_ids)` where `created_ids` contains only newly written nodes.

6. **Edge linkage** (line 170): Calls `_create_linkage_edges()` [E-019], which ensures a `SessionNode` exists via `_ensure_session_node()` and creates:
   - `REQUIRES_ACTION` edges from SessionNode to each newly created TaskNode
   - `INTRODUCES_RISK` edges from SessionNode to each newly created RiskNode
   - `ADDRESSES` edges from each newly created TaskNode to its source signal nodes

7. **Metrics and logging** (lines 186-190): Computes latency via `time.monotonic()`, calls `_log_metrics()` [E-017] which formats token usage and latency to console.

### Idempotency helpers (`integrator_dendrite.py:455-481`) [E-012]

Each `_find_existing_*()` method performs a linear scan:

```python
def _find_existing_task(self, task_text: str) -> Optional[Any]:
    existing = self._soma.query_by_type("TaskNode")
    for node in existing:
        if node.properties.get("task_text") == task_text:
            return node
    return None
```

All four helpers (`_find_existing_task`, `_find_existing_risk`, `_find_existing_decision`, `_find_existing_stack`) follow the same pattern — query all nodes of a type, compare the text field. No database index is used. This is a scalability concern for large graphs but functionally correct for the in-memory Soma instances used in testing and current run sizes.

### Node writers (`integrator_dendrite.py:300-420`) [E-017]

Each writer produces nodes with deterministic IDs: `task-{chat_set_id}-{seq}`, `risk-{chat_set_id}-{idx}`, `decision-{chat_set_id}-{idx}`, `stack-{chat_set_id}-{idx}`. Properties include:

- **TaskNode**: `task_text`, `sequence_number`, `priority`, `source_signal_ids` (JSON array), `session_id`, `chat_set_id`
- **RiskNode**: `risk_text`, `severity`, `source_signal_ids`, `session_id`, `chat_set_id`
- **DecisionNode**: `decision_text`, `rationale`, `session_id`, `chat_set_id`
- **StackNode**: `stack_text`, `role`, `dependencies` (JSON array), `session_id`, `chat_set_id`

### Edge linkage (`integrator_dendrite.py:537-556`)

Only edges for **newly created** nodes are written — existing nodes (from idempotent re-runs) do not generate duplicate edges. The edge semantics are:

- `SessionNode → REQUIRES_ACTION → TaskNode` [E-019]
- `SessionNode → INTRODUCES_RISK → RiskNode` [E-019]
- `TaskNode → ADDRESSES → SignalNode` (one per source signal) [E-019]

### Session node placeholder (`integrator_dendrite.py:523-535`)

`_ensure_session_node()` returns an existing `SessionNode` if one with id `session-{session_id}` exists; otherwise it creates a minimal `SessionNode` with only `id` and `session_id` properties. No reference to the original ChatSet is stored on the SessionNode.

### LLM call (`integrator_dendrite.py:218-252`)

The `_call_llm()` method:

1. Invokes `self._llm.chat([{"role": "system", "content": self._instruction}, {"role": "user", "content": signal_payload}])`
2. Strips markdown fences via `re.match(r"^```(?:json)?\s*(.*?)```?\s*$", content, re.DOTALL)`
3. Parses JSON with `json.loads()`
4. Returns `{ok: True, result: parsed_dict, metrics: {...}}` or `{ok: False, error: "...", metrics: {...}}`

The metrics object captures `model_id`, `prompt_tokens`, `completion_tokens`, `total_tokens` from the LLMResponse, plus `latency_ms` computed in the caller.

## Configuration and Invariants

| Key | Value | Source |
|---|---|---|
| `_INTEGRATOR_INSTRUCTION` | System prompt asking LLM to produce `tasks`, `risks`, `decisions`, `stack` JSON [E-006] | `integrator_dendrite.py:55-64` |
| `_VALID_PRIORITIES` | `{"HIGH", "MEDIUM", "LOW"}` | `integrator_dendrite.py:51` [E-007] |
| `_VALID_SEVERITIES` | `{"HIGH", "MEDIUM", "LOW"}` | `integrator_dendrite.py:52` [E-008] |
| `_OUTPUT_NODE_TYPES` | `{"TaskNode", "RiskNode", "DecisionNode", "StackNode"}` | `integrator_dendrite.py:34-39` [E-009] |
| `from pipeline.drafter_dendrite import LLMClient, LLMResponse, MockLLMClient` | LLM abstraction interface | `integrator_dendrite.py:22` [E-015] |
| Hard gate: no disk access | Documented in module docstring [E-010] | Not enforced in code |
| Hard gate: signal-only input | `_collect_signal_ids()` reads only `EXTRACTED_FROM` edges [E-011] | Enforced in code |
| Hard gate: idempotent output | `_find_existing_*()` pre-check before node creation [E-012] | Enforced in code |

The hard gates in the docstring are **documented but not programmatically enforced** — the "must NOT access physical files" gate is a development discipline, not a runtime check.

## Dependencies and Cross-Component Connections

### Upstream
- **ClassifierDendrite (introbeaver)**: Produces signal nodes (`IntentNode` through `NoiseNode`) linked to ChatSets via `EXTRACTED_FROM` edges. The integrator consumes these edges exclusively; it never reads raw chat set content directly. [E-011]
- **ChatSet nodes**: The entry point. Each ChatSet has `session_id`, `set_number`, `user_text`, `assistant_text`. The integrator reads `user_text` only if it is on the pipeline copy (line 259), where it is fetched but unused (dead code).

### Downstream
- **Soma graph**: The integrator writes TaskNode, RiskNode, DecisionNode, StackNode, SessionNode records and REQUIRES_ACTION, INTRODUCES_RISK, ADDRESSES edges. [E-019]
- **SomaBridge.write_integrator()**: The machinetalk engine's bridge module maps planbeaver artifacts (files, data_contracts) to Soma TaskNode records. This is a parallel write path that does not use the IntegratorDendrite module — it reads the JSON artifact and calls `self._soma.create_node("TaskNode", {...})` directly. [E-013]
- **machinetalk.engine._merged_plan()**: Loads all `planbeaver` artifacts across a session's ChatSets, merges `files` and `data_contracts` by key, and produces a single plan dict passed to stage 2+ as `planbeaver_output`. [E-014]

### Dependencies
- **pipeline.drafter_dendrite**: Provides `LLMClient`, `LLMResponse`, `MockLLMClient` — the integrator does not import a provider-specific client. [E-015]
- **store.Soma**: The graph store. The integrator creates a `Soma(path=None)` for in-memory use in runners, or receives an existing instance.

### Parallel execution paths (boundary gap)
Two distinct execution paths exist for the "integrator" role:

| Path | Caller | Input | LLM Prompt | Output | Evidence |
|---|---|---|---|---|---|
| Dendrite module | `run_tb004.py`, `walk.py` | Classified signal nodes (post-ClassifierDendrite) | `_INTEGRATOR_INSTRUCTION` constant | TaskNode/RiskNode/DecisionNode/StackNode | [E-004], [E-005] |
| Engine planbeaver stage | `machinetalk/engine.py` | Raw ChatSet transcript + codebase_context + invariant_rules | `tb-005-planbeaver.md` prompt | `planbeaver_output` JSON (files, contracts, sequence) | [E-020], [E-021] |

The dendrite module and the engine's planbeaver stage use **different LLM prompts, different inputs, and different output schemas**. They serve the same high-level role (transforming chat content into build artifacts) but are not interchangeable.

## Known Gaps and Uncertainties

### G-01
**Duplicate module conflict** — `integrator_dendrite.py` exists at root (574 lines) and under `pipeline/` (578 lines). The root is imported by `run_tb004.py` and `walk.py`; the pipeline copy is imported by `test_integrator_dendrite.py`. They differ by ~4 lines (console handler variable name, a `user_text` fetch, and a stray `import re`). The functional behavior is identical but the pipeline copy contains an unused `user_text` fetch at line 259 and an `import re` statement at line 269 that appears after a method body, suggesting a merge artifact. What would close it: a clear ownership directive in a top-level doc or a migration to a single authoritative copy.

### G-02
**Two execution paths, different contracts** — The dendrite module produces `tasks`/`risks`/`decisions`/`stack` JSON from classified signals. The engine's planbeaver stage produces `files`/`data_contracts`/`execution_sequence` JSON from raw chat sets. These are different LLM prompts (`_INTEGRATOR_INSTRUCTION` vs. `tb-005-planbeaver.md`), different inputs (signal edges vs. raw transcript), and different outputs. It is unclear whether both paths are intended to coexist, whether one is legacy, or whether a future migration is planned. What would close it: a migration design doc or a decision to deprecate one path.

### G-03
**No programmatic enforcement of "no disk access" hard gate** — The module docstring states "Must NOT access physical files on disk" but no runtime check exists. The integrator does not currently access files, but the gate is not defensively enforced. What would close it: adding a guard clause or a context-manager that raises if any `open()` call is made.

### G-04
**Idempotency is O(n) per lookup** — The `_find_existing_*()` helpers call `self._soma.query_by_type()` and scan linearly. For large Soma graphs this scales poorly. No index on `task_text`, `risk_text`, `decision_text`, or `stack_text` exists. Not a functional defect for current in-memory graph sizes. What would close it: an index on text fields in `store.Soma` or a lookup table in the integrator.

### G-05
**SomaBridge.write_integrator() writes TaskNode only** — The bridge method at `machinetalk/soma_bridge.py:136` creates only `TaskNode` records from planbeaver file artifacts, not RiskNode/DecisionNode/StackNode. This is a partial mapping that does not cover all four output node types the dendrite module produces. The exact implementation is outside scope and was not fully inspected. What would close it: reading `soma_bridge.py` lines 120-160 to confirm the full scope of the bridge write.

### G-06
**Pipeline copy `user_text` fetch is dead code** — The pipeline file at line 259 fetches `user_text` from the ChatSet node but the variable is never used in the surrounding method. Confirmed by grep — no reference to `user_text` exists after line 259 in the pipeline file. What would close it: removing the dead fetch or wiring it into the LLM prompt assembly.

## Evidence Log

| ID | Host | Kind | Locator | Captured at | Proves | Confidence |
|---|---|---|---|---|---|---|
| E-001 | flintx | source | `integrator_dendrite.py` | 12:32Z | Root module, 574 lines, TB-TK-REPLACE-003 | C1 |
| E-002 | flintx | source | `pipeline/integrator_dendrite.py` | 12:32Z | Pipeline copy, 578 lines, +4 lines | C1 |
| E-003 | flintx | source | `test_integrator_dendrite.py` | 12:32Z | Tests import `pipeline.integrator_dendrite` | C1 |
| E-004 | flintx | source | `run_tb004.py:18` | 12:32Z | Runner imports root integrator | C1 |
| E-005 | flintx | source | `walk.py:24` | 12:32Z | Pipeline imports root integrator | C1 |
| E-006 | flintx | source | `integrator_dendrite.py:55-64` | 12:32Z | LLM instruction constant | C1 |
| E-007 | flintx | source | `integrator_dendrite.py:51` | 12:32Z | `_VALID_PRIORITIES` constant | C1 |
| E-008 | flintx | source | `integrator_dendrite.py:52` | 12:32Z | `_VALID_SEVERITIES` constant | C1 |
| E-009 | flintx | source | `integrator_dendrite.py:34-39` | 12:32Z | `_OUTPUT_NODE_TYPES` constant | C1 |
| E-010 | flintx | source | `integrator_dendrite.py:6-10` | 12:32Z | Hard gates in docstring | C1 |
| E-011 | flintx | source | `integrator_dendrite.py:199-216` | 12:32Z | Signal-only consumption via EXTRACTED_FROM | C1 |
| E-012 | flintx | source | `integrator_dendrite.py:455-481` | 12:32Z | Idempotency helpers | C1 |
| E-013 | flintx | source | `machinetalk/soma_bridge.py:11,136` | 12:32Z | Bridge writes TaskNode from planbeaver | C2 |
| E-014 | flintx | source | `machinetalk/engine.py:766-790` | 12:32Z | `_merged_plan` loads planbeaver artifacts | C2 |
| E-015 | flintx | source | `integrator_dendrite.py:22` | 12:32Z | LLMClient import from `pipeline.drafter_dendrite` | C1 |
| E-016 | flintx | source | `integrator_dendrite.py:130-197` | 12:32Z | Core `run()` method | C1 |
| E-017 | flintx | source | `integrator_dendrite.py:300-420` | 12:32Z | Node writers with idempotent skip | C1 |
| E-018 | flintx | source | `integrator_dendrite.py:523-535` | 12:32Z | `_ensure_session_node` creates placeholder | C1 |
| E-019 | flintx | source | `integrator_dendrite.py:537-556` | 12:32Z | Edge linkage: REQUIRES_ACTION, INTRODUCES_RISK, ADDRESSES | C1 |
| E-020 | flintx | source | `machinetalk/engine.py:503-505` | 12:32Z | Engine planbeaver extra payload | C2 |
| E-021 | flintx | source | `machine-talk/tb-005-planbeaver.md` | 12:32Z | Planbeaver spec output contract | C3 |
| E-022 | flintx | source | `machine-talk/cli-manifest.json:46-50` | 12:32Z | CLI manifest: planbeaver input_source=raw_chat_set | C3 |
| E-023 | flintx | runtime | inventory `find` | 12:32Z | `soma/workspaces` does not exist | C1 |
| E-024 | flintx | runtime | `diff` output | 12:32Z | Root differs from pipeline by 4 logical lines | C1 |
