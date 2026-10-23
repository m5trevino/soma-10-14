# Classifier — Forensic Deep Dive

TARGET: classifier | RUN: 20261022T115433Z-49061e | DATE: 2026-10-22T11:54Z | HOSTS EXAMINED: flintx
CONFIDENCE SUMMARY: High on structure (C1/C2); Medium on constructor bug intent (C2); Low on production execution (C3)
SCOPE: Signal extraction and disposition classification for the Dendritic/Soma system

## Mandate

Extract signals from a user ChatSet's text, classify them into six disposition lanes plus a Noise fallback, and persist them as nodes with EXTRACTED_FROM edges in Soma.

## Current State

Two functionally divergent copies of `classifier_dendrite.py` exist [E-001] [E-002]. Both define a `ClassifierDendrite` class with an identical two-parameter constructor (`__init__(self, soma, llm_client)`). Neither copy is currently executable in production because all nine runner scripts instantiate the class with three arguments [E-003] [E-004], which would raise a `TypeError` (both copies accept only two positional arguments [E-005] [E-006]). The pipeline copy is the newer version (393 lines, mtime 2026-10-18 [E-015], added schema validation, self-contained LLM wrapper). The root copy is the one imported by all production runners [E-004] but those runners are all broken.

| Component | Path | Lines | Mtime (UTC) | Authority |
|---|---|---|---|---|
| Root copy | `classifier_dendrite.py` | 302 | 2026-10-17T18:40 | Imported by 9 runners (but broken); docstring "TB-DEND-020" [E-017] |
| Pipeline copy | `pipeline/classifier_dendrite.py` | 393 | 2026-10-18T16:30 | Imported by test file only; docstring "TB-TK-REPLACE-002" [E-018]; newer mtime [E-015] |
| Tests | `test_classifier_dendrite.py` | 386 | 2026-10-19T00:38 | Imports pipeline copy — tests pass against it |

## Key Paths and Entry Points

| Path | Host | Role | Entrypoint? | Lines | Mtime | Evidence |
|---|---|---|---|---|---|---|
| `classifier_dendrite.py` | flintx | Root classifier module | Class: `ClassifierDendrite` | 302 | 2026-10-17 | E-001 |
| `pipeline/classifier_dendrite.py` | flintx | Pipeline classifier module | Class: `ClassifierDendrite` | 393 | 2026-10-18 | E-002 |
| `pipeline/stage_complete.py` | flintx | Shared LLM orchestrator | Function: `complete_stage` | ~70 | 2026-10-14 | E-011 |
| `pipeline/drafter_dendrite.py` | flintx | LLMClient/LLMResponse types | Class: `LLMClient`, `LLMResponse` | — | 2026-10-14 | E-011 |
| `soma/helpers.py` | flintx | Receptor config helper | Function: `get_receptor_config` | — | — | E-012 |
| `run_pipeline.py` | flintx | Pipeline orchestrator | Class: `InteractiveRunner` | — | — | E-003 |
| `run_tb004.py` through `run_tb009.py`, `run_new_session.py`, `run_new_session_fix.py` | flintx | Individual runners | — | — | — | E-004 |

## Architecture and Data Flow

```text
┌──────────────────────────────────────────────────────────────────┐
│  Runner Process (run_tb004.py, run_pipeline.py, … 9 runners)     │
│    E-004                                                          │
│         │                                                         │
│         ▼                                                         │
│  ClassifierDendrite(soma, llm) ──── CONFLICT: 3-arg instantiation │
│    E-003  E-005/E-006                                             │
│         │                                                         │
│    ┌────┴────┐                                                    │
│    ▼         ▼                                                    │
│  LLM path  Regex fallback                                        │
│  E-011     E-009                                                  │
│    │         │                                                    │
│    ▼         ▼                                                    │
│  create_node()  create_edge() ──► Soma (store)                   │
│  E-001          E-001                                             │
└──────────────────────────────────────────────────────────────────┘
```

Sequence (LLM success path):
1. Runner calls `ClassifierDendrite(soma, llm).run(chat_set_id)` [E-001] [E-002]
2. Classifier reads ChatSet node from Soma [E-001:180, E-002:278]
3. Classifier fetches ReceptorConfig (root: via `soma.helpers.get_receptor_config` [E-012]; pipeline: direct Soma lookup [E-013])
4. Classifier calls `complete_stage(llm, "classifier", instruction, user_text)` [E-001:212, E-002:304]
5. `complete_stage()` calls `llm.call(stage, messages)` (or wraps `.chat()` in pipeline copy) [E-011, E-010]
6. LLM returns JSON-parsable signal array [E-011:47-58]
7. Pipeline copy validates each signal via `validate_signal()` [E-014]; root copy does not validate
8. Classifier creates signal nodes and EXTRACTED_FROM edges in Soma [E-001:216-228, E-002:316-328]

