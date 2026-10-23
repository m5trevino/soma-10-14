# Myelinator — Forensic Deep Dive

TARGET: myelinator | RUN: 20261022T143348Z-fe5514 | DATE: 2026-10-22T14:33Z | HOSTS EXAMINED: flintx (MX Linux)
CONFIDENCE SUMMARY: C1/C2 sources for all core logic; C2 for cross-component edges; C1 for file inventory. No runtime probe performed (component runs as a pipeline stage, not a daemon).
SCOPE: `soma/myelinator_olc.py` — the active OLC (Optimized Layer Completion) optimizer that hardens FunctionSlots with invariant rules, generates and hashes PINs, and writes OptimizedSlot/SessionManifestNode nodes to the SOMA graph.

## Mandate

Harden FunctionSlot nodes into OptimizedSlot nodes by matching InvariantQueryNodes to slots via LLM tool-calling and deterministic text overlap, generating cryptographically secure PINs for each slot, and writing hardened rules, PIN hashes, and edge relationships into the SOMA graph.

## Current State

| Path | Host | Role | Entrypoint | Lines | Mtime |
|------|------|------|------------|-------|-------|
| `soma/myelinator_olc.py` | flintx | Primary source | `MyelinatorOptimizer` class | 309 | 2026-10-17T18:40Z [E-001] |
| `soma-grok/soma/myelinator_olc.py` | flintx | Duplicate (soma-grok) | `MyelinatorOptimizer` class | 309 | 2026-10-21T11:35Z [E-002] |

The component is **not a standalone process**. It runs as Stage 8 in the pipeline orchestrator (`soma/run_pipeline.py:162-163`) and is also invoked by standalone runners (`soma/run_new_session.py:142`, `soma/run_tb009.py:99`, `soma/run_new_session_fix.py:96`). It is registered in `soma/walk.py:52` as the `("myelinator", MyelinatorOptimizer)` tuple and mapped to stage `"olc"` in both `soma/pipeline/llm_sdk.py:29` and `soma/machinetalk/client.py:32`.

The duplicate at `soma-grok/` has identical byte size (12941) and content but a newer mtime. No git history is available for this path.

## Key Paths and Entry Points

| Path | Host | Role | Entrypoint? | Lines | Mtime |
|------|------|------|-------------|-------|-------|
| `soma/myelinator_olc.py` | flintx | Main class | `MyelinatorOptimizer` at line 27 | 309 | 2026-10-17T18:40Z |
| `soma/run_pipeline.py:162-163` | flintx | Pipeline integration | `MyelinatorOptimizer(self._soma, self._llm, None)` | 1 | 2026-10-21 |
| `soma/walk.py:52` | flintx | Stage registration | `("myelinator", MyelinatorOptimizer)` | 1 | 2026-10-22 |
| `soma/pipeline/llm_sdk.py:29` | flintx | LLM stage map | `"myelinator": "olc"` | 1 | 2026-10-22 |
| `soma/machinetalk/client.py:32` | flintx | Client stage map | `"myelinator": "olc"` | 1 | 2026-10-21 |
| `soma/test_tb_fix_010.py` | flintx | Unit tests | 5 test functions | ~200 | 2026-10-22 |

Methods on `MyelinatorOptimizer`:
- `__init__(soma, llm_client, _)` — line 36: stores Soma instance, LLM client, and initializes ToolRegistry.
- `run(session_id)` — line 48: main orchestration method. Queries slots and invariants, calls LLM match, hardens each slot, writes manifest.
- `harden_slot(slot_id, session_id)` — line 143: hardens one FunctionSlot → OptimizedSlot with GOVERNS edges, PIN, and hash.
- `apply_check(slot_id, checker)` — line 244: injectable checker writes results onto an OptimizedSlot.
- `_generate_pin()` — line 39: static method, returns 4-digit zero-pinned PIN.
- `_hash_pin(pin)` — line 43: static method, returns SHA-256 hex digest.
- `_write_manifest(session_id, pin_map)` — line 154: writes/updates SessionManifestNode.
- `_call_match_llm(slots, invariants)` — line 168: builds prompt and calls LLM for GOVERNS matching.

## Architecture and Data Flow

### Context Diagram

