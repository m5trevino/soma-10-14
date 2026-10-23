# AxonHillock — Forensic Deep Dive
TARGET: axon | RUN: 20261022T142522Z-29c1c2 | DATE: 2026-10-22T14:25Z | HOSTS EXAMINED: flintx (local only)
CONFIDENCE SUMMARY: C1 (entry points confirmed), C2 (source analysis), C3 (docs/notes). No remote host reachable for axon.
SCOPE: Slices reference artifacts into FunctionSlot nodes linked by SLICED_FROM edges.

## Mandate

AxonHillock walks a session's drafter workspace, detects each file's language, slices every top-level function or class via regex into a FunctionSlot node, links each slot to its parent FileNode with a SLICED_FROM edge, and traces each slot to matching Directive/Constraint/Task evidence nodes via TRACES_TO edges.

## Current State

AxonHillock is a single module, `soma/axon_hillock_oc.py` (368 lines, mtime 2026-10-18T02:59:43Z, mtime 2026-10-17T19:59:43-07:00) [E-001, E-002]. It is **not a running service** — it is instantiated and executed once per pipeline run. No git history exists for this file. The workspace directory (`soma/workspaces/`) exists but is **empty**. Pipeline log files (October 2026) cover earlier stages (DISTILLER, INTROBEAVER) and do **not** mention axon, indicating axon stage logs were not captured in those runs [E-007, E-008].

The `AxonHillockSlicer` constructor accepts three parameters (`soma`, `llm_client`, `rotator`) but all call sites pass `None` for the LLM client — the LLM path is **dead in current usage**.

## Key Paths and Entry Points

| Path | Host | Role | Entry? | Lines | Mtime | Evidence |
|---|---|---|---|---|---|---|
| `soma/axon_hillock_oc.py` | flintx | Module | ✓ | 368 | 2026-10-18T02:59Z | E-001 |
| `soma/run_pipeline.py:154` | flintx | Pipeline stage 7 | ✓ | — | 2026-10-21T19:46Z | E-003 |
| `soma/walk.py:51` | flintx | CRYSTALLIZE list | ✓ | — | — | E-004 |
| `soma/run_new_session.py:134` | flintx | Standalone runner | ✓ | — | — | — |
| `soma/run_new_session_fix.py:88` | flintx | Standalone runner (fix) | ✓ | — | — | — |
| `soma/run_tb009.py:91` | flintx | TB-009 runner | ✓ | — | — | — |
| `soma/machinetalk/client.py:30` | flintx | Stage map | — | — | — | E-005 |
| `soma/pipeline/llm_sdk.py:28` | flintx | Stage map | — | — | — | E-006 |
| `soma/machinetalk/soma_bridge.py:349` | flintx | Duplicate slicer | — | — | — | E-017 |
| `soma/workspace.py:13` | flintx | Workspace path default | — | — | — | E-010 |

No remote entry points exist (confirmed by `fdd_targets.json`).

## Architecture and Data Flow

```
┌──────────────┐    import    ┌─────────────────────┐
│ run_pipeline │ ───────────→ │ AxonHillockSlicer   │
│ walk.py      │ ───────────→ │ (axon_hillock_oc)   │
│ run_*.py     │ ───────────→ │                     │
└──────────────┘              └─────────┬───────────┘
                                        │ run(session_id)
                                        │
                            ┌───────────▼───────────┐
                            │   workspace_for()     │
                            │   rglob files         │
                            └───────────┬───────────┘
                                        │
                  ┌─────────────────────┼─────────────────────┐
                  │                     │                     │
          ┌───────▼───────┐   ┌────────▼────────┐   ┌────────▼────────┐
          │ _detect_lang()│   │_extract_slot_   │   │ _find_or_create │
          │ .py/.js/.sh   │   │ spans() regex   │   │ _file_node()    │
          └───────────────┘   └────────┬────────┘   └────────────────┘
                                       │
                              ┌────────▼────────┐
                              │ process_file()  │
                              │ regex slice →   │
                              │ FunctionSlot[]  │
                              └────────┬────────┘
                                       │
                              ┌────────▼────────┐
                              │ Soma store      │
                              │ create_node()   │
                              │ create_edge()   │
                              └────────┬────────┘
                                       │
                              ┌────────▼────────┐
                              │ link_evidence   │
                              │ to_slots()      │
                              │ TRACES_TO edges │
                              └─────────────────┘
```

