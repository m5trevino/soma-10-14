# Drafter — Forensic Deep Dive

TARGET: drafter | RUN: 20261022T142207Z-015d91 | DATE: 2026-10-22T14:22Z | HOSTS EXAMINED: flintx
CONFIDENCE SUMMARY: C1=3, C2=16, C3=4 | SCOPE: generates reference application and maps FileNodes into the Soma through tool calls or fenced-code fallback
EXCLUDED: every other component; sibling components are interfaces only

## Mandate

Generates code files for a project and maps them as nodes and edges in the Soma graph store, operating in two distinct execution paths — a pipeline runner and a Machinetalk build stage.

## Current State

Two `drafter_dendrite.py` files exist with different responsibilities:

| File | Lines | Mtime | Status |
|------|-------|-------|--------|
| `soma/drafter_dendrite.py` | 631 | 2026-10-18T01:40Z | **Active implementation** — full `DrafterDendrite` class |
| `soma/pipeline/drafter_dendrite.py` | 190 | 2026-10-14T19:16Z | **Stub** — `LLMClient`, `LLMResponse`, `ModelRotator`, `MockLLMClient`, `StrictMockLLMClient`, `ToolRegistry` for tests |

The root file is newer by ~4 days and contains the executable `DrafterDendrite` class. The pipeline file is a minimal infrastructure stub used exclusively as an import target for LLM response types by test files and the `pipeline/integrator_dendrite.py` module.

The drafter is not a standalone service. It is invoked at runtime by:
- `run_pipeline.py` as STAGE 5 in the full dendrite pipeline [E-004, E-021]
- `run_new_session.py` as part of session creation [E-005]
- `machinetalk/engine.py` as a stage3 Machinetalk build stage [E-006, E-007]

No dedicated process, port, or health endpoint exists for the drafter.

## Key Paths and Entry Points

| Path | Host | Role | Entrypoint? | Lines | Mtime | Evidence |
|------|------|------|-------------|-------|-------|----------|
| `soma/drafter_dendrite.py` | flintx | Active DrafterDendrite + ToolRegistry + MockLLMClient | YES — `DrafterDendrite` @L287 | 631 | 2026-10-18 | C2 |
| `soma/pipeline/drafter_dendrite.py` | flintx | Stub LLM types + ToolRegistry for tests | NO — stubs only | 190 | 2026-10-14 | C2 |
| `machinetalk/engine.py` | flintx | Orchestrates build stages including drafter | YES — `engine.py:732,849` | 1000+ | 2026-10-21 | C2 |
| `machinetalk/soma_bridge.py` | flintx | `write_drafter()` persists drafter output to Soma | YES — `write_drafter` @L272 | 537 | 2026-10-21 | C2 |
| `run_pipeline.py` | flintx | Full dendrite pipeline runner | YES — imports DrafterDendrite @L29 | 291 | 2026-10-21 | C2 |
| `run_new_session.py` | flintx | New session creation | YES — imports DrafterDendrite @L17 | 156 | 2026-10-21 | C2 |
| `machine-talk/tb-011-drafter.md` | flintx | Machinetalk spec TB-004 | DOC — spec contract | — | — | C3 |

## Architecture and Data Flow

```
┌──────────────────────────────────────────────────────────────────┐
│                        Execution Paths                           │
│                                                                  │
│  ┌─────────────────┐      ┌──────────────────────────────────┐  │
│  │  run_pipeline.py │      │  machinetalk/engine.py           │  │
│  │  (STAGE 5)      │      │  (stage3 build stage)            │  │
│  └────────┬────────┘      └─────────────┬────────────────────┘  │
│           │                             │                       │
│           ▼                             ▼                       │
│  ┌─────────────────┐      ┌──────────────────────────────────┐  │
│  │DrafterDendrite   │      │ _run_build_stage("drafter",      │  │
│  │.run(session_id)  │      │  payload={planbeaver_output,...} │  │
│  │                  │      └─────────────┬────────────────────┘  │
│  │ Phase 1: map     │                    │                       │
│  │   files via LLM  │                    ▼                       │
│  │ Phase 2: generate│         ┌────────────────────────────────┐ │
│  │   code per file  │         │ LLM produces                   │ │
│  │                  │         │ draft_artifact.files[]          │ │
│  └───────┬──────────┘         └────────────┬───────────────────┘ │
│          │                                 │                    │
│          ▼                                 ▼                    │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │                     Soma Graph Store                       │ │
│  │                                                            │ │
│  │  Pipeline path:                                            │ │
│  │    FileNode (per file) ─PRODUCES→ ReferenceArtifactNode    │ │
│  │    (direct Soma.create_node via ToolRegistry)              │ │
│  │                                                            │ │
│  │  Machinetalk path:                                         │ │
│  │    ReferenceArtifactNode (single, all files concatenated)  │ │
│  │    via soma_bridge.write_drafter()                         │ │
│  └────────────────────────────────────────────────────────────┘ │
│          │                                                       │
│          ▼                                                       │
│  ┌─────────────────┐                                             │
│  │ scout_dendrite  │ ◄── reads FileNodes created by drafter     │
│  └─────────────────┘                                             │
│          │                                                       │
│          ▼                                                       │
│  ┌─────────────────┐                                             │
│  │ workspace/        │ ◄── files written under                    │
│  │ chats/<sid>/    │    chats/<session_id>/ for pipeline path   │
│  └─────────────────┘                                             │
└──────────────────────────────────────────────────────────────────┘
```