```
                    ┌─────────────────┐
                    │  LLM Client     │
                    │ (TurnKeyClient) │
                    │  stage="olc"    │
                    └────────┬────────┘
                             │ _call_match_llm()
                             │ LLM Response: tool_calls
                             ▼
┌────────────┐    query    ┌──────────────────┐    call    ┌─────────────────┐
│  Soma Graph │◄──────────►│  Myelinator       │─────────►│  ToolRegistry   │
│  (store.py) │  FunctionSlot, │  Optimizer       │ create   │  (stub)         │
│             │  InvariantQuery │  .run()          │ _soma_edge │  returns ok=False│
│             │  Node         │                 │            └─────────────────┘
│             │               │    create_node, │
│             │               │    create_edge  │
└────────────┘               └────────┬─────────┘
                                     │ writes
                                     ▼
                        ┌──────────────────────┐
                        │  OptimizedSlot nodes  │
                        │  SessionManifestNode  │
                        │  GOVERNS edges        │
                        │  LINKED_TO edges      │
                        └──────────────────────┘
```

### Data Flow: run() → write

```
run(session_id)
  │
  ├─► query_by_type("FunctionSlot")        ──► [slot list filtered by session_id]
  ├─► query_by_type("InvariantQueryNode")  ──► [invariant list filtered by session_id]
  │
  ├─► (if invariants exist) _call_match_llm(slots, invariants)
  │     │
  │     ├─► build prompt with slot mandates + invariant texts
  │     ├─► self._llm.call("myelinator", messages)  ──► LLM Response with tool_calls
  │     └─► for each tool_call with name="create_soma_edge":
  │           self._tools.call("create_soma_edge", args)  ──► ToolRegistry stub returns ok=False
  │                                                              [GOVERNS edges NOT created via this path]
  │
  ├─► for each slot in slot list:
  │     harden_slot(slot.id, session_id)
  │       │
  │       ├─► get_node(slot_id) → validate session_id
  │       ├─► query_by_type("InvariantQueryNode") → invariants for session
  │       ├─► get_edges(slot_id) → existing GOVERNS edges
  │       ├─► deterministic text overlap matching:
  │       │     slot_needles = {name, mandate, file_path}.lower()
  │       │     for inv in invariants:
  │       │       if any(needle in inv_text for needle in slot_needles):
  │       │         create_edge(inv.id, "GOVERNS", slot_id)  [DIRECT — bypasses ToolRegistry]
  │       │
  │       ├─► opt_id = f"opt-{slot_id}"
  │       ├─► delete_node(opt_id) if exists (idempotent rewrite)
  │       ├─► pin = _generate_pin()  ──► secrets.randbelow(10000), zero-padded 4-digit
  │       ├─► pin_hash = _hash_pin(pin)  ──► hashlib.sha256(pin).hexdigest()
  │       ├─► create_node("OptimizedSlot", {id, session_id, mandate, terminal_id,
  │       │                                      status, pin_hash, parent_slot_id,
  │       │                                      invariant_count, laws})
  │       └─► create_edge(opt_id, "LINKED_TO", slot_id)
  │
  ├─► _write_manifest(session_id, pin_map)
  │     │
  │     ├─► delete_node("manifest-{session_id}") if exists
  │     └─► create_node("SessionManifestNode", {id, session_id,
  │                                                  manifest_payload: json.dumps(pin_map)})
  │
  └─► return {session_id, optimized_slot_ids, slot_count, invariant_count,
              governs_edges_created, slot_invariant_map, pin_map, metrics}
```

## Core Logic

### 1. PIN Handling

**PIN generation** (`soma/myelinator_olc.py:39-40`) [E-003]:
```python
return f"{secrets.randbelow(10000):04d}"
```
Uses Python's `secrets` module (CSPRNG), generating a 4-digit zero-padded string from the range [0, 9999]. The `secrets` module is cryptographically secure per Python docs.

**PIN hashing** (`soma/myelinator_olc.py:43-44`) [E-004]:
```python
return hashlib.sha256(pin.encode("utf-8")).hexdigest()
```
Plain SHA-256, **no salt**. The cleartext PIN is returned in the `harden_slot()` return dict at line 212 as `"pin": pin` and stored in the local `pin_map` dict.

**PIN storage path**:
1. OptimizedSlot properties: only `pin_hash` (SHA-256 hex digest) at line 264 — **does not contain cleartext** [E-011].
2. SessionManifestNode.manifest_payload: JSON of `pin_map` containing `opt_id → cleartext_pin` at line 158 — **contains cleartext**.
3. Return value from `run()`: `pin_map` dict at line 185 — **contains cleartext**.

