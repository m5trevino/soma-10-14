# Discovery Notes: drafter

TARGET: drafter
RUN: 20261022T142207Z-015d91
CAPTURED: 2026-10-22T14:22:10Z

## 1. Target lock

MATCHED — target `drafter` confirmed against `fdd_targets.json`.
SLUG: drafter. Scope: generates reference application and maps FileNodes into Soma.

## 2. Inventory summary

- 184 files at `soma/` depth-3 (including tests, runners, machinetalk).
- 2 candidate roots for drafter:
  - `soma/drafter_dendrite.py` (631 lines, mtime 2026-10-18T01:40Z) — **active implementation**
  - `soma/pipeline/drafter_dendrite.py` (190 lines, mtime 2026-10-14T19:16Z) — **stub**
- Machinetalk engine: `machinetalk/engine.py:732-733` calls `write_drafter`.
- Pipeline runner: `run_pipeline.py:29` imports `DrafterDendrite` from root.
- Test imports: `test_integrator_dendrite.py:25`, `test_retrograde_dendrite.py:26` import `LLMResponse` from `pipeline.drafter_dendrite`.
- Machine Talk spec: `machine-talk/tb-011-drafter.md` — TB-004 drafter contract (631-line version).

## 3. Entry points

| Path | Lines | Mtime | Role | Entrypoint? |
|------|-------|-------|------|-------------|
| `soma/drafter_dendrite.py` | 631 | 2026-10-18T01:40Z | Active DrafterDendrite class + ToolRegistry + MockLLMClient | YES — class DrafterDendrite @L287 |
| `soma/pipeline/drafter_dendrite.py` | 190 | 2026-10-14T19:16Z | Stub LLMClient/LLMResponse/ModelRotator/ToolRegistry | NO — stubs only |

## 4. Runtime state

- **Not running** as a standalone service. It is called by:
  - `run_pipeline.py` (STAGE 5) — direct instantiation `DrafterDendrite(self._soma, d_llm, d_rot)` then `drafter.run(self._session_id)` [E-004]
  - `run_new_session.py` — same pattern [E-005]
  - `machinetalk/engine.py` — as stage3 build stage via `_run_build_stage("drafter", payload)` [E-006], then `_bridge.write_drafter(build, gate, model, latency)` [E-007]
- `machinetalk/engine.py` classifies `drafter` as `stage3` [E-001].
- No dedicated port or health endpoint for the drafter alone.

## 5. Data stores

- Uses `store.Soma` — graph store with nodes/edges.
- `soma_bridge.write_drafter` creates a `ReferenceArtifactNode` with id `artifact-{session_id}` [E-008].
- Workspace path resolved via `workspace.workspace_for(session_id)` — writes files under `chats/<session_id>/` [E-009].
- Files written to `/tmp/` by the root drafter for fallback code extraction [E-010] (per docstring TB-DRAFT-004).

## 6. Configuration and invariants

- `DrafterDendrite.COMPLETION_TOKEN_CEILING = 16000` — token ceiling warning threshold [E-011].
- `_CODE_FENCE_RE` — regex for triple-backtick/triple-tilde fenced code block extraction [E-012].
- `normalize_draft_relpath()` — path sanitization rejecting `..` escapes [E-013].
- Hard gates from docstring:
  - No physical files except workspace files under `chats/<session_id>/` [E-014]
  - All Soma access via tool calls [E-015]
  - Uses active model rotation [E-016]
- Machinetalk hard gates from `tb-011-drafter.md`:
  - Every `function_spec` from PlanBeaver MUST have implementation or TODO marker [E-017]
  - All files MUST have `parses_clean == true` [E-018]
  - MUST NOT optimize, harden invariants, or scope-creep [E-019]

## 7. Cross-component edges

