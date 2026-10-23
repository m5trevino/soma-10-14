# Falcon — Discovery Notes
TARGET: falcon | RUN: 20261022T141811Z-c590af | DATE: 2026-10-22T14:18Z

## Target lock
TARGET: falcon
SLUG: falcon
RUN ID: 20261022T141811Z-c590af
BASE DIR: /home/flintx/soma-10-14/soma
SCOPE: FalconDendrite — architecture derivation and contract building

## Inventory summary
- falcon_dendrite.py: 261 lines, mtime 2026-10-17T19:59Z
- run_tb009.py: 123 lines, mtime 2026-10-17T18:40Z
- run_tb007.py: 135 lines, mtime 2026-10-17T18:40Z
- test_tb_fix_001.py: 248 lines, mtime 2026-10-17T18:40Z
- run_pipeline.py: 291 lines, references falcon
- run_new_session.py: 156 lines, references falcon
- run_new_session_fix.py: 144 lines, references falcon
- machinetalk/engine.py: ~1032 lines, write_falcon + build stage path
- machinetalk/soma_bridge.py: 537 lines, write_falcon method
- machinetalk/fleet.py: 189 lines, FLEET prompt entry for falcon
- machinetalk/checkpoint.py: 293 lines, upstream=["spark"]
- machinetalk/gate.py: 289 lines, StageSpec for falcon
- pipeline/stage_complete.py: 88 lines, complete_stage() called by falcon
- pipeline/llm_sdk.py: 82 lines, stage mapping "falcon" → "falcon"
- store.py: 135 lines, Soma graph store
- soma/helpers.py: 26 lines, get_receptor_config helper
- tb-009-falcon.md: NOT FOUND in machinetalk/ directory (G-02)

## Entry points
- `falcon_dendrite.py:29` — class FalconDendrite definition
- `falcon_dendrite.py:50` — run() method
- `falcon_dendrite.py:156` — create_constrained_by() method
- `falcon_dendrite.py:190` — _build_contract_from_constraints() method
- `machinetalk/soma_bridge.py:231` — write_falcon() method (bridge path)

## Runtime state
- No falcon daemon observed — component runs as a synchronous module within pipeline runners
- tb-009-falcon.md prompt file: NOT FOUND — would cause FileNotFoundError at runtime if load_system_prompt("falcon") is called
- `ps -eo pid,etimes,cmd`: NOT PROBED — Falcon is not a standalone service

## Data stores
- Soma graph (JSON file, path determined by Soma constructor)
- Nodes created: ArchitectureNode, ArchitectureContractNode, ReceptorConfig (query)
- Edges created: DERIVED_FROM, CONSTRAINED_BY, LOCKS
- Checkpoint JSON: `checkpoints/<session_id>.checkpoint.json` — falcon status tracked in session_stages

## Configuration and invariants
- Default instruction: falcon_dendrite.py:26-33
- CHOSEN keys: frozenset(("store", "navigation", "backend")) — falcon_dendrite.py:38
- Gate spec: requires plan_hash_verification + component_architecture — gate.py:92
- Checkpoint upstream: ["spark"] — checkpoint.py:63
- Stage group: stage2 — fleet.py:76
- Fleet prompt: tb-009, FALCON_PAYLOAD marker — fleet.py:59
- TurnKeyClient stage map: "falcon" → "falcon" — llm_sdk.py:25

## Cross-component edges
- RequirementsNode ← query_by_type("RequirementsNode") — falcon_dendrite.py:53-58
- ConstraintNodes ← query_by_type("ConstraintNode") — falcon_dendrite.py:204-206
- ReceptorConfig ← query_by_type("ReceptorConfig") — helpers.py:12
- LLM ← complete_stage() — stage_complete.py:23
- ArchitectureNode ← create_node — falcon_dendrite.py:79-86
- ArchitectureContractNode ← create_node — falcon_dendrite.py:135-142
- DERIVED_FROM edge — falcon_dendrite.py:89-92
- CONSTRAINED_BY edges — falcon_dendrite.py:94
- LOCKS edge — falcon_dendrite.py:143-147
- Engine bridge: write_falcon() creates different ID prefix — soma_bridge.py:231-258