```
run_pipeline.py ──STAGE 7──► AxonHillockSlicer.run(session_id)
    │
    ├── workspace_for(id) ──► rglob files
    │                           │
    │                           ├─ _detect_language(ext) ──► python|shell|javascript
    │                           ├─ _extract_slot_spans(content, lang) ──► [(name, start, end)]
    │                           ├─ _find_or_create_file_node() ──► FileNode or create
    │                           ├─ process_file() ──► FunctionSlot[] (SLICED_FROM edges)
    │                           │   └─ cleanup: delete old FunctionSlot[s] for session
    │                           └─ link_evidence_to_slots() ──► TRACES_TO edges
    │
    └─ return {sliced_count, matched_count, slot_ids, slots_by_file, metrics}
         │
         ▼
    run_pipeline.py STAGE 8: Myelinator (reads FunctionSlot nodes)
```

## Core Logic

### 1. Initialization and cleanup

`run(session_id)` [E-014] begins by getting the workspace path for the session. If the workspace doesn't exist, it returns an empty report immediately [E-001:137-139].

**Pre-run cleanup** [E-001:142-146]: queries all existing FunctionSlot nodes for this session, then deletes them. This makes reruns idempotent at the slot level.

### 2. Workspace walk and language detection

Iterates all files in the workspace [E-001:148-150]. For each file:
- Reads text content
- Calls `_find_or_create_file_node()` [E-001:153] — queries existing FileNodes by session_id + path match, or creates a new one with `id = "file-{session_id}-{rel_path}"` and a ChatSet fallback
- Calls `process_file()` [E-001:154]

`_detect_language(rel_path)` [E-001:56-69] maps file extensions to `python`, `shell`, or `javascript`. Unknown extensions default to `python`.

### 3. Regex-based slicing

`_extract_slot_spans(content, language)` [E-001:72-102] uses language-specific regex patterns:

**Python** [E-001:28-30]:
```python
r"^\s*(?P<async>async\s+)?(?P<kind>def|class)\s+(?P<name>\w+)"
```

**Shell** [E-001:31-32]:
```python
r"^\s*(?:function\s+)?(?P<name>\w+)\s*\(\s*\)\s*\{"
```

**JavaScript** [E-001:33-37]:
```python
r"^\s*(?P<async>async\s+)?function\s+(?P<fname>\w+)\s*\("
r"|^\s*(?:const|let|var)\s+(?P<arrow>\w+)\s*=\s*(?:async\s*)?\(.*\)\s*=>"
r"|^\s*class\s+(?P<klass>\w+)"
```

For each match, `end` is the start of the next match or EOF. Returns `[(name, start, end)]`.

### 4. FunctionSlot creation

`process_file()` [E-001:256-292] creates one FunctionSlot per span:
- `slot_id = "slot-{session_id}-{file_hash}-{i}"` where file_hash is first 8 chars of MD5 of rel_path
- Node properties: `id`, `session_id`, `parent_file_node_id`, `file_path`, `name`, `mandate`, `terminal_id`, `status: "draft"`, `pin_hash: "pending"`, `code_block`, `inputs: []`, `outputs: []`, `evidence_ids: []`
- Creates `SLICED_FROM` edge from slot to parent FileNode (only if `parent_file_id` is provided)
- **No fallback monolith slot** when no definitions found (returns `[]`)

### 5. Evidence linking (TRACES_TO edges)

`link_evidence_to_slots(session_id)` [E-019] [E-001:295-351]:
- Collects all FunctionSlot nodes for the session
- Collects DirectiveNode, ConstraintNode, TaskNode for the session (by `source_text` or `task_text`)
- For each slot, checks if the slot's `name` or file basename (stem) appears in the evidence node's text
- Creates **actual `TRACES_TO` edges** from each matching FunctionSlot → evidence node
- Idempotent: checks for existing edges before creating

