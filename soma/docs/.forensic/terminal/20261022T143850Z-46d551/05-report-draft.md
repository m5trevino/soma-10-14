# terminal — Forensic Deep Dive

TARGET: terminal | RUN: 20261022T143850Z-46d551 | DATE: 2026-10-22T14:38Z | HOSTS EXAMINED: flintx
CONFIDENCE SUMMARY: C2 (static source analysis only; no runtime probe)
SCOPE: Terminal stage in machinetalk/soma_bridge.py — converts OptimizedSlot nodes into ImplementationNode and SmokeTestNode graph records.

## Mandate

Convert every OptimizedSlot node for a session into an ImplementationNode (carrying function metadata and code) and a SmokeTestNode (stubbed PASS record), then make them available for the subsequent gate verification stage.

## Current State

| Fact | Value |
|---|---|
| Source file | `machinetalk/soma_bridge.py` |
| Method | `write_terminal()` at line 435 |
| File size | 537 lines |
| Last write | 2026-10-18T20:49:51Z [E-001] |
| Invocation site | `machinetalk/engine.py:740` |
| Engine mtime | 2026-10-21T19:43:00Z [E-007] |
| Standalone process | No — called synchronously inside engine's olc-stage handler |
| Dedicated tests | None found |
| Output evidence | `output/soma.json` contains only legacy node types (ChatSet, ReceptorLog, TaskNode, SessionAnchor) — no ImplementationNode or SmokeTestNode records present [E-012] |

## Key Paths and Entry Points

| Path | Host | Role | Entrypoint? | Lines | mtime | Evidence |
|---|---|---|---|---|---|---|
| `machinetalk/soma_bridge.py` | flintx | Terminal logic (write_terminal) | Yes | 435-466 | 2026-10-18T20:49:51Z | [E-001] |
| `machinetalk/engine.py:740` | flintx | Call site (write_olc handler) | Yes | 740 | 2026-10-21T19:43:00Z | [E-008] |
| `machinetalk/soma_bridge.py:20` | flintx | Module-level mapping table (docstring) | Reference | 20 | 2026-10-18T20:49:51Z | [E-006] |
| `test_run_engine_soma_only.py:199-200` | flintx | Test scope assertion (excludes terminal types) | Reference | 197-201 | 2026-10-21T19:46:00Z | [E-010] |

## Architecture and Data Flow

```mermaid
flowchart TD
    E[machinetalk/engine.py\nstage "olc"] -->|write_olc()| O[write_olc()\ncreates OptimizedSlot]
    O -->|write_terminal()| T[write_terminal()]
    T -->|query OptimizedSlot| Q[filter by session_id]
    T -->|create_node| I[ImplementationNode]
    T -->|create_node| S[SmokeTestNode]
    I -->|counts.update()| M{merge into\ncounts}
    S -->|counts.update()| M
    M -->|write_gate()| G[write_gate()\nVerifiedNode or FailureNode]
```

```text
write_terminal() sequence:

  input: session_id, model_id="", latency_ms=0.0
         │
         ├─ query_by_type("OptimizedSlot") ── filter by session_id ──► opts []
         │
         ├─ for each opt in opts:
         │     │
         │     ├─ read opt.properties: name, code_block, language, file_path
         │     │
         │     ├─ impl_id = "impl-{opt_id}"
         │     │   get_node(impl_id) ── if exists ──► delete_node(impl_id)
         │     │   create_node("ImplementationNode", {
         │     │     id, session_id, slot_id, function_name,
         │     │     implementation_text, language, file_path,
         │     │     model_id, status: "implemented"
         │     │   })
         │     │
         │     ├─ smoke_id = "smoke-{impl_id}"
         │     │   get_node(smoke_id) ── if exists ──► delete_node(smoke_id)
         │     │   create_node("SmokeTestNode", {
         │     │     id, session_id, implementation_id,
         │     │     status: "PASS", stdout: "", stderr: "", return_code: 0
         │     │   })
         │     │
         │     └─ counts["ImplementationNode"] += 1
         │             counts["SmokeTestNode"] += 1
         │
         └─ return counts
```

## Core Logic

The method `write_terminal()` (`machinetalk/soma_bridge.py:435-466`) executes the following steps:

1. **Query OptimizedSlot nodes** (line 438-441): Iterates all Soma graph nodes of type `OptimizedSlot` and filters by `session_id` property matching the input. This is the sole data source for the terminal stage.