Sequence (LLM failure path):
1. `complete_stage()` returns `{"ok": False, ...}` [E-011:30-36]
2. Classifier calls regex fallback (`classify()` in root [E-001:102], `heuristic_classify()` in pipeline [E-002:75])
3. Regex fallback creates nodes the same way as LLM path [E-001:237-260, E-002:335-355]

## Core Logic

### Root copy (`classifier_dendrite.py`)

The root copy implements two classification strategies:

**LLM path** (lines 166-232):
- `ClassifierDendrite.__init__(soma, llm_client)` — 2 args [E-005]
- `run(chat_set_id)` reads ChatSet, fetches config via `get_receptor_config(self._soma, "classifier")` [E-012]
- Calls `complete_stage(self._llm, "classifier", instruction_body, user_text)` imported from `pipeline.stage_complete` [E-011] [E-012]
- Parses JSON result; normalizes signal_type with "Node" suffix if missing [E-001]
- Creates nodes via `self._soma.create_node()` and edges via `self._soma.create_edge()` [E-001]
- On LLM failure: delegates to `_run_regex_fallback()` [E-001]

**Regex path** (lines 237-270):
- Calls `classify(text)` which implements priority cascade: Question → Correction → Directive → Constraint → Preference → Noise → Intent fallback [E-001]
- Creates nodes with IDs `sig-{chat_set_id}-{signal_type}-{i}` [E-001]
- Same node/edge creation pattern as LLM path [E-001]

**Regex patterns** (lines 30-95):
- `_QUESTION_RE` matches `?` and question words [E-009]
- `_COMMAND_RE` matches 45+ imperative verbs [E-009]
- `_PREFERENCE_RE` matches preference indicators [E-009]
- `_CORRECTION_RE` matches correction indicators [E-009]
- `_CONSTRAINT_RE` matches constraint/modality words [E-009]
- `_NOISE_RE` matches greetings, thanks, acknowledgements [E-009]
- Priority: Question(0.85) > Correction(0.80) > Directive(0.75) > Constraint(0.70) > Preference(0.65) > Noise(0.90) > Intent(0.30 fallback) [E-009]

### Pipeline copy (`pipeline/classifier_dendrite.py`)

The pipeline copy adds seven components not present in the root copy:

**Added components** (not in root copy):
- `ClassifiedSignal` dataclass with `node_id` field [E-002:53-58]
- `DISPOSITION_LANES: frozenset` — explicit 6-lane enum [E-008]
- `heuristic_classify()` function (renamed from `classify()`) [E-002:75]
- `LLMToolCallClient` wrapper class for bare `.chat()` clients [E-010:161-174]
- Self-contained `complete_stage()` with JSON fence extraction [E-010:181-233]
- `validate_signal()` — schema enforcement: required keys, valid lane, confidence range [E-014]
- Direct Soma config lookup instead of `soma.helpers.get_receptor_config` [E-013]
- `_regex_fallback()` — same as root but uses `heuristic_classify()` [E-002:325]

**Divergences from root**:
- Pipeline copy's `complete_stage()` handles both `LLMClient` (has `.call()`) and bare clients (has `.chat()`) via `LLMToolCallClient` [E-010]
- Root copy's `complete_stage()` requires `.call()` interface only [E-011]
- Pipeline copy validates signal_type against `DISPOSITION_LANES` — rejects NoiseNode in LLM path [E-014, E-008]
- Root copy accepts any signal_type (no validation, normalizes "Node" suffix) [E-001]

## Configuration and Invariants

| Key | Root Copy | Pipeline Copy | Source |
|---|---|---|---|
| 6 Disposition Lanes | No explicit constant | `DISPOSITION_LANES` frozenset | E-008 |
| Noise handling | Accepted via regex fallback, no validation | Accepted as `NOISE_FALLBACK` constant, rejected by `validate_signal()` | E-008, E-014 |
| Config source | `get_receptor_config(soma, "classifier")` | `soma.get_node("config-classifier")` | E-012, E-013 |
| complete_stage | Imported from `pipeline.stage_complete` | Self-defined with `LLMToolCallClient` wrapper | E-011, E-010 |
| Required signal keys | None (trusts LLM output) | `{"signal_type", "confidence", "source_text", "rationale"}` | E-014 |
| Confidence validation | None | Must be float in [0.0, 1.0] | E-014 |
| Hard gates (docstring) | "stage_name → classifier" | "Must NOT generate code artifacts", "Must use only 6 lanes", "Must use create_soma_node/edge tools" | E-001, E-002 |

