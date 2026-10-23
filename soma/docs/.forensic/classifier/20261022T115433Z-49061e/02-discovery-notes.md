# 02-Discovery Notes: Classifier

TARGET: classifier | RUN: 20261022T115433Z-49061e

## Target lock
TARGET: classifier
SLUG: classifier
RUN ID: 20261022T115433Z-49061e
BASE DIR: /home/flintx/soma-10-14/soma
HOST: flintx
STARTED: 2026-10-22T11:54:33Z
SCOPE: Classifies chat content into disposition lanes (IntentNode, DirectiveNode, ConstraintNode, QuestionNode, PreferenceNode, CorrectionNode, NoiseNode).

## Inventory summary
- Project root: `/home/flintx/soma-10-14/soma` — 178 files (depth 3)
- Two classifier roots found:
  - `classifier_dendrite.py` — 302 lines, mtime 2026-10-17T18:40 UTC
  - `pipeline/classifier_dendrite.py` — 393 lines, mtime 2026-10-18T16:30 UTC
- Test: `test_classifier_dendrite.py` — 386 lines, mtime 2026-10-19T00:38 UTC (imports from pipeline)
- Runners: 9 files import `classifier_dendrite` (root), all with 3-arg instantiation
- No machinetalk engine dependency on classifier

## Entry points
| Path | Host | Lines | Mtime | Role |
|---|---|---|---|---|
| `classifier_dendrite.py` | flintx | 302 | 2026-10-17T18:40Z | Root module, imported by 7+ runners |
| `pipeline/classifier_dendrite.py` | flintx | 393 | 2026-10-18T16:30Z | Pipeline copy, imported by 1 test |
| `pipeline/stage_complete.py` | flintx | ~70 | 2026-10-14T12:16Z | Shared LLM call orchestrator |

## Runtime state
- No classifier process observed running standalone (it is a library module)
- Import graph: All 9 runners use `from classifier_dendrite import ClassifierDendrite` (root)
- All 9 runners instantiate with 3 args: `ClassifierDendrite(soma, llm, rotator/None)`
- Both classifier copies have `__init__(self, soma, llm_client)` — 2 params only
- **BUG**: Instantiation with 3 positional args would raise `TypeError: __init__() takes 3 positional arguments but 4 were given`

## Data stores
- Soma database: used by classifier to read ChatSet nodes, write signal nodes and EXTRACTED_FROM edges
- No dedicated classifier datastore

## Configuration and invariants
- **6 Disposition Lanes**: IntentNode, DirectiveNode, ConstraintNode, QuestionNode, PreferenceNode, CorrectionNode
- **Noise fallback**: NoiseNode — NOT a disposition lane
- **Pipeline copy** defines `DISPOSITION_LANES: frozenset` and `NOISE_FALLBACK` at module level
- **Pipeline copy** has `validate_signal()` with schema enforcement (required keys, valid signal_type, confidence range)
- **Root copy** has no `validate_signal()` — relies on `complete_stage` result or regex fallback
- Both copies use regex heuristic fallback when LLM call fails
- Both copies use `complete_stage()` for LLM calls
- Root copy: imports `complete_stage` from `pipeline.stage_complete`
- Pipeline copy: defines its own `complete_stage()` locally
- Root copy: uses `get_receptor_config(self._soma, "classifier")` from `soma.helpers`
- Pipeline copy: reads config directly from Soma (`self._soma.get_node("config-classifier")`)

## Cross-component edges
| Direction | Component | Mechanism | Evidence |
|---|---|---|---|
| Upstream | machinetalk/engine | indirect — engine processes sessions; classifier runs post-session via runners | No direct import from engine |
| Upstream | runners (run_tb*) | import + instantiate + run() on ChatSet nodes | `run_tb004.py:81`, `run_tb005.py:63`, etc. |
| Upstream | run_pipeline.py | imports root classifier, orchestrates 10-stage pipeline | `run_pipeline.py:25` |
| Upstream | test_classifier_dendrite.py | imports pipeline classifier, tests schema validation | `test_classifier_dendrite.py:23` |
| Downstream | store.Soma | create_node(), create_edge(), get_node() | both copies |
| Downstream | pipeline.stage_complete | complete_stage() LLM call + JSON parse | root copy imports, pipeline copy defines own |

