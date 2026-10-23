# SaltatoryGate — Forensic Deep Dive

TARGET: saltatory-gate | RUN: 20261022T144358Z-4625b3 | DATE: 2026-10-22T14:43Z | HOSTS EXAMINED: flintx
CONFIDENCE SUMMARY: C1 across all source claims. One latent runtime bug (`.id` vs `.node_id`) may prevent execution.
SCOPE: `pipeline/saltatory_gate.py` — verification gate for FunctionSlots that runs tests and creates VerifiedNode or FailureNode.

## Mandate

SaltatoryGate runs a pytest subprocess against the test files in a FunctionSlot's workspace, then creates a VerifiedNode (tests pass) or FailureNode (tests fail) linked by a VERIFIED edge.

## Current State

| File | Host | Lines | Mtime |
|------|------|-------|-------|
| `pipeline/saltatory_gate.py` | flintx | 192 | 2026-10-18T01:40:23Z |

The module exists and imports successfully (`python3 -c "from pipeline.saltatory_gate import SaltatoryGate"`) [E-016]. It is not a daemon; it is invoked in-process. It has no test file. No remote copy exists per target registry.

## Key Paths and Entry Points

| Path | Host | Role | Entrypoint? | Lines | Mtime | Evidence |
|------|------|------|-------------|-------|-------|----------|
| `pipeline/saltatory_gate.py` | flintx | Main module | Yes — `SaltatoryGate` class | 192 | 2026-10-18 | E-001 |
| `run_pipeline.py` | flintx | Stage 9 orchestrator | Caller | — | — | E-002 |
| `walk.py` | flintx | Standalone runner | Caller | — | — | E-003 |
| `pipeline/code_publisher.py` | flintx | Consumes VerifiedNode | Downstream | — | — | E-007 |
| `machinetalk/soma_bridge.py` | flintx | Parallel gate path | Sibling (not called by this) | — | — | E-008 |

## Architecture and Data Flow

```text
                    ┌──────────────┐
                    │  Myelinator  │──► Creates FunctionSlot nodes
                    └──────┬───────┘
                           │
                           ▼
┌─────────────────────────────────────────┐
│            SaltatoryGate.run()           │
│  1. Query FunctionSlot nodes            │
│  2. For each slot, run pytest via       │
│     subprocess (60s timeout)            │
│  3a. PASS → create VerifiedNode         │
│  3b. FAIL → create FailureNode          │
│  4. Create VERIFIED edge                │
└──────┬──────────────┬───────────────────┘
       │              │
       ▼              ▼
┌──────────────┐ ┌──────────────┐
│ VerifiedNode │ │ FailureNode  │
└──────┬───────┘ └──────┬───────┘
       │                │
       ▼                ▼
┌──────────────────────────────────────┐
│       CodePublisher (Stage 10)       │
│  - Publishes ONLY from VerifiedNode  │
│  - Skips if FailureNode exists       │
└──────────────────────────────────────┘
```

```text
─────────────────────                      ───────────────
gate = SaltatoryGate(self._soma)           │
gate_result = gate.run(session_id)         ├─► query_by_type("FunctionSlot")
verified = result["verified_count"]        ├─► for each slot:
failure = result["failure_count"]          │   ├─► _run_slot_tests(session, file_path)
if failure > 0:                            │   │   ├─► subprocess.run(pytest)
    ABORT publisher                        │   │   └─► {"passed": True/False, "skipped": bool}
else:                                      │   ├─► PASS → _create_verified_node()
    publisher.run(session_id)              │   │   └─► create_edge(slot, "VERIFIED", vid)
                                           │   └─► FAIL → _create_failure_node()
                                           │       └─► create_edge(slot, "VERIFIED", fid)
```

## Core Logic

### `run(session_id: str) -> dict` — main entry point

