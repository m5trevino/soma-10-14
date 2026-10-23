# session-seeder — Forensic Deep Dive

TARGET: session-seeder | RUN: 20261022T115219Z-1b9000 | DATE: 2026-10-22 | HOSTS EXAMINED: flintx (MX Linux, Tailscale 100.99.23.82)
CONFIDENCE SUMMARY: C1 (live file reads) for source code and import graph; C2 for caller citations; C3 for PIPELINE_ACTION_MAP documentation; no remote probe performed.
SCOPE: session-seeder.py only.

## Mandate

Create a SessionAnchor node and one ChatSet node per input record in a Soma graph, linking each ChatSet to the anchor with a HAS_CHATSET edge.

## Current State

| File | Host | Lines | Mtime |
|------|------|-------|-------|
| `soma/session_seeder.py` | flintx | 56 | 2026-10-18T01:40:17Z |
| `soma-grok/soma/session_seeder.py` | flintx | 56 | (sync copy) |

The file is a single public function `seed_session()` with two imports. No class, no module-level state. No pytest test file exists for it in the `soma/` directory. The duplicate at `soma-grok/soma/session_seeder.py` is a sync-copy artifact; no import analysis was performed on the grok tree to determine which path is active.

## Key Paths and Entry Points

| Path | Host | Role | Entrypoint? | Lines | Mtime | Evidence |
|------|------|------|-------------|-------|-------|----------|
| `soma/session_seeder.py` | flintx | Module providing `seed_session()` | Yes | 56 | 2026-10-18T01:40:17Z | [E-001] |
| `soma/store.py` | flintx | Soma graph store (import target) | No | ~130+ | observed | [E-005], [E-026] |
| `soma/pipeline/chat_log_adapter.py` | flintx | ChatSetRecord dataclass (import target) | No | 80 | 2026-10-14T19:16:04Z | [E-006] |
| `soma/run_pipeline.py` | flintx | Caller: full pipeline runner | No | — | observed | [E-010] |
| `soma/walk.py` | flintx | Caller: walk script | No | — | observed | [E-018] |
| `soma/run_new_session.py` | flintx | Caller: new session runner | No | — | observed | [E-017] |
| `soma/run_tb00{4-9}.py` | flintx | Callers: test harness scripts | No | — | observed | [E-011]-[E-016] |

## Architecture and Data Flow

```
┌──────────────┐    import     ┌───────────────┐
│   Caller      │ ──────────►  │ session_seeder │
│ (run_*.py)    │  seed_session│   seed_session │
└──────────────┘               │   (56 lines)   │
                               └───────┬────────┘
                                       │ from store import Soma, Node
                                       │ from pipeline.chat_log_adapter import ChatSetRecord
                                       ▼
                               ┌───────────────┐
                               │   Soma graph   │
                               │  (JSON file)   │
                               └───────────────┘
```

Sequence (seed_session execution):

```
caller ──seed_session(soma, chat_sets, session_id, session_type)──►
    │
    ├── if session_id not provided and chat_sets non-empty ──► generate session-{uuid4.hex[:8]} [E-021]
    │
    ├── soma.create_node("SessionAnchor", {id, session_id, session_type, chat_set_count, created_at}) [E-002]
    ├── for each ChatSetRecord:
    │     cs_id = f"cs-{cs.chat_set_id}"                          [E-035]
    │     soma.create_node("ChatSet", {id, chat_set_id, session_id, set_number, user_text, assistant_text}) [E-022]
    │     soma.create_edge(session_id, "HAS_CHATSET", cs_id)      [E-023]
    │
    └── return (anchor_id, {"nodes_created": N, "edges_created": M}) [E-024]
```

## Core Logic

**Function: `seed_session`** (`soma/session_seeder.py:13-54`)