### 6. Dead code: `_slice()` method

The `_slice()` method [E-001:193-248] implements a similar but distinct slicing algorithm:
- Uses a simpler regex: `^\s*(async\s+)?(def\s+(\w+)|class\s+(\w+))` — only Python
- Creates slots with properties: `id`, `session_id`, `parent_file_node_id`, `file_path`, `mandate`, `terminal_id`, `status`, `pin_hash`, `code_block`, `inputs: ["data"]`, `outputs: ["result"]`
- **Falls back to monolith slot** if no defs found (unlike `process_file()`)
- Creates `SLICED_FROM` edge to `parent_file_id` or `ref_id`
- **Zero callers** — never invoked by `run()`, `process_file()`, or any other method

## Configuration and Invariants

| Item | Value | Source |
|---|---|---|
| Stage map | `"axon_hillock": "oc"` | `machinetalk/client.py:30` [E-005] |
| Stage map | `"axon_hillock": "oc"` | `pipeline/llm_sdk.py:28` [E-006] |
| CODE_STOPWORDS | 12 stopwords | `axon_hillock_oc.py:23` [E-011] |
| Hard gates | (1) No filesystem access, (2) No invariant rules, (3) Only FunctionSlot + SLICED_FROM | docstring [E-013] |
| Language support | Python, Shell, JavaScript | patterns [E-012] |
| Workspace default | `/workspace/artifacts/soma-grok/workspaces` | `workspace.py:13` [E-010] |
| No invariant rules applied | Explicit in docstring | `axon_hillock_oc.py:7` [E-014] |

The LLM client parameter (`llm_client`) is accepted in `__init__` [E-001:113] but never used in `run()` or `process_file()`. The return dict includes `"model_id": "unknown"` and zero token counts [E-001:203-207].

## Dependencies and Cross-Component Connections

### Upstream (who calls AxonHillock)

| Component | Mechanism | Evidence |
|---|---|---|
| `run_pipeline.py` (Machinetalk pipeline) | Direct import and Stage 7 invocation [E-003] | `axon = AxonHillockSlicer(self._soma, self._llm, None)` |
| `walk.py` (CRYSTALLIZE list) | Registered as 11th entry [E-004] | `("axon_hillock", AxonHillockSlicer)` |
| `run_new_session.py`, `run_new_session_fix.py`, `run_tb009.py` | Standalone invocations | Direct import + `.run(session_id)` |

### Downstream (who consumes FunctionSlots)

| Component | Mechanism | Evidence |
|---|---|---|
| `myelinator_olc.py` (Myelinator) | Queries FunctionSlot nodes for optimization | Implied by pipeline order |
| `pipeline/code_publisher.py` | Follows SLICED_FROM edges to FileNodes [E-026] | `_resolve_file_path()` follows SLICED_FROM |

### Graph data types used

| Type | Created by | Properties |
|---|---|---|
| `FunctionSlot` | `AxonHillockSlicer.process_file()` | `id`, `session_id`, `parent_file_node_id`, `file_path`, `name`, `mandate`, `terminal_id`, `status`, `pin_hash`, `code_block`, `inputs`, `outputs`, `evidence_ids` |
| `FileNode` | `_find_or_create_file_node()` (if not existing) | `id`, `session_id`, `chat_set_id`, `path`, `source_text` |
| `SLICED_FROM` edge | `process_file()` | FunctionSlot → FileNode |
| `TRACES_TO` edge | `link_evidence_to_slots()` | FunctionSlot → DirectiveNode/ConstraintNode/TaskNode |

### Duplicate implementation (SomaBridge.write_oc)

`machinetalk/soma_bridge.py:349-384` [E-017] contains a parallel `write_oc()` method that:
- Reads from `FileNode.content_preview` (text preview, NOT workspace files)
- Uses same Python regex as `_slice()`
- Creates `FunctionSlot` with slightly different properties (includes `language`, no `terminal_id`, no `status`)
- No evidence linking (no TRACES_TO edges)
- Deletes existing FunctionSlots first (same as AxonHillockSlicer.run())