1. Queries all `FunctionSlot` nodes where `properties.session_id == session_id` [E-001:50-53]
2. Iterates each slot: extracts `slot_id`, `name`, `file_path` [E-001:54-57]
3. Calls `_run_slot_tests(session_id, file_path)` [E-001:59]
4. Branches on test result:
   - `skipped` → append to skipped list [E-001:62-65]
   - `passed` → creates VerifiedNode, creates VERIFIED edge [E-001:67-73]
   - failure → creates FailureNode, creates VERIFIED edge [E-001:75-82]
5. Returns dict with `verified_ids`, `failure_ids`, `skipped_ids`, counts, `latency_ms` [E-001:84-93]

### `_run_slot_tests(session_id, file_path) -> dict` — test execution

1. Resolves workspace via `_get_workspace_path(session_id)` [E-001:99]
2. Checks for test files via `workspace.rglob("test_*")` [E-001:103]
3. If no test files → `{"passed": False, "error": "no test files", "skipped": True}` [E-001:104]
4. If target file missing → `{"passed": False, "error": "file not in workspace", "skipped": False}` [E-001:108]
5. Runs `pytest -x --tb=short` on all test files via `subprocess.run()` [E-001:116-123]
   - Hardcoded binary: `/usr/bin/python3` [E-005]
   - Timeout: 60 seconds [E-005]
   - `returncode == 0` → `{"passed": True}` [E-001:120]
   - Non-zero → `{"passed": False, "error": stderr[:500]}` [E-001:122]
   - `TimeoutExpired` → `{"passed": False, "error": "test timeout"}` [E-001:124]
   - `FileNotFoundError` (pytest not installed) → `{"passed": False, "skipped": True}` [E-001:127]

### `_get_workspace_path(session_id) -> Path | None`

1. Sanitizes session_id: `re.sub(r"[^\w.-]", "_", session_id)` [E-001:108]
2. Constructs: `~/"soma"/"chats"/{safe_id}/"workspace"` [E-001:109]
3. Returns `None` if path does not exist [E-001:110]

### `_create_verified_node(session_id, slot_id, slot_name, file_path) -> str`

1. Generates id: `f"verified-{slot_id}"` [E-001:157]
2. Deletes existing node if present [E-001:158-159]
3. Creates VerifiedNode with properties: `id`, `session_id`, `slot_id`, `slot_name`, `file_path`, `status: "verified"`, `verification_method: "test_suite"` [E-001:160-167]
4. Returns id [E-001:168]

### `_create_failure_node(session_id, slot_id, slot_name, file_path, error) -> str`

1. Generates id: `f"failure-{slot_id}"` [E-001:179]
2. Deletes existing node if present [E-001:180-181]
3. Creates FailureNode with properties: `id`, `session_id`, `slot_id`, `slot_name`, `file_path`, `status: "failed"`, `failure_reason: error` [E-001:182-188]
4. Returns id [E-001:189]

### CONFLICT C-03: `.id` vs `.node_id` on Node objects

`Node` dataclass (`store.py:12-14`) defines attribute `node_id`. `pipeline/saltatory_gate.py:53` accesses `slot.id`. If `Node` has no `__getattr__` or `id` property (not visible in `store.py`), this raises `AttributeError` on the first slot iteration. Confirmed: `store.py` does not define `id` or `__getattr__` [E-012]. This is a latent crash bug.

## Configuration and Invariants

| Setting | Value | Source |
|---------|-------|--------|
| TB identifier | TB-DEND-022 | Module docstring [E-001:1] |
| Python binary | `/usr/bin/python3` | Hardcoded [E-001:117] |
| Test timeout | 60 seconds | `subprocess.run(timeout=60)` [E-001:121] |
| Test discovery | `workspace.rglob("test_*")` | [E-001:103] |
| Hard gate 1 | VerifiedNode ONLY if tests pass | Docstring [E-001:7] |
| Hard gate 2 | FailureNode if any test fails | Docstring [E-001:8] |
| Hard gate 3 | Must not modify FunctionSlot/OptimizedSlot | Docstring [E-001:9] |
| Hard gate 4 | All edges via `Soma.create_edge()` | Docstring [E-001:10] |

