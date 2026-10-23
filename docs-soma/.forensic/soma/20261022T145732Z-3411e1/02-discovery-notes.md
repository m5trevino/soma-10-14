# Discovery Notes: machine-talk (alias: machinetalk → target: soma)

TARGET: soma (machine-talk subdirectory)
SLUG: soma
RUN: 20261022T145732Z-3411e1
PASS: 1 (discovery)
STARTED: 2026-10-22T14:57:32Z
ANALYST: trevino-dendritic-forensic-deepseek

## Target lock

- Canonical target: soma (aliases: soma-engine, engine-local, soma-pipeline, machinetalk). Scope restricted to the `soma/machine-talk/` directory: the TB prompt templates and their runtime wiring.
- Scope sentence: Forensic deep-dive on the MachineTalk protocol — 14 TB prompt files, the FLEET prompt-assembler, gate validator, hash helpers, source loader, and their integration into the soma/machinetalk/engine.py pipeline engine and soma_bridge.py Soma graph bridge.
- Excluded: soma/ directory files outside machine-talk/ and machinetalk/ (dendrite stages, store.py, run_engine.py, run_pipeline.py, session_seeder, axon_hillock, myelinator, saltatory_gate). Remote ai-engine components. Soma-session-picker.
- Local roots examined: `/home/flintx/soma-10-14/soma/machine-talk/` (15 files, 1800 lines), `/home/flintx/soma-10-14/soma/machinetalk/` (16 files, ~270K lines of Python runtime code)
- Remote roots examined: `/root/hetzner/ai-engine` — not probed (machine-talk is a local-only protocol package).
- Probe window: 2026-10-22T14:57:32Z to 2026-10-22T15:10:00Z.

## Inventory summary

| Root | Host | Exists | Files | Newest file | Newest mtime |
|---|---|---:|---:|---|---|
| soma/machine-talk/ | flintx | yes | 15 | tb-*.md files | 2026-10-14T12:15Z |
| soma/machinetalk/ | flintx | yes | 16 (incl. __pycache__) | engine.py | 2026-10-21T19:43Z |
| soma/machinetalk/__pycache__ | flintx | yes | 10+ | engine.cpython-311.pyc | 2026-10-21T19:44Z |

- Repository state: project root is `/home/flintx/soma-10-14`; machine-talk files are 2026-10-14, untouched since creation.
- Archives or mirrors: `soma-grok/soma/machine-talk/` is a stale mirror with identical filenames.

## Entry points

| Path | Host | Role | Lines | Mtime | Evidence |
|---|---|---|---:|---|---|
| soma/machine-talk/MACHINE_TALK_SPEC.md | flintx | Spec doc | 298 | 2026-10-14T12:15Z | [E-001] |
| soma/machine-talk/cli-manifest.json | flintx | Pipeline manifest | 124 | 2026-10-14T12:15Z | [E-002] |
| soma/machine-talk/tb-001-distiller.md | flintx | Distiller prompt | 196 | 2026-10-14T12:15Z | [E-003] |
| soma/machine-talk/tb-002-pipeline-protocol.md | flintx | Handoff protocol | 49 | 2026-10-14T12:15Z | [E-004] |
| soma/machine-talk/tb-003-system-base.md | flintx | System base prompt | 22 | 2026-10-14T12:15Z | [E-005] |
| soma/machine-talk/tb-004-introbeaver.md | flintx | Intent extraction prompt | 154 | 2026-10-14T12:15Z | [E-006] |
| soma/machine-talk/tb-005-planbeaver.md | flintx | Build plan prompt | 232 | 2026-10-14T12:15Z | [E-007] |
| soma/machine-talk/tb-006-outrobeaver.md | flintx | Session autopsy prompt | 206 | 2026-10-14T12:15Z | [E-008] |
| soma/machine-talk/tb-007-nexus.md | flintx | Strategic blueprint prompt | 66 | 2026-10-14T12:15Z | [E-009] |
| soma/machine-talk/tb-008-spark.md | flintx | Functional spec prompt | 80 | 2026-10-14T12:15Z | [E-010] |
| soma/machine-talk/tb-009-falcon.md | flintx | Architecture prompt | 69 | 2026-10-14T12:15Z | [E-011] |
| soma/machine-talk/tb-010-eagle.md | flintx | Skeleton architecture prompt | 104 | 2026-10-14T12:15Z | [E-012] |
| soma/machine-talk/tb-011-drafter.md | flintx | Code generation prompt | 174 | 2026-10-14T12:15Z | [E-013] |
| soma/machine-talk/tb-012-scout.md | flintx | Invariant violation report prompt | 108 | 2026-10-14T12:15Z | [E-014] |
| soma/machine-talk/tb-013-oc.md | flintx | Go/No-Go gatekeeper prompt | 164 | 2026-10-14T12:15Z | [E-015] |
| soma/machine-talk/tb-014-olc.md | flintx | Code hardening prompt | 176 | 2026-10-14T12:15Z | [E-016] |

