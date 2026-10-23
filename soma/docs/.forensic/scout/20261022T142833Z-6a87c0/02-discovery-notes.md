# Scout — Discovery Notes

## Target lock

TARGET: scout
SLUG: scout
RUN: 20261022T142833Z-6a87c0
HOST: flintx (MX Linux, SysVinit, Tailscale 100.99.23.82)
SCOPE: Forensic deep-dive of the scout component in the Soma dendritic pipeline. Two entry points discovered: (1) scout_dendrite.py (rule-based InvariantsDB), (2) machinetalk engine → write_scout (InvariantRegistry + LLM-generated violation report).
EXCLUDED: all other dendrites, soma, pipeline/ modules, machinetalk engine internals.

## Inventory summary

- Project root: `/home/flintx/soma-10-14/soma` — 186 files at depth 3.
- Repository: git-managed (`.gitignore` present).
- Newest file in tree: `docs/axon-forensic.md` (2026-10-22T07:28).
- scout_dendrite.py mtime: 2026-10-18T01:40 (148 lines).
- machinetalk/invariants.py: 66 lines, 4 default rules.
- No test file for scout found (`grep -rl "ScoutDendrite\|scout_dendrite" --include="*test*" → 0 results`).

## Entry points

| Path | Host | Role | Entrypoint? | Lines | Mtime | Evidence |
|------|------|------|-------------|-------|-------|----------|
| `scout_dendrite.py` | flintx (local) | Standalone ScoutDendrite class with InvariantsDB | Yes (standalone) | 148 | 2026-10-18T01:40 | E-001 |
| `machinetalk/engine.py:734-735` | flintx (local) | Engine stage runner → bridge.write_scout | Yes (engine) | ~1 | 2026-10-21T19:43 | E-002 |
| `machinetalk/engine.py:863-904` | flintx (local) | Scout build stage setup (run_build_stage, artifact parsing) | Yes (engine) | ~40 | 2026-10-21T19:43 | E-003 |
| `machinetalk/soma_bridge.py:320-351` | flintx (local) | write_scout — persists violations as InvariantQueryNodes | Yes (bridge) | 32 | 2026-10-21T19:36 | E-004 |
| `machinetalk/invariants.py:23-24` | flintx (local) | InvariantRegistry — queried by engine for scout contracts | Yes (invariants) | 66 | mtime unknown | E-005 |

## Runtime state

- No standalone scout process observed (not a daemon/service).
- scout runs as part of pipeline orchestration:
  - `run_pipeline.py` stage 6 (E-015)
  - `run_new_session.py` stage 6 (E-016)
  - `run_tb009.py` (E-017)
  - `walk.py` CRYSTALLIZE list (E-018)
- No HTTP endpoint for scout (not a web service).
- No port bound by scout.

## Data stores

| Store | Path | Engine | Access | Evidence |
|-------|------|--------|--------|----------|
| Soma graph | `store.py` JSON-backed | Python dict + file persistence | Read/write via Soma class | E-020 |
| InvariantsDB (standalone) | Inline in scout_dendrite.py:26-67 | Hardcoded `_RULES` dict | Read-only | E-006 |
| InvariantRegistry (engine) | `machinetalk/invariants.py:12-22` | `_DEFAULT_RULES` list + optional JSON file | Read-only | E-007 |
| Workspaces | `workspaces/` (empty) | Directory | Not probed — `exists=False` per inventory | E-021 |

## Configuration and invariants

### scout_dendrite.py — Hard gates (lines 8-10):
1. No physical file reads/writes
2. No access to monolithic code payload
3. Only writes InvariantQueryNodes + connecting edges

### machinetalk/tb-012-scout.md — Role contract:
- ROLE: `sovereign_invariant_detector`
- OUTPUT: `violation_report_payload`
- Hard gates: no code modification, no refactoring, no feature addition
- Severity levels: critical, high, medium, low, info
- Violation types: security, performance, correctness, style, contract, logic

### InvariantsDB rules (scout_dendrite.py:29-50):
- `*.py`: 3 rules (type hints, no mutable module vars, docstrings)
- `*.json`: 2 rules (valid JSON, root object/array)
- `*.md`: 1 rule (top-level heading)
- `*test*.py`: 2 rules (pytest fixtures, no prod path writes)
- `default`: 2 rules (no hardcoded secrets, explicit error handling)

