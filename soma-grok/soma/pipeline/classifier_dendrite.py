"""TB-TK-REPLACE-002: Classifier Dendrite — signal extraction via LLM tool-calling.

Fetches ReceptorConfig, processes cleaned text from ReceptorDendrite via LLM
tool-calling, writes categorized nodes (IntentNode, DirectiveNode, ConstraintNode,
QuestionNode, PreferenceNode, CorrectionNode) and EXTRACTED_FROM edges to Soma.

Hard gates:
  - Must NOT generate any code artifacts
  - Must use only the 6 defined disposition lanes (enum enforcement)
  - Must use create_soma_node tool for all persistence
  - Must use create_soma_edge tool for all edges
"""
from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional, Sequence

from store import Soma

# ---------------------------------------------------------------------------
# 6 Disposition Lanes (strict enum)
# ---------------------------------------------------------------------------

DISPOSITION_LANES: frozenset[str] = frozenset({
    "IntentNode",
    "DirectiveNode",
    "ConstraintNode",
    "QuestionNode",
    "PreferenceNode",
    "CorrectionNode",
})

# Noise is NOT a disposition lane — fallback only
NOISE_FALLBACK = "NoiseNode"


# ---------------------------------------------------------------------------
# Data shapes
# ---------------------------------------------------------------------------

@dataclass
class ClassifiedSignal:
    """A classified signal from one ChatSet."""
    signal_type: str      # one of the 6 disposition lanes or NOISE_FALLBACK
    confidence: float     # 0.0 .. 1.0
    source_text: str
    rationale: str
    node_id: str = ""     # populated after node creation


# ---------------------------------------------------------------------------
# Heuristic classifier (regex-based fallback — no LLM dependency)
# ---------------------------------------------------------------------------

_QUESTION_PATTERNS = (
    r"\?(?:\s|$)",
    r"(?:who|what|when|where|why|how|can|could|would|should|is|are|do|does)\b",
)
_QUESTION_RE = re.compile("|".join(_QUESTION_PATTERNS), re.IGNORECASE)

_COMMAND_VERBS = (
    "create", "delete", "remove", "add", "set", "configure", "enable",
    "disable", "install", "run", "build", "deploy", "fix", "change",
    "update", "migrate", "refactor", "test", "check", "find", "write",
    "make", "show", "display", "print", "list", "get", "pull", "push",
)
_COMMAND_RE = re.compile(r"\b(" + "|".join(_COMMAND_VERBS) + r")\b", re.IGNORECASE)

_PREFERENCE_PATTERNS = (
    r"\b(prefer|like|want|would\s+like|enjoy|love|hate|dislike)\b",
    r"\b(i\s+usually|i\s+always|i\s+never|i\s+often)\b",
)
_PREFERENCE_RE = re.compile("|".join(_PREFERENCE_PATTERNS), re.IGNORECASE)

_CORRECTION_PATTERNS = (
    r"\b(not|no,|actually|wait|sorry|my\s+bad|i\s+meant|forget\s+that|nvm\b|oops)",
    r"(?:^|\.)\s*(i\s+mean|i\s+meant|correction)",
)
_CORRECTION_RE = re.compile("|".join(_CORRECTION_PATTERNS), re.IGNORECASE)

_CONSTRAINT_PATTERNS = (
    r"\b(must|should|have\s+to|need\s+to|require|only|never|always|can't|cannot)\b",
    r"\b(as\s+long\s+as|provided\s+that|unless|if\s+and\s+only\s+if)\b",
)
_CONSTRAINT_RE = re.compile("|".join(_CONSTRAINT_PATTERNS), re.IGNORECASE)

_NOISE_PATTERNS = (
    r"^(hi|hello|hey|greetings|good\s+morning|good\s+afternoon|good\s+evening)$",
    r"^(thanks|thank\s+you|thx|ty|tysm)$",
    r"^(ok|okay|alright|sure|yes|no)$",
)
_NOISE_RE = re.compile("|".join(_NOISE_PATTERNS), re.IGNORECASE)


def heuristic_classify(text: str) -> Sequence[ClassifiedSignal]:
    """Regex-based heuristic classification (no LLM).

    Priority cascade: Question > Correction > Directive > Constraint > Preference > Noise.
    Always returns at least one signal.
    """
    stripped = text.strip()
    if not stripped:
        return [ClassifiedSignal(signal_type=NOISE_FALLBACK, confidence=0.1,
                                source_text=text, rationale="empty")]

    signals: list[ClassifiedSignal] = []

    if _QUESTION_RE.search(stripped):
        signals.append(ClassifiedSignal(signal_type="QuestionNode", confidence=0.85,
                                        source_text=stripped, rationale="question pattern"))
    if _CORRECTION_RE.search(stripped):
        signals.append(ClassifiedSignal(signal_type="CorrectionNode", confidence=0.80,
                                        source_text=stripped, rationale="correction pattern"))
    if _COMMAND_RE.search(stripped):
        signals.append(ClassifiedSignal(signal_type="DirectiveNode", confidence=0.75,
                                        source_text=stripped, rationale="directive pattern"))
    if _CONSTRAINT_RE.search(stripped):
        signals.append(ClassifiedSignal(signal_type="ConstraintNode", confidence=0.70,
                                        source_text=stripped, rationale="constraint pattern"))
    if _PREFERENCE_RE.search(stripped):
        signals.append(ClassifiedSignal(signal_type="PreferenceNode", confidence=0.65,
                                        source_text=stripped, rationale="preference pattern"))
    if _NOISE_RE.match(stripped):
        signals.append(ClassifiedSignal(signal_type=NOISE_FALLBACK, confidence=0.90,
                                        source_text=stripped, rationale="noise pattern"))

    if not signals:
        signals.append(ClassifiedSignal(signal_type="IntentNode", confidence=0.30,
                                        source_text=stripped, rationale="unclassified default"))

    return signals


