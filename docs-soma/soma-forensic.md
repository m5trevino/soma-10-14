# machine-talk — Forensic Deep Dive

TARGET: soma (machine-talk) | RUN: 20261022T145732Z-3411e1 | DATE: 2026-10-22 | HOSTS EXAMINED: flintx
CONFIDENCE SUMMARY: C2 dominant (static source files read during this run); C1 only for runtime probe of soma.json | SCOPE: machine-talk/ directory (14 TB prompt files, 1800 lines) and its runtime wiring through machinetalk/ Python modules (fleet.py, gate.py, client.py, engine.py, soma_bridge.py).

## Mandate

MachineTalk is a structured prompt engineering protocol that transforms LLM interactions from prose-based conversation into deterministic machine-to-machine communication, enforcing strict JSON output, verbatim extraction, schema-validated payloads, processing sequences, hard gates, and exemplars.

## Current State

Fourteen TB prompt files exist in `soma/machine-talk/` (total: 1800 lines, all dated 2026-10-14T12:15Z, never modified since creation). The machine-talk protocol is consumed at runtime by the `soma/machinetalk/` Python package which assembles system prompts, calls the TurnKey SDK for model inference, validates responses through gate.py, and writes results to the Soma graph store. No machine-talk process is currently running; it is invoked via `soma/run_engine.py`.

The spec document (`MACHINE_TALK_SPEC.md`, 298 lines) describes two "flavors": Dendritic Chat Distillation (compressing raw chat transcripts into canonical payloads) and Shelly Inter-Agent Contracts (file-based signaling between autonomous agents). The cli-manifest.json describes an older 7-agent pipeline; the runtime fleet.py defines 12 stages across 4 groups.

## Key Paths and Entry Points

| Path | Host | Role | Lines | Mtime | Evidence |
|---|---|---|---:|---|---|
| machine-talk/MACHINE_TALK_SPEC.md | flintx | Protocol spec | 298 | 2026-10-14 | [E-001] |
| machine-talk/cli-manifest.json | flintx | 7-agent pipeline manifest | 124 | 2026-10-14 | [E-002] |
| machine-talk/tb-001-distiller.md | flintx | Distiller prompt (ingestion) | 196 | 2026-10-14 | [E-003] |
| machine-talk/tb-002-pipeline-protocol.md | flintx | Handoff protocol | 49 | 2026-10-14 | [E-004] |
| machine-talk/tb-003-system-base.md | flintx | System base for all stages | 22 | 2026-10-14 | [E-005] |
| machine-talk/tb-004-introbeaver.md | flintx | Intent extraction | 154 | 2026-10-14 | [E-006] |
| machine-talk/tb-005-planbeaver.md | flintx | Build plan architect | 232 | 2026-10-14 | [E-007] |
| machine-talk/tb-006-outrobeaver.md | flintx | Session autopsy | 206 | 2026-10-14 | [E-008] |
| machine-talk/tb-007-nexus.md | flintx | Strategic blueprint | 66 | 2026-10-14 | [E-009] |
| machine-talk/tb-008-spark.md | flintx | Functional specification | 80 | 2026-10-14 | [E-010] |
| machine-talk/tb-009-falcon.md | flintx | Technical architecture | 69 | 2026-10-14 | [E-011] |
| machine-talk/tb-010-eagle.md | flintx | Skeleton architecture | 104 | 2026-10-14 | [E-012] |
| machine-talk/tb-011-drafter.md | flintx | Code generation | 174 | 2026-10-14 | [E-013] |
| machine-talk/tb-012-scout.md | flintx | Invariant violation report | 108 | 2026-10-14 | [E-014] |
| machine-talk/tb-013-oc.md | flintx | Go/No-Go gatekeeper | 164 | 2026-10-14 | [E-015] |
| machine-talk/tb-014-olc.md | flintx | Code hardening | 176 | 2026-10-14 | [E-016] |
| machinetalk/fleet.py | flintx | Prompt assembler (FLEET list) | ~200 | 2026-10-14 | [E-019] [E-021] |
| machinetalk/gate.py | flintx | Gate validator (SPECS dict) | ~250 | 2026-10-14 | [E-022] |
| machinetalk/client.py | flintx | TurnKey client adapter | ~130 | 2026-10-17 | [E-025] |
| machinetalk/engine.py | flintx | Pipeline orchestration | 1025 | 2026-10-21 | [E-029] |
| machinetalk/soma_bridge.py | flintx | Pipeline→Soma node mapping | ~540 | 2026-10-18 | [E-031] |
| machinetalk/source.py | flintx | ChatSet/session loader | ~170 | 2026-10-14 | [E-030] |
| machinetalk/hashes.py | flintx | canonical_json + SHA-256 | 27 | 2026-10-14 | [E-023] |
| machinetalk/invariants.py | flintx | InvariantRegistry (4 rules) | 74 | 2026-10-14 | [E-024] |
| machinetalk/checkpoint.py | flintx | State machine + atomic writes | ~250 | 2026-10-15 | [E-018] |
| machinetalk/debug_dashboard.py | flintx | Per-stage JSONL telemetry | ~1150 | 2026-10-21 | [E-034] |