Both paths produce Soma nodes but with different architectures:

**Pipeline path** (root `DrafterDendrite.run()`):
- Creates one `FileNode` per file + one `ReferenceArtifactNode` per file, linked by `PRODUCES` edge.
- Writes actual source code files to `workspace.chats/<session_id>/`.

**Machinetalk path** (`engine.py` + `soma_bridge.write_drafter()`):
- Creates a single `ReferenceArtifactNode` with id `artifact-{session_id}`.
- Concatenates all file contents into one `artifact_text` field (truncated to 20,000 characters).
- No per-file `FileNode` objects created by this path.

## Core Logic

### Pipeline Path: `DrafterDendrite.run()` (root `drafter_dendrite.py`)

```
DrafterDendrite.run(session_id) [L443]
  │
  ├─ 1. _build_task_plan(session_id, chatsets_resp) [L540]
  │     └─ reads ChatSet nodes → concatenates user_text (≤500 chars each)
  │
  ├─ 2. Phase 1: _phase1_map_files(session_id, task_plan) [L360]
  │     ├─ selects model via rotator.next_model("drafter")
  │     ├─ LLM call: "You are the Drafter Dendrite — Architectural Mapper"
  │     ├─ Expects JSON array of file paths: ["app.py", "utils/helpers.py"]
  │     ├─ Falls back to ["main.py"] if parsing fails
  │     └─ Records planning metrics (tokens, latency)
  │
  ├─ 3. Create FileNodes for each path [L470-482]
  │     ├─ node id: "file-{session_id}-{path}"
  │     ├─ type: FileNode
  │     └─ links to last ChatSet via chat_set_id
  │
  ├─ 4. Phase 2: _phase2_generate_file() per file [L400]
  │     ├─ LLM call: "You are the Drafter Dendrite — Code Generator"
  │     ├─ Exactly 1 LLM call per file
  │     ├─ Creates ReferenceArtifactNode with code_payload
  │     ├─ Edge: ReferenceArtifactNode ─PRODUCES→ FileNode
  │     └─ Records per-file metrics
  │
  ├─ 5. Write files to workspace [L492-506]
  │     ├─ normalize_draft_relpath() rejects path escapes
  │     ├─ writes under workspace.chats/<session_id>/
  │     └─ resolves and validates path stays within workspace
  │
  └─ 6. Aggregate report [L508-540]
        ├─ _parse_code_structure(total_code) — counts functions/classes/imports
        ├─ token totals, latency totals
        └─ returns: file_paths, file_nodes, artifact_ids, structure, metrics
```

### Fallback Code Extraction (TB-DRAFT-003)

If the LLM returns no tool calls, `_extract_largest_code_block()` [L332] uses the regex `_CODE_FENCE_RE` [L295-298] to extract the largest fenced code block (triple-backtick or triple-tilde) from the response. The fallback path is `_create_fallback_nodes()` [L342] which creates a single `ReferenceArtifactNode` + `FileNode` pair without per-file granularity.

### Machinetalk Path: `machinetalk/engine.py`

```
_engine.py:849 (elif stage == "drafter")
  ├─ Gets planbeaver output from merged stage1 artifacts
  ├─ Constructs payload: {session_id, planbeaver_output, template_library, style_guide}
  ├─ _run_build_stage(build, "drafter", payload=payload) [L862]
  │     └─ runs LLM with planbeaver_output → captures gate
  └─ engine.py:732
        ├─ gate.parsed["draft_artifact"]["files"]
        └─ _bridge.write_drafter(build, gate, model, latency) [soma_bridge.py:272]
              ├─ concatenates all file content into single artifact_text (≤20K chars)
              ├─ creates ReferenceArtifactNode "artifact-{session_id}"
              └─ returns counts of nodes/edges created
```

### ToolRegistry (root drafter)