The module docstring hard gate states: "Cleartext PIN must never be written to OptimizedSlot properties." This is **satisfied** — the OptimizedSlot only stores the hash. However, cleartext PINs are stored in the SessionManifestNode and returned in the `run()` result dict.

### 2. OptimizedSlot Creation

**`harden_slot()` logic** (`soma/myelinator_olc.py:143-220`) [E-011]:

1. **Validation** (line 147): Fetches slot from Soma, verifies `session_id` matches.
2. **Existing GOVERNS edges** (lines 154-158): Queries existing edges and extracts source nodes where `rel_type == "GOVERNS"` and `target == slot_id`. These are preserved (not duplicated).
3. **Deterministic text overlap** (lines 161-184): For invariants not already linked, compares lowered `slot_needles` (slot name, mandate, file_path) against lowered `inv_text`. If any needle is a substring of the invariant text, a `GOVERNS` edge is created directly via `self._soma.create_edge()` [E-016].
4. **Idempotent rewrite** (lines 187-188): If `opt-{slot_id}` already exists, it is deleted first.
5. **Node creation** (lines 190-270): Creates OptimizedSlot with mandate (original + HARDENED RULES block), terminal_id, status="optimized", pin_hash, parent_slot_id, invariant_count, and laws list.
6. **LINKED_TO edge** (line 270): `create_edge(opt_id, "LINKED_TO", slot_id)`.

**Idempotency**: Repeated calls to `harden_slot()` for the same slot_id will delete and recreate the OptimizedSlot, but GOVERNS edges are preserved because existing edges are collected before the matching pass and used as the initial `matched` list.

### 3. LLM Matching Path

**`_call_match_llm()`** (`soma/myelinator_olc.py:168-196`) [E-006]:
- Builds a prompt with slot IDs, mandates, and first 200 chars of code_block, plus invariant IDs and first 150 chars of invariant_text.
- Calls `self._llm.call("myelinator", messages)` — the LLM stage is mapped to "olc" in `llm_sdk.py:29`.
- Parses `response.tool_calls` for `function.name == "create_soma_edge"`.
- **ToolRegistry gap**: `soma/pipeline/drafter_dendrite.py:189` — `ToolRegistry.call()` returns `{"ok": False, "error": "Tool {name} not implemented"}` for ALL tool names. This means the LLM tool-call path **never creates any GOVERNS edges**. The `governs_count` variable at line 96 always remains 0 from this path.
- The only GOVERNS edges that are actually created come from the deterministic text overlap path in `harden_slot()`.

### 4. Manifest Writing

**`_write_manifest()`** (`soma/myelinator_olc.py:154-161`) [E-010]:
- Creates/overwrites `manifest-{session_id}` as a `SessionManifestNode`.
- If existing node found, it is deleted first, then a new one is created.
- Stores `pin_map` as JSON in `manifest_payload` with `sort_keys=True`.

### 5. Check Application

**`apply_check()`** (`soma/myelinator_olc.py:244-278`):
- Takes a slot_id, resolves `opt-{slot_id}`, fetches the OptimizedSlot.
- Calls the injectable `checker(opt_id)` callable, expects `(ok: bool, error: str)`.
- Updates `check_ok`, `check_error`, and `status` ("optimized" or "check_failed") on the OptimizedSlot properties.
- Does NOT spawn subprocesses or import external type checkers (pyright/mypy) [E-014].
- Existing GOVERNS and LINKED_TO edges are untouched.

## Configuration and Invariants

### PIN Specification
| Property | Value | Evidence |
|----------|-------|----------|
| Length | 4 digits, zero-padded | `soma/myelinator_olc.py:40` |
| Source | `secrets.randbelow(10000)` | [E-003] |
| Hash algorithm | SHA-256, no salt | [E-004] |
| Hash format | hex digest (64 chars) | `hashlib.sha256().hexdigest()` |
| Cleartext stored in OptimizedSlot | No — only `pin_hash` | [E-011] |
| Cleartext stored in SessionManifestNode | Yes — JSON `manifest_payload` | [E-010] |