## Architecture and Data Flow

```
┌──────────────────────────────────────────────────────────────────────┐
│                        machine-talk/ (14 TB prompts)                 │
│  tb-001  tb-002  tb-003  tb-004-tb-014  │  SYSTEM BASE + PIPELINE  │
└──────────────────────┬───────────────────────────────────────────────┘
                       │ FLEET_DIR import
                       ▼
┌──────────────────────────────────────────────────────────────────────┐
│  machinetalk/fleet.py                                                │
│  FLEET: [distiller, introbeaver, planbeaver, outrobeaver,           │
│          nexus, spark, falcon, eagle, drafter, scout, oc, olc]      │
│                                                                      │
│  load_system_prompt(stage) = tb-003 + (tb-002 if handoff) + stage  │
│  assemble(stage, system_prompt, chunk, contracts, payload)         │
│      → (system_msg, user_msg)                                       │
└──────────────────────┬───────────────────────────────────────────────┘
                       │
          ┌────────────┼──────────────────────────────────────────┐
          │            │                                           │
          ▼            ▼                                           ▼
┌─────────────┐ ┌──────────────────┐              ┌──────────────────────┐
│  {chunk}    │ │  payload-fed     │              │  {chunk}+contracts   │
│  stages:    │ │  stages:         │              │  scout stage:        │
│  distiller  │ │  introbeaver     │              │  [CODE_ARTIFACT]     │
│  eagle      │ │  planbeaver      │              │  {chunk} + DNA_CON- │
│             │ │  outrobeaver     │              │  TRACTS             │
│             │ │  nexus, spark    │              └──────────────────────┘
│             │ │  falcon, eagle   │
│             │ │  drafter, oc,    │
│             │ │  olc             │
└─────────────┴──────────────────┘
          │            │
          │            │ system_msg + user_msg
          └────────────┼──────────────────────────────────────────┐
                       ▼                                           │
┌──────────────────────────────────────────────────────────────────┼──────────┐
│  machinetalk/client.py                                           │          │
│  EngineClient.call_stage(stage, payload, chunk, contracts)      │          │
│    ├─ assemble() → (sys_prompt, user_msg)                     │          │
│    ├─ TurnKeyClient._tk.call(stage, messages) ──────────────────┼──► model │
│    └─ gate.validate(stage, result.content, expected_hash)        │          │
└──────────────────────┬──────────────────────────────────────────┼──────────┘
                       │                                          │
                       │  GateResult(ok, parsed, verdict, skipped,│
                       │  block_reason, errors, warnings)         │
                       ▼                                          │
┌──────────────────────────────────────────────────────────────────┼──────────┐
│  machinetalk/gate.py                                             │          │
│  validate(stage, raw_text, expected_hash) ──► GateResult       │          │
│    ├─ _check_json(stage, spec, raw, hash)  ← 11 stages         │          │
│    └─ _check_scout(raw_text)               ← scout only        │          │
│                                                                 │          │
│  is_done(gate) → ok OR skipped                                   │          │
│  is_hard_block(gate) → verdict in block_tokens                  │          │
└──────────────────────┬──────────────────────────────────────────┼──────────┘
                       │                                          │
                       │  CallRecord(stage, session_id, model,   │          │
                       │  verdict, tokens, latency_ms, gate)     │          │
                       ▼                                          │
┌──────────────────────────────────────────────────────────────────┼──────────┐
│  machinetalk/engine.py                                           │          │
│  Engine.run_stage1(sessions) → per-ChatSet parallel:           │          │
│    distiller → introbeaver → planbeaver → outrobeaver           │          │
│                                                                  │          │
│  Engine.run_stages_2_4(build, sessions) → sequential:          │          │
│    nexus → spark → falcon → eagle → drafter → scout → oc → olc│          │
│                                                                  │          │
│  On DONE: write_artifact() → checkpoint → _bridge.write_*()   │          │
│                                                                  │          │
│  On REWORK: BLOCKED; operator drives --redo                    │          │
└──────────────────────┬──────────────────────────────────────────┼──────────┘
                       │                                          │
                       │  SomaBridge.write_*()                    │
                       ▼                                          │
┌──────────────────────────────────────────────────────────────────┼──────────┐
│  machinetalk/soma_bridge.py                                      │          │
│  write_session_anchor() → SessionAnchor node                    │          │
│  write_chatset() → ChatSet node + CONTAINS edge                 │          │
│  write_receptor() → ReceptorLog node                             │          │
│  write_intro_plan_outrobeaver() → IntentNode/TaskNode/OutcomeNode│          │
│  write_nexus() → Nexus/StrategicBlueprintNode                   │          │
│  write_spark() → RequirementsNode                                │          │
│  write_falcon() → ArchitectureNode + ArchitectureContractNode   │          │
│  write_drafter() → ReferenceArtifactNode + FileNode             │          │
│  write_scout() → InvariantQueryNode                              │          │
│  write_oc() → FunctionSlot (via AxonHillock pattern)            │          │
│  write_olc() → OptimizedSlot + SessionManifestNode              │          │
│  write_terminal() → ImplementationNode + SmokeTestNode          │          │
│  write_gate() → VerifiedNode/FailureNode + VERIFIED edge        │          │
│  write_publisher() → VerifiedNode (disk write confirmation)      │          │
└──────────────────────────────────────────────────────────────────┼──────────┘
                       │                                          │
                       │  AtomicSoma._persist() ──► soma.json     │          │
                       ▼                                          │
┌──────────────────────────────────────────────────────────────────┼──────────┐
│  <out>/soma.json (JSON-backed graph: nodes + edges)             │          │
└──────────────────────────────────────────────────────────────────┴──────────┘
```

