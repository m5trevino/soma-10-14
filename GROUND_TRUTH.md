# GROUND TRUTH — soma-10-14

**Verified 2026-10-31. Every statement below was checked against the code or the
database in that session. Nothing here is inferred or planned.**

Read this before changing anything. The architecture this project intends is
declared in `soma/soma_template.sql` and is **not** what the running code does.
An agent that reads only the code will conclude prompting is the design and
"improve" it further.

---

## 1. What the template declares

`soma/soma_template.sql` is 207 KB and contains:

- `stage_instructions` — 14 populated rows:

  | stage | tb | chars | handoff |
  |---|---|---|---|
  | distiller | tb-001 | 13,851 | 0 |
  | pipeline_protocol | tb-002 | 11,659 | 1 |
  | system_base | tb-003 | 11,494 | 0 |
  | introbeaver | tb-004 | 21,416 | 0 |
  | planbeaver | tb-005 | 11,561 | 0 |
  | outrobeaver | tb-006 | 12,329 | 0 |
  | nexus | tb-007 | 12,074 | 0 |
  | spark | tb-008 | 12,250 | 0 |
  | falcon | tb-009 | 11,845 | 0 |
  | eagle | tb-010 | 11,660 | 0 |
  | drafter | tb-011 | 12,079 | 0 |
  | scout | tb-012 | 11,480 | 0 |
  | oc | tb-013 | 11,813 | 0 |
  | olc | tb-014 | 12,272 | 0 |

- 16 per-stage views: `stage1_distiller_input`, `stage1_introbeaver_input`,
  `stage1_distiller_output`, `stage1_planbeaver_input`,
  `stage1_outrobeaver_input`, `stage2_nexus_input`, `stage2_spark_input`,
  `stage2_falcon_input`, `stage3_eagle_input`, `stage3_drafter_input`,
  `stage3_scout_input`, `stage4_oc_input`, `stage4_olc_input`, plus
  `node_types`, `edge_types`, `session_summary`.

- Header comment, line ~4206:
  `-- Each stage queries its view, never the base tables directly.`

Each row carries `version` and `loaded_from` (e.g. `machine-talk/distiller.v2.md`).

## 2. What the code actually does

| Claim | Reality |
|---|---|
| Stages read instructions from `stage_instructions` | **No.** Nothing reads it. Only `build_soma_template.py` writes it. |
| Stages query their view | **No.** Nothing queries any stage view. Only `build_soma_template.py` creates them. |
| The model is given tools to read the DB | **No.** `tools=` / `tool_choice=` are never passed anywhere in `soma/machinetalk/`. |
| — | Instead: `fleet.load_system_prompt()` reads `.md` from disk and concatenates into the message body. |

Measured distiller payload (`checkpoint` for chatset `83886`):

```
distiller (tb-001)      13,851   37%   <- its actual job
system_base (tb-003)    11,494   31%
pipeline_protocol       11,659   32%   <- describes the 14-agent machine
TOTAL                   37,004
```

`fleet.py` hardcodes `handoff=True` on all 12 stage entries, overriding the DB,
which says `handoff=0` for `pipeline_protocol`.

## 3. Verification gaps

- `char_start` / `char_end` are emitted by the distiller and **never read** by
  any code. Nothing checks that an emitted directive is a substring of the
  source at the offsets it claims.
- `gate.py` validates that JSON parses and required keys exist. It does not
  validate content against anything.
- Result: the model can describe a directive that does not exist in the
  transcript and it will be accepted.

## 4. Template defects

- `nodes` CHECK constraint permits 12 types. The views reference 13 more
  (`StrategicBlueprintNode`, `RequirementsNode`, `ArchitectureNode`, `FileNode`,
  `SmokeTestNode`, `SessionManifestNode`, …) which cannot be inserted.
  `store._widen_node_type_check()` exists to paper over this at runtime.
- 31 demo `INSERT` rows ship in every new database (`demo-001`, fake
  `DistilledChatSet` rows). These are the phantom nodes visible in
  `somas/25-11-20-multiclip.2.0.feature.overhaul/soma.db`.

## 5. Transport

- `/home/flintx/.local/lib/python3.11/site-packages/turnkey/sdk.py:287`
  hardcodes `"stream": False`. Nothing is sent until generation completes, so
  the connection is idle-killed at ~30 s. Verified by sending the same request
  twice: success at 20.1 s, `RemoteDisconnected` at 30.4 s.
- Two nested retry loops: SDK retries `max_retries+1` with model rotation, then
  `client.py::_call_with_retry` retries 10 more times on top.

---

## INVARIANTS — violate one of these and the stage must fail

These are binary. A change either preserves them or breaks them; there is no
version of "improved it" that satisfies both.

1. **Instructions come from `stage_instructions`.** Never from disk, never
   concatenated into a message body.
2. **A stage sees only what its view returns.** No cross-stage context.
3. **An emitted directive must be a literal substring of the source** at the
   `char_start`/`char_end` it claims. Otherwise the stage fails.
4. **`chatset_hash` is computed by the caller.** The model echoes it verbatim
   and is never asked to derive it.
5. **A stage's own instruction is the whole of what it knows about its job.**
   No `pipeline_protocol`, no agent roster, no routing table.

## Why this file exists

A model given a partial description of a system will fill the gaps with
plausible structure and present it as fact, with the same confidence it has
when it is right. The missing enforcement layer in this project *looks
incomplete*, so an agent optimizing for "make it work" will replace it with
prompting — and report that as a fix.

These invariants are the only check that does not depend on trusting the agent
that is making the change.
