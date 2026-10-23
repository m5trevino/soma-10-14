# FunctionSlots — Forensic Deep Dive

TARGET: function-slots | RUN: 20261022T114857Z-ee5565 | DATE: 2026-10-22T11:48Z | HOSTS EXAMINED: flintx (local)
CONFIDENCE SUMMARY: High for core logic, medium for runtime state (no live session data probed)
SCOPE: FunctionSlot graph node type — creation, consumption, and verification across the Dendritic pipeline
EXCLUDED: soma, machinetalk, pipeline, turn-key, chat-log-database, all other node types

---

## Mandate

FunctionSlots are graph node type `"FunctionSlot"` created by AxonHillock to represent one top-level function or class extracted from a generated code file; each slot is traced to its parent FileNode via a `SLICED_FROM` edge, optionally linked to DirectiveNode/ConstraintNode/TaskNode evidence via `TRACES_TO`, optionally hardened into OptimizedSlots by Myelinator, and optionally verified by SaltatoryGate.

## Current State

FunctionSlots are a **node type**, not a standalone directory. They exist exclusively as entries in the Soma in-memory JSON graph store (`soma/store.py`), created and consumed by four modules across two paths: the direct `soma/axon_hillock_oc.py` pipeline path and the `soma/machinetalk/soma_bridge.py` pipeline-translation path. Both paths create `FunctionSlot` nodes at runtime; the former is the primary production slicer, the latter is the bridge adapter.

| Aspect | Status |
|---|---|
| Live process running | Not running (no `axon_hillock` or `soma_bridge` process detected) |
| Entry points exist | Confirmed at `soma/axon_hillock_oc.py` and `soma/machinetalk/soma_bridge.py` |
| Graph store | `soma/store.py` — in-memory dict with JSON persistence to a configured path |
| Workspace | `/workspace/artifacts/soma-grok/workspaces/{sanitized_session_id}/` (via `soma/workspace.py`) |
| Node type enum | No schema enforcement — any string type accepted by `Soma.create_node()` |
| Dendrite copies | No duplicate FunctionSlot dendrite modules exist (unlike classifier/drafter) |

## Key Paths and Entry Points

| Path | Host | Role | Entry point? | Lines | Mtime | Evidence |
|---|---|---|---|---:|---|---|
| `soma/axon_hillock_oc.py` | flintx | Primary FunctionSlot slicer (AxonHillock OC) | `AxonHillockSlicer.run()` | ~350 | during run | [E-001] |
| `soma/store.py` | flintx | Soma graph store (all node types) | `Soma.create_node()` | ~135 | during run | [E-002] |
| `soma/myelinator_olc.py` | flintx | FunctionSlot hardener (Myelinator OLC) | `MyelinatorOptimizer.run()` | ~270 | during run | [E-003] |
| `soma/pipeline/saltatory_gate.py` | flintx | FunctionSlot verification gate | `SaltatoryGate.run()` | ~193 | during run | [E-004] |
| `soma/pipeline/code_publisher.py` | flintx | Verified FunctionSlot code publisher | `CodePublisher.run()` | ~184 | during run | [E-005] |
| `soma/machinetalk/soma_bridge.py` | flintx | Pipeline translation bridge (OC stage) | `SomaBridge.write_oc()` | ~537 | during run | [E-006] |
| `soma/workspace.py` | flintx | Shared workspace path for Drafter/AxonHillock | `workspace_for()` | ~20 | during run | [E-007] |

## Architecture and Data Flow

```
┌─────────────────────────────────────────────────────────┐
│                        Soma Graph Store                  │
│  ┌──────────┐  ┌──────────┐  ┌───────────┐  ┌─────────┐ │
│  │FileNode  │  │FunctionSlot│ │OptimizedSlot│ │Verified │ │
│  │          │──SLICED_FROM→│ │           │  │  Node    │ │
│  │          │←──TRACES_TO──│ │LINKED_TO→ │──VERIFIED→ │ │
│  │          │              │ │GOVERNS←── │  │Failure  │ │
│  │          │              │ │           │  │  Node    │ │
│  └──────────┘  └──────────┘  └───────────┘  └─────────┘ │
└─────────────────────────────────────────────────────────┘
         ▲                   ▲              ▲              ▲
         │                   │              │              │
    AxonHillock        Myelinator      SaltatoryGate   CodePublisher
    (create slots)    (harden to       (verify by      (publish
                      OptimizedSlot)    test execution)  verified code)
```