The root `DrafterDendrite` uses a `ToolRegistry` [L108-176] that exposes five callable tools to the LLM:
- `get_receptor_config(agent_id)` — fetches ReceptorConfig node
- `get_chatset(node_id)` — fetches a ChatSet node
- `list_chatsets_for_session(session_id)` — lists ChatSets ordered by set_number
- `create_soma_node(type_name, properties)` — creates a typed node
- `create_soma_edge(source_id, relationship, target_id)` — creates a directed edge

## Configuration and Invariants

| Key | Value | Source | Type |
|-----|-------|--------|------|
| `COMPLETION_TOKEN_CEILING` | `16000` | `drafter_dendrite.py:292` | Code constant |
| `_CODE_FENCE_RE` | `r"(?:^|\n)(\`\`\|~~~)(?:\w+)?\n(.*?)\1(?:\n|$)"` | `drafter_dendrite.py:295-298` | Regex constant |
| `ToolRegistry._SCHEMAS` | 5 tool definitions | `drafter_dendrite.py:110-176` | Class attribute |
| `normalize_draft_relpath()` | rejects `..` and absolute paths | `drafter_dendrite.py:204-220` | Function |
| Workspace base | `workspace_for(session_id)` | `drafter_dendrite.py:425-427` | Function call |
| Machinetalk indent | `"4 spaces"` | `engine.py:858` | Payload constant |
| Machinetalk naming | `{"functions": "snake_case", "files": "kebab-or_snake"}` | `engine.py:859-860` | Payload constant |
| Artifacts truncation | 20,000 chars | `soma_bridge.py:291` (implied by artifact_text[:20000]) | Code limit |

Hard gates (documented in source docstring and Machinetalk spec):
1. No physical files except workspace files under `chats/<session_id>/` — enforced in `_write_draft_file()` [E-014]
2. All Soma access via tool calls — enforced by `ToolRegistry` [E-015]
3. Uses active model rotation — `ModelRotator` rotates through configured models [E-016]
4. Every `function_spec` from PlanBeaver MUST have implementation or TODO marker — Machinetalk spec [E-017]
5. All files MUST have `parses_clean == true` — Machinetalk spec [E-018]
6. MUST NOT optimize, harden invariants, or scope-creep — Machinetalk spec [E-019]

## Dependencies and Cross-Component Connections

| Direction | Component | Mechanism | Payload | Confidence |
|-----------|-----------|-----------|---------|------------|
| Upstream | `run_pipeline.py` | `from drafter_dendrite import DrafterDendrite` + direct instantiation | `session_id` only | C2 |
| Upstream | `run_new_session.py` | `from drafter_dendrite import DrafterDendrite` | `session_id` only | C2 |
| Upstream | `machinetalk/engine.py` | `_run_build_stage("drafter", payload=...)` then `_bridge.write_drafter()` | `{planbeaver_output, template_library, style_guide}` | C2 |
| Upstream (types) | `pipeline.drafter_dendrite` | `from pipeline.drafter_dendrite import LLMClient as DrafterLLM` | Stub `LLMClient` only | C2 |
| Downstream | `soma_bridge.write_drafter()` | Called by engine after build stage completes | `gate.parsed["draft_artifact"]["files"]` | C2 |
| Downstream | `scout_dendrite` | Reads `FileNode` and `ReferenceArtifactNode` created by drafter | File node references | C2 |
| Dependent | `store.Soma` | `from store import Soma` | Graph store with nodes/edges | C2 |
| Dependent | `workspace.workspace_for()` | `from workspace import workspace_for` | Workspace path resolution | C2 |
| Sibling (stub) | `pipeline.drafter_dendrite` | Test imports `LLMResponse` and `LLMClient` | Stub types only | C2 |

## Known Gaps and Uncertainties

G-01: **Machinetalk engine's `_run_build_stage` for drafter** — The engine at `engine.py:849-862` constructs a planbeaver-derived payload and calls `_run_build_stage("drafter", payload=...)`. The LLM response from that stage is captured in `gate`, then passed to `soma_bridge.write_drafter()`. However, the internal transformation from raw LLM output to `gate.parsed["draft_artifact"]["files"]` is not fully traceable in the available source. Evidence needed: full `_run_build_stage` method with the drafter-specific branch.

G-02: **Node architecture divergence** — The pipeline path creates one `FileNode` + one `ReferenceArtifactNode` per file with `PRODUCES` edges (fine-grained). The Machinetalk path creates a single `ReferenceArtifactNode` with all files concatenated into one `artifact_text` field (coarse-grained). Whether downstream consumers (e.g., scout) handle both architectures correctly is UNKNOWN. Evidence needed: scout's read path that queries `FileNode` objects.