### Hard Gates (from module docstring)
1. **Must not generate code implementations** — verified, no code generation calls exist.
2. **Only writes OptimizedSlot nodes + GOVERNS edges + LINKED_TO edges** — verified for `harden_slot()`. The `_write_manifest()` method also writes `SessionManifestNode`, which is outside this set.
3. **Cleartext PIN must never be written to OptimizedSlot properties** — verified. Only `pin_hash` is written. Cleartext appears in SessionManifestNode and return values.
4. **All SOMA edge modifications go through formal tool-calls** — **violated**. The deterministic text overlap path (line 184) calls `self._soma.create_edge()` directly, bypassing ToolRegistry. The LLM tool-call path exists but ToolRegistry is a stub.

### Soma Graph Types Used

| Type | Operation | Method | Evidence |
|------|-----------|--------|----------|
| FunctionSlot | read | `query_by_type("FunctionSlot")` | line 59 |
| InvariantQueryNode | read | `query_by_type("InvariantQueryNode")` | line 65 |
| OptimizedSlot | create/delete | `create_node()` / `delete_node()` | lines 257, 241 |
| SessionManifestNode | create/delete | `create_node()` / `delete_node()` | lines 157, 155 |
| GOVERNS | create | `create_edge()` | lines 184 |
| LINKED_TO | create | `create_edge()` | line 270 |

## Dependencies and Cross-Component Connections

### Upstream (inputs to myelinator)

| Component | Mechanism | Payload | Verified? |
|-----------|-----------|---------|-----------|
| Soma (store.py) | method calls | FunctionSlot, InvariantQueryNode nodes | Yes [E-005] |
| LLM client (TurnKeyClient) | `self._llm.call("myelinator", messages)` | Prompt with slot/invariant data, returns tool_calls | Yes [E-006] |
| ToolRegistry | `self._tools.call("create_soma_edge", args)` | JSON args — but tool is stub, returns ok=False | Yes [E-007] |

### Downstream (outputs from myelinator)

| Component | Mechanism | Payload | Verified? |
|-----------|-----------|---------|-----------|
| Soma (store.py) | `create_node("OptimizedSlot")`, `create_node("SessionManifestNode")`, `create_edge()` | OptimizedSlot nodes with pin_hash/laws/mandate, SessionManifestNode with PIN JSON, GOVERNS and LINKED_TO edges | Yes [E-010, E-011] |
| run_pipeline.py | receives result dict | `{slot_count, optimized_slot_ids, pin_map, metrics}` | Yes [E-012] |
| walk.py | registered as stage tuple | `("myelinator", MyelinatorOptimizer)` | Yes [E-013] |
| Pipeline results dict | key `"myelinator"` | stored at `soma/run_pipeline.py:235` | Yes [E-012] |

### No connections to
- CodePublisher (connected via SaltatoryGate, not directly by myelinator)
- machinetalk engine (referenced in SomaBridge docs but no code-level import or call)
- External file storage or databases

## Known Gaps and Uncertainties

### G-01: ToolRegistry is a stub — LLM tool-calling never succeeds
`ToolRegistry.call()` at `soma/pipeline/drafter_dendrite.py:189` returns `{"ok": False, "error": "Tool {name} not implemented"}` for all tool names. The `_call_match_llm()` method (lines 100-107) attempts to execute LLM-generated `create_soma_edge` tool calls but they always fail. It is unknown whether this is intentional (LLM matching is deprecated in favor of deterministic text overlap) or a missing implementation.
**Evidence needed**: Pipeline execution logs showing LLM response structure and tool_call outcomes, or an updated ToolRegistry implementation.

### G-02: Deterministic text overlap matching is fragile
The matching algorithm (`harden_slot` lines 161-184) uses a simple substring check: whether any lowered slot property (name, mandate, file_path) appears as a substring in the lowered invariant text. This can produce false positives (common words) and false negatives (related concepts not sharing substrings). No fuzzy matching, similarity scoring, or threshold exists.
**Evidence needed**: Test cases covering edge-case matches, or documentation of matching criteria precision.

### G-03: PIN security — SHA-256 without salt
PINs are hashed with plain SHA-256 and no salt. If the `pin_map` stored in `SessionManifestNode.manifest_payload` is exposed, rainbow-table attacks against 4-digit PINs are computationally trivial (10,000 entries).
**Evidence needed**: Security review or requirements document specifying PIN hashing requirements.