### Data flow sequence

1. `AxonHillockSlicer.run(session_id)` scans workspace files → calls `process_file()` → for each top-level def, calls `create_node("FunctionSlot", {...})` → creates `SLICED_FROM` edge to parent FileNode [E-010]
2. `AxonHillockSlicer.link_evidence_to_slots(session_id)` matches DirectiveNode/ConstraintNode/TaskNode text to slot name/file basename → creates `TRACES_TO` edges [E-011]
3. `MyelinatorOptimizer.run(session_id)` queries FunctionSlots → calls `harden_slot()` → creates `OptimizedSlot` + `GOVERNS` + `LINKED_TO` edges [E-012]
4. `SaltatoryGate.run(session_id)` queries FunctionSlots → runs pytest → creates `VerifiedNode` or `FailureNode` + `VERIFIED` edge [E-013]
5. `CodePublisher.run(session_id)` queries VerifiedNodes → follows VERIFIED→source→FunctionSlot → reads `code_block` → writes to disk [E-014]

## Core Logic

### FunctionSlot creation — AxonHillock (`soma/axon_hillock_oc.py`)

Three distinct `create_node("FunctionSlot", ...)` call sites:

**Site 1 — `_slice()` (legacy/unused in production)** — `soma/axon_hillock_oc.py:231-245`

- Uses a naive regex `^\s*(async\s+)?(def\s+(\w+)|class\s+(\w+))`
- Slot ID format: `slot-{session_id}-{ref_id[-6:]}-{i}`
- Creates fallback monolith slot when no top-level defs found
- Hard-coded `inputs=["data"]`, `outputs=["result"]`
- Sets `status="draft"`, `pin_hash="pending"`

**Site 2 — `process_file()` (production slicer)** — `soma/axon_hillock_oc.py:298-315`

- Uses per-language patterns: `_PYTHON_PATTERN`, `_SHELL_PATTERN`, `_JS_PATTERN` [E-015]
- Slot ID format: `slot-{session_id}-{file_hash}-{i}` where file_hash = MD5 of rel_path[:8]
- Language detection from file extension: `py`→python, `js/ts`→javascript, `sh`→shell [E-016]
- No fallback monolith slot when no definitions found (returns `[]`)
- Properties: `id`, `session_id`, `parent_file_node_id`, `file_path`, `name`, `mandate`, `terminal_id`, `status="draft"`, `pin_hash="pending"`, `code_block`, `inputs=[]`, `outputs=[]`, `evidence_ids=[]`
- Creates `SLICED_FROM` edge to parent FileNode

**Site 3 — `soma_bridge.py write_oc()`** — `soma/machinetalk/soma_bridge.py:375-383`

- Slices from FileNode `content_preview` property (not live files)
- Uses same naive regex as Site 1
- Slot ID format: `slot-{fn.node_id}-{name}-{i}`
- Properties differ: includes `language` property, uses `parent_file_id` key
- Deletes existing FunctionSlots for the session before recreating

### FunctionSlot properties schema

Every create call writes these properties:

| Property | Site 1 | Site 2 | Site 3 |
|---|---|---|---|
| `id` | `slot-{session}-{ref[-6]}-{i}` | `slot-{session}-{hash[:8]}-{i}` | `slot-{file_node}-{name}-{i}` |
| `session_id` | ✓ | ✓ | ✓ |
| `name` | from regex match | from regex match | from regex match |
| `mandate` | `"Implement {name} from reference monolith"` | `"Implement {name} from {path}"` | `"Implement {name} from {fp}"` |
| `status` | `"draft"` | `"draft"` | not set |
| `pin_hash` | `"pending"` | `"pending"` | not set |
| `code_block` | first match span | matched span content | preview span |
| `inputs` | `["data"]` | `[]` | not set |
| `outputs` | `["result"]` | `[]` | not set |
| `parent_file_node_id` | ✓ | ✓ | `parent_file_id` |
| `file_path` | ✓ | ✓ | ✓ |
| `evidence_ids` | not set | `[]` | not set |
| `language` | not set | not set | ✓ |

