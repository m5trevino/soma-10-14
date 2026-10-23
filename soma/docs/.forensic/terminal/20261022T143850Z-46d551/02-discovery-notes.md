# Discovery Notes: terminal

## Target lock
TARGET: terminal
SLUG: terminal
RUN ID: 20261022T143850Z-46d551

## Inventory summary
- Local root: `/home/flintx/soma-10-14/soma` — 187 files at depth 3
- Entry point: `machinetalk/soma_bridge.py` (537 lines, mtime 2026-10-18T20:49:51Z)
- No `test_` files named for terminal specifically
- Test scope includes ImplementationNode at `test_run_engine_soma_only.py:199-201`
- No `workspaces/` directory exists (confirmed absent)
- Output `soma.json` contains legacy nodes only (ChatSet, ReceptorLog, TaskNode, SessionAnchor) — no terminal-era nodes

## Entry points
| Path | Lines | mtime | Role |
|---|---|---|---|
| `machinetalk/soma_bridge.py:435` | 435-466 | 2026-10-18T20:49:51Z | `write_terminal()` — main method |
| `machinetalk/soma_bridge.py:20` | 20 | 2026-10-18T20:49:51Z | Docstring mapping: `terminal → TerminalPlayer (ImplementationNode + SmokeTestNode)` |

## Runtime state
- Not probed directly (terminal is a graph-write method, not a standalone process)
- Invocation occurs inside `machinetalk/engine.py` at line 740, within the `olc` stage block
- The method is called synchronously after `write_olc()` returns, before `write_gate()`
- Evidence: `machinetalk/engine.py:739-742`
  ```
  elif stage == "olc":
      counts = self._bridge.write_olc(build, gate, rec.model, latency)
      t_counts = self._bridge.write_terminal(build, rec.model, latency)
      counts.update(t_counts)
  ```

## Data stores
- The terminal stage writes into the Soma graph via `self._soma` (a SomaGraph instance)
- Node types created: `ImplementationNode` and `SmokeTestNode`
- Node types queried: `OptimizedSlot` (upstream dependency), `ImplementationNode`, `SmokeTestNode` (by `write_gate`)
- No standalone database; the graph is persisted via `self._soma._persist()` (called in engine.py after all bridge writes)

## Configuration and invariants
- **Input**: `session_id`, `model_id` (default ""), `latency_ms` (default 0.0)
- **Source data**: `OptimizedSlot` nodes with `session_id` matching the input
  - Extracted properties: `name`, `code_block`, `language`, `file_path`
  - Source: `soma_bridge.py:438-441`
- **Gate/Invariant**: `self._soma.delete_node()` called before each `create_node()` to enforce idempotency — lines 444, 456
- **SmokeTestNode defaults**: status="PASS", stdout="", stderr="", return_code=0 (no real execution)
- **Output**: `dict[str, int]` with keys `ImplementationNode` and `SmokeTestNode` (counts per node type)

## Cross-component edges
| Direction | Mechanism | Payload | Evidence |
|---|---|---|---|
| Upstream: `OptimizedSlot` | graph query | `name`, `code_block`, `language`, `file_path` | `soma_bridge.py:438-441` |
| Upstream: `FunctionSlot` | via `OptimizedSlot` creation in `write_olc()` | `LINKED_TO` edge | `soma_bridge.py:425` |
| Downstream: `ImplementationNode` | `self._soma.create_node()` | session_id, slot_id, function_name, implementation_text, model_id, status | `soma_bridge.py:447-454` |
| Downstream: `SmokeTestNode` | `self._soma.create_node()` | implementation_id, status, stdout, stderr, return_code | `soma_bridge.py:459-463` |
| Downstream: `VerifiedNode`/`FailureNode` | via `write_gate()` calling `query_by_type("ImplementationNode")` and `query_by_type("SmokeTestNode")` | VERIFIES edge | `soma_bridge.py:470-519` |
| Caller: `machinetalk/engine.py` | method call | `write_olc()` result + `write_terminal()` result merged | `engine.py:739-743` |

## Instructions and recency
- `machinetalk/soma_bridge.py` mtime: 2026-10-18T20:49:51Z — last write to terminal logic
- `machinetalk/engine.py` mtime: 2026-10-21T19:43:00Z — last engine update (terminal invocation line 740 present)
- `docs/terminal-forensic.md` — does not yet exist (this run)
- `DROID-RESET.md` — not present in soma/ directory; historical intent only per skill rules

## Conflicts
No conflicts found. The terminal stage has a single definition in `soma_bridge.py`.

