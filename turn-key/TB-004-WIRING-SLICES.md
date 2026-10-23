# TB-004 Wiring — Tracer Bullet Slices (Execution Order)

## Context

`/home/flintx/dendritic/` has 5 flat Python files (`classifier_dendrite.py`, `integrator_dendrite.py`, `retrograde_dendrite.py`, `session_seeder.py`, `store.py`) that all import `from soma.store`, `from soma.helpers`, `from pipeline.stage_complete`, `from pipeline.chat_log_adapter` — but **those packages don't exist**. The dendrite files also have bugs (e.g. `stage_name` undefined variable on lines 192, 49, 55).

Goal: Build the `soma/` and `pipeline/` package scaffolding so all 5 dendrite files import correctly, then wire a runner script that seeds Soma with real ChatSets and runs the 3 stages, dumping stdout.

---

## Slice 1: Soma Package Scaffold

**Objective:** Create `soma/__init__.py`, `soma/store.py` (Node, Edge, Soma from flat file)

**Scope:** Copy the existing `store.py` flat file into `soma/store.py`. Add minimal `__init__.py` that re-exports `Soma, Node, Edge`. No schema changes.

**Acceptance criteria:**
- `from soma.store import Soma, Node, Edge` works from `/home/flintx/dendritic/`
- Soma.create_node, Soma.get_node, Soma.query_by_type, Soma.create_edge, Soma.start_batch, Soma.commit_batch all work
- Soma.persist to JSON file works

**Test strategy:** Inline test at bottom of `soma/store.py` or quick `python -c "..."` that creates a Soma, adds a node, queries it, creates an edge, checks count.

**Handoff format:** `soma/__init__.py` + `soma/store.py` present and importable.

**Estimated effort:** 30 min

**Hard gates:**
- Must not change the Soma class API (no new methods, no removed methods)
- Must not import anything external (only stdlib)
- Must preserve the exact file-persist format (JSON nodes dict + edges list)

---

## Slice 2: Soma Helpers Package

**Objective:** Create `soma/helpers.py` with `get_receptor_config` and `put_receptor_config`

**Scope:** Create the helpers module as imported by all 3 dendrite files. Both functions are pure Soma queries — no external dependencies.

**Acceptance criteria:**
- `from soma.helpers import get_receptor_config, put_receptor_config` works
- `get_receptor_config(soma, "classifier")` queries `query_by_type("ReceptorConfig")` and returns the matching node's properties
- `put_receptor_config(soma, "classifier", instruction_body="test")` creates a ReceptorConfig node

**Test strategy:** `python -c "from soma.helpers import get_receptor_config; print('OK')"` — no ReceptorConfig nodes exist yet so it should return None gracefully.

**Handoff format:** `soma/helpers.py` present and importable.

**Estimated effort:** 15 min

**Hard gates:**
- Must not change the signature from what the dendrite files expect
- Must not import anything outside stdlib

---

## Slice 3: Pipeline Chat Log Adapter

**Objective:** Create `pipeline/chat_log_adapter.py` with `ChatSetRecord` dataclass and parsing functions

**Scope:** Create the module. It needs no external imports (pure stdlib). `parse_chat_log()` and `parse_directory()` handle JSON input. `ChatSetRecord` is a frozen dataclass with `chat_set_id, session_id, set_number, user_text, assistant_text`.

**Acceptance criteria:**
- `from pipeline.chat_log_adapter import ChatSetRecord, parse_chat_log, parse_directory` works
- `ChatSetRecord.from_dict()` raises ValueError on missing required fields
- `parse_chat_log()` handles list input, dict with `chat_sets`/`messages`/`turns` key, and nested session dict
- Records sorted by `set_number` ascending
- Duplicate `chat_set_id` raises ValueError

**Test strategy:** `python -c "from pipeline.chat_log_adapter import ChatSetRecord; print(ChatSetRecord.from_dict({'chat_set_id': '1', 'session_id': 's1', 'set_number': 1, 'user_text': 'hi', 'assistant_text': 'hello'}))"`

**Handoff format:** `pipeline/chat_log_adapter.py` present and importable.

