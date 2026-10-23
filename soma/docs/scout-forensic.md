# Scout — Forensic Deep Dive

TARGET: scout | RUN: 20261022T142833Z-6a87c0 | DATE: 2026-10-22T14:28Z | HOSTS EXAMINED: flintx (local, MX Linux)
CONFIDENCE SUMMARY: C2 across all source evidence; C1 runtime claims N/A (scout has no standalone process)
SCOPE: scout component only — entry points, invariant rule systems, pipeline position, cross-component edges

## Mandate

Scout maps invariant rules to generated code files by creating InvariantQueryNode records in the Soma graph, each linked via GOVERNS edges, and (in the machinetalk engine path) produces a structured violation report from LLM analysis.

## Current State

Two live entry points execute scout in two materially different modes:

- **Standalone path** (`scout_dendrite.py`): A self-contained `ScoutDendrite` class with a hardcoded `InvariantsDB`. Invoked by `run_pipeline.py`, `run_new_session.py`, `run_tb009.py`, and `walk.py` at pipeline stage 6. Zero LLM calls. Pure rule-based matching via `fnmatch.fnmatch()` on file extension against 9 hardcoded rules.

- **Machinetalk engine path** (`machinetalk/engine.py:863-904`): The engine's scout stage invokes the TurnKeyClient LLM to produce a natural-language violation report, parses it via `parse_scout_report()`, and persists structured violations via `soma_bridge.write_scout()`. Invariant rules come from `machinetalk/invariants.py`'s `InvariantRegistry` (4 structured rules with severity/family metadata), not from `scout_dendrite.py`'s `InvariantsDB`.

No tests exist for scout. The component's source (`scout_dendrite.py`) is last modified 2026-10-18T01:40.

## Key Paths and Entry Points

| Path | Host | Role | Entrypoint? | Lines | Mtime | Evidence |
|------|------|------|-------------|-------|-------|----------|
| `scout_dendrite.py` | flintx | Standalone ScoutDendrite class + InvariantsDB | Yes | 148 | 2026-10-18 | E-001 |
| `machinetalk/engine.py:734-735` | flintx | Engine stage runner | Yes | 2 | 2026-10-21 | E-002 |
| `machinetalk/engine.py:863-904` | flintx | Scout build stage (prompt, parse, persist) | Yes | 42 | 2026-10-21 | E-003 |
| `machinetalk/soma_bridge.py:320-351` | flintx | write_scout — persists violations as graph nodes | Yes | 32 | 2026-10-21 | E-004 |
| `machinetalk/invariants.py` | flintx | InvariantRegistry — structured rule source | Yes | 66 | mtime unknown | E-005 |
| `machine-talk/tb-012-scout.md` | flintx | Role contract / prompt template | Yes | 80 | mtime unknown | E-010 |
| `run_pipeline.py:30,147` | flintx | Standalone path orchestrator | Import + stage 6 | 291 | 2026-10-21 | E-015 |
| `walk.py:30,50` | flintx | Walk pipeline (CRYSTALLIZE) | Import + stage | 150 | 2026-10-21 | E-018 |

## Architecture and Data Flow

```text
                    ┌─────────────────────────────────────────┐
                    │              STANDALONE PATH             │
                    │  (run_pipeline.py, run_tb009.py, walk.py)│
                    └─────────────────────────────────────────┘

Drafter (FileNodes) ──► ScoutDendrite.run() ──► InvariantsDB.query()
                                              │
                                              ├─ fnmatch("*.py", file_path)
                                              ├─ fnmatch("*.json", file_path)
                                              ├─ fnmatch("*.md", file_path)
                                              ├─ fnmatch("*test*.py", file_path)
                                              └─ default fallback
                                              │
                                              └─► Soma.create_node("InvariantQueryNode")
                                              └─► Soma.create_edge(FileNode, "GOVERNS", inv_id)

                    ┌─────────────────────────────────────────────────┐
                    │           MACHINETALK ENGINE PATH                │
                    │         (machinetalk/engine.py)                  │
                    └─────────────────────────────────────────────────┘

Drafter (code files) ──► InvariantRegistry.query(exts)
                       ──► _run_build_stage(build, "scout", chunk=code, contracts=rules_text)
                       │
                       │   [TurnKeyClient LLM call — TB-SOMA-005 role contract]
                       │   LLM returns text: [PASS/FAIL DNA-XXX — message, evidence, verdict]
                       │
                       ──► parse_scout_report(raw, verdict)  ──► {violations, blockers, health}
                       │
                       ──► soma_bridge.write_scout(session_id, parsed_violations)
                               │
                               ├─► Soma.create_node("InvariantQueryNode", {invariant_text, severity, type, contract_id})
                               └─► Soma.create_edge(FileNode, "GOVERNS", inv_id)
```


