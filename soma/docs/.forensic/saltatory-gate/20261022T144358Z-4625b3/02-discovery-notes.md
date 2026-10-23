# Discovery Notes: saltatory-gate

TARGET: saltatory-gate | RUN: 20261022T144358Z-4625b3 | DATE: 2026-10-22T14:43Z

## 1. Target lock

- Target: saltatory-gate
- Slug: saltatory-gate
- Run ID: 20261022T144358Z-4625b3
- Base dir: /home/flintx/soma-10-14/soma
- Host: flintx
- Alias: `gate` per target-registry.md

## 2. Inventory summary

- Local root: `/home/flintx/soma-10-14/soma` — 188 files at depth 3
- Entry point confirmed: `pipeline/saltatory_gate.py` — 192 lines, mtime 2026-10-18T01:40:23Z
- No test file for `saltatory_gate.py` exists (confirmed via `find`)
- `pipeline/` has no `__init__.py`
- `machinetalk/` has `__init__.py` (exports client symbols only)
- Repository is not a git repo (no `.git` in soma/). Top-level project has no git either.

## 3. Entry points

| Path | Host | Lines | Mtime | Entrypoint? |
|------|------|-------|-------|-------------|
| `pipeline/saltatory_gate.py` | flintx | 192 | 2026-10-18T01:40:23Z | Yes — class SaltatoryGate [E-001] |

No remote copy exists per target registry.

## 4. Runtime state

Not running as a daemon. Invoked in-process by:
- `run_pipeline.py` — Stage 9 (pipeline orchestrator) [E-002]
- `walk.py` — standalone runner [E-003]

No separate process, port, or HTTP endpoint.

## 5. Data stores

- Uses `Soma` in-memory JSON-backed graph store (`store.py`) [E-004]
- Nodes: VerifiedNode, FailureNode
- Edges: VERIFIED
- No dedicated database file

## 6. Configuration and invariants

- TB-DEND-022 identifier in docstring [E-001]
- Hard gates documented in module docstring:
  1. VerifiedNode exists ONLY if all tests pass [E-001]
  2. FailureNode created if any test fails [E-001]
  3. Must not modify FunctionSlot or OptimizedSlot nodes [E-001]
  4. All edge modifications go through Soma.create_edge() [E-001]
- Python binary hardcoded: `/usr/bin/python3` [E-005]
- Test timeout: 60 seconds [E-005]
- `re` imported at BOTTOM of file, after class definition [E-006] — works but fragile

## 7. Cross-component edges

| Direction | Mechanism | Evidence |
|-----------|-----------|----------|
| Upstream: Myelinator | SaltatoryGate queries FunctionSlot nodes created by Myelinator/AxonHillock | `run_pipeline.py:167-186` [E-002] |
| Upstream: walk.py | `walk.py:120-126` imports and runs SaltatoryGate | `walk.py:33,120-126` [E-003] |
| Downstream: CodePublisher | CodePublisher queries VerifiedNodes and skips FailureNodes | `pipeline/code_publisher.py:44-67` [E-007] |
| Downstream: run_pipeline.py | Failure count gates publisher; verified_count checked against optimized_count | `run_pipeline.py:188-207` [E-002] |
| Parallel: soma_bridge.write_gate() | Creates VerifiedNode/FailureNode for ImplementationNode/SmokeTestNode (different path) | `machinetalk/soma_bridge.py:470-533` [E-008] |
| Register: machinetalk.client | "saltatory_gate": "saltatory_gate" in stage name map | `machinetalk/client.py:35` [E-009] |

## 8. Instructions and recency

- `pipeline/saltatory_gate.py` — 2026-10-18T01:40:23Z — module docstring [E-001]
- `SESSION_HANDOFF.md` — contains an OUTDATED copy of SaltatoryGate code (queries OptimizedSlot, uses `verified_`/`failure_` prefix, different edge names) — stale documentation [E-010]
- `machinetalk/soma_bridge.py::write_gate()` — 2026-10-21 — parallel gate path [E-008]

## 9. Conflicts

### C-01: Node type queried — FunctionSlot vs OptimizedSlot
- Claim A: Current code queries `FunctionSlot` nodes [E-001]
- Claim B: SESSION_HANDOFF.md describes querying `OptimizedSlot` nodes [E-010]
- Resolution: A (current code wins per R4)
- Impact: SESSION_HANDOFF.md documentation is stale

### C-02: Two parallel verification paths
- Claim A: SaltatoryGate (pipeline/) queries FunctionSlot, runs tests via subprocess [E-001]
- Claim B: soma_bridge.write_gate() queries ImplementationNode/SmokeTestNode, reads smoke test status [E-008]
- Resolution: Both live, different call paths
- Impact: System has two distinct VerifiedNode/FailureNode creation paths that are not coordinated

### C-03: Node attribute access — .id vs .node_id
- Claim A: saltatory_gate.py uses `node.id` [E-011]
- Claim B: Node dataclass has attribute `node_id` (see store.py:12) [E-012]
- Resolution: A is a latent bug — `slot.id` will raise AttributeError at runtime
- Impact: The run() method will crash on the first FunctionSlot it encounters

## 10. Unknowns and boundary gaps

### U-01: No test suite for SaltatoryGate itself
- Evidence needed: No `test_saltatory_gate.py` exists. The module has no unit tests.
- Impact: Correctness of VerifiedNode/FailureNode creation, test orchestration, and error handling is unverified by automated tests.