## Instructions and recency
- falcon_dendrite.py (2026-10-17T19:59Z) — NEWEST, authoritative source
- test_tb_fix_001.py (2026-10-17T18:40Z) — tests create_constrained_by
- run_tb009.py (2026-10-17T18:40Z) — full pipeline runner
- run_tb007.py (2026-10-17T18:40Z) — standalone TB-007 runner
- All machinetalk/*.py — mtime ~2026-10-17
- tb-009-falcon.md — MISSING

## Conflicts
None identified in current codebase. Two distinct paths exist:
- FalconDendrite.run() → creates "arch-{id}" nodes, uses LOCKS edges
- SomaBridge.write_falcon() → creates "architecture-{id}" nodes, uses GOVERNED_BY edges
These do not conflict as they operate in separate call contexts.

## Unknowns and boundary gaps
- U-01: tb-009-falcon.md prompt file not found — would cause FileNotFoundError if load_system_prompt("falcon") called
- U-02: rotator parameter always None, never used in run() — dead parameter?
- U-03: complete_stage imports LLMClient/LLMResponse from drafter_dendrite — circular/unexpected dependency
- U-04: FalconDendrite and SomaBridge write different node IDs — could coexist or conflict
- U-05: Contract build error prevents LOCKS edge — downstream eagle behavior unknown
- U-06: No unit test for FalconDendrite.run() full path — only integration testing
- U-07: No live process probe performed — cannot confirm whether falcon runs as daemon

## Evidence index
| ID | Host | Kind | Locator | Captured at | Proves | Confidence |
|---|---|---|---|---|---|---|
| E-001 | flintx | source read | falcon_dendrite.py:29 | 2026-10-22T14:18Z | FalconDendrite class exists | C1 |
| E-002 | flintx | source read | run_tb009.py:80 | 2026-10-22T14:18Z | Pipeline calls falcon | C1 |
| E-003 | flintx | source read | run_tb007.py:80 | 2026-10-22T14:18Z | Standalone runner calls falcon | C1 |
| E-004 | flintx | source read | run_pipeline.py:131 | 2026-10-22T14:18Z | General pipeline calls falcon | C1 |
| E-005 | flintx | source read | run_new_session.py:16 | 2026-10-22T14:18Z | New session imports falcon | C1 |
| E-006 | flintx | source read | run_new_session_fix.py:13 | 2026-10-22T14:18Z | Fix runner imports falcon | C1 |
| E-007 | flintx | source read | test_tb_fix_001.py | 2026-10-22T14:18Z | Tests for create_constrained_by | C1 |
| E-008 | flintx | source read | store.py | 2026-10-22T14:18Z | Soma graph store | C1 |
| E-009 | flintx | source read | soma/helpers.py | 2026-10-22T14:18Z | get_receptor_config | C1 |
| E-010 | flintx | source read | pipeline/stage_complete.py | 2026-10-22T14:18Z | complete_stage LLM wrapper | C1 |
| E-011 | flintx | source read | machinetalk/engine.py:730 | 2026-10-22T14:18Z | Engine calls write_falcon | C1 |
| E-012 | flintx | source read | machinetalk/soma_bridge.py:231 | 2026-10-22T14:18Z | Bridge writes falcon nodes | C1 |
| E-013 | flintx | source read | machinetalk/fleet.py:59 | 2026-10-22T14:18Z | Fleet prompt entry | C1 |
| E-014 | flintx | source read | machinetalk/checkpoint.py:63 | 2026-10-22T14:18Z | Upstream=[spark] | C1 |
| E-015 | flintx | source read | machinetalk/gate.py:92 | 2026-10-22T14:18Z | Gate spec for falcon | C1 |
| E-016 | flintx | source read | pipeline/llm_sdk.py:25 | 2026-10-22T14:18Z | Stage map falcon→falcon | C1 |
| E-017 | flintx | source read | falcon_dendrite.py:53 | 2026-10-22T14:18Z | RequirementsNode lookup | C1 |
| E-018 | flintx | source read | falcon_dendrite.py:79 | 2026-10-22T14:18Z | ArchitectureNode creation | C1 |
| E-019 | flintx | source read | falcon_dendrite.py:77 | 2026-10-22T14:18Z | Stale node deletion | C1 |
| E-020 | flintx | source read | falcon_dendrite.py:89 | 2026-10-22T14:18Z | DERIVED_FROM edge | C1 |
| E-021 | flintx | source read | falcon_dendrite.py:94 | 2026-10-22T14:18Z | CONSTRAINED_BY call | C1 |
| E-022 | flintx | source read | falcon_dendrite.py:97 | 2026-10-22T14:18Z | Contract building | C1 |
| E-023 | flintx | source read | falcon_dendrite.py:101 | 2026-10-22T14:18Z | Error early return | C1 |
| E-024 | flintx | source read | falcon_dendrite.py:135 | 2026-10-22T14:18Z | Contract node creation | C1 |
| E-025 | flintx | source read | falcon_dendrite.py:143 | 2026-10-22T14:18Z | LOCKS edge | C1 |
| E-026 | flintx | source read | falcon_dendrite.py:26 | 2026-10-22T14:18Z | Default instruction | C1 |
| E-027 | flintx | source read | falcon_dendrite.py:38 | 2026-10-22T14:18Z | CHOSEN keys | C1 |
| E-028 | flintx | source read | machinetalk/engine.py:832 | 2026-10-22T14:18Z | Engine build stage | C1 |
| E-029 | flintx | source read | pipeline/drafter_dendrite.py:126 | 2026-10-22T14:18Z | Drafter references falcon | C2 |
| E-030 | flintx | source read | machinetalk/client.py:26 | 2026-10-22T14:18Z | Client stage map | C1 |

## Report plan
1. Mandate — one sentence from E-001
2. Current State — E-001 through E-006
3. Key Paths and Entry Points — E-001 through E-016
4. Architecture and Data Flow — E-001, E-009, E-010, E-011, E-012, E-017, E-022, E-028
5. Core Logic — E-017 through E-027
6. Configuration and Invariants — E-026 through E-027, E-013, E-014, E-015
7. Dependencies and Cross-Component — E-009, E-010, E-011, E-012, E-013, E-014, E-015, E-016, E-017, E-022
8. Known Gaps — G-01 through G-7 (from U-01 through U-07, plus additional analysis)
9. Evidence Log — E-001 through E-030