Stage 1 (parallel per ChatSet): distiller→introbeaver→planbeaver→outrobeaver
Stage 2-4 (sequential per build unit): nexus→spark→falcon→eagle→drafter→scout→oc→olc

## Core Logic

### Prompt Assembly (fleet.py:load_system_prompt, fleet.py:assemble)

Every machine-talk stage call assembles a system prompt by concatenating three components in order:

1. **System base** (`tb-003-system-base.md`): `prose → ∅`, `no_assistant_prose → true`, `no_markdown_fences → true`, `anthropomorphism → ∅` [E-019]. Applied to every stage.
2. **Pipeline protocol** (only if `p.handoff == True`, which is all 12 stages in FLEET): `tb-002-pipeline-protocol.md` defines `pipeline_sequence` (nexus→spark→falcon→eagle→scout→drafter), `handoff_rules` (payload_must_contain session_id|chatset_id|upstream_hash), and `failure → route_to_human_with_context_bundle` [E-020].
3. **Stage prompt** (the TB-NNN file): Contains IDENTITY, INPUT, PROCESSING, HARD GATE, OUTPUT SHAPE, and optional EXEMPLAR [E-003] through [E-016].

Slot-injection prompts (distiller, eagle, scout) use `{chunk}` markers that are stripped from the system prompt during assembly and re-emitted as the user message with real content [E-030].

### Payload Assembly (fleet.py:assemble)

Two patterns:
- **Slot prompts**: `distiller` receives `[CHAT_SET_META]\n{payload}\n[RAW_CHAT_TRANSCRIPT]\n{chunk}`. `eagle` receives `[FALCON_PAYLOAD]\n{content}`. `scout` receives `[CODE_ARTIFACT]\n{chunk}\n[DNA_CONTRACTS]\n{contracts}` [E-030].
- **Payload-fed prompts** (beavers, nexus, spark, falcon, drafter, oc, olc): The user message is the canonical JSON payload produced by `payload_envelope()` [E-023], which uses `canonical_json()` for deterministic serialization (sorted keys, compact separators, no ASCII escapes).