| Direction | Mechanism | Payload | Evidence |
|-----------|-----------|---------|----------|
| upstream: `machinetalk/engine.py` | `_run_build_stage("drafter", payload=...)` | `{"session_id", "planbeaver_output", "template_library", "style_guide"}` | `engine.py:849-862` [E-020] |
| upstream: `run_pipeline.py` | Direct import + `DrafterDendrite(...).run(session_id)` | None (session_id only) | `run_pipeline.py:140-141` [E-021] |
| downstream: `soma_bridge.write_drafter` | `gate.parsed["draft_artifact"]["files"]` | Draft artifact files array | `soma_bridge.py:272-292` [E-022] |
| downstream: `scout_dendrite` | Reads `DraftArtifactNode` / `FileNode` created by drafter | File nodes for invariant checking | `scout_dendrite.py:3,75` [E-023] |
| sibling: `pipeline.drafter_dendrite` | Import target for `LLMResponse`, `LLMClient`, `MockLLMClient` | Infra stubs | `test_integrator_dendrite.py:25` [E-024] |

## 8. Instructions and recency

| Doc | Mtime | Authority |
|-----|-------|-----------|
| `machine-talk/tb-011-drafter.md` | Not probed (static spec) | Spec: TB-004 drafter contract (Machinetalk mode) [E-025] |
| `soma/drafter_dendrite.py` docstring | 2026-10-18 | Source: TB-SOMA-004, TB-DRAFT-003, TB-DRAFT-004, TB-DRAFT-006-009 |
| `machinetalk/engine.py` stage classification | 2026-10-21 | stage3 [E-001] |

## 9. Conflicts

CONFLICT C-01
  claim A: 631-line `drafter_dendrite.py` at root is the active DrafterDendrite with full run() workflow (Phase 1 map, Phase 2 generate, workspace write)
  source: `soma/drafter_dendrite.py:287` | mtime: 2026-10-18T01:40Z
  claim B: 190-line `drafter_dendrite.py` in `pipeline/` is a minimal stub with LLMClient/LLMResponse/ModelRotator stubs
  source: `soma/pipeline/drafter_dendrite.py` | mtime: 2026-10-14T19:16Z
  resolution: both-live
  basis: import graph — `run_pipeline.py:29` imports `DrafterDendrite` from root; `run_pipeline.py:33` imports `LLMClient as DrafterLLM` from pipeline; `test_integrator_dendrite.py:25` imports `LLMResponse` from pipeline. The root file is the full implementation. The pipeline file is a stub.
  impact: pipeline stub is used only as import target for LLM types by tests; root file is the executable drafter. They serve different purposes but share the same filename in different directories.

CONFLICT C-02
  claim A: Drafter in machinetalk engine uses `planbeaver_output` with a rigid JSON contract (tb-011-drafter.md) and calls `write_drafter` on soma_bridge
  source: `machinetalk/engine.py:849-862`, `soma_bridge.py:272-292` | mtime: 2026-10-21T19:43Z
  claim B: Drafter in run_pipeline.py uses its own `run(session_id)` with Phase 1/Phase 2 LLM calls and direct Soma node creation
  source: `soma/drafter_dendrite.py:run() @L443` | mtime: 2026-10-18T01:40Z
  resolution: both-live (different execution contexts)
  basis: two distinct entry points invoke different behavior paths. Machinetalk path is spec-driven with JSON payloads; pipeline path is LLM-driven with Phase 1/2 calls.
  impact: the drafter component has two separate execution paths that must be documented. They are not interchangeable.

## 10. Unknowns and boundary gaps

U-01: The Machinetalk engine's `_run_build_stage("drafter", ...)` runs an LLM build stage with `planbeaver_output` payload. The actual LLM response from that stage is consumed by `soma_bridge.write_drafter`. However, the intermediate LLM response (what the engine captures as `gate`) is not fully documented in `soma_bridge.py:272-292` — it reads `gate.parsed["draft_artifact"]["files"]` but we don't know the exact transformation pipeline inside `_run_build_stage` for the drafter specifically. Evidence needed: full source of `_run_build_stage` with drafter-specific logic.