2. **For each OptimizedSlot** (line 443-465):
   - Extracts properties: `name`, `code_block`, `language`, `file_path` from the OptimizedSlot's `properties` dict [E-002].
   - **ImplementationNode creation** (lines 444-454):
     - Constructs `impl_id = f"impl-{opt_id}"`.
     - Idempotency: deletes existing node if present [E-003].
     - Creates node with: `id`, `session_id`, `slot_id`, `function_name` (from `name`), `implementation_text` (from `code_block`), `language`, `file_path`, `model_id` (passed from engine), `status: "implemented"`.
   - **SmokeTestNode creation** (lines 456-463):
     - Constructs `smoke_id = f"smoke-{impl_id}"`.
     - Idempotency: deletes existing node if present.
     - Creates node with: `id`, `session_id`, `implementation_id`, `status: "PASS"`, `stdout: ""`, `stderr: ""`, `return_code: 0` [E-016]. **These are hardcoded defaults** — no real execution occurs.

3. **Return counts** (lines 464-465): Returns `{"ImplementationNode": N, "SmokeTestNode": N}` where N equals the number of matching OptimizedSlot nodes.

Invocation by engine (line 740, inside `elif stage == "olc":`):

```python
t_counts = self._bridge.write_terminal(build, rec.model, latency)
```

Arguments: `build` (session/build ID), `rec.model` (LLM model identifier), `latency` (float in ms). The return value is merged into `counts` via `counts.update(t_counts)` at line 741.

## Configuration and Invariants

| Parameter | Default | Source | Notes |
|---|---|---|---|
| `session_id` | required | machinetalk/engine.py:740 | Pass-through from `build` variable |
| `model_id` | `""` | machinetalk/engine.py:740 | `rec.model` from the LLM response |
| `latency_ms` | `0.0` | machinetalk/engine.py:740 | Passed but **not used** inside `write_terminal()` — accepted as unused parameter |

**Idempotency invariant** (lines 444, 456): Each node type is deleted before recreation. This prevents duplicate nodes across re-runs of the same stage.

**SmokeTestNode defaults** (lines 460-462): All five fields after `id` and `implementation_id` are hardcoded:
- `status: "PASS"` — no actual code execution
- `stdout: ""` — no captured output
- `stderr: ""` — no captured errors
- `return_code: 0` — always success

**Property defaults** (lines 450-452): If an OptimizedSlot is missing `name`, `language`, or `file_path`, defaults of `"unknown"`, `"python"`, and `""` are used respectively.

## Dependencies and Cross-Component Connections

**Upstream (read):**
| Source | Mechanism | Payload | Confidence |
|---|---|---|---|
| `OptimizedSlot` nodes | `query_by_type()` + filter | `name`, `code_block`, `language`, `file_path`, `session_id` | C2 [E-002] |

`OptimizedSlot` is created by `write_olc()` (`machinetalk/soma_bridge.py:409`) which consumes `hardened_files` from the OLC gate's parsed output. Each OptimizedSlot receives a `LINKED_TO` edge back to its source `FunctionSlot` (line 425).

**Downstream (write):**
| Target | Mechanism | Payload | Confidence |
|---|---|---|---|
| `ImplementationNode` | `create_node()` | id, session_id, slot_id, function_name, implementation_text, language, file_path, model_id, status | C2 [E-015] |
| `SmokeTestNode` | `create_node()` | id, session_id, implementation_id, status, stdout, stderr, return_code | C2 [E-016] |

**Downstream consumer:**
| Consumer | Mechanism | Evidence |
|---|---|---|
| `write_gate()` | queries both `ImplementationNode` and `SmokeTestNode`, creates `VerifiedNode` or `FailureNode` | `machinetalk/soma_bridge.py:470-519` [E-009] |

**Caller:**
| Caller | Mechanism | Context | Evidence |
|---|---|---|---|
| `machinetalk/engine.py:740` | method call on `self._bridge` | Inside `elif stage == "olc":` block, after `write_olc()`, before `write_gate()` | [E-008], [E-007] |

## Known Gaps and Uncertainties