1. **Session ID resolution** [E-002], [E-021]: If `session_id` is falsy and `chat_sets` is non-empty, generate `session-{uuid.uuid4().hex[:8]}`. If both are falsy, `session_id` remains `None`.
2. **Stats init** [E-024]: `stats = {"nodes_created": 0, "edges_created": 0}`.
3. **SessionAnchor creation** [E-002]: If `session_id` exists, call `soma.create_node("SessionAnchor", {...})` with properties `id`, `session_id`, `session_type` (default `"conversations"`), `chat_set_count` (len of input), and `created_at` (UTC ISO 8601). Increment `nodes_created`.
4. **ChatSet loop** [E-022], [E-035], [E-023]: For each `ChatSetRecord`:
   a. Construct `cs_id = f"cs-{cs.chat_set_id}"` — prepends literal `"cs-"` to the record's `chat_set_id` field.
   b. Call `soma.create_node("ChatSet", {...})` with `id`, `chat_set_id`, `session_id`, `set_number`, `user_text`, `assistant_text`.
   c. If `session_id` exists, call `soma.create_edge(session_id, "HAS_CHATSET", cs_id)`.
5. **Return** [E-024]: Returns `(anchor_id, stats)`. If no session_id was provided, returns `("", stats)` — empty string as anchor.

**Import analysis**:
- `from store import Soma, Node` [E-003]: `Node` is imported but never used in the function body (dead import [C-02]).
- `from pipeline.chat_log_adapter import ChatSetRecord` [E-004]: The frozen dataclass with fields `chat_set_id`, `session_id`, `set_number`, `user_text`, `assistant_text`.

**Soma API surface observed** [E-005], [E-026]:
- `soma.create_node(type_name, properties)` — type name as first arg, dict of properties as second. Properties dict may contain an `"id"` key for deterministic node ID; otherwise UUID is generated. [store.py:75]
- `soma.create_edge(source, rel_type, target)` — returns edge ID. [store.py:101]

## Configuration and Invariants

| Key | Default | Source | Evidence |
|-----|---------|--------|----------|
| `session_type` | `"conversations"` | Parameter default | [E-002] |
| `session_id` generation | `session-{uuid4.hex[:8]}` | L15-16 | [E-021] |
| ChatSet ID prefix | `cs-` | L43 | [E-035] |
| Edge relation type | `HAS_CHATSET` | L50 | [E-023] |
| Node types | `SessionAnchor`, `ChatSet` | L29, L42 | [E-002], [E-022] |

No `.env`, config file, or environment variable reads exist in session_seeder.py.

## Dependencies and Cross-Component Connections

| Direction | Mechanism | Details | Confidence | Evidence |
|-----------|-----------|---------|------------|----------|
| **Callers → seed_session** | Python import | 10+ callers import `from session_seeder import seed_session` | C1 | [E-010]-[E-018] |
| **seed_session → Soma** | `from store import Soma` | Creates nodes/edges via Soma API | C1 | [E-003], [E-005] |
| **seed_session → ChatSetRecord** | `from pipeline.chat_log_adapter import ChatSetRecord` | Input type is a frozen dataclass | C1 | [E-004], [E-006] |
| **seed_session → soma_bridge** | Shared Soma instance | Both write `SessionAnchor` type nodes but with different property schemas | C2 | [E-019], [C-01] |

**Caller usage patterns**:
- Most callers pass explicit `session_id`: `seed_session(soma, chatsets, session_id=session_id)` [E-010]-[E-017]
- `walk.py` omits `session_id`: `seed_session(soma, records)` — triggering auto-generation [E-018]
- Test harnesses (run_tb004-009) all pass explicit session_id [E-011]-[E-016]
- `run_pipeline.py` loads chatsets from JSON files via `load_chatsets_from_dir()` before calling [E-010]

**PIPELINE context**: PIPELINE_ACTION_MAP.md [E-020] lists session_seeder as the PRE-PIPELINE stage (Step 1), executed before Stage 1 (Classifier).

## Known Gaps and Uncertainties

G-01: **Remote caller unknown**. Whether `seed_session` is imported or called from any runner on the Hetzner remote (Tailscale 100.87.51.23) at `/root/hetzner/ai-engine/`. Would require `ssh engine` probe.
G-02: **soma.json provenance unknown**. `output/soma.json` exists (mtime 2026-10-21T20:03) [E-007] but its contents were not read. Cannot confirm whether it contains nodes created by session_seeder or only by soma_bridge.
G-03: **soma-grok import path unknown**. The duplicate `soma-grok/soma/session_seeder.py` may be the active import path for grok-related runners. No import graph was resolved in that directory.
G-04: **No tests exist**. No `test_session_seeder.py` or equivalent was found in `soma/` or `soma-grok/soma/`. The contract (return type, node shapes, edge counts) is undocumented in any test file.
G-05: **Dead import**. `Node` is imported from `store` (L9) but never referenced in the function body. This is a code quality issue but has no behavioral impact.
G-06: **SessionAnchor schema conflict**. `soma_bridge.py` creates `SessionAnchor` with properties `project_context`, `total_sets`, `total_session_chars` [E-019], while `seed_session` creates it with `session_type`, `chat_set_count`, `created_at` [E-002]. If both run in the same session, only one survives (last-write-wins due to deterministic `id` field). The interaction is not documented.