### Model Call Path (client.py:EngineClient.call_stage)

1. `load_system_prompt(stage, strip_injection=True)` produces the system prompt with slot markers removed [E-019].
2. `assemble(stage, system_prompt, chunk, contracts, payload)` produces (system_msg, user_msg) [E-030].
3. `self._tk.call(stage, messages)` sends to TurnKey SDK [E-032].
4. The SDK returns raw content; `gate.validate(stage, content, expected_hash)` parses and validates [E-022].
5. A `CallRecord` is constructed with model, tokens, latency, and gate result.

### Gate Validation (gate.py:validate)

Each stage has a `StageSpec` defining:
- **required keys**: searched recursively in the LLM's JSON output; failure to find any produces an error [E-022].
- **verdict_key**: the field that determines the stage verdict (e.g., `skip` for distiller, `verdict` for oc) [E-022].
- **hash_key**: the field the LLM must echo back (chatset_hash for distiller/introbeaver; plan_hash_verification for nexus/spark/falcon) [E-022].
- **block_tokens**: verdict values that are hard halts (e.g., `REWORK` for oc, `BLOCKED` for planbeaver) [E-022].

For JSON stages: `_check_json()` extracts the JSON object, checks required keys, verifies hash echo against the expected hash computed from the input payload [E-023].

For scout (the only text stage): `_check_scout()` validates that the output starts with `### SCOUNT VIOLATION REPORT:` and ends with `SCOUT REVIEW COMPLETE. VERDICT: <status>` [E-014].

### Engine Pipeline Orchestration (engine.py:Engine)

**Stage 1** (run_stage1): For each ChatSet, runs all four ingestion stages sequentially within the same worker. Stage 1 stages run in parallel across ChatSets (ThreadPoolExecutor with configurable workers). A distiller skip cascades to SKIPPED for introbeaver/planbeaver/outrobeaver for the same ChatSet [E-033].

**Stages 2-4** (run_stages_2_4): Runs the 8 stages sequentially. Each stage loads its upstream artifact as input. If any stage fails or blocks, the entire build halts. The oc stage's REWORK verdict blocks the build and requires operator-driven `--redo` [E-033].

### Soma Graph Bridge (soma_bridge.py)

Every successful stage writes corresponding nodes to the Soma graph:
- Distiller → ReceptorLog (PROCESSED_BY edge from ChatSet)
- IntroBeaver → IntentNode (YIELDS edge from ChatSet)
- PlanBeaver → TaskNode (YIELDS edge from ChatSet)
- OutroBeaver → OutcomeNode (YIELDS edge from ChatSet)
- Nexus → Nexus + StrategicBlueprintNode
- Spark → RequirementsNode
- Falcon → ArchitectureNode + ArchitectureContractNode
- Drafter → ReferenceArtifactNode + FileNode
- Scout → InvariantQueryNode (GOVERNS edge)
- OC → FunctionSlot (via AxonHillock pattern)
- OLC → OptimizedSlot + SessionManifestNode
- Terminal (post-OLC) → ImplementationNode + SmokeTestNode
- Gate (post-terminal) → VerifiedNode/FailureNode (VERIFIED edge)

Writes are batched and persisted atomically via `AtomicSoma._persist()` (write to `.tmp`, then `os.rename`) [E-017].

### Hash Chain of Custody

The distiller computes `chatset_hash` from the canonical `raw_chat_set` array using `canonical_json()` + `SHA-256` [E-023]. The model must echo this hash back. The gate verifies the echo matches exactly [E-022]. Nexus/spark/falcon chain this hash forward as `plan_hash_verification` [E-009] [E-010] [E-011]. The eagle stage references `plan_hash` in its ANCHOR_SCHEMA (tb-010:19-25) but gate.py's SPECS[eagle] has no hash_key [CONFLICT C-04].

## Configuration and Invariants

### Config Sources

| Config | Source | Value |
|---|---|---|
| workers | run_engine.py:99 | default 2 |
| timeout | client.py:92 | 180.0 seconds per model call |
| max_chatsets | run_engine.py:102 | default None (all) |
| model deck | turnkey.profile_integration.initialize_sdk_with_profile() | per-stage model selection |
| base constraints | tb-003-system-base.md | prose→∅, no_fences, no_anthropomorphism |
| invariant rules | invariants.py:14-40 | 4 rules: security, correctness, safety, style |

