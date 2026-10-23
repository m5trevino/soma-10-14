# Discovery Notes — Myelinator

## Target lock
- TARGET: myelinator
- SLUG: myelinator
- RUN ID: 20261022T143348Z-fe5514
- BASE DIR: /home/flintx/soma-10-14
- HOST: flintx (MX Linux)
- STARTED: 2026-10-22T14:33:48Z
- SCOPE: Forensic analysis of `soma/myelinator_olc.py` — the active OLC optimizer that hardens FunctionSlots with invariant rules, generates PINs, and writes OptimizedSlot nodes to the SOMA graph.
- EXCLUDED: all other dendritic modules (classifier, receptor, drafter, scout, axon, falcon, spark, integrator, etc.), SomaBridge, machinetalk engine, run_pipeline internals, TurnKey SDK.

## Inventory summary
- Primary root: `soma/myelinator_olc.py` — 309 lines, mtime 2026-10-17T18:40:17Z (confirmed via `ls -la`: 12941 bytes, last modified Oct 17 18:40).
- Duplicate root (soma-grok): `soma-grok/soma/myelinator_olc.py` — 309 lines, mtime 2026-10-21T11:35, same byte size (12941). Content identical.
- Repository: not a git-tracked file (git log returns nothing for this path).
- Total external consumers (live `soma/`): 8 files import or reference myelinator symbols.

## Entry points

| Path | Host | Role | Entrypoint? | Lines | Mtime | Evidence |
|------|------|------|-------------|-------|-------|----------|
| `soma/myelinator_olc.py` | flintx | Primary source | class `MyelinatorOptimizer` (line 27) | 309 | 2026-10-17T18:40Z | [E-001] |
| `soma-grok/soma/myelinator_olc.py` | flintx | Duplicate (bak/sync) | class `MyelinatorOptimizer` | 309 | 2026-10-21T11:35 | [E-002] |

Primary entry points (methods on `MyelinatorOptimizer`):
- `__init__(soma, llm_client, _)` — line 36
- `run(session_id)` — line 48
- `harden_slot(slot_id, session_id)` — line 143
- `apply_check(slot_id, checker)` — line 244
- `_generate_pin()` — line 39 (staticmethod)
- `_hash_pin(pin)` — line 43 (staticmethod)
- `_write_manifest(session_id, pin_map)` — line 141
- `_call_match_llm(slots, invariants)` — line 168

## Runtime state
- **Not running as a standalone process.** No `ps` or `ss` probe was performed (skill does not request process-level probes for myelinator).
- **Invoked as a pipeline stage.** `soma/run_pipeline.py:162` constructs `MyelinatorOptimizer(self._soma, self._llm, None)` and calls `myel.run(self._session_id)`.
- **Invoked in standalone runners:** `soma/run_new_session.py:142`, `soma/run_tb009.py:99`, `soma/run_new_session_fix.py:96`.
- **Registered in walk.py:** `soma/walk.py:52` — `("myelinator", MyelinatorOptimizer)` in the stage list.
- **Registered in LLM SDK:** `soma/pipeline/llm_sdk.py:29` — `"myelinator": "olc"` in `_STAGE_MAP`.
- **Registered in machinetalk client:** `soma/machinetalk/client.py:32` — `"myelinator": "olc"` in `_STAGE_MAP`.
- **Registered in SomaBridge:** `soma/machinetalk/soma_bridge.py:19` — doc references `olc → Myelinator (OptimizedSlot + SessionManifestNode)`.

## Data stores
- **Soma graph (in-memory):** `soma/store.py` line 26 — `class Soma` provides `create_node`, `delete_node`, `query_by_type`, `create_edge`, `get_edges`, `get_node`.
  - myelinator reads: `query_by_type("FunctionSlot")`, `query_by_type("InvariantQueryNode")`, `get_node(slot_id)`, `get_edges(slot_id)`.
  - myelinator writes: `create_node("OptimizedSlot")` (line 258), `create_node("SessionManifestNode")` (line 157), `create_edge(opt_id, "LINKED_TO", slot_id)` (line 270), `create_edge(inv.id, "GOVERNS", slot_id)` (line 184).
  - myelinator deletes: `delete_node(opt_id)` before rewriting (line 241), `delete_node(manifest_id)` before rewriting (line 155).
- **No external database or file store accessed by myelinator.**

