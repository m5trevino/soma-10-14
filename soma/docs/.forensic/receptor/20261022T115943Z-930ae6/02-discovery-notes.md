# Discovery Notes: Receptor

TARGET: receptor
RUN ID: 20261022T115943Z-930ae6
CAPTURED: 2026-10-22T11:59:43Z

## Target lock
Canonical target: `receptor`.
The receptor concept in this codebase manifests in three distinct artifacts:
1. `machinetalk/soma_bridge.py:write_receptor()` — LIVE, creates `ReceptorLog` nodes
2. `pipeline/receptor_dendrite.py` — ORPHAN, `ReceptorDendrite` class never imported by production code
3. `soma/helpers.py:get_receptor_config()` — LIVE code, queries `ReceptorConfig` nodes (zero exist in output)

All three share the name "receptor" but serve different roles. This report documents the complete receptor ecosystem.

## Inventory summary
- Project root: `/home/flintx/soma-10-14/soma` (179 files at depth 3)
- Repository: No `.git` directory found — ARCHIVE-BASED state
- Entry points for receptor:
  - `pipeline/receptor_dendrite.py` — 136 lines, mtime 2026-10-18T21:42Z [E-001]
  - `test_receptor_dendrite.py` — 281 lines, mtime 2026-10-18T21:43Z [E-002]
  - `machinetalk/soma_bridge.py:write_receptor()` — 22 lines, [E-003]
  - `soma/helpers.py:get_receptor_config()` — 21 lines, [E-004]
- Newest file: `docs/classifier-forensic.md` (2026-10-22T04:58Z)
- Receptor-related files are not among newest — last modified 2026-10-18

## Entry points
| Path | Host | Lines | Mtime | Role |
|------|------|-------|-------|------|
| `pipeline/receptor_dendrite.py` | flintx | 136 | 2026-10-18T21:42Z | Orphan class + strip_raw [E-001] |
| `test_receptor_dendrite.py` | flintx | 281 | 2026-10-18T21:43Z | Tests only [E-002] |
| `machinetalk/soma_bridge.py:write_receptor()` | flintx | 22 | ~2026-10-18 | LIVE: creates ReceptorLog [E-003] |
| `soma/helpers.py:get_receptor_config()` | flintx | 21 | ~2026-10-18 | LIVE: queries ReceptorConfig [E-004] |

## Runtime state
- Receptor is NOT a standalone process or service.
- Receptor is a Soma graph node type created during engine runs.
- 60 `ReceptorLog` nodes observed in `output/soma.json` [E-011].
- Zero `ReceptorConfig` nodes observed in `output/soma.json` [E-012].
- Runtime creation triggered by `stage == "distiller"` in engine runs.

## Data stores
- **Soma graph**: `output/soma.json` — JSON-backed graph store. Contains 60 `ReceptorLog` nodes [E-011]. Node ID pattern: `receptor-{chatset_id}`. Properties: id, session_id, chat_set_id, set_number, model_id, latency_ms, verdict, skipped, timestamp.
- **No database** for receptor-specific data. All receptor state is in the Soma JSON graph.

## Configuration and invariants
- `soma/helpers.py:get_receptor_config(soma, name)` queries nodes by type `"ReceptorConfig"` [E-004]. Matches on `name` or `stage` property. Returns `dict | None`.
- `put_receptor_config(soma, name, instruction_body, stage)` creates/updates `ReceptorConfig` nodes — but this function is never called by any production code observed [E-012].
- `machinetalk/client.py:_STAGE_MAP["receptor"] = "distiller"` maps receptor stage name to distiller model [E-005].
- `ReceptorDendrite.run()` docstring states: "NO LLM calls. NO graph writes." [E-001] — but this class is never instantiated.

## Cross-component edges
| Direction | Mechanism | Payload | Evidence |
|-----------|-----------|---------|----------|
| engine → bridge | `write_receptor()` call | gate, rec.model, latency, session_id, chatset_id | `machinetalk/engine.py:448-450` [E-006] |
| bridge → soma | `soma.create_node("ReceptorLog", ...)` | id, session_id, chat_set_id, set_number, model_id, latency_ms, verdict, skipped, timestamp | `machinetalk/soma_bridge.py:82-103` [E-003] |
| engine → soma | `soma._persist()` after each stage | Full graph state | `machinetalk/soma_bridge.py:107` [E-007] |
| run_engine → bridge | `bridge.write_receptor()` | same fields | `run_engine.py:242-248` [E-008] |
| client → stage | `_STAGE_MAP["receptor"] = "distiller"` | model name mapping | `machinetalk/client.py:16` [E-005] |
| pipeline → soma | ReceptorDendrite.run() → soma.get_node() | (never called) | `pipeline/receptor_dendrite.py:72-74` [E-009] |

## Instructions and recency
- `machine-talk/tb-002-pipeline-protocol.md` — pipeline handoff spec, mentions nexus→spark→falcon→eagle→owl→scout→drafter. No receptor-specific protocol. [E-010]
- `PIPELINE_ACTION_MAP.md` — no receptor section. Only references `get_receptor_config` for config lookup. [E-010]
- `pipeline/receptor_dendrite.py` docstring: "TB-TK-REPLACE-001: ReceptorDendrite — Heuristic chatset cleaner." — suggests replacement intent. [E-001]
- No machine-talk spec (tb-XXX) for receptor. No tb-006-outrobeaver or tb-010-eagle cover receptor. [E-010]