**Estimated effort:** 15 min

**Hard gates:**
- Must not import anything outside stdlib
- Must match the frozen dataclass slots=True signature exactly

---

## Slice 4: Pipeline Denderite Stub

**Objective:** Create `pipeline/drafter_dendrite.py` minimal stub with `LLMClient`, `LLMResponse`, `ModelRotator`

**Scope:** The `stage_complete.py` imports `from pipeline.drafter_dendrite import LLMClient`. The dendrite files also use `self._rotator.next_model(stage_name)`. We need minimal stubs — NOT the full 633-line drafter (that's a crystallization stage, not classifier). Only:
- `LLMResponse` dataclass (model_id, content, prompt_tokens, completion_tokens, total_tokens, latency_ms, tool_calls)
- `LLMClient` abstract class with `chat(messages, tools, tool_choice, model, **kwargs) -> LLMResponse`
- `ModelRotator` with `__init__(models)` and `next_model(stage_name)` returning a model string

**Acceptance criteria:**
- `from pipeline.drafter_dendrite import LLMClient, LLMResponse, ModelRotator` works
- `ModelRotator` constructor accepts `models: list[str]`
- `ModelRotator.next_model(stage_name)` returns next model in round-robin (ignores stage_name)
- `LLMClient.chat()` raises `NotImplementedError`
- `MockLLMClient` (inline stub) returns pre-programmed responses

**Test strategy:** Create `ModelRotator(["gpt-4", "claude-3"])`, call `next_model("distiller")` twice, verify round-robin.

**Handoff format:** `pipeline/drafter_dendrite.py` with minimal stubs only.

**Estimated effort:** 30 min

**Hard gates:**
- `next_model(stage_name)` must accept the parameter (the dendrite files pass `stage_name`)
- Must NOT include `DrafterDendrite` class or any code generation logic
- Must NOT include `ToolRegistry`

---

## Slice 5: Pipeline Stage Complete Module

**Objective:** Create `pipeline/stage_complete.py` with `complete_stage()` function

**Scope:** Create the module. It needs `LLMClient` from `pipeline.drafter_dendrite` (Slice 4). The function calls `llm.chat()`, extracts JSON from response, rejects prose bleed, returns structured result.

**Acceptance criteria:**
- `from pipeline.stage_complete import complete_stage` works
- `complete_stage()` has signature `(llm, model_id, instruction_body, payload) -> dict`
- `complete_stage()` calls `llm.chat(messages=[{system, user}], model=model_id)`
- Extracts JSON from response, rejects prose bleed, returns `{"ok": True, "result": parsed, "metrics": {...}}` or `{"ok": False, "error": ..., "metrics": {...}}`
- Metrics always include: `model_id`, `prompt_tokens`, `completion_tokens`, `total_tokens`, `latency_ms`

**Test strategy:** Test with `MockLLMClient` (defined inline) that returns a JSON object — verify `ok: True`. Test with bad response — verify `ok: False`.

**Handoff format:** `pipeline/stage_complete.py` present and importable.

**Estimated effort:** 1 hour

**Hard gates:**
- Must not import classifier/integrator/retrograde
- Must not write Soma nodes
- Must not embed role prompts for any named agent

---

## Slice 6: Fix Dendrite Files and Session Seeder

**Objective:** Fix the 3 dendrite files' `stage_name` NameError and make session_seeder.py work

**Scope:** The flat files have `self._rotator.next_model(stage_name)` on lines 192, 49, 55 where `stage_name` is not a variable. Fix to use hard-coded stage name strings:
- `classifier_dendrite.py`: `self._rotator.next_model("classifier")`
- `integrator_dendrite.py`: `self._rotator.next_model("integrator")`
- `retrograde_dendrite.py`: `self._rotator.next_model("retrograde")`

Also verify `session_seeder.py` imports work after soma/pipeline are set up.

**Acceptance criteria:**
- `from classifier_dendrite import ClassifierDendrite` works
- `from integrator_dendrite import IntegratorDendrite` works
- `from retrograde_dendrite import RetrogradeDendrite` works
- `from session_seeder import seed_session` works
- No NameError on `stage_name` in any of the 3 files
- All class constructors accept `(soma, llm_client, model_rotator)` signature

**Test strategy:** `python -c "from classifier_dendrite import ClassifierDendrite; print('OK')"` for each file.

**Handoff format:** All 4 files importable with no errors.

**Estimated effort:** 30 min

**Hard gates:**
- Must not change the class API (`run(chat_set_id) -> dict`)
- Must not add any new dependencies
- Must use hard-coded stage name strings (e.g. `"classifier"`) not undefined variables

---

## Slice 7: Wiring Runner Script

**Objective:** Create a runner script that wires TurnKey SDK to the 3 dendrite stages and dumps stdout

**Scope:** Create a single Python script that:
1. Creates an in-memory `Soma` (no file persist needed for TB-004, or use a temp file)
2. Seeds it with real ChatSets from `soma/session_seeder.py`
3. Uses a `MockLLMClient` (from `pipeline.drafter_dendrite`) so no real LLM call is needed
4. Instantiates `ClassifierDendrite`, `IntegratorDendrite`, `RetrogradeDendrite` with the mock
5. Calls `dendrite.run(chat_set_id)` for each ChatSet
6. Prints to stdout:
   - Node types created with counts (IntentNode, DirectiveNode, ConstraintNode, TaskNode, RiskNode, etc.)
   - Edge types and counts (EXTRACTED_FROM, REQUIRES_ACTION, INTRODUCES_RISK, etc.)
   - Which nodes belong to which ChatSet

**Acceptance criteria:**
- All three stages run without errors on seeded data
- Stdout prints: "Node types created:" with each type and count
- Stdout prints: "Edge types:" with each relationship and count
- Stdout prints: "ChatSet <id> has nodes: [...]" for each ChatSet
- Node counts are non-zero (mock should return at least some signals)
- Mock returns tool-related nodes when ChatSet has tool call text

**Test strategy:** Run the script, verify stdout has all required sections. Run on a ChatSet that mentions tools (e.g., "use the get_weather tool") and verify tool-related nodes exist in output.

**Handoff format:** Single runner script at `/home/flintx/dendritic/run_stage1.py` that outputs node/edge dump to stdout only.

**Estimated effort:** 1 hour

**Hard gates:**
- Must not run any Crystallization stages (Nexus through CodePublisher)
- Must not write to disk beyond stdout (or a temporary JSON file if needed for Soma persistence)
- Must use real ChatSets (not synthetic test data)
- Must use `MockLLMClient` — no real LLM calls

---

## Slice 8: Integration Verification

**Objective:** End-to-end run on real Soma data, verify all node types and edges, confirm tool-call detection

**Scope:** Take real ChatSet data from the existing dendritic data (chats/ or fixtures/), seed Soma, run all 3 stages with the MockLLMClient, capture stdout, verify acceptance criteria. Fix any edge-case bugs found during the run.

**Acceptance criteria:**
- Script runs to completion without any exceptions
- All expected node types appear: IntentNode, DirectiveNode, ConstraintNode, QuestionNode, TaskNode, RiskNode, DecisionNode, StackNode, OutcomeNode, DeliverableNode
- All expected edge types appear: EXTRACTED_FROM, REQUIRES_ACTION, ADDRESSES, INTRODUCES_RISK, USES_STACK, TRIGGERED_BY
- Each ChatSet has at least 1 node and 1 edge
- Tool-related nodes appear when a ChatSet contains tool-call mentions
- Stdout is clean, structured, parseable

**Test strategy:** Run `python run_stage1.py` on 3 real ChatSets. Verify node counts > 0 for all expected types. Verify edges count > 0. Verify ChatSet-to-node mapping.

**Handoff format:** Clean stdout dump, no files written beyond optional temp Soma JSON.

**Estimated effort:** 30 min

**Hard gates:**
- Must not run any Crystallization stages
- Must not write to disk beyond stdout (temporary Soma JSON is acceptable if needed)
- Must use real Soma data from existing chats/fixtures