**Resolution**: `run_pipeline.py` uses `AxonHillockSlicer` directly. The SomaBridge `write_oc()` path is used when the Machinetalk engine (engine.py) calls stage methods through SomaBridge. These are two entirely separate code paths producing FunctionSlots.

## Known Gaps and Uncertainties

### G-01: No live execution evidence
**What is unknown**: No pipeline log file mentions "AXON" or "AxonHillock". The five pipeline logs (20261015–20261018) cover only stages 1–3 (DISTILLER, INTROBEAVER, PLANBEAVER, OUTROBEAVER). It is unknown whether axon has actually run successfully in a live pipeline execution.
**Why it matters**: Without live execution evidence, the return dict structure and actual metrics (scanned_count, sliced_count, matched_count) are theoretical.
**Closing evidence**: Re-run `run_pipeline.py` with a real session and capture full log output through Stage 7.

### G-02: Empty workspace — no real slicing data
**What is unknown**: `soma/workspaces/` is empty. `workspace_for()` defaults to `/workspace/artifacts/soma-grok/workspaces` which may or may not exist. Without workspace data, the core slicing logic has never been exercised on real files.
**Why it matters**: The slicing algorithms (regex patterns, language detection, code_block extraction) cannot be validated against actual code.
**Closing evidence**: Populate a workspace directory with draft files from a real Drafter run and invoke `axon.run(session_id)`.

### G-03: `_slice()` is dead code
**What is unknown**: The `_slice()` method [E-001:193-248] has zero callers. It implements a Python-only slicing algorithm with a monolith fallback, while `process_file()` is the live path with multi-language support and no fallback. No evidence explains why `_slice()` exists.
**Why it matters**: Dead code increases maintenance burden and creates confusion about which algorithm is authoritative.
**Closing evidence**: Confirm `_slice()` was intended for a removed code path or replace it with deprecation documentation.

### G-04: Duplicate slicer in SomaBridge.write_oc
**What is unknown**: `soma_bridge.write_oc()` [E-017] creates FunctionSlots from `FileNode.content_preview` — a text preview — while `AxonHillockSlicer` [E-001] reads actual workspace file contents. These produce FunctionSlots with different properties and different evidence-linking behavior. No evidence identifies which path the "main" pipeline uses.
**Why it matters**: Two different FunctionSlot schemas can coexist in the same Soma graph, causing downstream stages (Myelinator, CodePublisher) to encounter inconsistent node structures.
**Closing evidence**: Trace the Machinetalk engine.py stage dispatch to determine whether it calls `AxonHillockSlicer.run()` or `SomaBridge.write_oc()`.

### G-05: LLM client is always None
**What is unknown**: All call sites pass `None` for `llm_client`. The return dict always reports `"model_id": "unknown"` and zero tokens. No evidence indicates the LLM path is intentionally unused or that it is a missed integration.
**Why it matters**: If LLM-based slicing was intended (e.g., for semantic splitting or AST-aware slicing), it is not implemented. If the LLM path is intentionally unused, the `llm_client` and `rotator` parameters should be removed.
**Closing evidence**: Review design intent — is LLM integration planned, abandoned, or never required?

### G-06: No dedicated test coverage
**What is unknown**: Only `test_tb_fix_002.py` imports `AxonHillockSlicer` and tests `link_evidence_to_slots()` TRACES_TO edge creation [E-015]. The `process_file()` method, `_detect_language()`, `_extract_slot_spans()`, `_find_or_create_file_node()`, and `run()` all have zero test coverage.
**Why it matters**: Language detection, regex slicing, file node creation, and cleanup are all critical paths without tests. The duplicate `_slice()` method also lacks tests.
**Closing evidence**: Write tests for `process_file()` with Python, Shell, and JavaScript files; test `_detect_language()` for all extension mappings; test `_find_or_create_file_node()` for both existing and new FileNodes.

## Evidence Log