## Instructions and recency
| Document | Mtime | Authority |
|---|---|---|
| `classifier_dendrite.py` docstring: "TB-DEND-020: Classifier Dendrite (FIXED — stage_name → classifier)" | 2026-10-17 | Current source |
| `pipeline/classifier_dendrite.py` docstring: "TB-TK-REPLACE-002: Classifier Dendrite — signal extraction via LLM tool-calling" | 2026-10-18 | Newer source |
| `test_classifier_dendrite.py`: "Unit tests for TB-TK-REPLACE-002" | 2026-10-19 | Tests reference pipeline version |
| `pipeline/stage_complete.py`: "complete_stage() — orchestrate a single LLM call" | 2026-10-14 | Shared util |
| `machine-talk/tb-004-introbeaver.md` | — | Historical spec |

## Conflicts

CONFLICT C-01: DUPLICATE MODULE
  claim A: Root classifier_dendrite.py — 302 lines, uses Signal dataclass, classify() function, imports complete_stage from pipeline.stage_complete, uses get_receptor_config from soma.helpers
  claim B: pipeline/classifier_dendrite.py — 393 lines, uses ClassifiedSignal dataclass, heuristic_classify() function, self-contained complete_stage(), direct Soma config lookup, has validate_signal()
  source A: classifier_dendrite.py (mtime 2026-10-17T18:40Z)
  source B: pipeline/classifier_dendrite.py (mtime 2026-10-18T16:30Z)
  resolution: both-live
  basis: both files exist, different import paths used. Root imported by all 9 runners; pipeline imported by 1 test. Pipeline is newer (TB-TK-REPLACE-002 vs TB-DEND-020).

CONFLICT C-02: 3-ARG INSTANTIATION BUG
  claim A: All 9 runners call ClassifierDendrite(soma, llm, rotator/None) with 3 positional arguments
  claim B: Both classifier copies define __init__(self, soma, llm_client) with only 2 positional arguments
  source A: run_pipeline.py:106, run_tb004.py:81, run_tb005.py:63, run_tb006.py:61, run_tb007.py:63, run_tb008.py:69, run_tb009.py:56, run_new_session.py:95, run_new_session_fix.py:54
  source B: classifier_dendrite.py:169, pipeline/classifier_dendrite.py:265
  resolution: unresolved — likely rotator was intended as optional 3rd param and removed, or all instantiations are broken
  impact: All 9 runner scripts would crash with TypeError if executed. Classifier code has never been verified to run end-to-end in production.

CONFLICT C-03: DIFFERENT COMPLETE_STAGE IMPLEMENTATIONS
  claim A: Root classifier imports complete_stage from pipeline.stage_complete which requires llm.call() method (LLMClient interface)
  claim B: Pipeline classifier defines its own complete_stage() which wraps bare .chat() clients via LLMToolCallClient
  source A: classifier_dendrite.py:16, pipeline/stage_complete.py:20
  source B: pipeline/classifier_dendrite.py:159-259
  resolution: both-live — different callers pass different LLM client types; the root copy would fail if passed a bare .chat() client
  impact: Pipeline version is more robust (handles both LLMClient and bare chat clients); root copy is narrower

## Unknowns and boundary gaps

### U-01: Which copy is intended as the canonical classifier?
  Evidence needed: TB-TK-REPLACE-002 tracking doc or migration plan showing root copy should be retired.

### U-02: Was the 3rd constructor parameter ever valid?
  Evidence needed: git blame on the constructor definition, or git blame on the instantiation sites, to determine if the rotator parameter was removed from __init__ but callers were never updated.

### U-03: Does any production code path actually execute the classifier?
  Evidence needed: Execution logs from a full pipeline run, or confirmation that runners are never invoked in production.

### U-04: What is the machinetalk engine's relationship to classifier?
  Evidence needed: engine.py does not import classifier; need to confirm if engine ever invokes classifier indirectly via session processing.