## Core Logic

### Standalone path — scout_dendrite.py

**Constructor** (`scout_dendrite.py:79-84`): Accepts `soma`, `llm_client` (stored but unused), `repo` (optional), and `invariants_client` (defaults to `InvariantsDB`).

**run(session_id)** (`scout_dendrite.py:86-131`):

1. **Query FileNodes** (L91-94): `self._soma.query_by_type("FileNode")`, filtered by `session_id` property.
2. **Query RequirementsNodes** (L97-100): Same query, not used in output logic (count only).
3. **Resolve repo** (L103-113): If `self._repo` is falsy, queries `SessionAnchor` nodes for `repo` property.
4. **For each FileNode** (L116-129):
   - Extract `file_path` from node properties (L118).
   - Query `InvariantsDB.query(file_path, repo)` (L119) — matches extension via `fnmatch.fnmatch()` against 5 patterns, falls back to `default` rules if no pattern matches (L53-60).
   - For each returned rule text (L120-129):
     - Generates deterministic node ID: `inv-{fn.id}-{uuid4[:8]}` (L121).
     - Creates `InvariantQueryNode` with `session_id`, `invariant_text`, `target_file_node_id` (L122-127).
     - Creates `GOVERNS` edge from FileNode to InvariantQueryNode (L128).
5. **Return** (L131-141): Report dict with `file_nodes_scanned`, `requirements_found`, `invariant_nodes_created`, `search_summary`, and `metrics` (all token counts are 0 — no LLM calls).

### InvariantsDB — hardcoded mock (`scout_dendrite.py:26-67`)

- `_RULES`: dict keyed by glob pattern → list of rule strings.
- `query(file_path, repo)`: Iterates patterns; skips `default`; extends matches; if no pattern matched, returns `default` rules.
- `_match(pattern, path)`: Uses `fnmatch.fnmatch()` for glob matching.

### Engine path — parse_scout_report (`machinetalk/engine.py:110-138`)

- Splits LLM text by `[PASS|FAIL|WARN|SKIP]` regex pattern (L114).
- Extracts `contract_id`, `severity`, `type`, `message` from each violation block.
- Computes `aggregate_health`: 0.0 if critical violations exist or verdict is REWORK; 0.9 if no fails; `max(0.5, 1 - 0.15 * num_fails)` otherwise.

### Engine path — write_scout (`machinetalk/soma_bridge.py:320-351`)

- Iterates violations from LLM report.
- Creates `InvariantQueryNode` with deterministic ID `inv-{session_id}-{i}` (overwrites existing by same ID).
- Creates `GOVERNS` edge from all FileNodes (for session) to each InvariantQueryNode.

## Configuration and Invariants

### Hard gates (scout_dendrite.py:8-10)
1. No physical file reads/writes
2. No access to monolithic code payload
3. Only writes InvariantQueryNodes + connecting edges

### Hard gates (machine-talk/tb-012-scout.md)
- `code_modification → ∅` — scout does not fix code
- `refactoring → ∅` — scout does not suggest refactors
- `feature_addition → ∅` — scout does not add features
- `critical_severity → reserved_for_security_vulnerabilities_only`

### Standalone InvariantsDB — 9 rules across 5 patterns
| Pattern | Rules |
|---------|-------|
| `*.py` | type hints, no mutable module vars, docstrings |
| `*.json` | valid JSON, root object/array |
| `*.md` | top-level heading |
| `*test*.py` | pytest fixtures, no prod path writes |
| `default` | no hardcoded secrets, explicit error handling |