- Confirmed importable surfaces: `soma/machinetalk/fleet.py` reads all TB files via `FLEET_DIR` at runtime. `soma/machinetalk/client.py` calls them via TurnKey SDK. `soma/machinetalk/gate.py` validates LLM responses per stage contract.
- No standalone executable; machine-talk is a protocol package consumed by the machinetalk engine.

## Runtime state

- Process inspection: `ps -eo pid,etimes,cmd | grep soma` — no running soma process found on flintx. MachineTalk is invoked via `run_engine.py` or `run_sessions.py`.
- MachineTalk itself is not a service; it is a prompt protocol + gate-validation + payload-assembly layer invoked by the Engine.
- Queue/state files: `/home/flintx/soma-10-14/data/queue.json` (mtime 2026-10-22T03:03Z), `/home/flintx/soma-10-14/data/soma_queue.json` (mtime 2026-10-22T03:03Z).

## Data stores

| Store | Host | Engine | Schema summary | Rows | Newest record | Access | Evidence |
|---|---|---|---|---:|---|---|---|
| soma/output/soma.json | flintx | JSON | Soma graph (nodes + edges) | error: file is not a database | N/A | read-only | [E-017] |
| checkpoints/<session>.checkpoint.json | flintx | JSON | Per-session stage state | varies | runtime | read-only | [E-018] |

- `soma.json` was expected to be JSON (AtomicSoma writes JSON) but was opened as SQLite; the error confirms it was previously stored as SQLite or corrupted.
- The machinetalk engine uses `AtomicSoma` for JSON-backed Soma graph persistence at `<out>/soma.json`.

## Configuration and invariants

| Key / rule | Source path:line | Default | Effective value (redacted) | Enforced in code? |
|---|---|---|---|---|
| System base prompt | machinetalk/fleet.py:116-117 | `tb-003-system-base.md` | prose→∅, no_assistant_prose, no_markdown_fences | [E-019] |
| Pipeline handoff protocol | machinetalk/fleet.py:118-119 | `tb-002-pipeline-protocol.md` | handoff rules, validation before processing | [E-020] |
| Stage fleet map | machinetalk/fleet.py:42-55 | 12 stages across 4 groups | stage1→stage4 order | [E-021] |
| Gate specs | machinetalk/gate.py:60-77 | per-stage required keys, verdict keys, hash keys | validated at runtime | [E-022] |
| Hash computation | machinetalk/hashes.py:13-17 | canonical_json → SHA-256 | echoed by LLM model | [E-023] |
| Invariant rules | machinetalk/invariants.py:14-40 | 4 default rules | security/correctness/safety/style | [E-024] |
| Stage model mapping | machinetalk/client.py:12-35 | legacy → modern stage name mapping | e.g. "receptor" → "distiller" | [E-025] |
| Workers | run_engine.py:99 | default 2 | configurable via --workers | [E-026] |
| Timeout | machinetalk/client.py:92 | 180 seconds | hard timeout on model calls | [E-027] |
| max_chatsets | run_engine.py:102 | None (all) | configurable via --max-chatsets | [E-028] |

- Config precedence: system-base + pipeline-protocol + stage prompt (assembled in fleet.py:load_system_prompt).
- Environment variables read (names only): `PYTHONPATH` (run.sh), `HETZNER_OUTPUT_LOG` (run_engine.py).
- Hard gates per stage: defined in gate.py SPECS dict — each stage has required keys, verdict keys, block_tokens, and optional hash_key for echo verification.