## Configuration and invariants
- **PIN generation:** `secrets.randbelow(10000)` → 4-digit string, zero-padded. Cryptographically secure. [E-003]
- **PIN hashing:** `hashlib.sha256(pin.encode("utf-8")).hexdigest()` — plain SHA-256, no salt. [E-004]
- **Hard gates (from docstring):**
  1. Must not generate code implementations
  2. Only writes OptimizedSlot nodes + GOVERNS edges + LINKED_TO edges
  3. Cleartext PIN must never be written to OptimizedSlot properties
  4. All SOMA edge modifications go through formal tool-calls
- **Gate 4 conflict:** The `create_soma_edge` tool call path (lines 100-107) delegates to `ToolRegistry.call("create_soma_edge", args)`, but `ToolRegistry.call()` at `soma/pipeline/drafter_dendrite.py:189` returns `{"ok": False, "error": "Tool {name} not implemented"}`. This means the GOVERNS edges from LLM tool-calling **never actually execute** — the `governs_count` remains at zero from that path. The GOVERNS edges that DO get created come from the deterministic text overlap path (lines 173-184), which calls `self._soma.create_edge()` directly — bypassing the ToolRegistry.
- **PIN stored as cleartext in `pin_map` dict** (line 121, 206) — passed to `_write_manifest` as JSON in `manifest_payload`. The hard gate says cleartext PIN must never be written to OptimizedSlot properties. The pin_hash IS written to OptimizedSlot properties (line 264). The cleartext PIN is only stored in the local `pin_map` dict and the `SessionManifestNode.manifest_payload`. The SessionManifestNode does store cleartext PINs as JSON.

## Cross-component edges

| Direction | Mechanism | Payload | Evidence |
|-----------|-----------|---------|----------|
| → Soma (store) | method calls | node/edge CRUD | [E-005] |
| → TurnKeyClient (LLM) | `self._llm.call("myelinator", messages)` | prompt with slot + invariant list for matching | [E-006] |
| → ToolRegistry | `self._tools.call("create_soma_edge", args)` | JSON args with source_id, relationship, target_id | [E-007] |
| ← FunctionSlot (from Soma) | `query_by_type("FunctionSlot")` | nodes with session_id, mandate, code_block, name, file_path, terminal_id | [E-008] |
| ← InvariantQueryNode (from Soma) | `query_by_type("InvariantQueryNode")` | nodes with session_id, invariant_text | [E-009] |
| → SessionManifestNode (to Soma) | `create_node("SessionManifestNode")` | session_id, manifest_payload (JSON of pin_map) | [E-010] |
| → OptimizedSlot (to Soma) | `create_node("OptimizedSlot")` | session_id, mandate, terminal_id, status, pin_hash, parent_slot_id, invariant_count, laws | [E-011] |

## Instructions and recency
- `soma/myelinator_olc.py` — 309 lines, mtime 2026-10-17T18:40Z. Contains block comments with TB-OLC-001 through TB-OLC-006, TB-FIN-005, TB-FIN-010.
- `soma-grok/soma/myelinator_olc.py` — same content, newer mtime 2026-10-21T11:35Z (likely a sync/duplicate).
- No target-local instructions, AGENTS.md, or README for myelinator specifically.

## Conflicts

CONFLICT C-01
  claim A: "All SOMA edge modifications go through formal tool-calls" (myelinator_olc.py:9)
  claim B: `self._soma.create_edge(inv.id, "GOVERNS", slot_id)` called directly at line 184, bypassing ToolRegistry
  resolution: both-exist
  basis: source code inspection of harden_slot() at lines 173-184 vs _call_match_llm tool path at lines 100-107
  impact: The hard gate claims edges go through tool-calls, but deterministic GOVERNS linking bypasses ToolRegistry entirely. The LLM tool-call path exists but ToolRegistry.call() returns ok=False for all tools.

CONFLICT C-02
  claim A: "Cleartext PIN must never be written to OptimizedSlot properties" (myelinator_olc.py:8)
  claim B: `_write_manifest()` writes a `SessionManifestNode` with `manifest_payload: json.dumps(pin_map)` containing cleartext PINs (line 158)
  resolution: both-exist (clarification — gate says OptimizedSlot properties, SessionManifestNode is a separate node type)
  basis: line 264 writes pin_hash (not cleartext) to OptimizedSlot; line 158 writes cleartext PINs to SessionManifestNode
  impact: Gate is partially satisfied — OptimizedSlot properties contain only the hash, but cleartext PINs are stored in SessionManifestNode

## Unknowns and boundary gaps

