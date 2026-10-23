# Discovery Notes: integrator

## Target lock

TARGET: integrator
SLUG: integrator
RUN ID: 20261022T123201Z-e06851
BASE DIR: /home/flintx/soma-10-14/soma
HOST: flintx
SCOPE: Integrates classified signals into tasks, risks, decisions, and stack constraints.
EXCLUDED: every other component; siblings are interfaces only

## Inventory summary

| Path | Exists | Lines | Mtime |
|---|---|---|---|
| `integrator_dendrite.py` | Yes | 574 | 2026-10-19T18:02 |
| `pipeline/integrator_dendrite.py` | Yes | 578 | 2026-10-19T18:04 |
| `test_integrator_dendrite.py` | Yes | 558 | 2026-10-19T00:43 |
| `run_tb004.py` | Yes | 190 | — |
| `walk.py` | Yes | — | — |
| `machinetalk/soma_bridge.py` | Yes | — | — |
| `machinetalk/engine.py` | Yes | — | — |

Total project files (depth 3): 180

## Entry points

| Path | Host | Role | Entrypoint? | Lines | Mtime | Evidence |
|---|---|---|---|---|---|---|
| `integrator_dendrite.py` | flintx (local) | TB-TK-REPLACE-003 core module | Yes | 574 | 2026-10-19T18:02 | [E-001] |
| `pipeline/integrator_dendrite.py` | flintx (local) | TB-TK-REPLACE-003 core module (duplicate) | Yes | 578 | 2026-10-19T18:04 | [E-002] |
| `test_integrator_dendrite.py` | flintx (local) | Unit tests | No | 558 | 2026-10-19T00:43 | [E-003] |
| `run_tb004.py` | flintx (local) | TB-004 runner — imports root integrator | Import | 190 | — | [E-004] |
| `walk.py` | flintx (local) | Pipeline — imports root integrator | Import | — | — | [E-005] |

## Runtime state

Not running as a standalone process. The integrator is imported as a module and invoked through:
- `run_tb004.py` — direct execution for Stage 1 dendrite testing
- `walk.py` — pipeline execution
- `machinetalk/engine.py` — "planbeaver" stage in `_run_chatset_stage()`
- `SomaBridge.write_integrator()` — artifact-to-Soma bridge write

No persistent process or port associated with the integrator.

## Data stores

No dedicated datastore. The integrator writes to a `Soma` graph instance (in-memory by default, `path=None` in `run_tb004.py`). The `workspaces` directory at `/home/flintx/soma-10-14/soma/workspaces` does **not** exist (confirmed by inventory).

## Configuration and invariants

| Key | Default | Enforced |
|---|---|---|
| `_INTEGRATOR_INSTRUCTION` (LLM system prompt) | See `integrator_dendrite.py:55-64` | Code constant [E-006] |
| `_VALID_PRIORITIES` | `{"HIGH", "MEDIUM", "LOW"}` | Code constant [E-007] |
| `_VALID_SEVERITIES` | `{"HIGH", "MEDIUM", "LOW"}` | Code constant [E-008] |
| `_OUTPUT_NODE_TYPES` | `{"TaskNode", "RiskNode", "DecisionNode", "StackNode"}` | Code constant [E-009] |
| Hard gate: must NOT access physical files | Documented in docstring [E-010] | Not enforced in code |
| Hard gate: must consume signal nodes, not raw logs | Documented in docstring [E-010] | Enforced via `_collect_signal_ids()` which only reads `EXTRACTED_FROM` edges [E-011] |
| Hard gate: idempotent output (no duplicate TaskNode) | Documented in docstring [E-010] | Enforced via `_find_existing_*()` search [E-012] |

## Cross-component edges

| Direction | Mechanism | Payload | Evidence |
|---|---|---|---|
| Upstream (ClassifierDendrite) | Soma graph — reads `EXTRACTED_FROM` edges from ChatSet | Signal node IDs of type IntentNode/DirectiveNode/ConstraintNode/QuestionNode/PreferenceNode/CorrectionNode/NoiseNode | [E-011] |
| Downstream (SomaBridge) | `write_integrator()` maps planbeaver artifact to TaskNode/RiskNode/DecisionNode/StackNode | JSON artifact with `planbeaver_output` key | [E-013] |
| Downstream (machinetalk/engine.py) | `_merged_plan()` loads `planbeaver` artifacts for stages 2-4 | Merged plan dict with files + data_contracts | [E-014] |
| Downstream (run_tb004.py) | Direct `integrator.run(cs_id)` call on in-memory Soma | Result dict with task/risk/decision/stack node IDs | [E-004] |
| Downstream (walk.py) | `("integrator", IntegratorDendrite)` in `STAGE1` list | Calls `dendrite.run(target)` with chat_set_id | [E-005] |
| Dependency | `from pipeline.drafter_dendrite import LLMClient, LLMResponse, MockLLMClient` | LLM abstraction interface | [E-015] |

