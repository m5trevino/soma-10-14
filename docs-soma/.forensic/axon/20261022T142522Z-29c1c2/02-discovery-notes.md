# Discovery Notes: axon

## Target lock

TARGET: axon
SLUG: axon
RUN ID: 20261022T142522Z-29c1c2
SCOPE: Slices reference artifacts into FunctionSlot nodes linked by SLICED_FROM edges.

## Inventory summary

- Local root: `/home/flintx/soma-10-14/soma` (185 files, depth 3)
- Primary source: `axon_hillock_oc.py` (368 lines, mtime 2026-10-18T02:59:43Z)
- No git history for this file (`git log` returned nothing)
- 18 test files in root, 1 file imports AxonHillockSlicer (`test_tb_fix_002.py`)
- No dedicated `test_axon*.py` file exists
- `workspaces/` directory exists but is empty
- 5 pipeline log files (20261015–20261018) — none mention axon directly (logs are from older machine-talk pipeline, pre-AxonHillock)

## Entry points

| Path | Lines | Mtime | Host |
|---|---|---|---|
| `soma/axon_hillock_oc.py` | 368 | 2026-10-18T02:59:43Z | flintx (local) |
| `soma/run_pipeline.py:154` | — | 2026-10-21T19:46Z | flintx (local) |
| `soma/walk.py:51` | — | — | flintx (local) |
| `soma/run_new_session.py:134` | — | — | flintx (local) |
| `soma/run_new_session_fix.py:88` | — | — | flintx (local) |
| `soma/run_tb009.py:91` | — | — | flintx (local) |

No remote entry point found (fdd_targets.json confirms no remote roots for axon).

## Runtime state

- AxonHillockSlicer is **not a long-running service**. It is instantiated and run once per pipeline execution.
- Pipeline log files show older machine-talk stages (DISTILLER, INTROBEAVER, PLANBEAVER, OUTROBEAVER) from October 2026 — axon (Stage 7) is not present in any log.
- Confirmed: axon runs in `run_pipeline.py` at STAGE 7 (after Scout, before Myelinator) [E-007]
- Confirmed: axon is in `CRYSTALLIZE` list in `walk.py` at position 11 (after scout, before myelinator) [E-008]

## Data stores

| Path | Type | Notes |
|---|---|---|
| `soma/workspaces/` | directory | EXISTS but empty (tree depth 0) |
| `soma/output/soma.json` | file | Graph output from prior runs (mtime 2026-10-21T20:03) |
| `soma/turn-key-profiles/soma-current.json` | file | Model deck config (mtime 2026-10-20T21:08) |

Workspace path default: `/workspace/artifacts/soma-grok/workspaces` [E-010] — this path does NOT exist locally. The `workspace_for()` function creates it on demand.

## Configuration and invariants

- `_STAGE_MAP` in `machinetalk/client.py:30`: `"axon_hillock": "oc"` [E-012]
- `_STAGE_MAP` in `pipeline/llm_sdk.py:28`: `"axon_hillock": "oc"` [E-013]
- No `.env`, config JSON, or invariant rules apply to axon [HARD GATE: "No invariant rules applied in this stage"] [E-014]
- CODE_STOPWORDS: `{"def", "class", "import", "from", "json", "sys", "path", "return", "pass", "async", "await"}` [E-015]
- Language patterns: Python, Shell, JavaScript [E-016]
- Hard gates from docstring: (1) No filesystem access, (2) No invariant rules applied, (3) Only writes FunctionSlot + SLICED_FROM edges [E-017]

## Cross-component edges

