"""Machine-talk fleet: prompt loading, stage definitions, payload assembly.

Stage graph (matches the final cli-manifest.json + beaver v1.1.1 pipeline):

  Stage 1 -- INGESTION (per ChatSet, ChatSets run in parallel)
    distiller   (tb-001)  [RAW_CHAT_TRANSCRIPT]{chunk}        -> signal or skip
    introbeaver (tb-004)  input: distiller output             -> extraction
    planbeaver  (tb-005)  input: introbeaver + raw set        -> build plan
    outrobeaver (tb-006)  input: planbeaver + extraction      -> session journal

  Stage 2 -- MAPPING (per session, sessions sequential oldest -> newest)
    nexus   (tb-007)  payload: raw_chat_set JSON               -> blueprints
    spark   (tb-008)  payload: merged nexus blueprints         -> consolidated spec
    falcon  (tb-009)  payload: spark + blueprint               -> execution plan

  Stage 3 -- CREATION
    eagle   (tb-010)  [FALCON_PAYLOAD]{chunk}                  -> architecture
    drafter (tb-011)  input: eagle + plan                      -> first-draft code
    scout   (tb-012)  {chunk} + [DNA_CONTRACTS]{contracts}     -> violation report

  Stage 4 -- FINALIZING
    oc    (tb-013)  input: draft + scout                       -> verdict
    olc   (tb-014)  input: approved draft                      -> hardened code

Every system prompt = tb-003-system-base + (tb-002-pipeline-protocol on
handoff stages) + the stage's tb-NNN prompt. The user message carries a
machine-talk JSON payload; responses must be raw JSON echoing the payload's
hash. Python validates -- never the LLM.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .hashes import canonical_json, chatset_hash_for

FLEET_DIR = Path(__file__).resolve().parent.parent / "machine-talk"


@dataclass
class FleetPrompt:
    stage: str          # logical name, e.g. "distiller"
    number: str         # "tb-001"
    filename: str
    body: str
    handoff: bool = False   # append pipeline-protocol to system prompt
    slot: str = ""          # "{chunk}" injection, or "" for payload-fed
    payload_key: str = ""   # marker used when appending payload, e.g. "[FALCON_PAYLOAD]"


FLEET: list[FleetPrompt] = [
    FleetPrompt("distiller",   "tb-001", "tb-001-distiller.v2.md",   "", True,  "{chunk}",          "[RAW_CHAT_TRANSCRIPT]"),
    FleetPrompt("introbeaver", "tb-004", "tb-004-introbeaver.v2.md", "", True,  "",                "[EXTRACTION_PAYLOAD]"),
    FleetPrompt("planbeaver",  "tb-005", "tb-005-planbeaver.v2.md",  "", True,  "",                "[EXTRACTION_PAYLOAD]"),
    FleetPrompt("outrobeaver", "tb-006", "tb-006-outrobeaver.v2.md", "", True,  "",                "[EXTRACTION_PAYLOAD]"),
    FleetPrompt("nexus",       "tb-007", "tb-007-nexus.v2.md",       "", True,  "",                "[NEXUS_PAYLOAD]"),
    FleetPrompt("spark",       "tb-008", "tb-008-spark.v2.md",       "", True,  "",                "[NEXUS_PAYLOAD]"),
    FleetPrompt("falcon",      "tb-009", "tb-009-falcon.v2.md",      "", True,  "",                "[FALCON_PAYLOAD]"),
    FleetPrompt("eagle",       "tb-010", "tb-010-eagle.v2.md",       "", True,  "{chunk}",         "[FALCON_PAYLOAD]"),
    FleetPrompt("drafter",     "tb-011", "tb-011-drafter.v2.md",     "", True,  "",                "[DRAFTING_PAYLOAD]"),
    FleetPrompt("scout",       "tb-012", "tb-012-scout.v2.md",       "", True,  "{chunk}",         "[DNA_CONTRACTS]"),
    FleetPrompt("oc",          "tb-013", "tb-013-oc.v2.md",          "", True,  "",                "[REVIEW_PAYLOAD]"),
    FleetPrompt("olc",         "tb-014", "tb-014-olc.v2.md",         "", True,  "",                "[APPROVED_PAYLOAD]"),
]

_BY_STAGE = {p.stage: p for p in FLEET}

STAGE_ORDER = ["distiller", "introbeaver", "planbeaver", "outrobeaver",
               "nexus", "spark", "falcon",
               "eagle", "drafter", "scout",
               "oc", "olc"]

STAGE_GROUPS = {
    "stage1": ["distiller", "introbeaver", "planbeaver", "outrobeaver"],
    "stage2": ["nexus", "spark", "falcon"],
    "stage3": ["eagle", "drafter", "scout"],
    "stage4": ["oc", "olc"],
}

_STAGE_OF = {s: g for g, sts in STAGE_GROUPS.items() for s in sts}


def stage_of(stage: str) -> str:
    return _STAGE_OF.get(stage, stage)


def get_prompt(stage: str) -> FleetPrompt:
    if stage not in _BY_STAGE:
        raise KeyError(f"unknown stage: {stage!r} (known: {', '.join(_BY_STAGE)})")
    return _BY_STAGE[stage]


def load_system_prompt(stage: str, fleet_dir: Path | None = None,
                       strip_injection: bool = False) -> str:
    """system-base + (pipeline-protocol on handoffs) + stage prompt.

    strip_injection: for {chunk}/{contracts} slot prompts, drop the trailing
    marker+slot lines from the prompt body (they are re-emitted as the user
    message by assemble() with the real content).
    """
    fleet_dir = fleet_dir or FLEET_DIR
    p = get_prompt(stage)
    base = (fleet_dir / "tb-003-system-base.v2.md").read_text().rstrip()
    parts = [base]
    if p.handoff:
        proto = (fleet_dir / "tb-002-pipeline-protocol.v2.md").read_text().rstrip()
        parts.append(proto)
    # Load the actual stage prompt body from disk if not already cached
    body = p.body
    if not body:
        body = (fleet_dir / p.filename).read_text().rstrip()
    if strip_injection and p.slot == "{chunk}":
        body, _ = strip_injection_tail(body, stage)
    parts.append(body.rstrip())
    return "\n\n".join(parts)


_INJECTION_TAILS = {
    "distiller": "[RAW_CHAT_TRANSCRIPT]",
    "eagle":     "[FALCON_PAYLOAD]",
}


def strip_injection_tail(body: str, stage: str) -> tuple[str, list[str]]:
    """Split a {chunk}/{contracts} prompt into (instructions, marker_lines).

    Returns the prompt with its trailing marker/slot lines removed, plus the
    marker lines in order so assemble() can re-emit them with real content.
    """
    if stage == "scout":
        m = body.rfind("[CODE_ARTIFACT]")
        if m == -1:
            return body.rstrip(), ["[CODE_ARTIFACT]", "[DNA_CONTRACTS]"]
        return body[:m].rstrip(), ["[CODE_ARTIFACT]", "[DNA_CONTRACTS]"]
    marker = _INJECTION_TAILS[stage]
    i = body.rfind(marker)
    if i == -1:
        return body.rstrip(), [marker]
    return body[:i].rstrip(), [marker]


def assemble(stage: str, system_prompt: str, *,
             chunk: str = "", contracts: str = "",
             payload: dict | str | None = None) -> tuple[str, str]:
    """Build (system, user) for one stage call.

    - Slot prompts (distiller/eagle/scout): caller passes the system prompt
      from load_system_prompt(stage, strip_injection=True); the user message
      re-emits the markers with the real content.
    - Payload prompts (beavers/nexus/spark/falcon/drafter/oc/olc): the user
      message is the canonical JSON payload itself; the chatset_hash inside
      is what the model must echo back.
    """
    p = get_prompt(stage)
    if p.slot == "{chunk}":
        _, markers = strip_injection_tail(p.body, stage)
        if stage == "scout":
            user = f"{markers[0]}\n{chunk}\n{markers[1]}\n{contracts}"
        elif stage == "eagle":
            content = payload_envelope(payload) if isinstance(payload, dict) else (payload or chunk)
            user = f"{markers[0]}\n{content}"
        else:  # distiller: meta header (hash is given, never recomputed)
            meta = payload_envelope(payload) if isinstance(payload, dict) else ""
            header = f"[CHAT_SET_META]\n{meta}\n" if meta else ""
            user = f"{header}{markers[0]}\n{chunk}"
        return system_prompt, user
    if payload is not None:
        return system_prompt, (payload_envelope(payload) if isinstance(payload, dict) else payload)
    return system_prompt, chunk


def payload_envelope(payload: dict) -> str:
    """Canonical JSON for a payload block (the hash inside must be echoed)."""
    return canonical_json(payload)


def make_payload(*, session_id: str, chatset_id: str, raw_chat_set: list[dict],
                 **extra) -> dict:
    """Standard machine-talk payload: identity + timestamp + hash + data."""
    payload = {
        "session_id": session_id,
        "chatset_id": chatset_id,
        "timestamp_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "chatset_hash": chatset_hash_for(raw_chat_set),
        "raw_chat_set": raw_chat_set,
    }
    payload.update(extra)
    return payload