## Instructions and recency

| File | Date | Authority Rank |
|---|---|---|
| `integrator_dendrite.py` docstring (TB-TK-REPLACE-003) | 2026-10-19 | Rank 2 (source) |
| `machine-talk/tb-005-planbeaver.md` (PLANBEAVER spec) | 2026-10-14 | Rank 4 (design doc) |
| `machine-talk/cli-manifest.json` | 2026-10-14 | Rank 5 (top-level design) |
| `machine-talk/MACHINE_TALK_SPEC.md` | 2026-10-14 | Rank 5 (top-level design) |
| `test_integrator_dendrite.py` | 2026-10-19 | Rank 3 (tests) |

## Conflicts

CONFLICT C-01
  claim A: `integrator_dendrite.py` at root — 574 lines, mtime 2026-10-19T18:02
  claim B: `pipeline/integrator_dendrite.py` — 578 lines, mtime 2026-10-19T18:04
  resolution: both-live
  basis: Import graph analysis — `run_tb004.py` imports root (`from integrator_dendrite import`), `walk.py` imports root, but `test_integrator_dendrite.py` imports pipeline (`from pipeline.integrator_dendrite import`)
  impact: The test suite validates the pipeline copy, while the runtime runners use the root copy. They differ by ~4 lines (console logging config, a `_build_signal_payload` section, and a `user_text` fetch in pipeline).

CONFLICT C-02
  claim A: machinetalk engine calls planbeaver with `raw_chat_set` directly (reads ChatSet transcript)
  claim B: IntegratorDendrite dendrite reads classified signal nodes via `EXTRACTED_FROM` edges
  resolution: both-live (different execution paths)
  basis: `machinetalk/engine.py:503-530` runs planbeaver as a chatset-level LLM stage using raw chat sets. `run_tb004.py:82` runs the IntegratorDendrite module after ClassifierDendrite has populated signal edges. These are two distinct execution paths for the "integrator" role.
  impact: Two separate mechanisms exist to produce Task/Risk/Decision/Stack nodes. The report documents the dendrite module as the primary target (matching the canonical registry entry), and notes the engine path as a boundary interface.

## Unknowns and boundary gaps

### U-01
The `user_text` fetch in `pipeline/integrator_dendrite.py:259` (`self._soma.get_node(chat_set_id).properties.get("user_text", "")`) is read in inventory but not used in the surrounding code. No reference to this variable is found in the pipeline file after the fetch. GAP: need to read full pipeline file to confirm if it is dead code or part of an incomplete LLM prompt assembly. [Evidence needed: full pipeline file grep]

### U-02
The `import re` statement in `pipeline/integrator_dendrite.py:269` appears after the `_build_signal_payload` method body — this is likely an artifact of the diff merge. Confirm whether the root file's `re` usage in `_call_llm` (fence stripping) covers this. [Evidence needed: full pipeline file check]

### U-03
The `_find_existing_*()` idempotency helpers perform an in-memory linear scan over all nodes of each type (`self._soma.query_by_type()`). On large graphs this is O(n) per lookup. No index on `task_text`, `risk_text`, `decision_text`, or `stack_text` is configured. GAP: not a functional defect but a scalability concern.

### U-04
The `SomaBridge.write_integrator()` method at `machinetalk/soma_bridge.py:11` maps planbeaver output to Soma nodes, but the exact implementation is outside scope. The bridge writes TaskNode records with properties derived from the artifact rather than from the dendrite's LLM call. [Evidence needed: read soma_bridge.py lines 120-160]

### U-05
The machinetalk engine's planbeaver stage uses `tb-005-planbeaver.md` prompt (outputting `files`, `data_contracts`, `execution_sequence`) while the IntegratorDendrite module's LLM instruction (line 55-64) asks for `tasks`, `risks`, `decisions`, `stack`. These are different output contracts. The two paths serve different downstream consumers.

## Evidence index