U-02: The `soma_bridge.write_drafter` creates a single `ReferenceArtifactNode` combining all files into one `artifact_text` field (truncated to 20000 chars). However, the root `DrafterDendrite.run()` creates individual `ReferenceArtifactNode` + `FileNode` per file and links them via `PRODUCES` edges. These are different node architectures — U-02 is whether these two approaches produce compatible Soma graphs.

U-03: `run_tb005.py` is labeled "TB-005 Runner — Nexus Dendrite" but the machinetalk spec says TB-005 is PlanBeaver and TB-004 is Drafter. The runner file is mislabeled. No explicit test runner exists for the root `DrafterDendrite` class alone (tb-011-drafter.md references TB-004 but no `run_tb004.py` exists in the file tree — `run_tb004.py` exists but is actually for RetrogradeDendrite per its own docstring at L1).

## 11. Evidence index

| ID | Host | Kind | Locator | Proves | Conf |
|----|------|------|---------|--------|------|
| E-001 | flintx | source | `machinetalk/engine.py:100` | drafter classified as stage3 | C2 |
| E-004 | flintx | source | `run_pipeline.py:29,140-141` | root DrafterDendrite instantiated in pipeline | C2 |
| E-005 | flintx | source | `run_new_session.py:17` | root DrafterDendrite imported in new session runner | C2 |
| E-006 | flintx | source | `machinetalk/engine.py:849-862` | engine runs drafter build stage with planbeaver payload | C2 |
| E-007 | flintx | source | `machinetalk/engine.py:732-733` | engine calls write_drafter bridge after stage | C2 |
| E-008 | flintx | source | `machinetalk/soma_bridge.py:283-290` | write_drafter creates ReferenceArtifactNode in soma | C2 |
| E-009 | flintx | source | `soma/drafter_dendrite.py:425-427` | workspace_for resolves path under chats/<session_id>/ | C2 |
| E-010 | flintx | source | `soma/drafter_dendrite.py:docstring L8` | fallback code written to /tmp/ | C3 |
| E-011 | flintx | source | `soma/drafter_dendrite.py:292` | COMPLETION_TOKEN_CEILING = 16000 | C2 |
| E-012 | flintx | source | `soma/drafter_dendrite.py:295-298` | _CODE_FENCE_RE regex | C2 |
| E-013 | flintx | source | `soma/drafter_dendrite.py:204-220` | normalize_draft_relpath sanitization | C2 |
| E-014..016 | flintx | source | `soma/drafter_dendrite.py:docstring L15-17` | hard gates documented | C3 |
| E-017..019 | flintx | source | `machine-talk/tb-011-drafter.md` | Machinetalk hard gates | C3 |
| E-020 | flintx | source | `machinetalk/engine.py:855-861` | drafter payload structure from engine | C2 |
| E-021 | flintx | source | `run_pipeline.py:140-141` | pipeline drafter invocation | C2 |
| E-022 | flintx | source | `machinetalk/soma_bridge.py:272-292` | bridge write_drafter function | C2 |
| E-023 | flintx | source | `scout_dendrite.py:3,75` | scout reads FileNodes created by drafter | C2 |
| E-024 | flintx | source | `test_integrator_dendrite.py:25` | pipeline stub LLMResponse imported by tests | C2 |
| E-025 | flintx | source | `machine-talk/tb-011-drafter.md` | TB-004 drafter Machinetalk spec | C3 |

## 12. Report plan

1. **Mandate** — drafter generates code files and maps them to Soma nodes.
2. **Current State** — two files, root is active, pipeline is stub.
3. **Key Paths** — table of both files, engine.py, soma_bridge.py.
4. **Architecture** — ASCII context diagram showing engine ↔ drafter ↔ soma_bridge ↔ scout.
5. **Core Logic** — trace root DrafterDendrite.run() Phase 1→Phase 2→write; trace engine Machinetalk path.
6. **Configuration** — token ceiling, regex, path sanitization, hard gates from spec.
7. **Dependencies** — upstream (engine, run_pipeline), downstream (soma_bridge, scout), sibling (pipeline stub).
8. **Known Gaps** — U-01, U-02, U-03 with evidence needed.
9. **Evidence Log** — from index above.