The pipeline copy's `validate_signal()` rejects signals where `signal_type` is not in `DISPOSITION_LANES` (E-014), meaning NoiseNode — though accepted by the regex fallback — would be silently dropped if returned by the LLM. The root copy has no such filter and would persist any signal_type.

## Dependencies and Cross-Component Connections

### Downstream (what classifier writes to)
- **Soma** (`store.Soma`): reads ChatSet nodes, writes signal nodes (IntentNode, DirectiveNode, etc.), writes EXTRACTED_FROM edges [E-001] [E-002]. No foreign key constraints — free-form node types.

### Upstream (what classifier reads from)
- **LLM client**: receives `stage`, `messages` list (system + user content). Must provide either `.call(stage, messages)` (LLMClient interface) or `.chat(messages)` (wrapped by LLMToolCallClient in pipeline copy) [E-011, E-010]
- **ReceptorConfig**: stored in Soma as a node with key `"config-classifier"` (pipeline copy) or looked up via `soma.helpers.get_receptor_config()` (root copy) [E-012, E-013]
- **ChatSet nodes**: classifier reads `session_id`, `user_text`, `assistant_text` properties [E-001] [E-002]

### Sibling components (observed from classifier's side only)
- **pipeline.stage_complete**: shared LLM call orchestrator [E-011]
- **pipeline.drafter_dendrite**: provides LLMClient, LLMResponse types [E-011]
- **soma.helpers**: provides get_receptor_config() [E-012]
- **machinetalk.engine**: no import relationship observed [E-016]

## Known Gaps and Uncertainties

### G-01: 3-argument instantiation is fatal
All nine runner scripts call `ClassifierDendrite(soma, llm, rotator_or_None)` with three positional arguments. Both `ClassifierDendrite` copies define `__init__(self, soma, llm_client)` with two parameters. This would raise `TypeError` at runtime on every runner invocation.

- Evidence: `run_pipeline.py:106` [E-003], `run_tb004.py:81` [E-004], root `__init__` [E-005], pipeline `__init__` [E-006]
- Impact: All 9 runner scripts (`run_tb004.py` through `run_tb009.py`, `run_new_session.py`, `run_new_session_fix.py`, `run_pipeline.py`) crash at instantiation.
- Closure evidence needed: git blame on constructor and instantiation sites to confirm the `rotator` parameter was removed.

### G-02: Canonical authority is unresolved
The root copy [E-001] is imported by all production runners but is older (mtime 2026-10-17). The pipeline copy [E-002] is newer (mtime 2026-10-18 [E-015]), referenced by the test file [E-007], and implements schema validation, `LLMToolCallClient` wrapper, and a self-contained `complete_stage()` [E-010].

- Impact: No clear migration plan. Both copies coexist without deprecation markers.
- Closure evidence needed: TB-TK-REPLACE-002 tracking document or changelog entry.

### G-03: Production execution is unverified
No process, log, or artifact confirms that the classifier has ever executed successfully. The constructor bug (G-01) makes all runner scripts non-functional at instantiation.

- Evidence: no `ps`/`systemctl` evidence for classifier process; all 9 runners have broken instantiation [E-003] [E-004].
- Closure evidence needed: successful end-to-end pipeline run log.

### G-04: NoiseNode enforcement gap
The pipeline copy's `validate_signal()` rejects signals where `signal_type` is not in `DISPOSITION_LANES` [E-014] — NoiseNode is not in the frozenset [E-008]. Yet both copies accept NoiseNode in the regex fallback path. If the LLM returns `{"signal_type": "NoiseNode", ...}`, the pipeline copy silently drops it. The root copy persists it (no validation).

- Impact: Pipeline copy has a data loss path for NoiseNode LLM responses; root copy has no schema enforcement at all.
- Closure evidence needed: TB-TK-REPLACE-002 clarification on NoiseNode intent.

### G-05: No machinetalk engine integration
The machinetalk engine (`machinetalk/engine.py`) does not import or reference the classifier [E-016]. The gate module (`machinetalk/gate.py`) also has no classifier import.

- Impact: Classifier is exclusively runner-driven; engine session processing does not invoke classifier.
- Closure evidence needed: Confirmation that engine never invokes classifier indirectly.