G-03: **TB-004 vs TB-005 naming inconsistency** — `machine-talk/tb-011-drafter.md` labels itself TB-004 (Drafter) but `run_tb005.py` is labeled "TB-005 Runner — Nexus Dendrite" and actually runs the Classifier and Nexus (not drafter). No explicit test runner exists for `DrafterDendrite` alone. The machinetalk engine references TB-005 as "PlanBeaver" in the spec but classifies drafter as `stage3` (not stage1). Evidence needed: project-level naming convention documentation.

G-04: **`workspace_for()` implementation not examined** — The root drafter delegates workspace path resolution to `workspace.workspace_for(session_id)` [E-009]. The actual path construction (what directory structure it creates) is not traced. This matters for the hard gate about "no physical files except workspace files."

G-05: **Pipeline stub is never directly imported by the active DrafterDendrite** — The root `DrafterDendrite` defines its own `LLMClient`, `LLMResponse`, `ModelRotator`, `ToolRegistry`, and `MockLLMClient` classes internally (lines 41-106 and 222-246 of the root file). The pipeline stub provides the same class names but with different implementations. They are not used interchangeably in the same import chain. Evidence needed: whether any production code path mixes the two.

## Evidence Log

| ID | Host | Kind | Locator | Captured At | Proves | Confidence |
|----|------|------|---------|-------------|--------|------------|
| E-001 | flintx | source | `machinetalk/engine.py:100` | 14:22Z | drafter classified as stage3 | C2 |
| E-004 | flintx | source | `run_pipeline.py:29,140-141` | 14:22Z | root DrafterDendrite imported and instantiated in pipeline | C2 |
| E-005 | flintx | source | `run_new_session.py:17` | 14:22Z | root DrafterDendrite imported in new session runner | C2 |
| E-006 | flintx | source | `machinetalk/engine.py:849-862` | 14:22Z | engine runs drafter build stage with planbeaver payload | C2 |
| E-007 | flintx | source | `machinetalk/engine.py:732-733` | 14:22Z | engine calls soma_bridge.write_drafter after stage | C2 |
| E-008 | flintx | source | `machinetalk/soma_bridge.py:283-290` | 14:22Z | write_drafter creates ReferenceArtifactNode in soma | C2 |
| E-009 | flintx | source | `soma/drafter_dendrite.py:425-427` | 14:22Z | workspace_for resolves path under chats/<session_id>/ | C2 |
| E-010 | flintx | source | `soma/drafter_dendrite.py:docstring L8` | 14:22Z | fallback code written to /tmp/ per TB-DRAFT-004 | C3 |
| E-011 | flintx | source | `soma/drafter_dendrite.py:292` | 14:22Z | COMPLETION_TOKEN_CEILING = 16000 | C2 |
| E-012 | flintx | source | `soma/drafter_dendrite.py:295-298` | 14:22Z | _CODE_FENCE_RE regex for fenced block extraction | C2 |
| E-013 | flintx | source | `soma/drafter_dendrite.py:204-220` | 14:22Z | normalize_draft_relpath rejects .. escapes | C2 |
| E-014 | flintx | source | `soma/drafter_dendrite.py:docstring L15` | 14:22Z | hard gate: no files outside workspace | C3 |
| E-015 | flintx | source | `soma/drafter_dendrite.py:docstring L16` | 14:22Z | hard gate: all Soma access via tool calls | C3 |
| E-016 | flintx | source | `soma/drafter_dendrite.py:docstring L17` | 14:22Z | hard gate: uses active model rotation | C3 |
| E-017 | flintx | source | `machine-talk/tb-011-drafter.md` | 14:22Z | Machinetalk: every function_spec must have impl or TODO | C3 |
| E-018 | flintx | source | `machine-talk/tb-011-drafter.md` | 14:22Z | Machinetalk: all files must parse_clean | C3 |
| E-019 | flintx | source | `machine-talk/tb-011-drafter.md` | 14:22Z | Machinetalk: no optimize/harden/scope-creep | C3 |
| E-020 | flintx | source | `machinetalk/engine.py:855-861` | 14:22Z | drafter payload structure from engine | C2 |
| E-021 | flintx | source | `run_pipeline.py:140-141` | 14:22Z | pipeline drafter invocation | C2 |
| E-022 | flintx | source | `machinetalk/soma_bridge.py:272-292` | 14:22Z | bridge write_drafter function implementation | C2 |
| E-023 | flintx | source | `scout_dendrite.py:3,75` | 14:22Z | scout reads FileNodes created by drafter | C2 |
| E-024 | flintx | source | `test_integrator_dendrite.py:25` | 14:22Z | pipeline stub LLMResponse imported by tests | C2 |
| E-025 | flintx | source | `machine-talk/tb-011-drafter.md` | 14:22Z | TB-004 drafter Machinetalk spec | C3 |
