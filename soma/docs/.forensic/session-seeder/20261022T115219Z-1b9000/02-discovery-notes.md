# Pass 1 — Discovery Notes

## Target lock

TARGET: session-seeder
SLUG: session-seeder
RUN ID: 20261022T115219Z-1b9000

## Inventory summary

- Local root: `/home/flintx/soma-10-14/soma` (177 files at depth 3)
- session_seeder.py: 56 lines, mtime 2026-10-18T01:40:17Z, size 1757 bytes [E-001]
- Duplicate exists at `soma-grok/soma/session_seeder.py` (same content, copied in sync)
- Repository: no git metadata found at `/home/flintx/soma-10-14/soma/`

## Entry points

| Path | Lines | Host | Mtime | Evidence |
|------|-------|------|-------|----------|
| `soma/session_seeder.py` | 56 | flintx | 2026-10-18T01:40:17Z | [E-001] |
| `soma/store.py` | ~130+ | flintx | observed | [E-005] |
| `soma/pipeline/chat_log_adapter.py` | 80 | flintx | 2026-10-14T19:16:04Z | [E-006] |

## Runtime state

- Not running as a daemon/service. Only invoked as a called module by run scripts.
- No HTTP endpoint, no queue file, no service unit references session_seeder.
- Soma graph output: `/home/flintx/soma-10-14/soma/output/soma.json` (mtime 2026-10-21T20:03) [E-007]

## Data stores

| Store | Path | Engine | Mtime | Evidence |
|-------|------|--------|-------|----------|
| Soma JSON | `output/soma.json` | JSON file | 2026-10-21T20:03 | [E-007] |
| Checkpoints | `output/checkpoints/` | JSON files | 2026-10-21T19:46 | [E-008] |
| Workspaces | `workspaces/` | DIR NOT FOUND | — | [E-009] |

## Configuration and invariants

- `session_type` parameter: defaults to `"conversations"` [E-002]
- `session_id` parameter: optional; if not provided and `chat_sets` is non-empty, generates `session-{uuid4.hex[:8]}` [E-002]
- No external `.env`, `pyproject.toml`, or config file reads in session_seeder.py
- No tests exist for session_seeder.py in the main `soma/` directory

## Cross-component edges

| Direction | Mechanism | Payload | Evidence |
|-----------|-----------|---------|----------|
| Caller → session_seeder | `from session_seeder import seed_session` | Soma instance, list[ChatSetRecord], session_id | [E-010]-[E-018] |
| session_seeder → store | `from store import Soma, Node` | Soma.create_node(), Soma.create_edge() | [E-003] |
| session_seeder → chat_log_adapter | `from pipeline.chat_log_adapter import ChatSetRecord` | ChatSetRecord dataclass | [E-004] |
| session_seeder → soma_bridge (interface) | writes SessionAnchor node to same Soma instance | "SessionAnchor" type node | [E-019] |

## Instructions and recency

| Doc | Path | Mtime | Authority |
|-----|------|-------|-----------|
| PIPELINE_ACTION_MAP.md | `soma/PIPELINE_ACTION_MAP.md` | observed | C3 |
| TB-004-WIRING-SLICES.md | `turn-key/TB-004-WIRING-SLICES.md` | observed | C3 (historical) |

## Conflicts

CONFLICT C-01
  claim A: SessionAnchor properties include `session_type` and `chat_set_count` (from session_seeder.py)
  claim B: SessionAnchor properties include `project_context`, `total_sets`, `total_session_chars` (from machinetalk/soma_bridge.py)
  resolution: both-live — two different SessionAnchor writers exist
  basis: session_seeder.py L29-34 vs soma_bridge.py L53-59; they write to the same node type with different property schemas
  impact: the report must note both schemas; session_seeder uses a narrower set

CONFLICT C-02
  claim A: `Node` is imported from `store` in session_seeder.py L9
  claim B: `Node` is never used in the body of session_seeder.py
  resolution: dead import
  basis: rg confirmed no usage of `Node` in session_seeder.py beyond the import line
  impact: unnecessary import, no behavioral effect

## Unknowns and boundary gaps

U-01: The Soma `create_node` function — does it accept a type name as first argument and a properties dict as second, as session_seeder.py calls? Yes, confirmed at store.py:75.
U-02: The Soma `create_edge` function — does it accept (source_id, rel_type, target_id) and return an edge ID? Confirmed at store.py:101, but full signature (including optional return value) is unknown without reading the complete function.
U-03: Whether `seed_session` is called from any remote (Hetzner) runner. `ssh engine` was not probed; unknown.
U-04: The exact contents of `output/soma.json` — whether it contains nodes created by session_seeder or only by soma_bridge. Only observed at path level.
U-05: Whether the duplicate at `soma-grok/soma/session_seeder.py` is ever the active import path (vs the main `soma/session_seeder.py`). No import analysis of the grok directory was performed.
U-06: Whether `seed_session` is tested by any pytest suite. No test file named `test_session_seeder.py` was found.

## Evidence index

See 03-evidence-index.tsv

## Report plan

- Mandate: one sentence
- Current State: file exists, 56 lines, last modified 2026-10-18
- Key Paths: entry point, import targets, callers
- Architecture: ASCII context diagram
- Core Logic: step-by-step execution path of seed_session()
- Configuration: session_type default, session_id generation
- Dependencies: store, chat_log_adapter, callers
- Known Gaps: U-01 through U-06
- Evidence Log: table of all E-XXX entries
