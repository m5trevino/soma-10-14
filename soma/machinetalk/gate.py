"""Python gate: validates every machine-talk response BEFORE it is trusted.

The LLM is never the gate. Each stage's prompt defines its own output
contract (wrapper object, verdict key, hash-echo key, text-vs-JSON). This
module parses the raw response, enforces that contract, and returns a
structured GateResult. A failed gate means the stage is not DONE (checkpoint
stays PENDING) and the caller rotates to the next model and retries.

Per-stage facts (verified against the installed tb-NNN prompts):

  stage        format  wrapper            verdict key  hash echo
  distiller    json    (top-level)        skip(bool)   chatset_hash
  introbeaver  json    introbeaver_output status       input_hash
  planbeaver   json    planbeaver_output  status       --
  outrobeaver  json    outrobeaver_output status/health --
  nexus        json    (top-level)        artifact_type plan_hash_verification
  spark        json    (top-level)        artifact_type plan_hash_verification
  falcon       json    (top-level)        artifact_type plan_hash_verification
  eagle        json    (top-level)        --           plan_hash
  drafter      json    draft_artifact     status       --
  scout        TEXT    --                 scout_verdict --
  oc           json    oc_decision        verdict      --
  olc          json    olc_output         status       --

The hash the model echoes is the SAME canonical chatset hash the caller
computed (nexus/spark/falcon/eagle chain it forward as plan_hash). We verify
the echo matches, exactly.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

_FENCE_RE = re.compile(r"```")


@dataclass
class GateResult:
    ok: bool
    stage: str
    parsed: Any = None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    skipped: bool = False          # distiller SKIP / introbeaver NO_INTENT
    verdict: str = ""              # stage verdict token, if any
    skip_reason: str = ""
    exfil_type: str = ""
    signal_quality: str = ""
    provenance: str = ""           # provenance check summary, when run

    @property
    def reasons(self) -> str:
        return "; ".join(self.errors)

    def first_reason(self) -> str:
        """The first error, not the first character of the joined string."""
        if self.errors:
            return self.errors[0]
        return "UNKNOWN"


# ---------------------------------------------------------------------------
# Per-stage spec
# ---------------------------------------------------------------------------

@dataclass
class StageSpec:
    stage: str
    text: bool = False             # True only for scout
    required: tuple[str, ...] = ()  # keys that must exist (searched recursively)
    verdict_key: str | None = None
    hash_key: str | None = None     # echoed-hash key (searched recursively)
    # Verdict tokens that are terminal-soft (vault, like a skip)
    skip_tokens: tuple[str, ...] = ()
    # Verdict tokens that are hard halts (operator must look; not a retry)
    block_tokens: tuple[str, ...] = ()


SPECS: dict[str, StageSpec] = {
    "distiller": StageSpec("distiller", required=("chatset_hash", "skip"),
                            verdict_key="skip", hash_key="chatset_hash"),
    "introbeaver": StageSpec("introbeaver", required=("introbeaver_output",),
                            verdict_key="status", hash_key="input_hash",
                            skip_tokens=("NO_INTENT",)),
    "planbeaver": StageSpec("planbeaver", required=("planbeaver_output",),
                            verdict_key="status",
                            block_tokens=("BLOCKED", "INVALID_PLAN",
                                          "INCOMPLETE_PLAN", "NEEDS_DECOMPOSITION")),
    "outrobeaver": StageSpec("outrobeaver", required=("outrobeaver_output",),
                            verdict_key="session_health",
                            block_tokens=("GHOST_SESSION", "CORRUPT_INPUT")),
    "nexus": StageSpec("nexus", required=("plan_hash_verification", "blueprints"),
                        verdict_key="artifact_type", hash_key="plan_hash_verification"),
    "spark": StageSpec("spark", required=("plan_hash_verification",
                                          "functional_requirements"),
                        verdict_key="artifact_type", hash_key="plan_hash_verification"),
    "falcon": StageSpec("falcon", required=("plan_hash_verification",
                                            "component_architecture"),
                        verdict_key="artifact_type", hash_key="plan_hash_verification"),
    "eagle": StageSpec("eagle", required=("file_tree", "skeleton_blocks"),
                       hash_key="plan_hash"),
    "drafter": StageSpec("drafter", required=("draft_artifact",),
                        verdict_key="status",
                        block_tokens=("BROKEN_DRAFT", "INCOMPLETE_DRAFT",
                                      "CONTRACT_VIOLATION")),
    "scout": StageSpec("scout", text=True, verdict_key="scout_verdict"),
    "oc": StageSpec("oc", required=("oc_decision",), verdict_key="verdict"),
    "olc": StageSpec("olc", required=("olc_output",), verdict_key="status",
                     block_tokens=("UNAUTHORIZED", "SIGNATURE_BREACH",
                                   "INVALID_HARDENING")),
}


# ---------------------------------------------------------------------------
# Recursive helpers
# ---------------------------------------------------------------------------

def _find(obj: Any, key: str) -> Any:
    """First value for `key` anywhere in the (dict/list) tree, else None."""
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        for v in obj.values():
            r = _find(v, key)
            if r is not None:
                return r
    elif isinstance(obj, list):
        for v in obj:
            r = _find(v, key)
            if r is not None:
                return r
    return None


def _find_all(obj: Any, key: str) -> list[Any]:
    out: list[Any] = []
    if isinstance(obj, dict):
        if key in obj:
            out.append(obj[key])
        for v in obj.values():
            out.extend(_find_all(v, key))
    elif isinstance(obj, list):
        for v in obj:
            out.extend(_find_all(v, key))
    return out


# ---------------------------------------------------------------------------
# JSON path
# ---------------------------------------------------------------------------

def _strip_fences(text: str) -> str:
    """Remove markdown code fences so LLM-wrapped JSON parses cleanly."""
    text = re.sub(r"^```[a-zA-Z]*\s*\n?", "", text, flags=re.MULTILINE)
    text = re.sub(r"\n?\s*```\s*$", "", text, flags=re.MULTILINE)
    return text


def _repair_json(body: str) -> str:
    """Fix the two breakages models actually produce, without guessing.

    Trailing commas and raw control characters (a literal newline or tab
    inside a string) are the only repairs applied. Neither can change what
    the object means; both make ``json.loads`` reject an otherwise correct
    document.
    """
    # Trailing commas before a closing brace or bracket.
    body = re.sub(r",(\s*[}\]])", r"\1", body)
    # Raw control characters inside strings must be escaped to be legal JSON.
    out: list[str] = []
    in_string = False
    escaped = False
    for ch in body:
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            elif ch in "\n\r\t":
                out.append({"\n": "\\n", "\r": "\\r", "\t": "\\t"}[ch])
                continue
        elif ch == '"':
            in_string = True
        out.append(ch)
    return "".join(out)


def _extract_json_object(text: str,
                         warnings: list[str] | None = None
                         ) -> tuple[dict | None, list[str]]:
    """Locate and parse the JSON object inside a model response.

    Narrative around the object is recorded as a warning, not an error. A
    model that writes "Here is the result:" and then a complete, correct
    object has done its job; failing it for the sentence made every
    well-behaved model look broken and made model comparison meaningless.
    Only text that prevents a parse is fatal.

    ``warnings`` is appended to in place when the caller wants the narrative
    kept for the record.
    """
    s = _strip_fences(text.strip())
    errs: list[str] = []
    start = s.find("{")
    end = s.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None, ["no_json_object"]

    prose = []
    if s[:start].strip():
        prose.append(f"prose_before_json:{s[:start].strip()[:40]!r}")
    if s[end + 1:].strip():
        prose.append(f"prose_after_json:{s[end+1:].strip()[:40]!r}")

    body = s[start:end + 1]
    try:
        obj = json.loads(body)
    except json.JSONDecodeError as e:
        repaired = _repair_json(body)
        try:
            obj = json.loads(repaired)
            prose.append(f"repaired_json:{e.msg}@{e.pos}")
        except json.JSONDecodeError as e2:
            return None, [f"json_parse:{e2.msg}@{e2.pos}"]

    if not isinstance(obj, dict):
        return None, ["top_level_not_object"]

    if warnings is not None:
        warnings.extend(prose)
    return obj, errs


def _check_json(stage: str, spec: StageSpec, raw: str,
                expected_hash: str | None) -> GateResult:
    warnings: list[str] = []
    obj, errs = _extract_json_object(raw, warnings)
    if obj is None:
        return GateResult(False, stage, errors=errs)

    for key in spec.required:
        if _find(obj, key) is None:
            errs.append(f"missing:{key}")

    # Hash echo (only for stages that echo one).
    #
    # A wrong or absent hash is fatal, not a warning. The echo is how a stage
    # attests which input it actually processed; a stage that reports a hash
    # it was never given has not verified its own input, and downstream
    # provenance cannot rely on anything it produced. Models cannot compute
    # sha256, so an unverifiable echo is also the signature of a fabricated
    # one.
    if spec.hash_key:
        echoed = _find(obj, spec.hash_key)
        if expected_hash is not None:
            if not isinstance(echoed, str) or not echoed:
                errs.append("missing_hash_echo")
            elif echoed != expected_hash:
                errs.append(f"hash_mismatch:{echoed[:12]}!={expected_hash[:12]}")
        elif isinstance(echoed, str) and echoed:
            # No caller-expected hash (re-run): still require it be a sha256.
            if not re.fullmatch(r"[0-9a-f]{64}", echoed):
                errs.append("hash_echo_not_sha256")

    # Verdict.
    verdict = ""
    if spec.verdict_key:
        v = _find(obj, spec.verdict_key)
        if isinstance(v, bool):
            verdict = str(v).lower()
        elif isinstance(v, str):
            verdict = v.strip()

    blocked = verdict.upper() in spec.block_tokens
    skipped = False
    skip_reason = ""
    exfil = ""
    sigq = ""

    # Distiller / introbeaver skip routing.
    if stage == "distiller" and verdict in ("true", "1", "yes"):
        skipped = True
        skip_reason = str(_find(obj, "skip_reason") or "")
        exfil = str(_find(obj, "exfil_type") or "")
        sigq = str(_find(obj, "signal_quality") or "")
        errs.clear()  # a clean skip is a PASS
    if stage == "introbeaver" and verdict.upper() in ("NO_INTENT",):
        skipped = True
        skip_reason = "no_user_messages"
        errs.clear()

    if stage == "outrobeaver" and verdict.upper() == "RED":
        warnings.append("session_health_RED")

    ok = not errs and not blocked
    return GateResult(
        ok=ok, stage=stage, parsed=obj,
        errors=errs + ([f"blocked:{verdict}"] if blocked else []),
        skipped=skipped, verdict=verdict,
        skip_reason=skip_reason, exfil_type=exfil,
        signal_quality=sigq, warnings=warnings,
    )


# ---------------------------------------------------------------------------
# Scout text path
# ---------------------------------------------------------------------------

_SCOUT_HEAD = "### SCOUT VIOLATION REPORT:"
_SCOUT_TAIL = re.compile(r"SCOUT REVIEW COMPLETE\. VERDICT:\s*(\w+)\s*$")


def _check_scout(raw: str) -> GateResult:
    s = _strip_fences(raw.strip())
    errs: list[str] = []
    if not s.startswith(_SCOUT_HEAD):
        errs.append(f"missing_head:{s[:40]!r}")
    m = None
    for line in reversed(s.splitlines()):
        mm = _SCOUT_TAIL.search(line.strip())
        if mm:
            m = mm
            break
    if m is None:
        errs.append("missing_verdict_tail")
        verdict = ""
    else:
        verdict = m.group(1).upper()
    ok = not errs
    return GateResult(ok=ok, stage="scout",
                      parsed={"scout_verdict": verdict} if verdict else None,
                      errors=errs, verdict=verdict)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def validate(stage: str, raw: str, expected_hash: str | None = None) -> GateResult:
    spec = SPECS.get(stage)
    if spec is None:
        return GateResult(False, stage, errors=[f"unknown_stage:{stage}"])
    if spec.text:
        return _check_scout(raw)
    return _check_json(stage, spec, raw, expected_hash)


def is_done(gate: GateResult) -> bool:
    """A stage is DONE when the gate passes OR it is a clean skip."""
    return gate.ok or gate.skipped


def is_hard_block(gate: GateResult) -> bool:
    """True when the verdict is a hard halt (not a retry, not a skip)."""
    spec = SPECS.get(gate.stage)
    if spec is None:
        return False
    return gate.verdict.upper() in spec.block_tokens