### U-02: Attribute `.id` on Node objects
- Evidence needed: Confirm whether any `Node` instance ever has `.id` (e.g., via `__getattr__` not visible in source). The dataclass only defines `node_id`.
- Impact: If `.id` does not exist, `run()` crashes immediately on the first slot iteration.

### U-03: Which path actually executes in production?
- Evidence needed: Determine whether the machine-talk pipeline (`machinetalk/engine.py`) calls `SaltatoryGate` or only calls `soma_bridge.write_gate()`. Current evidence: `machinetalk/engine.py` does NOT import or reference `SaltatoryGate` [E-009].
- Impact: The `pipeline/saltatory_gate.py` module may only run via `run_pipeline.py` or `walk.py`, not via the production machine-talk engine.

### U-04: Workspace path resolution
- Evidence needed: The workspace path is `~/"soma"/"chats"/{safe_session_id}/"workspace"`. This requires a manually created directory structure. Confirm whether this path exists in test runs.
- Impact: If workspace does not exist, `_run_slot_tests` returns `{"passed": False, "skipped": False}` — meaning every slot is treated as a FAILURE, not a SKIP.

### U-05: `integrity_check` comparison in run_pipeline.py
- Evidence needed: `verified_count != optimized_count` comparison — but gate queries FunctionSlot, not OptimizedSlot. If Myelinator produces OptimizedSlot nodes and gate produces VerifiedNode from FunctionSlot, the counts can never match.
- Impact: The integrity check at `run_pipeline.py:192-194` will always warn unless OptimizedSlot count equals FunctionSlot count for the session.

## 11. Evidence index

| ID | Host | Kind | Locator | Captured at | Proves | Confidence |
|----|------|------|---------|-------------|--------|------------|
| E-001 | flintx | source | `pipeline/saltatory_gate.py` lines 1-192 | 2026-10-22T14:43Z | Class definition, module docstring, hard gates, VerifiedNode/FailureNode creation, VERIFIED edge | C1 |
| E-002 | flintx | source | `run_pipeline.py:37,79,167-207` | 2026-10-22T14:43Z | SaltatoryGate import, Stage 9 call, failure gating, integrity check | C1 |
| E-003 | flintx | source | `walk.py:33,120-126` | 2026-10-22T14:43Z | SaltatoryGate import and call in standalone runner | C1 |
| E-004 | flintx | source | `store.py:26-101` | 2026-10-22T14:43Z | Soma class: create_node, get_node, delete_node, query_by_type, create_edge | C1 |
| E-005 | flintx | source | `pipeline/saltatory_gate.py:117,119` | 2026-10-22T14:43Z | Hardcoded Python binary /usr/bin/python3, 60s timeout | C1 |
| E-006 | flintx | source | `pipeline/saltatory_gate.py:192` | 2026-10-22T14:43Z | `import re` at bottom of file | C1 |
| E-007 | flintx | source | `pipeline/code_publisher.py:1-90` | 2026-10-22T14:43Z | CodePublisher consumes VerifiedNode/FailureNode output | C1 |
| E-008 | flintx | source | `machinetalk/soma_bridge.py:470-533` | 2026-10-22T14:43Z | Parallel write_gate() path creates VerifiedNode/FailureNode for ImplementationNode | C1 |
| E-009 | flintx | source | `machinetalk/client.py:35` | 2026-10-22T14:43Z | Stage name mapping | C1 |
| E-010 | flintx | doc | `SESSION_HANDOFF.md:21-64` | 2026-10-22T14:43Z | Stale code description querying OptimizedSlot | C1 |
| E-011 | flintx | source | `pipeline/saltatory_gate.py:53` | 2026-10-22T14:43Z | Uses `slot.id` | C1 |
| E-012 | flintx | source | `store.py:12-14` | 2026-10-22T14:43Z | Node dataclass has `node_id`, not `id` | C1 |
| E-013 | flintx | source | `pipeline/saltatory_gate.py:108-110` | 2026-10-22T14:43Z | `_get_workspace_path` uses `~/"soma"/"chats"/` | C1 |
| E-014 | flintx | source | `machinetalk/soma_bridge.py:520-533` | 2026-10-22T14:43Z | write_publisher creates VerifiedNode with "CodePublisher wrote file" text | C1 |
| E-015 | flintx | source | `run_pipeline.py:192-194` | 2026-10-22T14:43Z | Integrity check: verified_count vs optimized_count | C1 |
| E-016 | flintx | runtime | `python3 -c "from pipeline.saltatory_gate import SaltatoryGate"` | 2026-10-22T14:43Z | Module imports successfully | C1 |
| E-017 | flintx | source | `test_run_engine_soma_only.py:201` | 2026-10-22T14:43Z | VerifiedNode in expected downstream types | C1 |

## 12. Report plan

1. Mandate — one sentence
2. Current State — file exists, not running, two call paths
3. Key Paths and Entry Points — table
4. Architecture and Data Flow — context + sequence diagrams
5. Core Logic — run() execution path with evidence
6. Configuration and Invariants — docstring gates, hardcoded values
7. Dependencies and Cross-Component Connections — upstream/downstream/parallel
8. Known Gaps and Uncertainties — U-01 through U-05
