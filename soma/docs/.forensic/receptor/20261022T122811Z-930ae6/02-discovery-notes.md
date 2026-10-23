# Discovery Notes: receptor

TARGET: receptor | RUN: 20261022T122811Z-930ae6

## Target lock

TARGET: receptor
SLUG: receptor
RUN ID: 20261022T122811Z-930ae6
HOST: flintx
SCOPE: Ingests a chat set and produces the raw receptor output consumed by classification.
EXCLUDED: soma, classifier, integrator, retrograde, nexus, spark, falcon, drafter, axon, scout, myelinator, terminal, saltatory-gate, ai-engine, turn-key, session-seeder, classifier-dendrite, all sibling dendrites

## Inventory summary

- Project root: `/home/flintx/soma-10-14/soma` — 180 files at depth 3
- Git: no `.git` directory (archive-only copy)
- Newest files: `docs/receptor-forensic.md` (2026-10-22T05:06), `docs/classifier-forensic.md` (2026-10-22T04:58)
- Output data: `output/soma.json` (2026-10-21T20:03)
- Entry points discovered: 6 (see below)
- Data stores: 1 (output/soma.json, 2.5 MB)
- No remote probe completed (ssh engine not tested)

## Entry points

1. `machinetalk/soma_bridge.py:82-103` — `write_receptor()` — LIVE, production trigger from engine
2. `machinetalk/engine.py:449` — calls `self._bridge.write_receptor()` — LIVE trigger site
3. `run_engine.py:243` — calls `bridge.write_receptor()` — LIVE secondary trigger (soma-only mode)
4. `soma/helpers.py:5-13` — `get_receptor_config()` — LIVE helper, imported by 5 dendrites
5. `soma/helpers.py:14-25` — `put_receptor_config()` — LIVE helper, no callers found
6. `machinetalk/client.py:16` — `_STAGE_MAP["receptor"] = "distiller"` — config mapping

ORPHAN entry points (never imported in production):
- `pipeline/receptor_dendrite.py:63-134` — `ReceptorDendrite` class
- `pipeline/receptor_dendrite.py:24-41` — `ReceptorOutput` dataclass
- `pipeline/receptor_dendrite.py:44-57` — `strip_raw()` function

## Runtime state

- No receptor-specific process running (not a daemon)
- `write_receptor()` is called synchronously inside engine.py's `_run_chatset_stage()` method [E-006]
- `write_receptor()` is called synchronously inside run_engine.py's `--soma-only` path [E-008]
- No HTTP endpoint, no queue, no service unit
- ReceptorLog nodes persist in `output/soma.json` after graph save [E-011]

## Data stores

**`output/soma.json`** (2026-10-21T20:03Z, ~2.5 MB)
- Contains 60 `ReceptorLog` nodes (pattern: `id` starts with `receptor-`) [E-011]
- Contains 0 `ReceptorConfig` nodes [E-012]
- 0 `ReceptorDendrite` or `ReceptorOutput` nodes (expected — these are Python classes, not graph nodes)
- Sample ReceptorLog properties: `id`, `session_id`, `chat_set_id`, `set_number`, `model_id`, `latency_ms`, `verdict`, `skipped`, `timestamp`
- All ReceptorLog nodes have `PROCESSED_BY` edge from the corresponding ChatSet

## Configuration and invariants

| Config | Value/Default | Source | Enforced |
|--------|--------------|--------|----------|
| `_STAGE_MAP["receptor"]` = `"distiller"` | literal `"distiller"` | `machinetalk/client.py:16` | `machinetalk/client.py:146` |
| `get_receptor_config(soma, name)` | `None` (no ReceptorConfig nodes) | `soma/helpers.py:10` | `soma/helpers.py:5-13` |
| `write_receptor()` node_id pattern | `f"receptor-{chatset_id}"` | `machinetalk/soma_bridge.py:85` | code |
| `write_receptor()` edge | `chatset_id →PROCESSED_BY→ receptor-{chatset_id}` | `machinetalk/soma_bridge.py:102` | code |
| `strip_raw()` pattern | `_EXCESS_BLANK = re.compile(r"\n{4,}")` | `pipeline/receptor_dendrite.py:29` | code |
| `ReceptorOutput` fields | 8 fields: chatset_id, cleaned_text, compression_ratio, bytes_original, bytes_cleaned, whitespace_removed, lines_original, lines_cleaned | `pipeline/receptor_dendrite.py:24-41` | dataclass |

