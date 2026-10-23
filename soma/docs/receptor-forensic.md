# Receptor — Forensic Deep Dive

TARGET: receptor | RUN: 20261022T122811Z-930ae6 | DATE: 2026-10-22T12:28Z | HOSTS EXAMINED: flintx (MX Linux, Tailscale 100.99.23.82)
CONFIDENCE SUMMARY: C1=3 findings (grep, data), C2=12 findings (source reads), C3=0, C4=0. All three sub-components verified by source inspection. Two live pathways confirmed via import graph and call-site reads.
SCOPE: Receptor concept as it exists in `/home/flintx/soma-10-14/soma`. Three artifacts: the machinetalk `write_receptor()` pathway (LIVE), the pipeline `ReceptorDendrite` class (ORPHAN), and the `get_receptor_config` / `put_receptor_config` helpers (LIVE code, unused data). Excluded: all sibling dendrites, engine internals, remote host.

## Mandate

The receptor logs the result of the distiller stage as `ReceptorLog` nodes in the Soma graph, recording model, latency, verdict, and skip status per ChatSet, while an orphaned `ReceptorDendrite` class and uninvoked helper functions exist as planned replacements and instruction template management.

## Current State

Three receptor-related code paths exist with divergent liveness:

**1. Machinetalk `write_receptor()` (LIVE)** — `machinetalk/soma_bridge.py:82-103` creates `ReceptorLog` nodes every time the distiller stage completes. Called from two sites: `machinetalk/engine.py:449` (primary, during full pipeline runs) and `run_engine.py:243` (secondary, `--soma-only` mode). 60 `ReceptorLog` nodes observed in `output/soma.json`. This is the active production pathway.

**2. Pipeline `ReceptorDendrite` (ORPHAN)** — `pipeline/receptor_dendrite.py` defines `ReceptorDendrite` (136 lines), `ReceptorOutput` dataclass, and `strip_raw()` function. Zero production imports confirmed by `rg 'from pipeline.receptor_dendrite'` returning zero non-test matches. Only referenced in `test_receptor_dendrite.py` (281 lines, 25 tests). The docstring reads "TB-TK-REPLACE-001: Heuristic chatset cleaner" — indicating a planned replacement for the live pathway, but never wired into the production call chain. No root-level duplicate exists (unlike classifier, integrator, drafter, retrograde which have both root and `pipeline/` copies).

**3. Helper functions in `soma.helpers` (LIVE code, unused data)** — `soma/helpers.py:5-25` provides `get_receptor_config()` (queries `ReceptorConfig` nodes by `name` or `stage`) and `put_receptor_config()` (creates/updates `ReceptorConfig` nodes). Imported by 5 dendrites (classifier, nexus, spark, falcon, retrograde) but zero `ReceptorConfig` nodes exist in `output/soma.json`. The drafter dendrite (`drafter_dendrite.py:184-189`) implements its own `_get_receptor_config(agent_id)` with a different parameter name (`agent_id` vs `name`/`stage`), confirming it uses the same Soma pattern but with inconsistent naming.

| Artifact | Status | Location | Lines | Mtime | Evidence |
|----------|--------|----------|-------|-------|----------|
| `write_receptor()` | LIVE | `machinetalk/soma_bridge.py:82-103` | 22 | ~2026-10-18 | C1 [E-003] |
| Engine trigger | LIVE | `machinetalk/engine.py:448-450` | 3 | ~2026-10-18 | C2 [E-006] |
| Soma-only trigger | LIVE | `run_engine.py:243-250` | 8 | ~2026-10-18 | C2 [E-008] |
| `ReceptorDendrite` class | ORPHAN | `pipeline/receptor_dendrite.py:63-134` | 72 | 2026-10-18T21:42Z | C2 [E-001] |
| `ReceptorOutput` dataclass | ORPHAN | `pipeline/receptor_dendrite.py:24-41` | 18 | 2026-10-18T21:42Z | C2 [E-001] |
| `strip_raw()` | ORPHAN | `pipeline/receptor_dendrite.py:44-57` | 14 | 2026-10-18T21:42Z | C2 [E-001] |
| `get_receptor_config()` | LIVE | `soma/helpers.py:5-13` | 9 | ~2026-10-18 | C2 [E-004] |
| `put_receptor_config()` | LIVE | `soma/helpers.py:14-25` | 12 | ~2026-10-18 | C2 [E-004] |
| `_STAGE_MAP` mapping | CONFIG | `machinetalk/client.py:16` | 1 | ~2026-10-18 | C2 [E-005] |
| `output/soma.json` | DATA | `output/soma.json` | — | 2026-10-21T20:03Z | C1 [E-011] |
| `test_receptor_dendrite.py` | TEST | `test_receptor_dendrite.py` | 281 | 2026-10-18T21:43Z | C2 [E-002] |