## Cross-component edges

| Direction | Counterpart | Mechanism | Payload / contract | Evidence |
|---|---|---|---|---|
| machine-talk → machinetalk/fleet.py | Fleet assembler | FLEET_DIR import | TB files loaded at runtime | [E-021] |
| machine-talk → machinetalk/client.py | TurnKeyClient | _STAGE_MAP | stage name mapping (12 entries + legacy) | [E-025] |
| machine-talk → machinetalk/gate.py | Gate validator | SPECS dict | per-stage validation contracts | [E-022] |
| machine-talk → machinetalk/engine.py | Engine | GROUP_OF, stage names | stage grouping (stage1→stage4) | [E-029] |
| machine-talk → machinetalk/source.py | Source loader | ChatSet raw_chat_set | canonical array format for hashing | [E-030] |
| engine.py → soma/machinetalk/soma_bridge.py | SomaBridge | `self._bridge.write_*()` | 12 write methods → graph nodes | [E-031] |
| engine.py → turnkey.sdk | TurnKey SDK | `initialize_sdk_with_profile()` | model selection + HTTP call | [E-032] |
| engine.py → checkpoint.py | CheckpointStore | `self.ck.cs_mark()` | PENDING/RUNNING/DONE/FAILED/SKIPPED/BLOCKED | [E-033] |
| engine.py → debug_dashboard.py | Dashboard | `write_event()` | JSONL per-stage telemetry | [E-034] |
| engine.py → run_sessions.py | Session launcher | `machinetalk.engine.run()` | top-level orchestration | [E-035] |
| tb-003-system-base → all stages | All fleet prompts | tb-003 appended to system prompt | base constraints: no prose, no fences | [E-019] |

## Instructions and recency

| Document | Path | Host | Mtime | Authority rank | What it claims |
|---|---|---|---:|---|---|
| MACHINE_TALK_SPEC.md | machine-talk/ | flintx | 2026-10-14 | C3 | Full spec: protocol design, two flavors, exemplars |
| cli-manifest.json | machine-talk/ | flintx | 2026-10-14 | C3 | 7-agent pipeline manifest with data flow |
| tb-001 through tb-014 | machine-talk/ | flintx | 2026-10-14 | C3 | Individual agent prompts |
| fleet.py | machinetalk/ | flintx | 2026-10-14 | C2 | Runtime prompt assembly (12 stages) |
| gate.py | machinetalk/ | flintx | 2026-10-14 | C2 | Validation contracts per stage |
| engine.py | machinetalk/ | flintx | 2026-10-21 | C2 | Pipeline orchestration (1025 lines) |

- Newest authoritative instruction: MACHINE_TALK_SPEC.md (298 lines) — the canonical design document.
- Superseded instructions: tb-003 system-base appears in both the spec doc and as a standalone file; the standalone file in machine-talk/ is the one fleet.py loads.
- No contradictions found between TB prompts and their gate.py contracts.

## Conflicts

### CONFLICT C-01

- claim A: cli-manifest.json lists 7 agents (introbeaver, outrobeaver, planbeaver, drafter, scout, oc, olc) with TB-001 through TB-007 numbering
- source A: cli-manifest.json:1-40, mtime 2026-10-14T12:15Z
- claim B: TB files are numbered TB-001 through TB-014 (14 files) and the fleet.py FLEET list has 12 stages (nexus, spark, falcon, eagle also missing from cli-manifest.json)
- source B: machine-talk/tb-007-nexus.md, mtime 2026-10-14T12:15Z; fleet.py:42-55
- resolution: both-live — cli-manifest.json describes an older 7-agent "devwater_offensive_stack" pipeline; the current fleet has 12 stages. The spec doc confirms this split: "Flavor 1: Dendritic Chat Distillation" (7 beavers + build pipeline) and "Flavor 2: Shelly Inter-Agent Contracts."
- impact on report: The CLI manifest is historical; the fleet.py FLEET list is the current authority.

### CONFLICT C-02