# ---------------------------------------------------------------------------
# Default classifier instruction template
# ---------------------------------------------------------------------------

_DEFAULT_CLASSIFIER_INSTRUCTION = (
    "You are the Classifier Dendrite. Analyse the user text below and return "
    "a JSON array of signal objects. Each object must have exactly these keys:\n"
    '  "signal_type": one of IntentNode, DirectiveNode, ConstraintNode, '
    'QuestionNode, PreferenceNode, CorrectionNode\n'
    '  "confidence": float 0.0..1.0\n'
    '  "source_text": the original text span\n'
    '  "rationale": brief explanation\n'
    "Return ONLY the JSON array. No prose, no markdown, no explanation."
)


# ---------------------------------------------------------------------------
# Tool-calling LLM interface wrapper
# ---------------------------------------------------------------------------

class LLMToolCallClient:
    """Thin wrapper that provides the .call() method expected by complete_stage."""

    def __init__(self, llm_client: Any) -> None:
        self._llm = llm_client

    def call(self, stage: str, messages: list[dict[str, str]]) -> Any:
        """Call the underlying LLM client with .chat().

        The underlying client may be a real TurnKeyClient, MockLLMClient, etc.
        """
        if hasattr(self._llm, "chat"):
            return self._llm.chat(messages)
        raise NotImplementedError("LLM client has neither .chat() nor .call()")


# ---------------------------------------------------------------------------
# Complete Stage (LLM call + JSON parse)
# ---------------------------------------------------------------------------

_JSON_FENCE = re.compile(r"^```(?:json)?\s*(.*?)```?\s*$", re.DOTALL)


def complete_stage(
    llm_client: Any,
    stage: str,
    instruction_body: str,
    payload: str,
) -> dict[str, Any]:
    """Call the LLM tool-client and parse JSON result.

    Returns:
        {"ok": True, "result": parsed, "metrics": {...}}
        {"ok": False, "error": ..., "metrics": {...}}
    """
    start = time.monotonic()

    # Wrap if bare LLM client (has .chat) vs full client (has .call)
    if not hasattr(llm_client, "call"):
        llm_client = LLMToolCallClient(llm_client)

    try:
        response = llm_client.call(stage, [
            {"role": "system", "content": instruction_body},
            {"role": "user", "content": payload},
        ])
    except Exception as exc:
        elapsed = (time.monotonic() - start) * 1000
        return {"ok": False, "error": str(exc), "metrics": _empty_metrics(elapsed)}

    content = (getattr(response, "content", "") or "").strip()
    cleaned = _JSON_FENCE.sub(r"\1", content).strip()

    try:
        result = json.loads(cleaned)
    except (json.JSONDecodeError, ValueError):
        elapsed = (time.monotonic() - start) * 1000
        return {"ok": False, "error": f"non-JSON response: {cleaned[:200]}",
                "metrics": _empty_metrics(elapsed)}

    elapsed = (time.monotonic() - start) * 1000
    metrics = {
        "model_id": getattr(response, "model_id", "unknown"),
        "prompt_tokens": getattr(response, "prompt_tokens", 0),
        "completion_tokens": getattr(response, "completion_tokens", 0),
        "total_tokens": getattr(response, "total_tokens", 0),
        "latency_ms": elapsed,
    }
    return {"ok": True, "result": result, "metrics": metrics}


def _empty_metrics(elapsed_ms: float) -> dict[str, Any]:
    return {
        "model_id": "unknown", "prompt_tokens": 0,
        "completion_tokens": 0, "total_tokens": 0, "latency_ms": elapsed_ms,
    }


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------

_REQUIRED_SIGNAL_KEYS = frozenset({"signal_type", "confidence", "source_text", "rationale"})


def validate_signal(sig: dict[str, Any]) -> Optional[str]:
    """Return an error string if the signal dict fails schema validation, else None."""
    for key in _REQUIRED_SIGNAL_KEYS:
        if key not in sig:
            return f"missing key: {key}"
    stype = sig["signal_type"]
    if stype not in DISPOSITION_LANES:
        return f"invalid signal_type: {stype!r} (must be one of {DISPOSITION_LANES})"
    conf = sig.get("confidence")
    if not isinstance(conf, (int, float)) or not (0.0 <= conf <= 1.0):
        return f"confidence out of range: {conf}"
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