| ID | Host | Kind | Locator | Captured At | Proves | Confidence |
|---|---|---|---|---|---|---|
| E-001 | flintx | source | `soma/axon_hillock_oc.py` | 2026-10-22T14:25Z | Primary module, 368 lines, full source | C2 |
| E-002 | flintx | metadata | axon_hillock_oc.py mtime | stat | File mtime 2026-10-18T02:59Z | C1 |
| E-003 | flintx | source | `run_pipeline.py:154-157` | 2026-10-22T14:25Z | Stage 7 import + instantiation + run | C2 |
| E-004 | flintx | source | `walk.py:51` | 2026-10-22T14:25Z | CRYSTALLIZE list registration | C2 |
| E-005 | flintx | source | `machinetalk/client.py:30` | 2026-10-22T14:25Z | _STAGE_MAP: axon_hillock → oc | C2 |
| E-006 | flintx | source | `pipeline/llm_sdk.py:28` | 2026-10-22T14:25Z | _STAGE_MAP: axon_hillock → oc (dual) | C2 |
| E-007 | flintx | source | `run_pipeline.py:152-157` | 2026-10-22T14:25Z | Exact pipeline position (Stage 7) | C2 |
| E-008 | flintx | source | `walk.py:46-53` | 2026-10-22T14:25Z | Position in CRYSTALLIZE (11th) | C2 |
| E-009 | flintx | filesystem | `soma/workspaces/` | 2026-10-22T14:25Z | Directory exists but empty | C1 |
| E-010 | flintx | source | `workspace.py:13` | 2026-10-22T14:25Z | Default workspace path | C2 |
| E-011 | flintx | source | `axon_hillock_oc.py:23` | 2026-10-22T14:25Z | CODE_STOPWORDS constant | C2 |
| E-012 | flintx | source | `axon_hillock_oc.py:28-46` | 2026-10-22T14:25Z | Language regex patterns (3 langs) | C2 |
| E-013 | flintx | source | `axon_hillock_oc.py:1-8` | 2026-10-22T14:25Z | Hard gates in module docstring | C2 |
| E-014 | flintx | source | `axon_hillock_oc.py:117` | 2026-10-22T14:25Z | stage_name = "axon_hillock" | C2 |
| E-015 | flintx | source | `test_tb_fix_002.py:4` | 2026-10-22T14:25Z | Only test file importing AxonHillockSlicer | C2 |
| E-016 | flintx | source | `run_pipeline.py:234` | 2026-10-22T14:25Z | Return dict includes "axon" key | C2 |
| E-017 | flintx | source | `soma_bridge.py:349-384` | 2026-10-22T14:25Z | Duplicate write_oc() FunctionSlot creation | C2 |
| E-018 | flintx | source | `axon_hillock_oc.py:186` | 2026-10-22T14:25Z | process_file() is live, _slice() is dead | C2 |
| E-019 | flintx | source | `axon_hillock_oc.py:295-351` | 2026-10-22T14:25Z | link_evidence_to_slots() creates TRACES_TO edges | C2 |
| E-020 | flintx | source | `soma_bridge.py:17` | 2026-10-22T14:25Z | soma_bridge docstring: oc → AxonHillock | C2 |
| E-021 | flintx | source | `axon_hillock_oc.py:187` | 2026-10-22T14:25Z | process_file() deletes old slots first | C2 |
| E-022 | flintx | source | `axon_hillock_oc.py:343-346` | 2026-10-22T14:25Z | TRACES_TO edge idempotency check | C2 |
| E-023 | flintx | source | `axon_hillock_oc.py:133-139` | 2026-10-22T14:25Z | workspace_for() return, existence check | C2 |
| E-024 | flintx | source | `run_pipeline.py:154` | 2026-10-22T14:25Z | LLM client passed as None | C2 |
| E-025 | flintx | source | `run_pipeline.py:159-163` | 2026-10-22T14:25Z | Pipeline order: Axon → Myelinator | C2 |
| E-026 | flintx | source | `pipeline/code_publisher.py:92-112` | 2026-10-22T14:25Z | CodePublisher follows SLICED_FROM chain | C2 |