| ID | Host | Kind | Locator | Captured at | Proves | Confidence |
|---|---|---|---|---|---|---|
| E-001 | flintx | source | `integrator_dendrite.py` | 2026-10-22T12:32Z | Root integrator module, 574 lines, TB-TK-REPLACE-003 | C1 |
| E-002 | flintx | source | `pipeline/integrator_dendrite.py` | 2026-10-22T12:32Z | Pipeline copy, 578 lines, +4 lines vs root | C1 |
| E-003 | flintx | source | `test_integrator_dendrite.py` | 2026-10-22T12:32Z | Tests import pipeline copy | C1 |
| E-004 | flintx | source | `run_tb004.py:18` | 2026-10-22T12:32Z | Runner imports root integrator | C1 |
| E-005 | flintx | source | `walk.py:24` | 2026-10-22T12:32Z | Pipeline imports root integrator | C1 |
| E-006 | flintx | source | `integrator_dendrite.py:55-64` | 2026-10-22T12:32Z | LLM instruction constant | C1 |
| E-007 | flintx | source | `integrator_dendrite.py:51` | 2026-10-22T12:32Z | Valid priorities constant | C1 |
| E-008 | flintx | source | `integrator_dendrite.py:52` | 2026-10-22T12:32Z | Valid severities constant | C1 |
| E-009 | flintx | source | `integrator_dendrite.py:34-39` | 2026-10-22T12:32Z | Output node types constant | C1 |
| E-010 | flintx | source | `integrator_dendrite.py:6-10` | 2026-10-22T12:32Z | Hard gates in docstring | C1 |
| E-011 | flintx | source | `integrator_dendrite.py:199-216` | 2026-10-22T12:32Z | Signal-only consumption via EXTRACTED_FROM edges | C1 |
| E-012 | flintx | source | `integrator_dendrite.py:455-481` | 2026-10-22T12:32Z | Idempotency helpers | C1 |
| E-013 | flintx | source | `machinetalk/soma_bridge.py:11,136` | 2026-10-22T12:32Z | Bridge writes TaskNode from planbeaver artifact | C2 |
| E-014 | flintx | source | `machinetalk/engine.py:766-790` | 2026-10-22T12:32Z | Merged plan loads planbeaver artifacts | C2 |
| E-015 | flintx | source | `integrator_dendrite.py:22` | 2026-10-22T12:32Z | LLMClient import from pipeline.drafter_dendrite | C1 |
| E-016 | flintx | source | `integrator_dendrite.py:130-197` | 2026-10-22T12:32Z | Core `run()` method | C1 |
| E-017 | flintx | source | `integrator_dendrite.py:421-454` | 2026-10-22T12:32Z | `_write_task_nodes` with idempotent skip | C1 |
| E-018 | flintx | source | `integrator_dendrite.py:523-535` | 2026-10-22T12:32Z | `_ensure_session_node` creates placeholder | C1 |
| E-019 | flintx | source | `integrator_dendrite.py:537-556` | 2026-10-22T12:32Z | Edge linkage: REQUIRES_ACTION, INTRODUCES_RISK, ADDRESSES | C1 |
| E-020 | flintx | source | `machinetalk/engine.py:503-505` | 2026-10-22T12:32Z | Engine planbeaver extra: codebase_context + invariant_rules | C2 |
| E-021 | flintx | source | `machine-talk/tb-005-planbeaver.md` | 2026-10-22T12:32Z | Planbeaver spec: files/contracts/sequence output | C3 |
| E-022 | flintx | source | `machine-talk/cli-manifest.json:46-50` | 2026-10-22T12:32Z | CLI manifest: planbeaver input_source=raw_chat_set | C3 |
| E-023 | flintx | runtime | inventory `find` | 2026-10-22T12:32Z | workspaces directory does not exist | C1 |
| E-024 | flintx | source | `diff` output | 2026-10-22T12:32Z | Root differs from pipeline by 4 logical lines | C1 |

## Report plan

1. **Mandate** — one sentence from docstring
2. **Current State** — two copies exist; root is live in runners, pipeline is live in tests
3. **Key Paths** — table of all entry points
4. **Architecture** — ASCII context diagram + run() flow diagram
5. **Core Logic** — run() method, signal collection, LLM call, node writing, edge linkage, idempotency
6. **Configuration** — constants, hard gates
7. **Dependencies** — cross-component connections
8. **Known Gaps** — C-01, C-02, U-01 through U-05