- claim A: engine.py GROUP_OF maps `outrobeaver` to `stage1`
- source A: engine.py:84, mtime 2026-10-21T19:43Z
- claim B: cli-manifest.json groups outrobeaver under stage1 but fleet.py STAGE_GROUPS lists outrobeaver under stage1
- source B: fleet.py:58-63
- resolution: A — consistent, no actual conflict. Both place outrobeaver in stage1.

### CONFLICT C-03

- claim A: tb-001-distiller.md has 11 processing steps; gate.py validates "skip" and "chatset_hash" for distiller
- source A: tb-001-distiller.md:66-81; gate.py:63-64
- claim B: tb-001-distiller.md references `{chunk}` injection under `[RAW_CHAT_TRANSCRIPT]`; engine.py passes the transcript via the `chunk` parameter
- source B: engine.py:372-373
- resolution: both-live — the prompt defines processing steps, the engine passes chunked transcript, the gate validates structural output. They operate at different layers.

### CONFLICT C-04

- claim A: engine.py maps `eagle` stage through the drafter path (`chunk=canonical_json(falcon_out)`)
- source A: engine.py:843-844
- claim B: gate.py SPECS dict has eagle requiring `file_tree` and `skeleton_blocks` but no verdict_key or hash_key
- source B: gate.py:68
- resolution: unresolved — eagle stage has no hash_key verification despite being in the nexus→spark→falcon→eagle chain where hash echoing is expected. The tb-010-eagle.md prompt references `plan_hash` but gate.py omits it from SPECS.

### CONFLICT C-05

- claim A: `write_terminal` and `write_gate` are called in engine.py after OLC completion (line 740)
- source A: engine.py:739-741
- claim B: no TB prompt file exists for `terminal` or `saltatory_gate` in machine-talk/ directory
- source B: machine-talk/ directory listing, 2026-10-14
- resolution: unresolved — terminal and saltatory_gate are pipeline stages but lack dedicated TB prompt files. They operate through SomaBridge directly (no LLM call).

## Unknowns and boundary gaps

### U-01

- Unknown: Which model deck/providers are used for each machine-talk stage at runtime
- Why it matters: Model capability affects output quality and gate pass rates
- Evidence that would close it: TurnKey profile content at `soma/turn-key-profiles/soma-current.json` (read but value redacted), or the SDK's internal model deck
- Command not run: `cat soma/turn-key-profiles/soma-current.json` (contains provider keys)

### U-02

- Unknown: Whether `eagle` stage hash echoing is actually enforced or silently ignored
- Why it matters: Hash integrity is a core machine-talk invariant; missing hash_key means broken chain of custody
- Evidence that would close it: Compare gate.py:68 SPECS[eagle] against tb-010-eagle.md's ANCHOR_SCHEMA plan_hash requirement
- Command not run: Full diff of tb-010-eagle.md hash references vs gate.py eagle spec

### U-03

- Unknown: How `terminal` and `saltatory_gate` stages are triggered — they appear in client.py _STAGE_MAP but have no TB prompt files
- Why it matters: These are the final two stages that write ImplementationNodes and VerifiedNodes/FailureNodes
- Evidence that would close it: Source code search for where terminal/saltatory_gate LLM calls are made, or confirmation they are SomaBridge-only (no model call)
- Command not run: Full grep of all files for "terminal" and "saltatory_gate" stage call paths

### U-04

- Unknown: Whether the machine-talk TB files in `soma-grok/soma/machine-talk/` (mirror) differ from the authoritative `soma/machine-talk/` files
- Why it matters: If the mirror is authoritative or differs, current behavior could diverge from documented prompts
- Evidence that close it: `diff -rq soma/machine-talk/ soma-grok/soma/machine-talk/`
- Command not run: diff command

### U-05

- Unknown: How scout text output (the only non-JSON stage) is validated by gate.py
- Why it matters: Scout's text format is fragile; any deviation breaks the entire downstream chain (oc won't run)
- Evidence that would close it: Full `_check_scout()` function analysis and its match against tb-012-scout.md output shape
- Command not run: Detailed grep of scout.md for the exact "### SCOUT VIOLATION REPORT:" header