| Direction | Mechanism | Evidence |
|---|---|---|
| upstream → axon | `run_pipeline.py:154` imports and instantiates | `AxonHillockSlicer(self._soma, self._llm, None)` [E-018] |
| upstream → axon | `walk.py:51` registers in CRYSTALLIZE list [E-019] |
| axon → Soma store | `self._soma.create_node("FunctionSlot", ...)` [E-020] |
| axon → Soma store | `self._soma.create_edge("SLICED_FROM", ...)` [E-021] |
| axon → Soma store | `self._soma.create_edge("TRACES_TO", ...)` (evidence linking) [E-022] |
| axon → workspace | `workspace_for(session_id)` reads files from workspace dir [E-023] |
| axon ← TurnKey client | `self._llm` is passed as LLM client (though `None` in all call sites) [E-024] |
| downstream ← axon | Myelinator queries FunctionSlot nodes for optimization [E-025] |
| downstream ← axon | CodePublisher follows SLICED_FROM edges to FileNodes [E-026] |

## Conflicts

CONFLICT C-01: Duplicate FunctionSlot creation
  claim A: `axon_hillock_oc.py:193-248` — `_slice()` method reads workspace file contents and creates FunctionSlots from raw code content. Uses regex pattern `^\s*(async\s+)?(def\s+(\w+)|class\s+(\w+))`. Creates `code_block`, `inputs`, `outputs`, `status`, `pin_hash`, `terminal_id`. Falls back to monolith slot if no defs found.
  claim B: `soma_bridge.py:349-384` — `write_oc()` method reads FileNode `content_preview` properties and creates FunctionSlots. Uses regex `^\s*(async\s+)?(def\s+(\w+)|class\s+(\w+))`. Creates `code_block`, `language`, `file_path`, `parent_file_id`. No fallback, no evidence linking. Deletes existing slots first.
  resolution: both-live — two different code paths create FunctionSlots
  basis: import graph. `run_pipeline.py` imports `axon_hillock_oc.AxonHillockSlicer` directly. `soma_bridge.write_oc()` is called in the Machinetalk engine stage path (engine.py → SomaBridge). The `_slice()` method is NOT called by `run()` or `process_file()` — it is dead code. The `process_file()` method is the live path in AxonHillockSlicer.
  impact: two distinct slicing implementations exist; the Machinetalk path uses SomaBridge.write_oc() instead of AxonHillockSlicer entirely. This means two completely different FunctionSlot creation flows coexist.

CONFLICT C-02: `_slice()` is dead code
  claim A: `_slice()` exists as a method on AxonHillockSlicer [E-030]
  claim B: `run()` calls `self.process_file()` exclusively, never `self._slice()` [E-031]
  resolution: A is dead code, B is live
  basis: source inspection — `run()` calls `self.process_file()` at line 186; `_slice()` has zero callers in any file (rg confirmed).
  impact: `_slice()` should be removed or flagged as deprecated.

## Unknowns and boundary gaps

U-01: No dedicated test coverage for `axon_hillock_oc.py`. Only `test_tb_fix_002.py:4` imports `AxonHillockSlicer` and tests the `link_evidence_to_slots()` TRACES_TO edge creation. The `process_file()` and `run()` paths have no test assertions.

U-02: The `soma_bridge.write_oc()` duplicate creates FunctionSlots from `FileNode.content_preview` (a text preview), while `AxonHillockSlicer.run()` creates them from actual workspace file contents. No evidence of which path the "main" pipeline uses (Machinetalk engine.py vs run_pipeline.py).

U-03: `self._llm` is passed as `None` in all call sites (`run_pipeline.py:154`, `walk.py:51`, `run_new_session.py:134`, `run_tb009.py:91`, `run_new_session_fix.py:88`). The LLM client is never actually used in the current AxonHillockSlicer implementation — the class accepts it in `__init__` but `run()` and `process_file()` never call it. The `run()` return dict still includes `"model_id": "unknown"` and token counts all 0.

U-04: Workspace path is `soma/workspaces/` (empty) but `workspace_for()` defaults to `/workspace/artifacts/soma-grok/workspaces`. No workspace data found on disk. Unclear if any real session data has been sliced.

U-05: No git history for `axon_hillock_oc.py`. Cannot determine when or why it was created, or whether it evolved from an earlier file.

## Evidence index