## Unknowns and boundary gaps
- **U-01**: Actual runtime execution of smoke tests — `SmokeTestNode` is created with hardcoded PASS status, stdout/stderr/return_code all defaults. No subprocess or exec call exists. Evidence needed: confirmation that no real code execution occurs, or discovery of a separate smoke-test runner.
- **U-02**: The `_soma` interface contract — what methods it provides (`get_node`, `create_node`, `query_by_type`, `delete_node`, `_persist`) are observed, but its full API and persistence backend are not examined.
- **U-03**: Whether `write_terminal` is ever called outside the `olc` stage path in `engine.py`. No grep of `write_terminal` found other callers.
- **U-04**: No test file specifically covers `write_terminal()`. The `test_run_engine_soma_only.py` excludes downstream types including `ImplementationNode` and `OptimizedSlot` (assertion at lines 197-201) but does not test the terminal method itself.
- **U-05**: The `nonce` field does not appear in any source file in the soma project. Not found in `soma_bridge.py`, `engine.py`, or any other `.py` file in the project.

## Evidence index
| ID | Host | Kind | Locator | Captured At | Proves | Confidence |
|---|---|---|---|---|---|---|
| E-001 | flintx | source | `machinetalk/soma_bridge.py:435` | 2026-10-22T14:38Z | `write_terminal()` method signature | C2 |
| E-002 | flintx | source | `machinetalk/soma_bridge.py:438-441` | 2026-10-22T14:38Z | OptimizedSlot query and property extraction | C2 |
| E-003 | flintx | source | `machinetalk/soma_bridge.py:444-454` | 2026-10-22T14:38Z | ImplementationNode creation with idempotency | C2 |
| E-004 | flintx | source | `machinetalk/soma_bridge.py:456-463` | 2026-10-22T14:38Z | SmokeTestNode creation with hardcoded PASS | C2 |
| E-005 | flintx | source | `machinetalk/soma_bridge.py:464-465` | 2026-10-22T14:38Z | Return counts dict | C2 |
| E-006 | flintx | source | `machinetalk/soma_bridge.py:20` | 2026-10-22T14:38Z | TerminalPlayer mapping in docstring | C2 |
| E-007 | flintx | source | `machinetalk/engine.py:739-742` | 2026-10-22T14:38Z | Terminal called after olc, before gate | C2 |
| E-008 | flintx | source | `machinetalk/engine.py:740` | 2026-10-22T14:38Z | `write_terminal(build, rec.model, latency)` call site | C2 |
| E-009 | flintx | source | `machinetalk/soma_bridge.py:470-477` | 2026-10-22T14:38Z | write_gate() queries ImplementationNode and SmokeTestNode | C2 |
| E-010 | flintx | source | `test_run_engine_soma_only.py:197-201` | 2026-10-22T14:38Z | Test excludes ImplementationNode and OptimizedSlot from soma-only scope | C2 |
| E-011 | flintx | source | `machinetalk/soma_bridge.py:1-24` | 2026-10-22T14:38Z | Full mapping table in module docstring | C2 |
| E-012 | flintx | source | `output/soma.json` | 2026-10-22T14:38Z | Output contains only legacy node types (no terminal-era nodes) | C2 |
| E-013 | flintx | shell | `rg -rn 'nonce' machinetalk/` | 2026-10-22T14:38Z | No nonce reference in machinetalk | C2 |
| E-014 | flintx | shell | `rg -rn 'nonce' *.py` | 2026-10-22T14:38Z | No nonce reference in soma root | C2 |
| E-015 | flintx | source | `machinetalk/soma_bridge.py:447-454` | 2026-10-22T14:38Z | ImplementationNode properties: id, session_id, slot_id, function_name, implementation_text, language, file_path, model_id, status | C2 |
| E-016 | flintx | source | `machinetalk/soma_bridge.py:459-463` | 2026-10-22T14:38Z | SmokeTestNode properties: id, session_id, implementation_id, status, stdout, stderr, return_code | C2 |

## Report plan
1. Mandate — one sentence from docstring
2. Current State — file exists, method signature, no runtime process
3. Key Paths — `soma_bridge.py:435`, `engine.py:740`
4. Architecture — ASCII context diagram showing olc→terminal→gate chain
5. Core Logic — step-by-step through write_terminal with line citations
6. Configuration — params, defaults, idempotency, SmokeTestNode defaults
7. Dependencies — OptimizedSlot (upstream), ImplementationNode/SmokeTestNode (downstream), write_gate (downstream consumer)
8. Known Gaps — U-01 through U-05