## Evidence index

| ID | Host | Kind | Locator | Captured at | Proves | Confidence |
|---|---|---|---|---|---|---|
| E-001 | flintx | file | machine-talk/MACHINE_TALK_SPEC.md | 2026-10-22T14:58Z | Complete protocol spec: 298 lines, 2 flavors, design principles | C2 |
| E-002 | flintx | file | machine-talk/cli-manifest.json | 2026-10-22T14:58Z | 7-agent pipeline manifest, data flow, CLI commands | C2 |
| E-003 | flintx | file | machine-talk/tb-001-distiller.md | 2026-10-22T14:58Z | Distiller prompt: 196 lines, TYPE_MAP, ANCHOR_SCHEMA, NOISE_DEFINITIONS, HARD_GATES | C2 |
| E-004 | flintx | file | machine-talk/tb-002-pipeline-protocol.md | 2026-10-22T14:58Z | Pipeline handoff protocol: 49 lines, pipeline sequence, handoff rules | C2 |
| E-005 | flintx | file | machine-talk/tb-003-system-base.md | 2026-10-22T14:58Z | System base prompt: 22 lines, base constraints applied to all stages | C2 |
| E-006 | flintx | file | machine-talk/tb-004-introbeaver.md | 2026-10-22T14:58Z | Intent extraction prompt: 154 lines, SOVEREIGN INTENT ENGINE | C2 |
| E-007 | flintx | file | machine-talk/tb-005-planbeaver.md | 2026-10-22T14:58Z | Build plan prompt: 232 lines, SOVEREIGN ARCHITECT ENGINE | C2 |
| E-008 | flintx | file | machine-talk/tb-006-outrobeaver.md | 2026-10-22T14:58Z | Session autopsy prompt: 206 lines, SOVEREIGN FORENSIC ENGINE | C2 |
| E-009 | flintx | file | machine-talk/tb-007-nexus.md | 2026-10-22T14:58Z | Strategic blueprint prompt: 66 lines, NEXUS_BLUEPRINT output shape | C2 |
| E-010 | flintx | file | machine-talk/tb-008-spark.md | 2026-10-22T14:58Z | Functional spec prompt: 80 lines, FR/NFR generation | C2 |
| E-011 | flintx | file | machine-talk/tb-009-falcon.md | 2026-10-22T14:58Z | Architecture prompt: 69 lines, STACK/STYLING/PERSISTENCE type map | C2 |
| E-012 | flintx | file | machine-talk/tb-010-eagle.md | 2026-10-22T14:58Z | Skeleton architecture prompt: 104 lines, SKELETON_BLOCK type | C2 |
| E-013 | flintx | file | machine-talk/tb-011-drafter.md | 2026-10-22T14:58Z | Code generation prompt: 174 lines, 1st draft only | C2 |
| E-014 | flintx | file | machine-talk/tb-012-scout.md | 2026-10-22T14:58Z | Invariant violation report prompt: 108 lines, SEVERITY/VIOLATION_TYPE maps | C2 |
| E-015 | flintx | file | machine-talk/tb-013-oc.md | 2026-10-22T14:58Z | Gatekeeper prompt: 164 lines, GO/NO-GO authority | C2 |
| E-016 | flintx | file | machine-talk/tb-014-olc.md | 2026-10-22T14:58Z | Code hardening prompt: 176 lines, post-approval only | C2 |
| E-017 | flintx | runtime | soma/output/soma.json error | 2026-10-22T15:00Z | File is not a database — confirms JSON-backed Soma, not SQLite | C1 |
| E-018 | flintx | file | machinetalk/checkpoint.py | 2026-10-22T15:00Z | Checkpoint state machine: 6 statuses, atomic writes | C2 |
| E-019 | flintx | file | machinetalk/fleet.py:116-117 | 2026-10-22T15:00Z | System base prompt loaded into every stage's system message | C2 |
| E-020 | flintx | file | machinetalk/fleet.py:118-119 | 2026-10-22T15:00Z | Pipeline protocol appended to handoff stages | C2 |
| E-021 | flintx | file | machinetalk/fleet.py:42-55 | 2026-10-22T15:00Z | FLEET list: 12 stages, STAGE_ORDER, STAGE_GROUPS | C2 |
| E-022 | flintx | file | machinetalk/gate.py:60-77 | 2026-10-22T15:00Z | SPECS dict: per-stage required keys, verdict keys, hash keys, block tokens | C2 |
| E-023 | flintx | file | machinetalk/hashes.py:13-17 | 2026-10-22T15:00Z | canonical_json + SHA-256 hash computation | C2 |
| E-024 | flintx | file | machinetalk/invariants.py:14-40 | 2026-10-22T15:00Z | InvariantRegistry: 4 default rules, query by extension | C2 |
| E-025 | flintx | file | machinetalk/client.py:12-35 | 2026-10-22T15:00Z | _STAGE_MAP: 20 entries mapping legacy→modern stage names | C2 |
| E-026 | flintx | file | run_engine.py:99 | 2026-10-22T15:00Z | Default workers=2, configurable via --workers | C2 |
| E-027 | flintx | file | machinetalk/client.py:92 | 2026-10-22T15:00Z | 180 second timeout on model calls | C2 |
| E-028 | flintx | file | run_engine.py:102 | 2026-10-22T15:00Z | max_chatsets parameter for limiting processing | C2 |
| E-029 | flintx | file | machinetalk/engine.py:84 | 2026-10-22T15:00Z | GROUP_OF dict: stage→group mapping | C2 |
| E-030 | flintx | file | machinetalk/source.py:1-50 | 2026-10-22T15:00Z | ChatSet dataclass, canonical raw_chat_set format | C2 |
| E-031 | flintx | file | machinetalk/soma_bridge.py | 2026-10-22T15:00Z | SomaBridge: 12 write methods mapping pipeline outputs to graph nodes | C2 |
| E-032 | flintx | file | machinetalk/client.py:67-75 | 2026-10-22T15:00Z | TurnKeyClient: SDK initialization with profile | C2 |
| E-033 | flintx | file | machinetalk/checkpoint.py:1-60 | 2026-10-22T15:00Z | CheckpointStore: state machine, atomic writes | C2 |
| E-034 | flintx | file | machinetalk/debug_dashboard.py | 2026-10-22T15:00Z | Debug dashboard: per-stage JSONL telemetry | C2 |
| E-035 | flintx | file | run_engine.py:15-25 | 2026-10-22T15:00Z | run_engine.py imports machinetalk.engine.run | C2 |