| ID | Host | Kind | Locator | Captured At | Proves | Confidence |
|---|---|---|---|---|---|---|
| E-001 | flintx | source | soma/axon_hillock_oc.py | 2026-10-22T14:25Z | Primary module exists, 368 lines | C2 |
| E-002 | flintx | metadata | axon_hillock_oc.py mtime | stat | File mtime 2026-10-18T02:59:43Z | C1 |
| E-003 | flintx | source | run_pipeline.py:154-157 | 2026-10-22T14:25Z | Stage 7 instantiation and run | C2 |
| E-004 | flintx | source | walk.py:51 | 2026-10-22T14:25Z | CRYSTALLIZE list registration | C2 |
| E-005 | flintx | source | machinetalk/client.py:30 | 2026-10-22T14:25Z | _STAGE_MAP: axon_hillock → oc | C2 |
| E-006 | flintx | source | pipeline/llm_sdk.py:28 | 2026-10-22T14:25Z | _STAGE_MAP: axon_hillock → oc | C2 |
| E-007 | flintx | source | run_pipeline.py:152-157 | 2026-10-22T14:25Z | Exact pipeline position (Stage 7) | C2 |
| E-008 | flintx | source | walk.py:51 | 2026-10-22T14:25Z | Position in CRYSTALLIZE (11th) | C2 |
| E-009 | flintx | filesystem | soma/workspaces/ | 2026-10-22T14:25Z | Exists but empty | C1 |
| E-010 | flintx | source | workspace.py:13 | 2026-10-22T14:25Z | Default workspace path | C2 |
| E-011 | flintx | source | axon_hillock_oc.py:23 | 2026-10-22T14:25Z | CODE_STOPWORDS constant | C2 |
| E-012 | flintx | source | axon_hillock_oc.py:28-46 | 2026-10-22T14:25Z | Language patterns: Python, Shell, JS | C2 |
| E-013 | flintx | source | axon_hillock_oc.py:1-8 | 2026-10-22T14:25Z | Hard gates in docstring | C2 |
| E-014 | flintx | source | axon_hillock_oc.py:117 | 2026-10-22T14:25Z | stage_name = "axon_hillock" | C2 |
| E-015 | flintx | source | test_tb_fix_002.py:4 | 2026-10-22T14:25Z | Only test importing AxonHillockSlicer | C2 |
| E-016 | flintx | source | run_pipeline.py:234 | 2026-10-22T14:25Z | Return dict includes axon key | C2 |
| E-017 | flintx | source | soma_bridge.py:349-384 | 2026-10-22T14:25Z | Duplicate write_oc FunctionSlot creation | C2 |
| E-018 | flintx | source | axon_hillock_oc.py:186 | 2026-10-22T14:25Z | process_file() is live, _slice() is dead | C2 |
| E-019 | flintx | source | axon_hillock_oc.py:268-320 | 2026-10-22T14:25Z | link_evidence_to_slots() creates TRACES_TO edges | C2 |
| E-020 | flintx | source | machinetalk/soma_bridge.py:17 | 2026-10-22T14:25Z | soma_bridge docstring: oc → AxonHillock | C2 |

## Report plan

1. Mandate: Slice reference artifacts into FunctionSlot nodes
2. Current State: One live module (axon_hillock_oc.py), dead `_slice()` method, duplicate SomaBridge.write_oc()
3. Key Paths: Entry points in run_pipeline.py, walk.py, run_new_session*.py, run_tb009.py
4. Architecture: Pipeline → AxonHillockSlicer → Soma (FunctionSlot + SLICED_FROM + TRACES_TO)
5. Core Logic: Workspace walk → language detection → regex slice → FunctionSlot creation → evidence linking
6. Configuration: stage map, no invariants, language patterns
7. Dependencies: Soma store, workspace, downstream (Myelinator, CodePublisher)
8. Known Gaps: No live pipeline execution evidence, dead _slice(), duplicate write_oc(), no test coverage for main path