### FunctionSlot consumption

**Myelinator (`soma/myelinator_olc.py`)** — `soma/myelinator_olc.py:58-66`

- Queries `self._soma.query_by_type("FunctionSlot")` filtered by `session_id`
- For each slot, calls `harden_slot()` which:
  - Queries InvariantQueryNodes for same session
  - Performs deterministic text overlap matching on slot name/mandate/path vs invariant text
  - Creates `GOVERNS` edges from InvariantQueryNode → FunctionSlot
  - Creates `OptimizedSlot` with `id="opt-{slot_id}"`, `status="optimized"`, `pin_hash` (SHA-256 of random 4-digit PIN)
  - Creates `LINKED_TO` edge from OptimizedSlot → FunctionSlot
  - Generates cryptographically secure 4-digit PIN via `secrets.randbelow(10000)` [E-017]
  - Writes master `SessionManifestNode` with PIN mapping

**SaltatoryGate (`soma/pipeline/saltatory_gate.py`)** — `soma/pipeline/saltatory_gate.py:40-45`

- Queries `self._soma.query_by_type("FunctionSlot")` filtered by `session_id`
- For each slot, runs pytest on workspace test files
- Creates `VerifiedNode` (id: `verified-{slot_id}`) + `VERIFIED` edge on pass
- Creates `FailureNode` (id: `failure-{slot_id}`) + `VERIFIED` edge on failure

**CodePublisher (`soma/pipeline/code_publisher.py`)** — `soma/pipeline/code_publisher.py:55-85`

- Queries VerifiedNodes, NOT FunctionSlots directly
- Follows VERIFIED edge back to source slot_id
- Skips if `failure-{slot_id}` node exists
- Reads `code_block` from FunctionSlot
- Resolves file path via `SLICED_FROM` edge to FileNode
- Writes code to disk at resolved path

### Nonce / pin_hash analysis

The acceptance criteria reference "Nonce echoed" as a hard gate. In the codebase:

- `pin_hash` is a property on FunctionSlot nodes, always set to `"pending"` at creation time [E-018]
- Myelinator replaces this with an actual SHA-256 hash of a cryptographically generated 4-digit PIN on the OptimizedSlot only — FunctionSlot `pin_hash` remains `"pending"` after hardening
- The nonce `97add545-3ec3-475e-b10b-aeb6507125a1` is a **slice execution nonce** required by this forensic task to prove fresh context; it is not stored in or echoed by any pipeline module
- No module generates, stores, or validates a UUID-format nonce

## Configuration and Invariants

| Key / rule | Source | Default | Enforced in code? |
|---|---|---|---|
| Node type validation | `soma/store.py:75` | None — accepts any string type | No schema enforcement |
| SLICED_FROM edge to FileNode | `soma/axon_hillock_oc.py:313` | N/A | Yes, always created |
| TRACES_TO edge idempotency | `soma/axon_hillock_oc.py:344-349` | N/A | Yes, checks for existing edge before creating |
| Pre-run FunctionSlot cleanup | `soma/axon_hillock_oc.py:123-127` | N/A | Yes, deletes existing FunctionSlots for session before recreating |
| OptimizedSlot idempotency | `soma/myelinator_olc.py:253-254` | N/A | Yes, deletes existing `opt-{slot_id}` before recreating |
| GOVERNS edge dedup | `soma/myelinator_olc.py:240-242` | N/A | Yes, tracks `existing_governs` set |
| Cleartext PIN never on OptimizedSlot | `soma/myelinator_olc.py:9` | N/A | Partial — PIN stored in `pin_map` dict returned by `run()`, not in node properties, but `pin_map` is exposed to caller |
| Batch mode | `soma/store.py:86-92` | Off | Yes, `_persist()` deferred until `commit_batch()` |

## Dependencies and Cross-Component Connections