Gate 3 is verified: the class only calls `create_node` for VerifiedNode/FailureNode and `create_edge` for VERIFIED edges. No `create_node` call targets FunctionSlot or OptimizedSlot [E-001:160,182].

## Dependencies and Cross-Component Connections

| Dependency | Direction | Mechanism | Payload | Verified? |
|------------|-----------|-----------|---------|-----------|
| `store.Soma` | Upstream | `import from store` | create_node, delete_node, query_by_type, create_edge, get_node, get_edges | Yes [E-001:22] |
| `subprocess` | Upstream | `import subprocess` | Runs pytest | Yes [E-001:23] |
| `time` | Upstream | `import time` | monotonic timer | Yes [E-001:25] |
| `pathlib.Path` | Upstream | `from pathlib import Path` | workspace path resolution | Yes [E-001:26] |
| `typing.Any` | Upstream | `from typing import Any` | type hints | Yes [E-001:27] |
| `re` | Upstream | `import re` (bottom of file) | session_id sanitization | Yes, but misplaced [E-006] |
| Myelinator/Ontology | Upstream | Reads FunctionSlot nodes | FunctionSlot graph nodes | Yes [E-001:50-53] |
| CodePublisher | Downstream | Reads VerifiedNode/FailureNode | Verification outcome | Yes [E-007] |
| `run_pipeline.py` | Downstream | Stage 9 caller | failure_count gates publisher | Yes [E-002] |
| `walk.py` | Downstream | Standalone caller | session verification | Yes [E-003] |
| `machinetalk/soma_bridge.write_gate()` | Parallel | Creates VerifiedNode/FailureNode for different node types | ImplementationNode verification | Yes [E-008] |

Two parallel paths write VerifiedNode/FailureNode:
- **SaltatoryGate** (`pipeline/saltatory_gate.py`): For FunctionSlot, uses `VERIFIED` edge, creates `verified-{slot_id}` / `failure-{slot_id}` ids.
- **soma_bridge.write_gate()** (`machinetalk/soma_bridge.py:470-533`): For ImplementationNode/SmokeTestNode, uses `VERIFIES` edge, creates `ver-{impl_id}` / `fail-{impl_id}` ids.
- These paths do not coordinate. No shared config, no cross-check.

## Known Gaps and Uncertainties

### G-01: Latent `.id` attribute bug
- **Unknown:** Whether `Node` has an `id` property or `__getattr__` not visible in `store.py`. The dataclass defines only `node_id`.
- **Why it matters:** `pipeline/saltatory_gate.py:53` (`slot_id = slot.id`) will raise `AttributeError` on first slot, crashing `run()`.
- **Closing evidence:** Run `python3 -c "from store import Node; n = Node('x','y',{}); print(n.id)"` — if it fails, the bug is confirmed.

### G-02: No unit tests for SaltatoryGate
- **Unknown:** Whether the module's logic (test orchestration, VerifiedNode/FailureNode creation, error handling) is correct.
- **Why it matters:** The module is imported by `run_pipeline.py` and `walk.py` with no automated test coverage of its own behavior.
- **Closing evidence:** A test file exercising `SaltatoryGate` with a mock `Soma` instance.

### G-03: Workspace path does not exist in standard project layout
- **Unknown:** Whether `~/"soma"/"chats"/{session_id}/workspace` directories are ever created by the pipeline. The code at `walk.py` and `run_pipeline.py` does not create this path.
- **Why it matters:** If the workspace does not exist, `_run_slot_tests` returns `{"passed": False, "skipped": False}`, causing every slot to be marked as a FAILURE rather than skipped. This means the gate's SKIP logic is unreachable unless the workspace is manually or externally created.
- **Closing evidence:** Verify that `~/"soma"/"chats/"` exists and contains session workspaces from prior runs.