U-01: ToolRegistry `create_soma_edge` implementation is never resolved. The stub returns `ok=False` for all tool names. It is unclear whether this is intentional (LLM matching is a soft path) or a missing implementation.
U-02: The `session_id` parameter is passed to `run()` but never used for session-scoped cleanup or pruning of old nodes before writing. Each `run()` call creates new OptimizedSlot and SessionManifestNode IDs (`opt-{slot_id}`, `manifest-{session_id}`), deleting and recreating them. This could lead to node accumulation if multiple run() calls occur per session.
U-03: PIN security: SHA-256 without salt. If the same PIN is used across sessions or the pin_map is compromised, rainbow-table attacks are feasible. It is unknown whether the invariants or security team have raised this.

## Evidence index

| ID | Host | Kind | Locator | Captured At | Proves | Confidence |
|----|------|------|---------|-------------|--------|------------|
| E-001 | flintx | source | `soma/myelinator_olc.py` | 2026-10-22T14:33Z | Primary file exists, 309 lines, class definition at line 27 | C1 |
| E-002 | flintx | source | `soma-grok/soma/myelinator_olc.py` | 2026-10-22T14:33Z | Duplicate exists, identical size, newer mtime | C1 |
| E-003 | flintx | source | `soma/myelinator_olc.py:39-40` | 2026-10-22T14:33Z | PIN generation via `secrets.randbelow(10000)` | C1 |
| E-004 | flintx | source | `soma/myelinator_olc.py:43-44` | 2026-10-22T14:33Z | PIN hashing via `hashlib.sha256` | C1 |
| E-005 | flintx | source | `soma/store.py:75-128` | 2026-10-22T14:33Z | Soma CRUD methods myelinator depends on | C1 |
| E-006 | flintx | source | `soma/myelinator_olc.py:194-196`, `soma/pipeline/llm_sdk.py:29` | 2026-10-22T14:33Z | LLM call path with "myelinator" stage mapping to "olc" | C1 |
| E-007 | flintx | source | `soma/pipeline/drafter_dendrite.py:178-189` | 2026-10-22T14:33Z | ToolRegistry stub — all tools return ok=False | C1 |
| E-008 | flintx | source | `soma/myelinator_olc.py:59-64` | 2026-10-22T14:33Z | FunctionSlot query pattern (session_id filter) | C1 |
| E-009 | flintx | source | `soma/myelinator_olc.py:65-68` | 2026-10-22T14:33Z | InvariantQueryNode query pattern (session_id filter) | C1 |
| E-010 | flintx | source | `soma/myelinator_olc.py:154-161` | 2026-10-22T14:33Z | SessionManifestNode creation with JSON pin_map | C1 |
| E-011 | flintx | source | `soma/myelinator_olc.py:257-270` | 2026-10-22T14:33Z | OptimizedSlot creation with properties and LINKED_TO edge | C1 |
| E-012 | flintx | source | `soma/run_pipeline.py:162-163` | 2026-10-22T14:33Z | Pipeline stage 8 instantiation and execution | C1 |
| E-013 | flintx | source | `soma/walk.py:52` | 2026-10-22T14:33Z | Stage registration in walk.py | C1 |
| E-014 | flintx | source | `soma/test_tb_fix_010.py` | 2026-10-22T14:33Z | Unit tests for apply_check — 5 test functions | C1 |
| E-015 | flintx | source | `soma/myelinator_olc.py:3-9` | 2026-10-22T14:33Z | Hard gate declarations in module docstring | C1 |
| E-016 | flintx | source | `soma/myelinator_olc.py:184` | 2026-10-22T14:33Z | Direct create_edge call bypassing ToolRegistry | C1 |

## Report plan
- Mandate: one sentence from docstring + analysis
- Current State: file exists, 309 lines, live in soma/, duplicate in soma-grok/, pipeline stage 8
- Key Paths: primary file, run_pipeline integration, walk.py registration, test file
- Architecture: context diagram (myelinator at center, inputs from Soma+LLM, outputs to Soma), data flow from run() through harden_slot to Soma writes
- Core Logic: run() → query → LLM match → harden_slot (for each slot) → manifest write. Detail the text-overlap matching algorithm. Detail PIN generation and hashing.
- Configuration: PIN spec, hash spec, hard gates, ToolRegistry gap
- Dependencies: Soma, ToolRegistry, TurnKeyClient via LLM, pipeline orchestration
- Known Gaps: ToolRegistry stub, PIN security (no salt), node accumulation risk