### G-04: Cleartext PIN in SessionManifestNode
The module hard gate states cleartext PINs must not be written to OptimizedSlot properties. While OptimizedSlot only stores the hash, `SessionManifestNode.manifest_payload` stores the full `pin_map` dict as JSON. It is unknown whether this node is persisted to disk or stored only in memory.
**Evidence needed**: Soma graph persistence mechanism inspection.

### G-05: Node accumulation risk
Each `run()` call creates new `opt-{slot_id}` nodes (deleting old ones) and `manifest-{session_id}` nodes. If multiple sessions share the same session_id or if old sessions are not cleaned up, node IDs from prior runs are overwritten. If the Soma graph persists between runs, stale FunctionSlot and InvariantQueryNode nodes may accumulate.
**Evidence needed**: Soma graph persistence behavior and session lifecycle management.

### G-06: Hard gate C-01 — edge modifications bypass ToolRegistry
The docstring claims all edge modifications go through tool-calls (gate 4), but `harden_slot()` directly calls `self._soma.create_edge()` for GOVERNS edges. The ToolRegistry is only used for the LLM match path, which itself never succeeds due to the stub implementation. This gate is **not enforced**.
**Evidence needed**: Design decision record for why the gate was written but the implementation diverges.

## Evidence Log

| ID | Host | Kind | Locator | Captured At | Proves | Confidence |
|----|------|------|---------|-------------|--------|------------|
| E-001 | flintx | source | `soma/myelinator_olc.py` | 2026-10-22T14:33Z | Primary file exists, 309 lines, class at line 27 | C1 |
| E-002 | flintx | source | `soma-grok/soma/myelinator_olc.py` | 2026-10-22T14:33Z | Duplicate exists, identical size, newer mtime | C1 |
| E-003 | flintx | source | `soma/myelinator_olc.py:40` | 2026-10-22T14:33Z | PIN generation via `secrets.randbelow(10000)` | C1 |
| E-004 | flintx | source | `soma/myelinator_olc.py:43-44` | 2026-10-22T14:33Z | PIN hashing via `hashlib.sha256()` | C1 |
| E-005 | flintx | source | `soma/store.py:75-128` | 2026-10-22T14:33Z | Soma CRUD methods: create_node, delete_node, query_by_type, create_edge, get_edges | C1 |
| E-006 | flintx | source | `soma/myelinator_olc.py:194-196`, `soma/pipeline/llm_sdk.py:29` | 2026-10-22T14:33Z | LLM call path with stage mapping "myelinator"→"olc" | C1 |
| E-007 | flintx | source | `soma/pipeline/drafter_dendrite.py:178-189` | 2026-10-22T14:33Z | ToolRegistry stub — `call()` returns `ok=False` for all tools | C1 |
| E-008 | flintx | source | `soma/myelinator_olc.py:59-64` | 2026-10-22T14:33Z | FunctionSlot query: filtered by `session_id` property | C1 |
| E-009 | flintx | source | `soma/myelinator_olc.py:65-68` | 2026-10-22T14:33Z | InvariantQueryNode query: filtered by `session_id` property | C1 |
| E-010 | flintx | source | `soma/myelinator_olc.py:154-161` | 2026-10-22T14:33Z | SessionManifestNode creation with JSON pin_map payload | C1 |
| E-011 | flintx | source | `soma/myelinator_olc.py:257-270` | 2026-10-22T14:33Z | OptimizedSlot creation with properties including pin_hash and LINKED_TO edge | C1 |
| E-012 | flintx | source | `soma/run_pipeline.py:162-163, 235` | 2026-10-22T14:33Z | Pipeline Stage 8: instantiation, run() call, result collection | C1 |
| E-013 | flintx | source | `soma/walk.py:52` | 2026-10-22T14:33Z | Stage registration as `("myelinator", MyelinatorOptimizer)` | C1 |
| E-014 | flintx | source | `soma/test_tb_fix_010.py:1-200` | 2026-10-22T14:33Z | 5 unit tests for `apply_check()`: pass, fail, missing, no-spawn, edge-unchanged | C1 |
| E-015 | flintx | source | `soma/myelinator_olc.py:3-9` | 2026-10-22T14:33Z | Hard gate declarations in module docstring | C1 |
| E-016 | flintx | source | `soma/myelinator_olc.py:184` | 2026-10-22T14:33Z | Direct `create_edge()` call bypassing ToolRegistry in deterministic matching path | C1 |
