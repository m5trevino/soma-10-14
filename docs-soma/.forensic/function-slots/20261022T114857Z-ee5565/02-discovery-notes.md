# Discovery Notes: function-slots

TARGET: function-slots
SLUG: function-slots
RUN: 20261022T114857Z-ee5565
PASS: 1 (discovery)
STARTED: <ISO 8601 UTC>
ANALYST: <model/agent identifier>

> Fill this file before writing any report prose. Empty sections are findings.
> Every row must resolve to a path, a command output, or a numbered unknown.

## Target lock

- Canonical target:
- Scope sentence:
- Excluded:
- Local roots examined:
- Remote roots examined:
- Probe window (start/end):

## Inventory summary

| Root | Host | Exists | Files (depth 3) | Newest file | Newest mtime |
|---|---|---:|---:|---|---|

- Repository state (git HEAD, branch, dirty):
- Archives or mirrors discovered (do not treat as authoritative):
- Inventory artifacts: `01-inventory.txt`, `01-inventory.json`

## Entry points

| Path | Host | Role | Lines | Mtime | Evidence |
|---|---|---|---:|---|---|
|  |  |  |  |  |  |

- Confirmed executable/importable surfaces:
- Launch scripts and their actual `exec` targets:
- Entry points named in docs but absent on disk:

## Runtime state

- Process inspection command:
- Matching processes (PID, elapsed, command):
- Listening sockets:
- HTTP probes (URL, status, body shape, timestamp):
- Service units (remote `systemctl status/cat`, local SysVinit/`ps`):
- Queue/state files and their mtimes:
- Last log lines that indicate current behavior:

## Data stores

| Store | Host | Engine | Schema summary | Rows | Newest record | Access | Evidence |
|---|---|---|---|---|---:|---|---|---|
|  |  |  |  |  |  | read-only |  |

- Tables actually queried by the target (cite the query site):
- Stores present but unused by this target:
- Locked or unreadable stores and exact error:

## Configuration and invariants

| Key / rule | Source path:line | Default | Effective value (redacted if secret) | Enforced in code? |
|---|---|---|---|---|

- Config precedence observed:
- Environment variables read (names only):
- Profiles / model decks:
- Hard gates and validation rules:
- Invariants that are documented but not enforced:

## Cross-component edges

| Direction | Counterpart | Mechanism | Payload / contract | Evidence |
|---|---|---|---|---|
| target →  |  |  |  |  |

- Edges observed in code but not observed at runtime:
- Edges observed at runtime but not found in code:
- Boundary gaps (sibling internals deliberately not opened):

## Instructions and recency

| Document | Path | Host | Mtime | Authority rank | What it claims |
|---|---|---|---:|---|---|

- Newest authoritative instruction:
- Superseded instructions:
- Instructions that contradict code:
- Archived/chat-log evidence (lowest rank):

## Conflicts

### CONFLICT C-01

- claim A:
- source A (path:line, mtime):
- claim B:
- source B (path:line, mtime):
- resolution: A | B | both-live | unresolved
- basis:
- impact on report:

## Unknowns and boundary gaps

### U-01

- Unknown:
- Why it matters:
- Evidence that would close it:
- Command or path not run (and why):

## Evidence index

Mirror of `03-evidence-index.tsv`.

| ID | Host | Kind | Locator | Captured at | Proves | Confidence |
|---|---|---|---|---|---|---|
| E-001 |  |  |  |  |  | C1/C2/C3/C4 |

## Report plan

| Report section | Core claim | Evidence IDs | Diagram? |
|---|---|---|---|
| Mandate |  |  | no |
| Current State |  |  | no |
| Key Paths and Entry Points |  |  | no |
| Architecture and Data Flow |  |  | yes |
| Core Logic |  |  | yes |
| Configuration and Invariants |  |  | no |
| Dependencies and Cross-Component Connections |  |  | yes |
| Known Gaps and Uncertainties |  |  | no |
| Evidence Log |  |  | no |

## Pass 1 gate

- [ ] Target lock matches the request.
- [ ] Entry point confirmed or absence recorded.
- [ ] Runtime state captured or reason recorded.
- [ ] Every cross-component edge has a mechanism and evidence ID.
- [ ] Every conflict resolved or marked unresolved.
- [ ] At least three actionable unknowns.
- [ ] Evidence index has at least 10 rows with confidence classes.