| Direction | Counterpart | Mechanism | Payload | Evidence |
|---|---|---|---|---|
| AxonHillock → Soma | All node types | `create_node()` | FunctionSlot properties dict | [E-010] |
| AxonHillock → workspace | Filesystem | `workspace_for()` → `rglob()` | Source code files | [E-007], [E-010] |
| AxonHillock → Store | Edges | `create_edge()` | SLICED_FROM, TRACES_TO | [E-010], [E-011] |
| Myelinator → Soma | FunctionSlot, InvariantQueryNode | `query_by_type()` | Slot list, invariant list | [E-012] |
| Myelinator → Soma | Edges | `create_edge()` | GOVERNS, LINKED_TO | [E-012] |
| Myelinator → LLM | External | `_llm.call("myelinator", messages)` | Match prompt, tool calls | [E-019] |
| SaltatoryGate → Soma | FunctionSlot | `query_by_type()` | Slot list per session | [E-013] |
| SaltatoryGate → subprocess | pytest | `subprocess.run()` | Test execution | [E-020] |
| CodePublisher → Soma | VerifiedNode, FunctionSlot, FileNode | `query_by_type()`, `get_node()`, `get_edges()` | Code block, file path | [E-014] |
| CodePublisher → workspace | Filesystem | `Path.write_text()` | Published code | [E-014] |
| soma_bridge → Soma | FunctionSlot | `create_node()`, `delete_node()` | Sliced slots from FileNode previews | [E-006] |
| soma_bridge → Soma | OptimizedSlot, SessionManifestNode | `create_node()` | Hardened slots and PIN map | [E-006] |
| soma_bridge → Soma | VerifiedNode, FailureNode, ImplementationNode | `create_node()` | Terminal output and smoke test results | [E-006] |

### Duplicate node type definitions

No duplicate FunctionSlot type definitions exist (unlike classifier/integrator/drafter/retrograde dendrites which have both `soma/` and `soma/pipeline/` copies). FunctionSlots are only created through the four modules listed above, all of which share the same `soma/store.py`.

### Store.py — the single authority

`soma/store.py:create_node()` at line 75 creates nodes with:
```python
node_id = properties.get("id", uuid.uuid4().hex)
```
No type validation. Any string can be a node type. FunctionSlot is one of many types.

## Known Gaps and Uncertainties

### G-01: No schema enforcement for FunctionSlot properties
- **Unknown:** Whether missing or extra properties cause downstream failures
- **Why it matters:** `soma_bridge.py` reads `parent_file_id` while `axon_hillock_oc.py` writes `parent_file_node_id` — two different property keys for the same concept
- **Evidence to close:** Run `test_tb_fix_002.py` and `test_tb_fix_010.py` to verify property key sensitivity

### G-02: soma_bridge.py and axon_hillock_oc.py create FunctionSlots with different schemas
- **Unknown:** Which path is actually used in production vs which is legacy/dead
- **Why it matters:** `write_oc()` in soma_bridge uses `parent_file_id` key, no `name` property in slot (reads from FileNode preview), different ID format, no `pin_hash` field
- **Evidence to close:** Check pipeline orchestration to see which creates FunctionSlots at runtime

### G-03: SaltatoryGate workspace path mismatch
- **Unknown:** `_get_workspace_path()` uses `Path.home() / "soma" / "chats" / safe_id / "workspace"` while `workspace_for()` uses `/workspace/artifacts/soma-grok/workspaces`
- **Why it matters:** AxonHillock writes files to one location, SaltatoryGate reads tests from another — they may never find the same workspace
- **Evidence to close:** Run a full pipeline session and trace the actual workspace path used

### G-04: CodePublisher skips FunctionSlots without VerifiedNodes
- **Unknown:** Whether there is a code path that publishes unverified slots
- **Why it matters:** Only VerifiedNodes trigger publishing; FunctionSlots that never reach the gate are silently dropped
- **Evidence to close:** Trace the pipeline orchestration from `run_pipeline.py`

### G-05: Pin hash lifecycle is broken on FunctionSlot nodes
- **Unknown:** Whether the `pin_hash="pending"` on FunctionSlot nodes is ever updated after Myelinator creates OptimizedSlots
- **Why it matters:** The `pin_hash` property on FunctionSlot is set to `"pending"` and never changed; the actual hash lives only on the OptimizedSlot
- **Evidence to close:** Inspect `harden_slot()` return value and post-run node state

## Evidence Log