class ClassifierDendrite:
    """Active Classifier — signal extraction for one ChatSet via LLM tool-calling."""

    def __init__(self, soma: Soma, llm_client: Any) -> None:
        self._soma = soma
        self._llm = llm_client

    def run(self, chat_set_id: str) -> dict[str, Any]:
        """Extract signals from user text of *chat_set_id*.

        Returns dict with chat_set_id, signal_node_ids, signal_counts, metrics.
        """
        start = time.monotonic()

        cs = self._soma.get_node(chat_set_id)
        if cs is None or cs.node_type != "ChatSet":
            return {"error": f"ChatSet not found: {chat_set_id}"}

        session_id = cs.properties.get("session_id", "")
        user_text = str(cs.properties.get("user_text", "")).strip()

        signal_ids: list[str] = []
        signal_counts: dict[str, int] = {}

        if not user_text:
            return {
                "chat_set_id": chat_set_id,
                "signal_node_ids": signal_ids,
                "signal_counts": signal_counts,
                "metrics": {"model_id": "unknown", "prompt_tokens": 0,
                            "completion_tokens": 0, "total_tokens": 0,
                            "latency_ms": (time.monotonic() - start) * 1000},
            }

        # Fetch ReceptorConfig
        config = self._soma.get_node(f"config-classifier")
        if config:
            instruction_body = config.properties.get("instruction_body", _DEFAULT_CLASSIFIER_INSTRUCTION)
        else:
            instruction_body = _DEFAULT_CLASSIFIER_INSTRUCTION

        # LLM tool-call
        stage_result = complete_stage(self._llm, "classifier", instruction_body, user_text)

        if not stage_result["ok"]:
            return self._regex_fallback(chat_set_id, session_id, user_text, start)

        # Parse result
        result_data = stage_result["result"]
        if isinstance(result_data, dict):
            result_data = result_data.get("signals", [result_data])
        if not isinstance(result_data, list):
            return self._regex_fallback(chat_set_id, session_id, user_text, start)

        # Validate and create nodes for each signal
        for i, sig in enumerate(result_data):
            err = validate_signal(sig)
            if err:
                continue  # skip invalid signals

            sig_type = sig["signal_type"]  # validated — always one of 6 lanes

            node_id = f"sig-{chat_set_id}-{sig_type}-{i}"
            if self._soma.get_node(node_id):
                signal_ids.append(node_id)
                signal_counts[sig_type] = signal_counts.get(sig_type, 0) + 1
                continue

            # create_soma_node (hard gate: must use tool for persistence)
            self._soma.create_node(sig_type, {
                "id": node_id,
                "session_id": session_id,
                "chat_set_id": chat_set_id,
                "confidence": float(sig["confidence"]),
                "source_text": str(sig.get("source_text", user_text)),
                "rationale": str(sig.get("rationale", "llm classified")),
            })

            # create_soma_edge (hard gate: must use tool for edges)
            self._soma.create_edge(chat_set_id, "EXTRACTED_FROM", node_id)

            signal_ids.append(node_id)
            signal_counts[sig_type] = signal_counts.get(sig_type, 0) + 1

        return {
            "chat_set_id": chat_set_id,
            "signal_node_ids": signal_ids,
            "signal_counts": signal_counts,
            "metrics": stage_result["metrics"],
        }

    def _regex_fallback(
        self,
        chat_set_id: str,
        session_id: str,
        user_text: str,
        start: float,
    ) -> dict[str, Any]:
        """Fallback to heuristic_classify when LLM call fails."""
        signals = heuristic_classify(user_text)
        signal_ids: list[str] = []
        signal_counts: dict[str, int] = {}

        for i, signal in enumerate(signals):
            node_id = f"sig-{chat_set_id}-{signal.signal_type}-{i}"
            if self._soma.get_node(node_id):
                signal_ids.append(node_id)
                signal_counts[signal.signal_type] = signal_counts.get(signal.signal_type, 0) + 1
                continue

            self._soma.create_node(signal.signal_type, {
                "id": node_id,
                "session_id": session_id,
                "chat_set_id": chat_set_id,
                "confidence": signal.confidence,
                "source_text": signal.source_text,
                "rationale": signal.rationale,
            })
            self._soma.create_edge(chat_set_id, "EXTRACTED_FROM", node_id)
            signal_ids.append(node_id)
            signal_counts[signal.signal_type] = signal_counts.get(signal.signal_type, 0) + 1

        return {
            "chat_set_id": chat_set_id,
            "signal_node_ids": signal_ids,
            "signal_counts": signal_counts,
            "metrics": {
                "model_id": "unknown", "prompt_tokens": 0,
                "completion_tokens": 0, "total_tokens": 0,
                "latency_ms": (time.monotonic() - start) * 1000,
            },
        }