No env vars, no `.env` keys, no service units for receptor.

## Cross-component edges

1. **distiller → write_receptor** — `machinetalk/engine.py:448`: `if stage == "distiller":` triggers `write_receptor()` call. Mechanism: conditional function call. Payload: sid, chatset_id, set_number, gate, model, latency. Evidence: `machinetalk/engine.py:449` [E-006]
2. **write_receptor → Soma graph** — `machinetalk/soma_bridge.py:91-102`. Mechanism: `create_node("ReceptorLog", ...)` + `create_edge(...)`. Payload: full ReceptorLog properties + edge. Evidence: `machinetalk/soma_bridge.py:82-103` [E-003]
3. **get_receptor_config → 5 dendrites** — classifier, nexus, spark, falcon, retrograde import and call `get_receptor_config(soma, <stage>)`. Mechanism: function call. Evidence: grep results [E-005]
4. **drafter_dendrite.py → ReceptorConfig** — `drafter_dendrite.py:184-189` implements its own `_get_receptor_config(agent_id)` with different signature (agent_id vs name/stage). Mechanism: direct Soma query. Evidence: `drafter_dendrite.py:184-189`
5. **ReceptorDendrite (orphan) → store** — `pipeline/receptor_dendrite.py:16`: `from store import Soma, Node`. Mechanism: Python import. Never resolved in production. Evidence: `rg` results [E-009]
6. **Soma → soma.json** — `soma_bridge.py:107` calls `self._soma._persist()` after each stage write. Mechanism: JSON serialization. Evidence: `machinetalk/soma_bridge.py:107` [E-007]

## Instructions and recency

| Doc | Path | Date | Authority |
|-----|------|------|-----------|
| receptor-forensic.md | docs/receptor-forensic.md | 2026-10-22T05:06Z | C3 — previous run |
| classifier-forensic.md | docs/classifier-forensic.md | 2026-10-22T04:58Z | C3 — previous run |
| SESSION_HANDOFF.md | SESSION_HANDOFF.md | ~2026-10-18 | C3 |
| PIPELINE_ACTION_MAP.md | PIPELINE_ACTION_MAP.md | ~2026-10-18 | C3 |

No target-local design docs (no `receptor.md` or `TB-XXX-receptor.md` in machine-talk/).

## Conflicts

No conflicts found between live code, source, and data. The orphan ReceptorDendrite is the only structural anomaly: it exists as source code with tests but is never imported by production. This is intentional design (planned replacement TB-TK-REPLACE-001), not a conflict.

## Unknowns and boundary gaps

U-01: No consumer for ReceptorLog. Zero production code queries `ReceptorLog` nodes or follows `PROCESSED_BY` edges. Unclear whether intentional (logging-only artifact) or incomplete implementation.

U-02: TB-TK-REPLACE-001 — original implementation unknown. The docstring at `pipeline/receptor_dendrite.py:1` references this task but no prior receptor source was found in the archive.

U-03: Remote host not probed. The Hetzner remote (`ssh engine`, `100.87.51.23`) was not accessed. Receptor state on the remote may differ.

U-04: Drafter's `_get_receptor_config()` uses `agent_id`; `soma.helpers.get_receptor_config()` uses `name`/`stage`. Semantic difference is unverified.

U-05: `put_receptor_config()` has zero callers. UNKNOWN whether used historically or dead code.

## Evidence index

See 03-evidence-index.tsv (generated during report draft).

## Report plan

1. Mandate — one sentence on what receptor exists to do
2. Current State — three sub-components with liveness status
3. Key Paths and Entry Points — table of all 6 entry points
4. Architecture and Data Flow — ASCII diagram
5. Core Logic — three paths: live (write_receptor), orphan (ReceptorDendrite), helper (get_receptor_config)
6. Configuration and Invariants — table
7. Dependencies and Cross-Component Connections — upstream, downstream, orphan
8. Known Gaps and Uncertainties — U-01 through U-05
9. Evidence Log — numbered entries
