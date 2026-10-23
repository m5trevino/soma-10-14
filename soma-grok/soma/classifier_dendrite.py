"""TB-DEND-020: Classifier Dendrite (FIXED — stage_name → "classifier").

Extracts signals from a single ChatSet's user text via LLM and classifies
them into the disposition lanes, writing IntentNode, DirectiveNode, and
Constraint nodes (plus Question, Preference, Correction, Noise as needed).
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any, Sequence

from store import Soma
from soma.helpers import get_receptor_config
from pipeline.stage_complete import complete_stage


@dataclass(frozen=True, slots=True)
class Signal:
    """A single classified signal extracted from a USER message."""
    signal_type: str  # Intent, Directive, Constraint, Question, Preference, Correction, Noise
    confidence: float  # 0.0 .. 1.0
    source_text: str
    rationale: str


# ------------------------------------------------------------------
# Heuristic classifiers (no LLM dependency — rules-only)
# ------------------------------------------------------------------

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


def classify(text: str) -> Sequence[Signal]:
    """Classify a single USER text into signal nodes.

    Always returns at least one signal. Uses a priority cascade:
    Question > Correction > Command/Directive > Constraint > Preference > Intent > Noise.
    """
    text_stripped = text.strip()
    if not text_stripped:
        return [Signal(signal_type="Noise", confidence=0.1, source_text=text, rationale="empty")]

    signals: list[Signal] = []

    # 1. Question
    if _QUESTION_RE.search(text_stripped):
        signals.append(Signal(
            signal_type="QuestionNode",
            confidence=0.85,
            source_text=text_stripped,
            rationale="matches question pattern",
        ))

    # 2. Correction
    if _CORRECTION_RE.search(text_stripped):
        signals.append(Signal(
            signal_type="CorrectionNode",
            confidence=0.80,
            source_text=text_stripped,
            rationale="matches correction pattern",
        ))

    # 3. Directive (imperative command)
    if _COMMAND_RE.search(text_stripped):
        signals.append(Signal(
            signal_type="DirectiveNode",
            confidence=0.75,
            source_text=text_stripped,
            rationale="matches directive/command pattern",
        ))

    # 4. Constraint
    if _CONSTRAINT_RE.search(text_stripped):
        signals.append(Signal(
            signal_type="ConstraintNode",
            confidence=0.70,
            source_text=text_stripped,
            rationale="matches constraint pattern",
        ))

    # 5. Preference
    if _PREFERENCE_RE.search(text_stripped):
        signals.append(Signal(
            signal_type="PreferenceNode",
            confidence=0.65,
            source_text=text_stripped,
            rationale="matches preference pattern",
        ))

    # 6. Noise (greetings, acknowledgements)
    if _NOISE_RE.match(text_stripped):
        signals.append(Signal(
            signal_type="NoiseNode",
            confidence=0.90,
            source_text=text_stripped,
            rationale="matches noise/greeting pattern",
        ))

    # 7. Fallback — always classify at least something as Intent
    if not signals:
        signals.append(Signal(
            signal_type="IntentNode",
            confidence=0.30,
            source_text=text_stripped,
            rationale="no pattern matched, defaulting to Intent",
        ))

    return signals


# ------------------------------------------------------------------
# Classifier Dendrite — LLM-driven via complete_stage
# ------------------------------------------------------------------

_DEFAULT_CLASSIFIER_INSTRUCTION = (
    "You are the Classifier Dendrite. Analyse the user text below and return "
    "a JSON array of signal objects. Each object must have exactly these keys:\n"
    '  "signal_type": one of IntentNode, DirectiveNode, ConstraintNode, '
    'QuestionNode, PreferenceNode, CorrectionNode, NoiseNode\n'
    '  "confidence": float 0.0..1.0\n'
    '  "source_text": the original text span\n'
    '  "rationale": brief explanation\n'
    "Return ONLY the JSON array. No prose, no markdown, no explanation."
)


class ClassifierDendrite:
    """Active Classifier — signal extraction for one ChatSet."""

    def __init__(self, soma: Soma, llm_client: Any) -> None:
        self._soma = soma
        self._llm = llm_client

    def run(self, chat_set_id: str) -> dict[str, Any]:
        """Extract signals from the user text of *chat_set_id*."""
        start = time.monotonic()
        # FIXED: "classifier" instead of undefined stage_name
        stage_name = "classifier"

        cs = self._soma.get_node(chat_set_id)
        if cs is None or cs.node_type != "ChatSet":
            return {"error": f"ChatSet not found: {chat_set_id}"}

        session_id = cs.properties.get("session_id", "")
        user_text = str(cs.properties.get("user_text", "")).strip()

        signal_ids: list[str] = []
        signal_counts: dict[str, int] = {}

        if not user_text:
            elapsed_ms = (time.monotonic() - start) * 1000
            return {
                "chat_set_id": chat_set_id,
                "signal_node_ids": signal_ids,
                "signal_counts": signal_counts,
                "metrics": {
                    "model_id": "unknown",
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                    "latency_ms": elapsed_ms,
                },
            }

        # Load ReceptorConfig instruction body
        config = get_receptor_config(self._soma, "classifier")
        instruction_body = (
            config.get("instruction_body", _DEFAULT_CLASSIFIER_INSTRUCTION)
            if config else _DEFAULT_CLASSIFIER_INSTRUCTION
        )

        # Call complete_stage
        stage_result = complete_stage(
            self._llm, stage_name, instruction_body, user_text,
        )

        if not stage_result["ok"]:
            # Fallback to regex classify() when the LLM call fails
            return self._run_regex_fallback(
                chat_set_id, session_id, user_text, "unknown",
            )

        # Parse the LLM result into signal nodes
        signals_data = stage_result["result"]
        if isinstance(signals_data, dict):
            signals_data = signals_data.get("signals", [signals_data])

        for i, sig in enumerate(signals_data):
            sig_type = sig.get("signal_type", "IntentNode")
            # Normalise: ensure Node suffix
            if not sig_type.endswith("Node"):
                sig_type = sig_type + "Node"

            node_id = f"sig-{chat_set_id}-{sig_type}-{i}"
            existing = self._soma.get_node(node_id)
            if existing:
                signal_ids.append(node_id)
                signal_counts[sig_type] = signal_counts.get(sig_type, 0) + 1
                continue

            self._soma.create_node(sig_type, {
                "id": node_id,
                "session_id": session_id,
                "chat_set_id": chat_set_id,
                "confidence": sig.get("confidence", 0.5),
                "source_text": sig.get("source_text", user_text),
                "rationale": sig.get("rationale", "llm classified"),
            })
            self._soma.create_edge(chat_set_id, "EXTRACTED_FROM", node_id)
            signal_ids.append(node_id)
            signal_counts[sig_type] = signal_counts.get(sig_type, 0) + 1

        return {
            "chat_set_id": chat_set_id,
            "signal_node_ids": signal_ids,
            "signal_counts": signal_counts,
            "metrics": stage_result["metrics"],
        }

    def _run_regex_fallback(
        self,
        chat_set_id: str,
        session_id: str,
        user_text: str,
        model_id: str = "unknown",
    ) -> dict[str, Any]:
        """Fallback to regex classify() when the LLM call fails."""
        start = time.monotonic()
        signal_ids: list[str] = []
        signal_counts: dict[str, int] = {}

        signals = classify(user_text)
        for i, signal in enumerate(signals):
            node_id = f"sig-{chat_set_id}-{signal.signal_type}-{i}"
            existing = self._soma.get_node(node_id)
            if existing:
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

        elapsed_ms = (time.monotonic() - start) * 1000
        return {
            "chat_set_id": chat_set_id,
            "signal_node_ids": signal_ids,
            "signal_counts": signal_counts,
            "metrics": {
                "model_id": "unknown",
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "latency_ms": elapsed_ms,
            },
        }