### InvariantRegistry rules (machinetalk/invariants.py:13-42):
- INV-001 (CRITICAL, security): no secrets in source
- INV-002 (HIGH, correctness): clear input/output per public function
- INV-003 (HIGH, safety): no unbounded recursion/loops
- INV-004 (MEDIUM, style): no TODO/placeholder

## Cross-component edges

| Direction | Mechanism | Payload | Evidence |
|-----------|-----------|---------|----------|
| Drafter → Scout | Pipeline order (stage 5→6) | FileNode nodes in Soma | E-015, E-016, E-017 |
| Scout → AxonHillock | Pipeline order (stage 6→7) | InvariantQueryNode + GOVERNS edges | E-015, E-017 |
| Scout → Myelinator | Indirect — Myelinator queries InvariantQueryNodes for GOVERNS edges | E-030 (myelinator_olc.py:65-68) |
| Scout → Engine (bridge) | write_scout persists violations from LLM report | E-004 |
| Engine → Scout | _run_build_stage passes code chunk + contracts text to LLM | E-003 |

## Instructions and recency

| Doc | Path | Mtime | Authority |
|-----|------|-------|-----------|
| tb-012-scout.md (role contract) | `machine-talk/tb-012-scout.md` | mtime unknown | C3 |
| PIPELINE_ACTION_MAP.md | `PIPELINE_ACTION_MAP.md` | 2026-10-08 | C3 |
| scout_dendrite.py docstring | `scout_dendrite.py:1-10` | 2026-10-18 | C2 |

## Conflicts

CONFLICT C-01
  claim A: scout uses InvariantsDB (hardcoded mock rules by file extension) | source: scout_dendrite.py:26-67 | mtime: 2026-10-18
  claim B: scout uses InvariantRegistry (rule_id+family+severity+applies_to) queried from machinetalk/invariants.py | source: machinetalk/engine.py:873-876 | mtime: 2026-10-21
  resolution: both-live — two separate call paths use different invariant sources
  impact: Standalone/run_pipeline.py path uses hardcoded fnmatch rules; machinetalk engine path uses structured rule registry with severity/family metadata. Different rule counts, different matching mechanisms.

CONFLICT C-02
  claim A: Scout has 0 LLM calls (pure rule-based) | source: PIPELINE_ACTION_MAP.md | mtime: 2026-10-08
  claim B: Engine calls _run_build_stage(build, "scout", chunk=code, contracts=contracts_txt) which invokes LLM to produce violation report | source: machinetalk/engine.py:878 | mtime: 2026-10-21
  resolution: both-live — standalone path has 0 LLM calls; engine path has 1 LLM call per build
  impact: LLM-call metric is context-dependent. The standalone ScoutDendrite.run() makes zero LLM calls. The engine's scout stage calls the TurnKeyClient LLM to produce a text violation report.

## Unknowns and boundary gaps

### U-01: No test coverage for ScoutDendrite. `grep -rl "scout" --include="test_*.py" → 0 results`.
  Evidence needed: any test file or test invocation targeting scout.

### U-02: Scout output is not consumed by downstream stages in the standalone path. AxonHillock does not query InvariantQueryNodes; it only queries FileNode and Directive/Constraint nodes for TRACES_TO edges.
  Evidence needed: review axon_hillock_oc.py for InvariantQueryNode references.

### U-03: The machinetalk engine's LLM call for scout uses the TB-SOMA-005 role contract (tb-012-scout.md), but the exact prompt sent to the LLM is assembled by _run_build_stage (engine internals). The prompt template is not visible without spelunking the client/turn-key infrastructure.
  Evidence needed: read machinetalk/client.py to see how _run_build_stage assembles the scout prompt.

### U-04: InvariantRegistry can be initialized from an external JSON file (`path` parameter), but no such file exists in the repo. Path is None by default.
  Evidence needed: confirm no external invariant JSON file is mounted at runtime.

## Evidence index

See 03-evidence-index.tsv (same rows).

## Report plan

1. Mandate — invariant detection and violation mapping
2. Current State — two live entry points, no tests
3. Key Paths and Entry Points — table with line counts and mtimes
4. Architecture and Data Flow — two separate invocation paths
5. Core Logic — standalone path (InvariantsDB fnmatch) vs engine path (InvariantRegistry + LLM)
6. Configuration and Invariants — hard gates, rule sets, severity maps
7. Dependencies and Cross-Component Connections — pipeline position, downstream consumers
8. Known Gaps and Uncertainties — U-01 through U-04
9. Evidence Log — numbered evidence entries