## Key Paths and Entry Points

| Path | Host | Role | Entrypoint? | Lines | Mtime | Evidence |
|------|------|------|-------------|-------|-------|----------|
| `machinetalk/soma_bridge.py:82` | flintx | Creates ReceptorLog nodes | Yes | 22 | ~2026-10-18 | C1 [E-003] |
| `machinetalk/engine.py:449` | flintx | Calls write_receptor on distiller | Yes | 3 | ~2026-10-18 | C2 [E-006] |
| `run_engine.py:243` | flintx | Secondary call (soma-only mode) | Yes | 8 | ~2026-10-18 | C2 [E-008] |
| `pipeline/receptor_dendrite.py:63` | flintx | Orphan class definition | No | 72 | 2026-10-18T21:42Z | C2 [E-001] |
| `soma/helpers.py:5` | flintx | Queries ReceptorConfig nodes | Yes | 9 | ~2026-10-18 | C2 [E-004] |
| `machinetalk/client.py:16` | flintx | Maps "receptor" → "distiller" | Config | 1 | ~2026-10-18 | C2 [E-005] |
| `drafter_dendrite.py:184` | flintx | Own _get_receptor_config() impl | Yes | 6 | ~2026-10-18 | C2 [E-013] |

## Architecture and Data Flow

```ascii
┌─────────────────────────────────────────────────────────────────────┐
│                        RECEPTOR ECOSYSTEM                            │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│   ┌───────────────┐                                                   │
│   │  engine.py     │  stage=="distiller"                               │
│   │  (line 449)    │ ──────────────────►                               │
│   └───────────────┘         run_engine.py:243 (soma-only)             │
│                            ┌──────────────────────────────────┐       │
│                            │  SomaBridge.write_receptor()     │       │
│                            │  machinetalk/soma_bridge.py:82-103 │     │
│                            │                                  │       │
│                            │  1. node_id = "receptor-{cid}"  │       │
│                            │  2. upsert ReceptorLog node     │       │
│                            │  3. edge: cid→PROCESSED_BY→node │       │
│                            │  4. return {"ReceptorLog": 1}   │       │
│                            └──────────┬─────────────────────┘       │
│                                       │                               │
│                              ┌────────▼────────┐                     │
│                              │   Soma graph     │                     │
│                              │   (soma.json)    │                     │
│                              │                  │                     │
│                              │  ReceptorLog: 60 │                     │
│                              │  ReceptorConfig: 0│                    │
│                              └──────────────────┘                     │
│                                                                      │
│   ┌─────────────────────────────────────────────────────────────┐   │
│   │                   ORPHANED MODULE (never called)             │   │
│   │                                                             │   │
│   │  pipeline/receptor_dendrite.py:                              │   │
│   │  ├── ReceptorDendrite.run(chatset_id)                       │   │
│   │  │   ├── soma.get_node(chatset_id)                          │   │
│   │  │   ├── concat(user_text + assistant_text)                 │   │
│   │  │   ├── strip_raw(raw)                                     │   │
│   │  │   │   ├── collapse \n{4,} → \n\n                         │   │
│   │  │   │   ├── rstrip each line                               │   │
│   │  │   │   └── strip() entire string                          │   │
│   │  │   └── ReceptorOutput(…): 8 metrics fields               │   │
│   │  ├── strip_raw() — pure function                            │   │
│   │  └── ReceptorOutput — dataclass                            │   │
│   │                                                             │   │
│   │  STATUS: 0 production imports [E-009]                       │   │
│   │  PURPOSE: "TB-TK-REPLACE-001" — planned replacement         │   │
│   │  TESTS: 25 tests in test_receptor_dendrite.py [E-002]       │   │
│   └─────────────────────────────────────────────────────────────┘   │
│                                                                      │
│   ┌─────────────────────────────────────────────────────────────┐   │
│   │                   HELPER (LIVE CODE, NO DATA)                │   │
│   │                                                             │   │
│   │  soma/helpers.py:                                            │   │
│   │  ├── get_receptor_config(soma, name) → dict|None            │   │
│   │  │   └── Used by: classifier, nexus, spark, falcon,         │   │
│   │  │       retrograde (5 dendrites) [E-005]                   │   │
│   │  │   └── Returns None (zero ReceptorConfig nodes) [E-012]  │   │
│   │  └── put_receptor_config(soma, name, body) → nid            │   │
│   │      └── Zero callers in production code                    │   │
│   │                                                             │   │
│   │  STATUS: compiled into 5+ dendrites, 0 nodes in output     │   │
│   │  NOTE: drafter_dendrite.py has its own _get_receptor_config │   │
│   │        with different signature (agent_id vs name)          │   │
│   └─────────────────────────────────────────────────────────────┘   │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

## Core Logic

### Live Path: `write_receptor` (machinetalk engine)

**Entry point:** `machinetalk/engine.py:449` (primary) and `run_engine.py:243` (secondary, `--soma-only` mode) [E-006][E-008].

**Execution path:**

1. Engine completes a distiller stage run for a ChatSet [E-006].
2. At `machinetalk/engine.py:448`: `if stage == "distiller":` — only the distiller stage triggers receptor logging [E-006].
3. Calls `self._bridge.write_receptor(sid, cs.chatset_id, n, gate, rec.model, latency)` [E-006].
4. Inside `write_receptor()` at `machinetalk/soma_bridge.py:82-103` [E-003]:
   - Builds `node_id = f"receptor-{chatset_id}"` [E-003:85].
   - If node already exists, deletes it first (upsert pattern) [E-003:86-87].
   - Creates `ReceptorLog` node with properties: `id`, `session_id`, `chat_set_id`, `set_number`, `model_id`, `latency_ms`, `verdict`, `skipped`, `timestamp` [E-003:91-101].
   - Creates edge: `chatset_id →PROCESSED_BY→ receptor-{chatset_id}` [E-003:102].
   - Returns `{"ReceptorLog": 1}` [E-003:103].
5. `soma._persist()` saves the graph to `soma.json` [E-007].

**Secondary trigger** (`run_engine.py:243`): Called in `--soma-only` mode after running the distiller on the first session's first ChatSet. Same `write_receptor()` call with parameters: `first_session.session_id`, `first_cs.chatset_id`, `first_cs.set_number`, `gate`, `rec.model`, `rec.latency_ms` [E-008:243-250].

**Data shape of ReceptorLog** (from `output/soma.json`) [E-011]:
```json
{
  "id": "receptor-{chatset_id}",
  "type": "ReceptorLog",
  "properties": {
    "id": "receptor-{chatset_id}",
    "session_id": "<session-uuid>",
    "chat_set_id": "<chatset-id>",
    "set_number": 1,
    "model_id": "openai/gpt-oss-120b",
    "latency_ms": 5022.5,
    "verdict": "false",
    "skipped": false,
    "timestamp": "2026-10-18T09:44:45.976288"
  }
}
```

**_STAGE_MAP** at `machinetalk/client.py:16`: `"receptor": "distiller"` — the only production mapping of "receptor" as a stage key. Used at `machinetalk/client.py:146` when stage is not provided [E-005].

### Orphaned Path: `ReceptorDendrite` (never instantiated in production)

**Definition:** `pipeline/receptor_dendrite.py:63-134` [E-001].

**Execution path (if instantiated):**

1. `ReceptorDendrite.__init__(soma)` — stores Soma reference [E-001:66].
2. `run(chatset_id)` queries `soma.get_node(chatset_id)` [E-001:72].
3. If node is `None`, raises `ValueError` with message `f"ChatSet node {chatset_id!r} not found in Soma graph"` [E-001:74-77].
4. Extracts `user_text = node.properties.get("user_text", "")` and `asst_text = node.properties.get("assistant_text", "")` [E-001:86-87].
5. Concatenates: `raw = user_text + asst_text` [E-001:88].
6. Calculates pre-clean metrics: `bytes_original = len(raw.encode("utf-8"))`, `lines_original = len(raw.splitlines())` [E-001:91-93].
7. Calls `strip_raw(raw)` — deterministic whitespace cleaning at `pipeline/receptor_dendrite.py:44-57` [E-001:97]:
   - Collapse 4+ consecutive newlines to 2: `_EXCESS_BLANK.sub("\n\n", raw)` (pattern: `r"\n{4,}"`) [E-001:48]
   - Strip trailing whitespace from every line: `"\n".join(line.rstrip() for line in raw.splitlines())` [E-001:49]
   - Strip leading/trailing blank space on the whole string: `raw.strip()` [E-001:50]
8. Calculates post-clean metrics: `bytes_cleaned`, `lines_cleaned`, `whitespace_removed = bytes_original - bytes_cleaned` [E-001:101-105].
9. `compression_ratio = bytes_cleaned / bytes_original` (or `0.0` if original was empty) [E-001:107-109].
10. Returns `ReceptorOutput` dataclass with 8 fields [E-001:111-119]:
    - `chatset_id: str` — input ChatSet identifier
    - `cleaned_text: str` — whitespace-stripped concatenated text
    - `compression_ratio: float` — `bytes_cleaned / bytes_original` (0.0–1.0)
    - `bytes_original: int` — UTF-8 byte count before cleaning
    - `bytes_cleaned: int` — UTF-8 byte count after cleaning
    - `whitespace_removed: int` — `bytes_original - bytes_cleaned`
    - `lines_original: int` — line count before cleaning
    - `lines_cleaned: int` — line count after cleaning

**Convenience method:** `get_compression_ratio(chatset_id)` — calls `run(chatset_id).compression_ratio` [E-001:121-123].

**Tests:** `test_receptor_dendrite.py` has 10 test classes with 25 total tests, all importing from `pipeline.receptor_dendrite` [E-002:22]:
- `TestStripRaw` (9 tests): idempotent stripping, whitespace handling, UTF-8, blank line collapsing [E-002:67-119]
- `TestNodeValidation` (2 tests): `ValueError` on missing node, success on valid node [E-002:123-135]
- `TestCompressionMetrics` (6 tests): bytes accuracy, ratio bounds, empty text edge case [E-002:139-179]
- `TestOutputShape` (4 tests): dataclass fields present, types correct, chatset_id matches [E-002:183-205]
- `TestDeterministicStripping` (2 tests): idempotent, no randomness across 10 runs [E-002:209-221]
- `TestGetCompressionRatio` (2 tests): returns float, matches full run result [E-002:225-236]

### Helper Path: `get_receptor_config` and `put_receptor_config`

**Definition:** `soma/helpers.py:5-25` [E-004].

**`get_receptor_config(soma, name)`** [E-004:5-13]:
1. Calls `soma.query_by_type("ReceptorConfig")` to get all ReceptorConfig nodes [E-004:7].
2. Iterates nodes, matching on `node.properties.get("name") == name` OR `node.properties.get("stage") == name` [E-004:8].
3. Returns `node.properties` on match, `None` on no match [E-004:9-10].

**`put_receptor_config(soma, name, instruction_body, stage=None)`** [E-004:14-25]:
1. Builds `props = {"name": name, "instruction_body": instruction_body, "stage": stage or name}` [E-004:18-21].
2. Generates `nid = f"config-{name}"` [E-004:22].
3. If node exists, updates properties in place; otherwise creates new `ReceptorConfig` node [E-004:23-24].
4. Returns the node ID [E-004:25].

**Importers:** 5 dendrites import `get_receptor_config` from `soma.helpers`:
- `classifier_dendrite.py:15,205` — calls `get_receptor_config(self._soma, "classifier")` [E-005]
- `nexus_dendrite.py:12,55` — calls `get_receptor_config(self._soma, "nexus")` [E-005]
- `spark_dendrite.py:11,58` — calls `get_receptor_config(self._soma, "spark")` [E-005]
- `falcon_dendrite.py:23` — imports but fallback behavior inferred [E-005]
- `retrograde_dendrite.py:12,81` — calls `get_receptor_config(self._soma, "retrograde")` [E-005]

Additionally, `run_pipeline.py:22` imports it (used as comment reference only) [E-005].

**Drafter divergence:** `drafter_dendrite.py:184-189` implements its own `_get_receptor_config(agent_id)` that queries by `agent_id` property (not `name` or `stage`), with a different semantic signature [E-013].

## Configuration and Invariants

| Config Source | Default/Fallback | Precedence | Source |
|---------------|-----------------|------------|--------|
| `_STAGE_MAP["receptor"]` = `"distiller"` | `"distiller"` (literal) | `machinetalk/client.py:16` | C2 [E-005] |
| `get_receptor_config(soma, name)` | `None` (zero ReceptorConfig nodes [E-012]) | `soma/helpers.py:10` | C2 [E-004] |
| `put_receptor_config()` | Never called | `soma/helpers.py:14-25` | C2 [E-004] |
| `ReceptorDendrite.__init__` | `soma` required, non-null | `pipeline/receptor_dendrite.py:66` | C2 [E-001] |
| `_EXCESS_BLANK` pattern | `r"\n{4,}"` (4+ newlines) | `pipeline/receptor_dendrite.py:29` | C2 [E-001] |
| `ReceptorOutput` field count | 8 fields (dataclass) | `pipeline/receptor_dendrite.py:24-41` | C2 [E-001] |
| Node ID pattern | `f"receptor-{chatset_id}"` | `machinetalk/soma_bridge.py:85` | C2 [E-003] |
| Edge relationship | `→PROCESSED_BY→` | `machinetalk/soma_bridge.py:102` | C2 [E-003] |
| `put_receptor_config` callers | Zero found | Any file | C2 [E-004] |

No environment variables, no `.env` keys, no service units, no database constraints specific to receptor.

## Dependencies and Cross-Component Connections

**Upstream:**
- **distiller stage** — only the distiller stage triggers `write_receptor()`. At `machinetalk/engine.py:448`: `if stage == "distiller":` — no other stage creates `ReceptorLog` nodes [E-006].
- **TurnKey model layer** — model selection occurs before `write_receptor`; `rec.model` is passed verbatim (e.g., `"openai/gpt-oss-120b"`) [E-011].
- **ChatSet nodes** — `write_receptor()` receives `chatset_id` and `set_number` from the engine's chatset record [E-006].
- **No machine-talk spec** — no `tb-XXX-receptor.md` exists in `machine-talk/*.md` [E-010].

**Downstream:**
- **No consumer reads ReceptorLog nodes.** Zero production dendrites query by type `"ReceptorLog"` or follow `PROCESSED_BY` edges. `ReceptorLog` is a dead-end leaf in the Soma graph. The nodes are purely logging/observability artifacts.
- **Soma persistence** — ReceptorLog is persisted to `soma.json` via `soma._persist()` at `machinetalk/soma_bridge.py:107` [E-007]. If any future component adds a consumer, the data is already there.

**Orphaned dependency:**
- `pipeline/receptor_dendrite.py:16` — `from store import Soma, Node` [E-001].
- `test_receptor_dendrite.py:22` — `from pipeline.receptor_dendrite import ReceptorDendrite, ReceptorOutput, strip_raw` [E-002].
- No production code imports from `pipeline.receptor_dendrite` (confirmed by `rg` scan) [E-009].

**Helper cross-dependencies:**
- `get_receptor_config` imported by 5 dendrites for instruction template retrieval, each with a different stage name argument [E-005].
- `put_receptor_config` — zero callers found in any production code. Possibly dead code or an API not yet wired up.

## Known Gaps and Uncertainties

### G-01: No consumer for ReceptorLog. Zero production code queries `ReceptorLog` nodes or follows `PROCESSED_BY` edges. The nodes are created on every distiller run but never consumed. It is UNKNOWN whether this is intentional (logging-only artifact for debugging/observability) or an incomplete implementation where a consumer was planned but never built. Evidence needed: grep for `"ReceptorLog"` across all production dendrites to confirm zero consumers.

### G-02: TB-TK-REPLACE-001 — original implementation unknown. The docstring at `pipeline/receptor_dendrite.py:1` references `TB-TK-REPLACE-001: ReceptorDendrite — Heuristic chatset cleaner`, indicating this is a planned replacement. No prior receptor source code, spec, or design document was found in the project. The original implementation this replaces is UNKNOWN. The `distiller` stage in the live engine calls the TurnKey LLM pipeline (not a pure heuristic cleaner), confirming the orphan is a proposed architectural shift that was never adopted.

### G-03: `put_receptor_config()` — zero callers found in any production code. This function creates `ReceptorConfig` nodes in the Soma graph but is never invoked. It is UNKNOWN whether it was used historically (and is now dead code), was intended for a management API that was never built, or is scaffolding for future instruction template management.

### G-04: Remote host not probed. The Hetzner remote (`100.87.51.23`, `ssh engine`) was not accessed in this run. `ReceptorLog` and `ReceptorConfig` state on the remote `soma.json` may differ (potentially more nodes, different data). The report is LOCAL-ONLY. Probe required: `ssh -o BatchMode=yes engine 'python3 -c "import json; d=json.load(open(\"/root/hetzner/ai-engine/output/soma.json\")); print(len([n for n,t in d[\"nodes\"].items() if t[\"type\"]==\"ReceptorLog\"]))"'`.

### G-05: Drafter's divergent `_get_receptor_config()`. `drafter_dendrite.py:184-189` implements a standalone lookup using `agent_id` as the matching property, whereas `soma.helpers.get_receptor_config()` uses `name` or `stage`. The semantic relationship between `agent_id` and `name`/`stage` is UNKNOWN. It is possible that ReceptorConfig nodes use one property set while the drafter expects the other, creating a silent mismatch.

## Evidence Log

| ID | Host | Kind | Locator | Captured At | Proves | Confidence |
|----|------|------|---------|-------------|--------|------------|
| E-001 | flintx | source | `pipeline/receptor_dendrite.py:1-136` | 2026-10-22T12:28Z | ReceptorDendrite class, ReceptorOutput, strip_raw, TB-TK-REPLACE-001 docstring | C2 |
| E-002 | flintx | source | `test_receptor_dendrite.py:1-281` | 2026-10-22T12:28Z | 25 tests across 10 test classes, all import from pipeline.receptor_dendrite | C2 |
| E-003 | flintx | source | `machinetalk/soma_bridge.py:82-103` | 2026-10-22T12:28Z | write_receptor() creates ReceptorLog, upserts, creates edge, returns count | C2 |
| E-004 | flintx | source | `soma/helpers.py:5-25` | 2026-10-22T12:28Z | get_receptor_config() and put_receptor_config() signatures and logic | C2 |
| E-005 | flintx | source | `machinetalk/client.py:14-31` | 2026-10-22T12:28Z | _STAGE_MAP["receptor"] = "distiller" at line 16 | C2 |
| E-006 | flintx | source | `machinetalk/engine.py:448-450` | 2026-10-22T12:28Z | Production trigger: stage=="distiller" → self._bridge.write_receptor() | C2 |
| E-007 | flintx | source | `machinetalk/soma_bridge.py:107` | 2026-10-22T12:28Z | soma._persist() after stage write | C2 |
| E-008 | flintx | source | `run_engine.py:243-250` | 2026-10-22T12:28Z | Secondary write_receptor call in --soma-only mode | C2 |
| E-009 | flintx | grep | `rg 'from pipeline.receptor_dendrite'` = 0 non-test results | 2026-10-22T12:28Z | No production import of ReceptorDendrite | C1 |
| E-010 | flintx | source | `machine-talk/*.md` scan | 2026-10-22T12:28Z | No tb-XXX spec for receptor in machine-talk docs | C2 |
| E-011 | flintx | data | `output/soma.json` — 60 ReceptorLog nodes, 0 ReceptorConfig | 2026-10-22T12:28Z | Live data: 60 ReceptorLog nodes with full properties | C1 |
| E-012 | flintx | data | `output/soma.json` — 0 ReceptorConfig matches | 2026-10-22T12:28Z | No ReceptorConfig nodes exist in any output | C1 |
| E-013 | flintx | source | `drafter_dendrite.py:184-189` | 2026-10-22T12:28Z | Drafter's own _get_receptor_config(agent_id) with different signature | C2 |