## Evidence Log

| ID | Host | Kind | Locator | Captured At | Proves | Confidence |
|---|---|---|---|---|---|---|
| E-001 | flintx | source | `classifier_dendrite.py:1-302` | 2026-10-22T11:54Z | Root copy: Signal dataclass, classify(), complete_stage import, get_receptor_config usage, __init__(soma,llm), run(), _run_regex_fallback() | C1 |
| E-002 | flintx | source | `pipeline/classifier_dendrite.py:1-393` | 2026-10-22T11:54Z | Pipeline copy: ClassifiedSignal, heuristic_classify(), DISPOSITION_LANES, validate_signal(), LLMToolCallClient, self-contained complete_stage, __init__(soma,llm), run(), _regex_fallback() | C1 |
| E-003 | flintx | grep | `run_pipeline.py:25,106` | 2026-10-22T11:54Z | 3-arg instantiation: `ClassifierDendrite(self._soma, self._llm, None)` | C1 |
| E-004 | flintx | grep | `run_tb004.py:81` through `run_new_session_fix.py:54` (9 files) | 2026-10-22T11:54Z | All runners use 3-arg instantiation: `ClassifierDendrite(soma, llm, rotator_or_None)` | C1 |
| E-005 | flintx | source | `classifier_dendrite.py:169` | 2026-10-22T11:54Z | Root `__init__` signature: `def __init__(self, soma: Soma, llm_client: Any)` — 2 params | C1 |
| E-006 | flintx | source | `pipeline/classifier_dendrite.py:265` | 2026-10-22T11:54Z | Pipeline `__init__` signature: `def __init__(self, soma: Soma, llm_client: Any)` — 2 params | C1 |
| E-007 | flintx | grep | `test_classifier_dendrite.py:23` | 2026-10-22T11:54Z | Tests import from `pipeline.classifier_dendrite` (not root) | C1 |
| E-008 | flintx | source | `pipeline/classifier_dendrite.py:38-50` | 2026-10-22T11:54Z | `DISPOSITION_LANES` frozenset with 6 lanes, `NOISE_FALLBACK = "NoiseNode"` | C1 |
| E-009 | flintx | source | `classifier_dendrite.py:34-63` | 2026-10-22T11:54Z | Root regex patterns: _QUESTION_RE, _COMMAND_RE, _PREFERENCE_RE, _CORRECTION_RE, _CONSTRAINT_RE, _NOISE_RE | C1 |
| E-010 | flintx | source | `pipeline/classifier_dendrite.py:159-259` | 2026-10-22T11:54Z | Pipeline's self-contained complete_stage() with LLMToolCallClient wrapper and JSON fence extraction | C1 |
| E-011 | flintx | source | `pipeline/stage_complete.py:20-70` | 2026-10-22T11:54Z | Shared complete_stage() requiring llm.call() interface | C1 |
| E-012 | flintx | source | `classifier_dendrite.py:15-16,205-206` | 2026-10-22T11:54Z | Root imports complete_stage from pipeline.stage_complete and get_receptor_config from soma.helpers; uses get_receptor_config at line 205 | C1 |
| E-013 | flintx | source | `pipeline/classifier_dendrite.py:280-282` | 2026-10-22T11:54Z | Pipeline reads config directly: `config = self._soma.get_node("config-classifier")` | C1 |
| E-014 | flintx | source | `pipeline/classifier_dendrite.py:230-250` | 2026-10-22T11:54Z | validate_signal() checks required keys, valid signal_type against DISPOSITION_LANES, confidence in [0.0, 1.0] | C1 |
| E-015 | flintx | stat | `stat -c '%Y'` on both files | 2026-10-22T11:54Z | Pipeline copy mtime (1792366212) > root copy mtime (1792287617) — pipeline is newer by ~22 hours | C1 |
| E-016 | flintx | grep | `machinetalk/engine.py`, `machinetalk/gate.py` | 2026-10-22T11:54Z | No classifier import found in engine or gate | C1 |
| E-017 | flintx | source | `classifier_dendrite.py:30` | 2026-10-22T11:54Z | Root docstring: "TB-DEND-020: Classifier Dendrite (FIXED — stage_name → "classifier")" | C1 |
| E-018 | flintx | source | `pipeline/classifier_dendrite.py:1` | 2026-10-22T11:54Z | Pipeline docstring: "TB-TK-REPLACE-002: Classifier Dendrite — signal extraction via LLM tool-calling" | C1 |