### G-01: SmokeTestNode contains no real execution. Status is hardcoded to `"PASS"`, stdout/stderr/return_code are all defaults (`""`, `""`, `0`). The method creates a smoke test record without executing any code. It is unclear whether a separate smoke-test runner exists elsewhere in the system or whether these records are consumed by downstream stages purely as structural placeholders. Evidence needed: search for subprocess/exec/call invocations that consume ImplementationNode records, or confirmation that write_gate() uses SmokeTestNode records as truth.

### G-02: The Soma graph interface is not examined. Observed methods are `get_node()`, `create_node()`, `query_by_type()`, `delete_node()`, and `_persist()`, but the full API surface, persistence backend (SQLite, JSON file, in-memory), and serialization format are unknown. Evidence needed: read the SomaGraph class definition.

### G-03: `latency_ms` parameter is accepted but never used inside `write_terminal()` (machinetalk/soma_bridge.py:435-466). The value is passed from machinetalk/engine.py line 740 but dropped. Evidence needed: confirm this is intentional (unused for logging) or a bug.

### G-04: No dedicated test for `write_terminal()`. The test file `test_run_engine_soma_only.py` at lines 197-201 asserts that the soma-only path must NOT produce `ImplementationNode` or `OptimizedSlot` downstream types — meaning the terminal stage is explicitly excluded from soma-only testing. Evidence needed: confirm whether terminal is tested under any integration or full-pipeline test.

### G-05: No nonce reference exists anywhere in the soma codebase. Searched all `.py` files in the project and all `.md` files. The term `nonce` was not found. Evidence needed: if nonce is a concept that should exist in the terminal stage, determine where it belongs and verify absence.

## Evidence Log

| ID | Host | Kind | Locator | Captured at | Proves | Confidence |
|---|---|---|---|---|---|---|
| E-001 | flintx | source | machinetalk/soma_bridge.py:435 | 2026-10-22T14:38Z | write_terminal() method signature | C2 |
| E-002 | flintx | source | machinetalk/soma_bridge.py:438-441 | 2026-10-22T14:38Z | OptimizedSlot query and property extraction | C2 |
| E-003 | flintx | source | machinetalk/soma_bridge.py:444-454 | 2026-10-22T14:38Z | ImplementationNode creation with idempotency | C2 |
| E-004 | flintx | source | machinetalk/soma_bridge.py:456-463 | 2026-10-22T14:38Z | SmokeTestNode creation with hardcoded PASS | C2 |
| E-005 | flintx | source | machinetalk/soma_bridge.py:464-465 | 2026-10-22T14:38Z | Return counts dict | C2 |
| E-006 | flintx | source | machinetalk/soma_bridge.py:20 | 2026-10-22T14:38Z | TerminalPlayer mapping in docstring | C2 |
| E-007 | flintx | source | machinetalk/engine.py:739-742 | 2026-10-22T14:38Z | Terminal called after olc, before gate | C2 |
| E-008 | flintx | source | machinetalk/engine.py:740 | 2026-10-22T14:38Z | write_terminal(build, rec.model, latency) call site | C2 |
| E-009 | flintx | source | machinetalk/soma_bridge.py:470-477 | 2026-10-22T14:38Z | write_gate() queries ImplementationNode and SmokeTestNode | C2 |
| E-010 | flintx | source | test_run_engine_soma_only.py:197-201 | 2026-10-22T14:38Z | Test excludes ImplementationNode and OptimizedSlot from soma-only scope | C2 |
| E-011 | flintx | source | machinetalk/soma_bridge.py:1-24 | 2026-10-22T14:38Z | Full mapping table in module docstring | C2 |
| E-012 | flintx | source | output/soma.json | 2026-10-22T14:38Z | Output contains only legacy node types (no terminal-era nodes) | C2 |
| E-013 | flintx | shell | `rg -rn 'nonce' machinetalk/` | 2026-10-22T14:38Z | No nonce reference in machinetalk | C2 |
| E-014 | flintx | shell | `rg -rn 'nonce' *.py` | 2026-10-22T14:38Z | No nonce reference in soma root | C2 |
| E-015 | flintx | source | machinetalk/soma_bridge.py:447-454 | 2026-10-22T14:38Z | ImplementationNode properties: id, session_id, slot_id, function_name, implementation_text, language, file_path, model_id, status | C2 |
| E-016 | flintx | source | machinetalk/soma_bridge.py:459-463 | 2026-10-22T14:38Z | SmokeTestNode properties: id, session_id, implementation_id, status, stdout, stderr, return_code | C2 |