## Evidence Log

| ID | Host | Kind | Locator | Captured At | Proves | Confidence |
|----|------|------|---------|-------------|--------|------------|
| E-001 | flintx | source | `soma/session_seeder.py:1-56` | 11:52Z | Full module source, 56 lines | C1 |
| E-002 | flintx | source | `soma/session_seeder.py:13-36` | 11:52Z | Function signature, params, defaults | C1 |
| E-003 | flintx | source | `soma/session_seeder.py:9` | 11:52Z | `from store import Soma, Node` | C1 |
| E-004 | flintx | source | `soma/session_seeder.py:10` | 11:52Z | `from pipeline.chat_log_adapter import ChatSetRecord` | C1 |
| E-005 | flintx | source | `soma/store.py:75,101,128,131` | 11:52Z | Soma.create_node, create_edge, node_count, edge_count | C1 |
| E-006 | flintx | source | `soma/pipeline/chat_log_adapter.py:1-80` | 11:52Z | ChatSetRecord frozen dataclass | C1 |
| E-007 | flintx | file | `soma/output/soma.json` | 11:52Z | Output artifact exists | C1 |
| E-008 | flintx | file | `soma/output/checkpoints/` | 11:52Z | Checkpoints directory | C1 |
| E-009 | flintx | file | `soma/workspaces/` not found | 11:52Z | Workspaces dir absent | C1 |
| E-010 | flintx | source | `soma/run_pipeline.py:24,271` | 11:52Z | Caller: import + call with explicit session_id | C1 |
| E-011 | flintx | source | `soma/run_tb004.py:16,73` | 11:52Z | Caller: test harness | C1 |
| E-012 | flintx | source | `soma/run_tb005.py:15,55` | 11:52Z | Caller: test harness | C1 |
| E-013 | flintx | source | `soma/run_tb006.py:15,54` | 11:52Z | Caller: test harness | C1 |
| E-014 | flintx | source | `soma/run_tb007.py:15,56` | 11:52Z | Caller: test harness | C1 |
| E-015 | flintx | source | `soma/run_tb008.py:19,61` | 11:52Z | Caller: test harness | C1 |
| E-016 | flintx | source | `soma/run_tb009.py:14,49` | 11:52Z | Caller: test harness | C1 |
| E-017 | flintx | source | `soma/run_new_session.py:12,87` | 11:52Z | Caller: new session runner | C1 |
| E-018 | flintx | source | `soma/walk.py:20,103` | 11:52Z | Caller: walk.py omits session_id | C1 |
| E-019 | flintx | source | `soma/machinetalk/soma_bridge.py:48-61` | 11:52Z | write_session_anchor — different SessionAnchor schema | C1 |
| E-020 | flintx | source | `soma/PIPELINE_ACTION_MAP.md:4-10` | 11:52Z | Documents seed_session as PRE-PIPELINE stage | C1 |
| E-021 | flintx | source | `soma/session_seeder.py:15-16` | 11:52Z | UUID session ID generation | C1 |
| E-022 | flintx | source | `soma/session_seeder.py:42-47` | 11:52Z | ChatSet node properties | C1 |
| E-023 | flintx | source | `soma/session_seeder.py:50-51` | 11:52Z | HAS_CHATSET edge creation | C1 |
| E-024 | flintx | source | `soma/session_seeder.py:53-54` | 11:52Z | Return value shape | C1 |
| E-025 | flintx | source | `soma/session_seeder.py:38-40` | 11:52Z | ChatSet node ID format | C1 |
| E-026 | flintx | source | `soma/store.py:11-15,18-23` | 11:52Z | Node/Edge dataclass definitions | C1 |