### Engine InvariantRegistry — 4 structured rules
| Rule ID | Severity | Family | Applies To | Statement |
|---------|----------|--------|-----------|-----------|
| INV-001 | CRITICAL | security | py, js, ts, go, sh | No secrets or credentials in source |
| INV-002 | HIGH | correctness | py, js, ts, go | Clear input/output per public function |
| INV-003 | HIGH | safety | py, js, ts, go | No unbounded recursion or loops |
| INV-004 | MEDIUM | style | py, js, ts, go, md | No TODO or placeholder |

### LLM scoring (engine path)
- `critical` violations + `fail` status → `blockers` list
- `aggregate_health`: 0.0 (critical/fail), 0.9 (clean), 0.5–0.85 (graded by fail count)

## Dependencies and Cross-Component Connections

| Direction | Mechanism | Payload | Provenance | Confidence |
|-----------|-----------|---------|------------|------------|
| Drafter → Scout | Pipeline ordering (stage 5 → 6) | FileNodes created by Drafter | `run_pipeline.py:141-148` [E-015] | C2 |
| Scout → AxonHillock | Pipeline ordering (stage 6 → 7) | InvariantQueryNodes + GOVERNS edges | `run_pipeline.py:150-157` [E-015] | C2 |
| Scout → Myelinator | Indirect — Myelinator queries InvariantQueryNodes for GOVERNS edges | InvariantQueryNode list | `myelinator_olc.py:65-68` [E-022] | C2 |
| Engine → Scout (LLM) | `_run_build_stage(build, "scout", chunk=code, contracts=contracts_txt)` | Code + contracts text | `machinetalk/engine.py:878` [E-003] | C2 |
| Scout → Soma | `soma.create_node("InvariantQueryNode", ...)` + `soma.create_edge(...)` | Graph mutations | `scout_dendrite.py:122-128` [E-008] | C2 |
| Scout → Soma (engine) | `soma_bridge.write_scout(session_id, violations)` | Violations persisted as nodes | `machinetalk/soma_bridge.py:320-351` [E-004] | C2 |

### Pipeline position

- **Standalone path** (`run_pipeline.py`, `run_new_session.py`, `run_tb009.py`, `walk.py`): Stage 6 in a linear pipeline: Classifier → Nexus → Spark → Falcon → Drafter → **Scout** → AxonHillock → Myelinator.
- **Machinetalk engine**: Stage 3 in the `stage3` group (nexus, spark, falcon, eagle, drafter, scout). Scout runs after drafter and before oc (AxonHillock).

## Known Gaps and Uncertainties

### G-01: No test coverage.
  Zero test files reference `scout` or `ScoutDendrite`.
  Why it matters: A regression in the standalone path's rule-matching logic or the engine path's report parsing would go undetected.
  Evidence needed: any test invocation targeting scout.

### G-02: Scout output not consumed by AxonHillock in standalone path.
  AxonHillock (`axon_hillock_oc.py`) queries FileNode and Directive/Constraint/Task nodes for TRACES_TO edges but does not query InvariantQueryNodes.
  Why it matters: InvariantQueryNodes created by scout exist in the graph as a dead-end; AxonHillock has no mechanism to use them.
  Evidence needed: confirm `axon_hillock_oc.py` has no InvariantQueryNode references.

### G-03: Scout output IS consumed by Myelinator.
  Myelinator queries InvariantQueryNodes (line 65-68 of `myelinator_olc.py`) and creates GOVERNS edges from InvariantQueryNode → FunctionSlot.
  Why it matters: Scout's output is actually consumed downstream — but only by Myelinator, not by AxonHillock (which sits between Scout and Myelinator). The edge chain is: FileNode →GOVERNS→ InvariantQueryNode →GOVERNS→ FunctionSlot.

### G-04: LLM prompt for scout is opaque.
  The engine calls `_run_build_stage(build, "scout", ...)` which assembles the prompt internally. The exact prompt template is in `machinetalk/client.py` (turn-key client infrastructure).
  Why it matters: The violation format, instruction body, and output schema depend on this prompt, which is not fully visible without spelunking the client.
  Evidence needed: read `machinetalk/client.py` to see how scout prompts are assembled.

### G-05: InvariantRegistry can be sourced from external JSON.
  Constructor accepts a `path` parameter that overrides `_DEFAULT_RULES`. No such file exists in the repository.
  Why it matters: If deployed with an external rules file, the 4 hardcoded rules may be replaced entirely.
  Evidence needed: confirm runtime deployment does not mount a custom rules file.