| ID | Host | Kind | Locator | Captured at | Proves | Confidence |
|---|---|---|---|---|---|---|
| E-001 | flintx | Source | `soma/axon_hillock_oc.py` | 2026-10-22T11:48Z | Primary slicer entry point | C2 |
| E-002 | flintx | Source | `soma/store.py:75` | 2026-10-22T11:48Z | Node creation with no type validation | C2 |
| E-003 | flintx | Source | `soma/myelinator_olc.py:45` | 2026-10-22T11:48Z | OLC entry point, PIN generation via secrets | C2 |
| E-004 | flintx | Source | `soma/pipeline/saltatory_gate.py:29` | 2026-10-22T11:48Z | Verification gate entry point | C2 |
| E-005 | flintx | Source | `soma/pipeline/code_publisher.py:28` | 2026-10-22T11:48Z | Publisher entry point, skips on FailureNode | C2 |
| E-006 | flintx | Source | `soma/machinetalk/soma_bridge.py:350` | 2026-10-22T11:48Z | Bridge OC stage creates FunctionSlots from FileNode previews | C2 |
| E-007 | flintx | Source | `soma/workspace.py:14` | 2026-10-22T11:48Z | Workspace path: `/workspace/artifacts/soma-grok/workspaces/` | C2 |
| E-008 | flintx | Source | `soma/axon_hillock_oc.py:18-28` | 2026-10-22T11:48Z | Per-language regex patterns (Python, Shell, JavaScript) | C2 |
| E-009 | flintx | Source | `soma/axon_hillock_oc.py:45-54` | 2026-10-22T11:48Z | Language detection from file extension | C2 |
| E-010 | flintx | Source | `soma/axon_hillock_oc.py:298-315` | 2026-10-22T11:48Z | Production FunctionSlot creation in process_file() | C2 |
| E-011 | flintx | Source | `soma/axon_hillock_oc.py:319-355` | 2026-10-22T11:48Z | Evidence linking via TRACES_TO edges | C2 |
| E-012 | flintx | Source | `soma/myelinator_olc.py:201-269` | 2026-10-22T11:48Z | Harden slot: text overlap matching + OptimizedSlot creation | C2 |
| E-013 | flintx | Source | `soma/pipeline/saltatory_gate.py:40-80` | 2026-10-22T11:48Z | Verification: pytest execution + Verified/Failure Node creation | C2 |
| E-014 | flintx | Source | `soma/pipeline/code_publisher.py:55-85` | 2026-10-22T11:48Z | Publisher: VerifiedNode→FunctionSlot→FileNode→disk | C2 |
| E-015 | flintx | Source | `soma/axon_hillock_oc.py:18-28` | 2026-10-22T11:48Z | Language-specific top-level def patterns | C2 |
| E-016 | flintx | Source | `soma/axon_hillock_oc.py:38-45` | 2026-10-22T11:48Z | Slot span extraction with start/end indices | C2 |
| E-017 | flintx | Source | `soma/myelinator_olc.py:37-42` | 2026-10-22T11:48Z | Cryptographic PIN generation + SHA-256 hashing | C2 |
| E-018 | flintx | Source | `soma/axon_hillock_oc.py:239,260,307` | 2026-10-22T11:48Z | pin_hash="pending" set at all three creation sites | C2 |
| E-019 | flintx | Source | `soma/myelinator_olc.py:158-177` | 2026-10-22T11:48Z | LLM match prompt with tool-calling for GOVERNS edges | C2 |
| E-020 | flintx | Source | `soma/pipeline/saltatory_gate.py:116-130` | 2026-10-22T11:48Z | Subprocess pytest execution with 60s timeout | C2 |
| E-021 | flintx | Source | `soma/store.py:12-23` | 2026-10-22T11:48Z | Node and Edge dataclass definitions | C2 |
| E-022 | flintx | Source | `soma/axon_hillock_oc.py:123-127` | 2026-10-22T11:48Z | Pre-run cleanup deletes existing FunctionSlots for session | C2 |
| E-023 | flintx | Source | `soma/machinetalk/soma_bridge.py:355-383` | 2026-10-22T11:48Z | Bridge write_oc: deletes all FunctionSlots for session then recreates | C2 |
| E-024 | flintx | Source | `soma/store.py:97-103` | 2026-10-22T11:48Z | delete_node removes node and all incident edges | C2 |