### Per-Stage Gate Contracts (gate.py:60-77)

| Stage | Format | Required Keys | Verdict Key | Hash Key | Block Tokens |
|---|---|---|---|---|---|
| distiller | JSON | chatset_hash, skip | skip (bool) | chatset_hash | — |
| introbeaver | JSON | introbeaver_output | status | input_hash | — |
| planbeaver | JSON | planbeaver_output | status | — | BLOCKED, INVALID_PLAN, INCOMPLETE_PLAN, NEEDS_DECOMPOSITION |
| outrobeaver | JSON | outrobeaver_output | session_health | — | GHOST_SESSION, CORRUPT_INPUT |
| nexus | JSON | plan_hash_verification, blueprints | artifact_type | plan_hash_verification | — |
| spark | JSON | plan_hash_verification, functional_requirements | artifact_type | plan_hash_verification | — |
| falcon | JSON | plan_hash_verification, component_architecture | artifact_type | plan_hash_verification | — |
| eagle | JSON | file_tree, skeleton_blocks | — | — | — |
| drafter | JSON | draft_artifact | status | — | BROKEN_DRAFT, INCOMPLETE_DRAFT, CONTRACT_VIOLATION |
| scout | TEXT | (none) | scout_verdict | — | — |
| oc | JSON | oc_decision | verdict | — | — |
| olc | JSON | olc_output | status | — | UNAUTHORIZED, SIGNATURE_BREACH, INVALID_HARDENING |

### Invariant Rules (invariants.py:14-40)

4 rules in InvariantRegistry, queried by file extension:
- **INV-001** (CRITICAL, security): No secrets or credentials in source [E-024].
- **INV-002** (HIGH, correctness): Every public function must have clear input/output [E-024].
- **INV-003** (HIGH, safety): No unbounded recursion or loops without exit condition [E-024].
- **INV-004** (MEDIUM, style): No TODO or placeholder in committed code [E-024].

### Hard Gates in TB Prompts

All 14 TB files include HARD_GATES sections. Common constraints: no prose output, no markdown fences, no inference beyond explicit input, verbatim extraction only, schema validation required. The distiller has the most granular gates: heredoc_discard→∅, metadata_loss→∅, constraint_injection_loss→∅, chronology_violation→∅, unmerged_fragments→∅, drop_without_trace→∅ [E-003].

## Dependencies and Cross-Component Connections

### Internal Dependencies (within soma-10-14)