## Evidence Log

| ID | Host | Kind | Locator | Captured at | Proves | Confidence |
|----|------|------|---------|-------------|--------|------------|
| E-001 | flintx | Source | scout_dendrite.py:1-148 | 2026-10-22T14:28Z | ScoutDendrite class, InvariantsDB, run() method | C2 |
| E-002 | flintx | Source | machinetalk/engine.py:734-735 | 2026-10-22T14:28Z | Engine invokes bridge.write_scout() | C2 |
| E-003 | flintx | Source | machinetalk/engine.py:863-904 | 2026-10-22T14:28Z | Scout build stage: prompt, parse, persist | C2 |
| E-004 | flintx | Source | machinetalk/soma_bridge.py:320-351 | 2026-10-22T14:28Z | write_scout() creates InvariantQueryNodes + GOVERNS | C2 |
| E-005 | flintx | Source | machinetalk/invariants.py:1-66 | 2026-10-22T14:28Z | InvariantRegistry with 4 structured rules | C2 |
| E-006 | flintx | Source | scout_dendrite.py:29-50 | 2026-10-22T14:28Z | InvariantsDB._RULES (9 rules, 5 patterns) | C2 |
| E-007 | flintx | Source | scout_dendrite.py:52-67 | 2026-10-22T14:28Z | InvariantsDB.fnmatch matching logic | C2 |
| E-008 | flintx | Source | scout_dendrite.py:74-131 | 2026-10-22T14:28Z | ScoutDendrite.run() full execution path | C2 |
| E-009 | flintx | Source | scout_dendrite.py:88-94 | 2026-10-22T14:28Z | Repo resolution from SessionAnchor | C2 |
| E-010 | flintx | Source | machine-talk/tb-012-scout.md:1-80 | 2026-10-22T14:28Z | Role contract, type maps, hard gates, exemplar | C2 |
| E-011 | flintx | Source | machinetalk/engine.py:110-138 | 2026-10-22T14:28Z | parse_scout_report() regex parsing | C2 |
| E-012 | flintx | Source | machinetalk/engine.py:101 | 2026-10-22T14:28Z | Scout is stage3 in machinetalk pipeline | C2 |
| E-013 | flintx | Source | machinetalk/soma_bridge.py:18 | 2026-10-22T14:28Z | scout → InvariantQueryNode mapping | C2 |
| E-014 | flintx | Source | machinetalk/soma_bridge.py:345 | 2026-10-22T14:28Z | GOVERNS edge creation in write_scout | C2 |
| E-015 | flintx | Source | run_pipeline.py:30,147 | 2026-10-22T14:28Z | Standalone path stage 6 invocation | C2 |
| E-016 | flintx | Source | run_new_session.py:18,123-127 | 2026-10-22T14:28Z | Standalone path stage 6 (alternate runner) | C2 |
| E-017 | flintx | Source | run_tb009.py:23,77-80 | 2026-10-22T14:28Z | Standalone path stage 6 (TB-009 runner) | C2 |
| E-018 | flintx | Source | walk.py:30,50 | 2026-10-22T14:28Z | Walk pipeline CRYSTALLIZE includes scout | C2 |
| E-019 | flintx | Source | store.py:1-135 | 2026-10-22T14:28Z | Soma graph class — Node, Edge, create_node, query_by_type | C2 |
| E-020 | flintx | Source | store.py:38-113 | 2026-10-22T14:28Z | Soma JSON persistence + batch mode | C2 |
| E-021 | flintx | Inventory | Inventory report | 2026-10-22T14:28Z | workspaces/ directory does not exist | C2 |
| E-022 | flintx | Source | myelinator_olc.py:65-68 | 2026-10-22T14:28Z | Myelinator consumes InvariantQueryNodes | C2 |
| E-023 | flintx | Source | machinetalk/invariants.py:13-42 | 2026-10-22T14:28Z | 4 InvariantRegistry default rules | C2 |
| E-024 | flintx | Source | machinetalk/invariants.py:47-55 | 2026-10-22T14:28Z | InvariantRegistry.extension-based query | C2 |