## Conflicts
CONFLICT C-01
  claim A: `pipeline/receptor_dendrite.py` docstring says "Queries a ChatSet node from the Soma graph, extracts the raw text (user_text + assistant_text), runs deterministic whitespace stripping" [E-001]
  claim B: Zero production imports of `ReceptorDendrite` found — `rg 'from pipeline.receptor_dendrite'` returns nothing outside tests [E-009]
  resolution: both-live — the spec exists but is not wired into production
  impact: The documented behavior (whitespace stripping + metrics) is the SPEC, not the actual pipeline behavior. The actual receptor behavior is ReceptorLog creation in the machinetalk pathway.
  basis: import graph scan [E-009]

CONFLICT C-02
  claim A: `soma/helpers.py:get_receptor_config()` and `put_receptor_config()` exist for managing instruction templates [E-004]
  claim B: Zero `ReceptorConfig` nodes exist in output data [E-012]
  resolution: both-live — the helper functions are compiled into production code but no ReceptorConfig nodes have ever been created in any output
  impact: The instruction-template pathway is defined but unused
  basis: output/soma.json scan [E-012]

## Unknowns and boundary gaps
### U-01: No git history available (no `.git` directory). Cannot determine when receptor code was added, who authored it, or how it evolved. Would need access to the parent repository or prior archives.
### U-02: The `TB-TK-REPLACE-001` identifier in the docstring suggests this module is a planned replacement for an older receptor implementation. No older receptor code found. The original implementation is UNKNOWN.
### U-03: `get_receptor_config()` is imported by 5 production dendrites (classifier, nexus, spark, falcon, retrograde) but always with a fallback to a default instruction. Never tested for the case where no ReceptorConfig exists. The actual behavior when no config is found is: falls back to inline defaults — but this is inferred, not tested.
### U-04: No `tb-XXX` machine-talk spec exists for the receptor. The receptor's contract with upstream (distiller) and downstream consumers is documented only by code structure, not by a spec document.
### U-05: Remote (Hetzner) host not probed for receptor-related state. Would need `ssh engine` access to verify if ReceptorLog or ReceptorConfig nodes are created in the remote engine output.

## Evidence index
| ID | Host | Kind | Locator | Captured At | Proves | Confidence |
|----|------|------|---------|-------------|--------|------------|
| E-001 | flintx | source | `pipeline/receptor_dendrite.py:1-136` | 2026-10-22T11:59Z | ReceptorDendrite class definition, ReceptorOutput dataclass, strip_raw function | C2 |
| E-002 | flintx | source | `test_receptor_dendrite.py:1-281` | 2026-10-22T11:59Z | All tests reference only pipeline/receptor_dendrite.py, no production module imports | C2 |
| E-003 | flintx | source | `machinetalk/soma_bridge.py:82-103` | 2026-10-22T11:59Z | write_receptor() creates ReceptorLog nodes, called on stage="distiller" | C2 |
| E-004 | flintx | source | `soma/helpers.py:5-25` | 2026-10-22T11:59Z | get_receptor_config() queries ReceptorConfig nodes by name or stage | C2 |
| E-005 | flintx | source | `machinetalk/client.py:16` | 2026-10-22T11:59Z | _STAGE_MAP["receptor"] = "distiller" maps receptor to distiller model | C2 |
| E-006 | flintx | source | `machinetalk/engine.py:448-450` | 2026-10-22T11:59Z | Production call site: `if stage == "distiller": self._bridge.write_receptor(...)` | C2 |
| E-007 | flintx | source | `machinetalk/soma_bridge.py:107` | 2026-10-22T11:59Z | soma._persist() called after each stage write | C2 |
| E-008 | flintx | source | `run_engine.py:242-248` | 2026-10-22T11:59Z | Secondary production call site: bridge.write_receptor() | C2 |
| E-009 | flintx | grep | `rg 'from pipeline.receptor_dendrite'` returns 0 results outside tests | 2026-10-22T11:59Z | ReceptorDendrite is never imported by production code | C1 |
| E-010 | flintx | source | `machine-talk/*.md` | 2026-10-22T11:59Z | No machine-talk spec for receptor exists | C2 |
| E-011 | flintx | data | `output/soma.json` — 60 ReceptorLog nodes | 2026-10-22T11:59Z | ReceptorLog nodes exist in real output data | C1 |
| E-012 | flintx | data | `output/soma.json` — 0 ReceptorConfig nodes | 2026-10-22T11:59Z | No ReceptorConfig nodes have been created | C1 |

## Report plan
1. Mandate: receptor is the distiller result logging layer — creates ReceptorLog nodes from stage-1 distiller runs
2. Current State: Two code paths exist; one live (machinetalk bridge), one orphaned (pipeline dendrite); config helper is live but unused
3. Key Paths: 4 entry points documented above
4. Architecture: ASCII context diagram showing distiller → write_receptor → ReceptorLog → downstream dendrites
5. Core Logic: write_receptor flow from engine → bridge → soma persistence
6. Configuration: _STAGE_MAP mapping; get_receptor_config helper
7. Dependencies: upstream (distiller/engine), downstream (no one reads ReceptorLog)
8. Known Gaps: U-01 through U-05