### U-05: Is NoiseNode correctly handled per the hard-gate rule?
  Evidence needed: TB-TK-REPLACE-002 says "Must use only the 6 defined disposition lanes" but both copies accept NoiseNode as a fallback. Verify this is intentional.

## Evidence index
| ID | Host | Kind | Locator | Captured At | Proves | Confidence |
|---|---|---|---|---|---|---|
| E-001 | flintx | source | classifier_dendrite.py:1-302 | 2026-10-22T11:54Z | Root copy structure, Signal dataclass, classify() function, import graph | C1 |
| E-002 | flintx | source | pipeline/classifier_dendrite.py:1-393 | 2026-10-22T11:54Z | Pipeline copy structure, ClassifiedSignal, heuristic_classify(), validate_signal(), self-contained complete_stage | C1 |
| E-003 | flintx | grep | run_pipeline.py:25,106 | 2026-10-22T11:54Z | 3-arg instantiation bug | C1 |
| E-004 | flintx | grep | run_tb004.py:81, run_tb005.py:63, run_tb006.py:61, run_tb007.py:63, run_tb008.py:69, run_tb009.py:56, run_new_session.py:95, run_new_session_fix.py:54 | 2026-10-22T11:54Z | All 9 runners use 3-arg instantiation | C1 |
| E-005 | flintx | source | classifier_dendrite.py:169 | 2026-10-22T11:54Z | Root __init__ takes 2 args | C1 |
| E-006 | flintx | source | pipeline/classifier_dendrite.py:265 | 2026-10-22T11:54Z | Pipeline __init__ takes 2 args | C1 |
| E-007 | flintx | grep | test_classifier_dendrite.py:23 | 2026-10-22T11:54Z | Tests import from pipeline, not root | C1 |
| E-008 | flintx | source | pipeline/classifier_dendrite.py:38-50 | 2026-10-22T11:54Z | DISPOSITION_LANES set and NOISE_FALLBACK | C1 |
| E-009 | flintx | source | classifier_dendrite.py:37-55 | 2026-10-22T11:54Z | Root regex patterns (no named constants) | C1 |
| E-010 | flintx | source | pipeline/classifier_dendrite.py:181-259 | 2026-10-22T11:54Z | Pipeline's self-contained complete_stage() with LLMToolCallClient wrapper | C1 |
| E-011 | flintx | source | pipeline/stage_complete.py:20-70 | 2026-10-22T11:54Z | Shared complete_stage() requiring llm.call() interface | C1 |
| E-012 | flintx | source | classifier_dendrite.py:15-16 | 2026-10-22T11:54Z | Root imports complete_stage from pipeline.stage_complete and get_receptor_config from soma.helpers | C1 |
| E-013 | flintx | source | pipeline/classifier_dendrite.py:280-282 | 2026-10-22T11:54Z | Pipeline reads config directly from Soma, not via soma.helpers | C1 |
| E-014 | flintx | source | pipeline/classifier_dendrite.py:230-250 | 2026-10-22T11:54Z | Pipeline's validate_signal() schema enforcement | C1 |
| E-015 | flintx | stat | classifier_dendrite.py mtime vs pipeline/classifier_dendrite.py mtime | 2026-10-22T11:54Z | Pipeline copy is newer (Oct 18 vs Oct 17) | C1 |
| E-016 | flintx | grep | machinetalk/engine.py, machinetalk/gate.py | 2026-10-22T11:54Z | No classifier import in engine or gate | C1 |

## Report plan
1. Mandate: classify user text into 6 disposition lanes + Noise fallback
2. Current State: two duplicate copies, both with constructor bug
3. Key Paths: root (7+ runners), pipeline (1 test), shared complete_stage
4. Architecture: ASCII context diagram showing runner → classifier → Soma
5. Core Logic: LLM complete_stage → JSON parse → validate → create nodes; regex fallback
6. Configuration: 6 lanes, Noise fallback, config sources differ between copies
7. Dependencies: Soma (downstream), LLM client (upstream via complete_stage)
8. Known Gaps: authority determination, constructor bug, production execution