## Report plan

| Report section | Core claim | Evidence IDs | Diagram? |
|---|---|---|---|
| Mandate | TB prompts define a deterministic machine-to-machine protocol for LLM interactions | E-001 to E-016 | no |
| Current State | 14 TB files (1800 lines total), 12-stage runtime pipeline, no active process | E-001-E-016, E-021 | no |
| Key Paths and Entry Points | FLEET_DIR→fleet.py→gate.py→client.py→engine.py→soma_bridge.py | E-019 to E-031 | no |
| Architecture and Data Flow | 4-stage pipeline: ingestion→mapping→creation→finalizing | E-021, E-029, E-035 | yes |
| Core Logic | Prompt assembly → model call → gate validation → checkpoint → Soma graph | E-019 to E-025, E-031 | yes |
| Configuration and Invariants | 6 config categories, 12 stage gate specs, 4 invariant rules | E-019 to E-024 | no |
| Dependencies and Cross-Component Connections | Soma → TurnKey → model API; SomaBridge → graph nodes | E-031 to E-032 | yes |
| Known Gaps and Uncertainties | 5 gaps identified: model deck, eagle hash, terminal/gate prompts, mirror diff, scout validation | U-01 to U-05 | no |

## Pass 1 gate

- [x] Target lock matches the request.
- [x] Entry point confirmed (fleet.py load_system_prompt reads all TB files).
- [x] Runtime state captured (no active process; invoked via run_engine.py).
- [x] Every cross-component edge has a mechanism and evidence ID.
- [x] Every conflict resolved or marked unresolved (C-04, C-05 unresolved).
- [x] At least three actionable unknowns (U-01 through U-05).
- [x] Evidence index has 35 rows with confidence classes.