### G-04: Integrity check in run_pipeline.py is comparing wrong types
- **Unknown:** Whether Myelinator produces FunctionSlot or OptimizedSlot nodes. The docstring in `pipeline/saltatory_gate.py` says it must not modify `OptimizedSlot` nodes, implying Myelinator creates OptimizedSlot. But the gate queries FunctionSlot.
- **Why it matters:** `run_pipeline.py:192-194` compares `verified_count` (from FunctionSlot query) against `optimized_count` (from Myelinator result). If Myelinator produces OptimizedSlot and gate consumes FunctionSlot, these counts are from disjoint sets and will never match.
- **Closing evidence:** Inspect Myelinator's `run()` output and the node types it creates.

### G-05: Machine-talk engine does not call SaltatoryGate
- **Unknown:** Whether `machinetalk/engine.py` (the production pipeline) ever invokes `SaltatoryGate`. The file does not import or reference the class [E-009].
- **Why it matters:** If the machine-talk engine is the production runner and only uses `soma_bridge.write_gate()` for verification, then `pipeline/saltatory_gate.py` is dead code — reachable only via `run_pipeline.py` or `walk.py`.
- **Closing evidence:** Trace the full production run path from `run.sh` through `machinetalk/engine.py` to confirm whether any code path reaches `SaltatoryGate`.

## Evidence Log

| ID | Host | Kind | Locator | Captured at | Proves | Confidence |
|----|------|------|---------|-------------|--------|------------|
| E-001 | flintx | source | `pipeline/saltatory_gate.py` lines 1-192 | 2026-10-22T14:43Z | SaltatoryGate class, all methods, module docstring, hard gates | C1 |
| E-002 | flintx | source | `run_pipeline.py:37,79,167-207` | 2026-10-22T14:43Z | Stage 9 integration, failure gating, integrity check | C1 |
| E-003 | flintx | source | `walk.py:33,120-126` | 2026-10-22T14:43Z | Standalone runner integration | C1 |
| E-004 | flintx | source | `store.py:26-101` | 2026-10-22T14:43Z | Soma class interface used by SaltatoryGate | C1 |
| E-005 | flintx | source | `pipeline/saltatory_gate.py:117,121` | 2026-10-22T14:43Z | Hardcoded Python binary and 60s timeout | C1 |
| E-006 | flintx | source | `pipeline/saltatory_gate.py:192` | 2026-10-22T14:43Z | `import re` at bottom of file | C1 |
| E-007 | flintx | source | `pipeline/code_publisher.py:1-90` | 2026-10-22T14:43Z | CodePublisher downstream consumer | C1 |
| E-008 | flintx | source | `machinetalk/soma_bridge.py:470-533` | 2026-10-22T14:43Z | Parallel write_gate() verification path | C1 |
| E-009 | flintx | source | `machinetalk/engine.py` (grep -n) | 2026-10-22T14:43Z | No SaltatoryGate reference in engine.py | C1 |
| E-010 | flintx | doc | `SESSION_HANDOFF.md:21-64` | 2026-10-22T14:43Z | Stale code description (OptimizedSlot, different prefix) | C1 |
| E-011 | flintx | source | `pipeline/saltatory_gate.py:53` | 2026-10-22T14:43Z | Uses `slot.id` attribute | C1 |
| E-012 | flintx | source | `store.py:12-14` | 2026-10-22T14:43Z | Node dataclass has `node_id` only | C1 |
| E-013 | flintx | source | `pipeline/saltatory_gate.py:108-110` | 2026-10-22T14:43Z | Workspace path resolution logic | C1 |
| E-014 | flintx | source | `machinetalk/soma_bridge.py:520-533` | 2026-10-22T14:43Z | write_publisher creates VerifiedNode | C1 |
| E-015 | flintx | source | `run_pipeline.py:192-194` | 2026-10-22T14:43Z | Integrity check comparing verified_count to optimized_count | C1 |
| E-016 | flintx | runtime | `python3 -c "from pipeline.saltatory_gate import SaltatoryGate"` | 2026-10-22T14:43Z | Module imports without error | C1 |
| E-017 | flintx | source | `test_run_engine_soma_only.py:201` | 2026-10-22T14:43Z | VerifiedNode in expected downstream types | C1 |