| Upstream | Downstream | Mechanism | Evidence |
|---|---|---|---|
| turnkey.profile_integration (external package) | machinetalk/client.py | `initialize_sdk_with_profile(profile_path)` | [E-032] |
| machine-talk/*.md | machinetalk/fleet.py | FLEET_DIR read at runtime | [E-021] |
| machinetalk/source.py | machinetalk/engine.py | load_source() → Session/ChatSet | [E-030] |
| machinetalk/hashes.py | machinetalk/source.py, fleet.py | chatset_hash_for() for canonical hashing | [E-023] |
| machinetalk/client.py | machinetalk/engine.py | EngineClient.call_stage() | [E-025] |
| machinetalk/gate.py | machinetalk/client.py | validate() | [E-022] |
| machinetalk/engine.py | machinetalk/soma_bridge.py | self._bridge.write_*() | [E-031] |
| machinetalk/engine.py | machinetalk/checkpoint.py | self.ck.cs_mark(), ss_mark() | [E-033] |
| machinetalk/engine.py | run_engine.py | `machinetalk.engine.run()` entry point | [E-035] |
| machinetalk/invariants.py | machinetalk/engine.py (scout) | InvariantRegistry().query(exts) for scout contracts | [E-024] |
| run_sessions.py | machinetalk/engine.py | Top-level orchestrator | [E-035] |

### External Dependencies

- **TurnKey SDK** (turnkey.profile_integration): Model selection, gateway rotation, retry, and HTTP inference calls. Profile path loaded from command line.
- **Model API** (provider-agnostic): HTTP calls to LLM endpoints. Model per stage determined by TurnKey SDK.

### Data Flow Summary

```
Session data → source.py (ChatSet assembly) → engine.py (per-ChatSet parallel ingestion)
                                                      → engine.py (per-build sequential stages 2-4)
                                                      → client.py → TurnKey SDK → model API
                                                      → gate.py (validate LLM output)
                                                      → soma_bridge.py → Soma graph (soma.json)
                                                      → checkpoint.py (resume state)
                                                      → debug_dashboard.py (telemetry)
```

## Known Gaps and Uncertainties

### G-01: Missing eagle hash_key in gate.py SPECS

tb-010-eagle.md defines `plan_hash::sha256_hex` in its ANCHOR_SCHEMA (tb-010:20), and the engine passes `expected_hash=h` to the eagle stage call (engine.py:843). However, gate.py:68 defines `SPECS["eagle"]` with no `hash_key`. The model may echo the hash, but gate.py does not validate it [CONFLICT C-04]. This breaks the hash chain of custody for the nexus→spark→falcon→eagle pipeline. Evidence that would close it: confirm that eagle's output is consumed only by drafter (which does not require hash verification).

### G-02: No TB prompt files for terminal and saltatory_gate

client.py:34-35 maps "terminal" and "saltatory_gate" to themselves in _STAGE_MAP. engine.py:739-741 calls `self._bridge.write_terminal()` and `self._bridge.write_gate()` after OLC completion — but these are SomaBridge methods that operate on already-existing graph nodes, not LLM calls. No TB prompt files exist for these stages in machine-talk/. The terminal stage is purely a Soma graph write (reads OptimizedSlot nodes, creates ImplementationNode/SmokeTestNode) [E-031]. The saltatory_gate is similarly a verification pass. However, this means they are not "machine-talk" stages in the protocol sense — they are deterministic post-processing.

### G-03: Model deck and per-stage model assignment

The TurnKey SDK's `initialize_sdk_with_profile()` determines which model serves each stage. The profile file at `soma/turn-key-profiles/soma-current.json` (mtime 2026-10-21T04:08Z) contains this mapping but its contents were not inspected (provider keys may be present). Without this, we cannot determine which model produces output for each stage or whether different models have different pass rates through the gate.

### G-04: Scout text format fragility

Scout is the only non-JSON stage. Its gate validation (gate.py:_check_scout) requires the output to start with `### SCOUT VIOLATION REPORT:` and end with `SCOUT REVIEW COMPLETE. VERDICT: <status>` [E-014]. Any deviation (prose preamble, markdown fence, or missing verdict) causes the gate to fail, blocking the entire downstream chain (oc cannot run without scout output). The tb-012-scout.md prompt defines the output shape but its exact string matching is not visible in the prompt body we read.

### G-05: cli-manifest.json vs. current fleet mismatch

cli-manifest.json (2026-10-14) describes a 7-agent "devwater_offensive_stack" pipeline with TB-001 through TB-007. The current fleet has 12 stages (TB-001 through TB-014) with additional stages (nexus, spark, falcon, eagle) not present in the manifest. The manifest's agent numbering (introbeaver=TB-001, outrobeaver=TB-002, planbeaver=TB-003, drafter=TB-004, scout=TB-005, oc=TB-006, olc=TB-007) uses different numbering than the TB files (introbeaver=tb-004, outrobeaver=tb-006, planbeaver=tb-005, drafter=tb-011, scout=tb-012, oc=tb-013, olc=tb-014). The cli-manifest.json is historical and does not reflect the current pipeline.

## Evidence Log

| ID | Host | Kind | Locator | Captured at | Proves | Confidence |
|---|---|---|---|---|---|---|
| E-001 | flintx | file | machine-talk/MACHINE_TALK_SPEC.md | 2026-10-22T14:58Z | Protocol spec | C2 |
| E-002 | flintx | file | machine-talk/cli-manifest.json | 2026-10-22T14:58Z | 7-agent manifest | C2 |
| E-003 | flintx | file | machine-talk/tb-001-distiller.md | 2026-10-22T14:58Z | Distiller prompt | C2 |
| E-004 | flintx | file | machine-talk/tb-002-pipeline-protocol.md | 2026-10-22T14:58Z | Handoff protocol | C2 |
| E-005 | flintx | file | machine-talk/tb-003-system-base.md | 2026-10-22T14:58Z | System base prompt | C2 |
| E-006 | flintx | file | machine-talk/tb-004-introbeaver.md | 2026-10-22T14:58Z | Intent extraction prompt | C2 |
| E-007 | flintx | file | machine-talk/tb-005-planbeaver.md | 2026-10-22T14:58Z | Build plan prompt | C2 |
| E-008 | flintx | file | machine-talk/tb-006-outrobeaver.md | 2026-10-22T14:58Z | Session autopsy prompt | C2 |
| E-009 | flintx | file | machine-talk/tb-007-nexus.md | 2026-10-22T14:58Z | Strategic blueprint prompt | C2 |
| E-010 | flintx | file | machine-talk/tb-008-spark.md | 2026-10-22T14:58Z | Functional spec prompt | C2 |
| E-011 | flintx | file | machine-talk/tb-009-falcon.md | 2026-10-22T14:58Z | Architecture prompt | C2 |
| E-012 | flintx | file | machine-talk/tb-010-eagle.md | 2026-10-22T14:58Z | Skeleton architecture prompt | C2 |
| E-013 | flintx | file | machine-talk/tb-011-drafter.md | 2026-10-22T14:58Z | Code generation prompt | C2 |
| E-014 | flintx | file | machine-talk/tb-012-scout.md | 2026-10-22T14:58Z | Invariant violation report prompt | C2 |
| E-015 | flintx | file | machine-talk/tb-013-oc.md | 2026-10-22T14:58Z | Go/No-Go gatekeeper prompt | C2 |
| E-016 | flintx | file | machine-talk/tb-014-olc.md | 2026-10-22T14:58Z | Code hardening prompt | C2 |
| E-017 | flintx | runtime | soma/output/soma.json | 2026-10-22T15:00Z | JSON-backed Soma | C1 |
| E-018 | flintx | file | machinetalk/checkpoint.py | 2026-10-22T15:00Z | Checkpoint state machine | C2 |
| E-019 | flintx | file | machinetalk/fleet.py:116-117 | 2026-10-22T15:00Z | System base in system prompt | C2 |
| E-020 | flintx | file | machinetalk/fleet.py:118-119 | 2026-10-22T15:00Z | Pipeline protocol appended | C2 |
| E-021 | flintx | file | machinetalk/fleet.py:42-55 | 2026-10-22T15:00Z | FLEET: 12 stages | C2 |
| E-022 | flintx | file | machinetalk/gate.py:60-77 | 2026-10-22T15:00Z | SPECS dict | C2 |
| E-023 | flintx | file | machinetalk/hashes.py:13-17 | 2026-10-22T15:00Z | canonical_json + SHA-256 | C2 |
| E-024 | flintx | file | machinetalk/invariants.py:14-40 | 2026-10-22T15:00Z | InvariantRegistry | C2 |
| E-025 | flintx | file | machinetalk/client.py:12-35 | 2026-10-22T15:00Z | _STAGE_MAP | C2 |
| E-026 | flintx | file | run_engine.py:99 | 2026-10-22T15:00Z | Workers default | C2 |
| E-027 | flintx | file | machinetalk/client.py:92 | 2026-10-22T15:00Z | 180s timeout | C2 |
| E-028 | flintx | file | run_engine.py:102 | 2026-10-22T15:00Z | max_chatsets | C2 |
| E-029 | flintx | file | machinetalk/engine.py:84 | 2026-10-22T15:00Z | GROUP_OF mapping | C2 |
| E-030 | flintx | file | machinetalk/source.py:1-50 | 2026-10-22T15:00Z | ChatSet dataclass | C2 |
| E-031 | flintx | file | machinetalk/soma_bridge.py | 2026-10-22T15:00Z | SomaBridge write methods | C2 |
| E-032 | flintx | file | machinetalk/client.py:67-75 | 2026-10-22T15:00Z | TurnKeyClient init | C2 |
| E-033 | flintx | file | machinetalk/checkpoint.py:1-60 | 2026-10-22T15:00Z | CheckpointStore | C2 |
| E-034 | flintx | file | machinetalk/debug_dashboard.py | 2026-10-22T15:00Z | Debug telemetry | C2 |
| E-035 | flintx | file | run_engine.py:15-25 | 2026-10-22T15:00Z | run_engine imports engine.run | C2 |
