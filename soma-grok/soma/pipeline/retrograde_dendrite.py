"""TB-TK-REPLACE-004: Retrograde Dendrite — session closure via LLM.

Reads assistant_text from the ChatSet node, calls the LLM to produce a session
closure payload, then writes OutcomeNode / DeliverableNode / LessonNode /
DriftNode / ActionNode records into Soma and links them with physical edges.

Edge semantics:
  OutcomeNode -> TRIGGERED_BY -> ChatSet
  OutcomeNode -> PRODUCES -> DeliverableNode
  OutcomeNode -> LEARNS -> LessonNode
  DriftNode -> DRIFTS_FROM -> from_node  (plan node that was changed)
  ActionNode  -> ASSIGNED_TO -> assigned target (dendrite name or plan node)

Hard gates:
  - Must write outcome nodes ONCE and cache the result (idempotent)
  - Must NOT generate any code artifacts
  - Outcome nodes are definitive and immutable post-creation
  - Drift nodes must accurately map plan changes (from_node -> DRIFTS_FROM -> to_node)
  - Actions must be linked to assigned dendrites via ASSIGNED_TO edges
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Optional

from store import Soma

from pipeline.drafter_dendrite import LLMClient, LLMResponse, MockLLMClient

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Output node types
# ---------------------------------------------------------------------------

_OUTPUT_NODE_TYPES = frozenset({
    "OutcomeNode",
    "DeliverableNode",
    "LessonNode",
    "DriftNode",
    "ActionNode",
})

# ---------------------------------------------------------------------------
# Default LLM instruction
# ---------------------------------------------------------------------------

_RETROGRADE_INSTRUCTION = (
    "You are the Retrograde Dendrite. Given the assistant text from a completed "
    "session, produce a structured session-closure record. Return a JSON object "
    "with exactly these keys:\n"
    '  "outcome": { "outcome_text": str }\n'
    '  "deliverables": [{ "deliverable_text": str }]\n'
    '  "lessons": [{ "lesson_text": str }]\n'
    '  "drifts": [{ "drift_description": str, "from_node": str, "to_node": str, "drift_type": str }]\n'
    '  "actions": [{ "action_text": str, "assigned_to": str }]\n'
    '  "unresolved": [str]\n'
    'Return ONLY the JSON object. No prose, no markdown, no explanation.'
)

# ---------------------------------------------------------------------------
# Schema validation helpers
# ---------------------------------------------------------------------------

_VALID_DRIFT_TYPES = frozenset({"scope_creep", "requirement_change", "technical_decision",
                                "constraint_override", "priority_shift", "unknown"})


def validate_outcome(outcome: dict[str, Any]) -> Optional[str]:
    """Return error string if outcome dict is malformed."""
    if "outcome_text" not in outcome:
        return "outcome missing outcome_text"
    return None


def validate_deliverable(deliverable: dict[str, Any]) -> Optional[str]:
    if "deliverable_text" not in deliverable:
        return "deliverable missing deliverable_text"
    return None


def validate_lesson(lesson: dict[str, Any]) -> Optional[str]:
    if "lesson_text" not in lesson:
        return "lesson missing lesson_text"
    return None


def validate_drift(drift: dict[str, Any]) -> Optional[str]:
    for key in ("drift_description", "from_node", "to_node"):
        if key not in drift:
            return f"drift missing {key}"
    drift_type = drift.get("drift_type", "unknown").lower()
    if drift_type not in _VALID_DRIFT_TYPES:
        return f"invalid drift_type: {drift.get('drift_type')!r}"
    return None


def validate_action(action: dict[str, Any]) -> Optional[str]:
    if "action_text" not in action:
        return "action missing action_text"
    if "assigned_to" not in action:
        return "action missing assigned_to"
    return None


# ---------------------------------------------------------------------------
# RetrogradeDendrite
# ---------------------------------------------------------------------------


class RetrogradeDendrite:
    """Reads assistant_text from a ChatSet and produces session closure nodes."""

    def __init__(
        self,
        soma: Soma,
        llm_client: Optional[LLMClient] = None,
        instruction: Optional[str] = None,
    ) -> None:
        self._soma = soma
        self._llm = llm_client or MockLLMClient()
        self._instruction = (
            instruction if instruction is not None else _RETROGRADE_INSTRUCTION
        )
        # Cache for outcome node created in this run
        self._cached_outcome_id: Optional[str] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self, chat_set_id: str) -> dict[str, Any]:
        """Process one ChatSet: read assistant_text, produce closure nodes.

        Returns dict with:
          - chat_set_id, session_id
          - outcome_node_id, deliverable_node_ids, lesson_node_ids,
            drift_node_ids, action_node_ids
          - metrics
        """
        start = time.monotonic()

        cs = self._soma.get_node(chat_set_id)
        if cs is None or cs.node_type != "ChatSet":
            return {"error": f"ChatSet not found: {chat_set_id}"}

        session_id = cs.properties.get("session_id", "")
        assistant_text = str(cs.properties.get("assistant_text", "")).strip()

        # ---------------------------------------------------------------
        # Idempotency gate: check for pre-existing OutcomeNode
        # ---------------------------------------------------------------
        existing_outcome = self._find_existing_outcome(chat_set_id)
        if existing_outcome is not None:
            return self._cached_result(
                chat_set_id, session_id, existing_outcome.node_id, start)

        # ---------------------------------------------------------------
        # Call LLM to produce closure payload
        # ---------------------------------------------------------------
        stage_result = self._call_llm(chat_set_id, assistant_text)

        if not stage_result["ok"]:
            return self._failure_result(
                chat_set_id, session_id, stage_result, start)

        result_data = stage_result["result"]

        # ---------------------------------------------------------------
        # 1. Write OutcomeNode (definitive, immutable)
        # ---------------------------------------------------------------
        outcome_payload = result_data.get("outcome", {})
        err = validate_outcome(outcome_payload)
        if err:
            logger.warning("Skipping outcome: %s", err)
            outcome_node = None
        else:
            outcome_node = self._soma.create_node("OutcomeNode", {
                "id": f"outcome-{chat_set_id}",
                "outcome_text": str(outcome_payload["outcome_text"]),
                "session_id": session_id,
                "chat_set_id": chat_set_id,
                "immutable": True,
                "created_at": time.time(),
            })
            self._cached_outcome_id = outcome_node.node_id

        # ---------------------------------------------------------------
        # 2. Write DeliverableNodes
        # ---------------------------------------------------------------
        deliverable_ids, created_deliverable_ids = self._write_deliverable_nodes(
            chat_set_id, session_id, result_data.get("deliverables", []))

        # ---------------------------------------------------------------
        # 3. Write LessonNodes
        # ---------------------------------------------------------------
        lesson_ids, created_lesson_ids = self._write_lesson_nodes(
            chat_set_id, session_id, result_data.get("lessons", []))

        # ---------------------------------------------------------------
        # 4. Write DriftNodes
        # ---------------------------------------------------------------
        drift_ids, created_drift_ids = self._write_drift_nodes(
            chat_set_id, session_id, result_data.get("drifts", []))

        # ---------------------------------------------------------------
        # 5. Write ActionNodes
        # ---------------------------------------------------------------
        action_ids, created_action_ids = self._write_action_nodes(
            chat_set_id, session_id, result_data.get("actions", []))

        # ---------------------------------------------------------------
        # 6. Create edges — only for newly created nodes
        # ---------------------------------------------------------------
        if outcome_node is not None:
            self._create_closure_edges(
                chat_set_id, outcome_node.node_id,
                created_deliverable_ids, created_lesson_ids,
                created_drift_ids, created_action_ids,
            )

        elapsed_ms = (time.monotonic() - start) * 1000
        metrics = dict(stage_result.get("metrics", {}))
        metrics["latency_ms"] = elapsed_ms

        return {
            "chat_set_id": chat_set_id,
            "session_id": session_id,
            "outcome_node_id": outcome_node.node_id if outcome_node else None,
            "deliverable_node_ids": deliverable_ids,
            "lesson_node_ids": lesson_ids,
            "drift_node_ids": drift_ids,
            "action_node_ids": action_ids,
            "metrics": metrics,
        }

    # ------------------------------------------------------------------
    # Internal: LLM call
    # ------------------------------------------------------------------

    def _call_llm(self, chat_set_id: str, assistant_text: str) -> dict[str, Any]:
        """Call the LLM and parse the JSON closure payload."""
        import re
        llm_response = self._llm.chat([
            {"role": "system", "content": self._instruction},
            {"role": "user", "content": assistant_text},
        ])

        content = (llm_response.content or "").strip()
        fence_match = re.match(r"^```(?:json)?\s*(.*?)```?\s*$", content, re.DOTALL)
        if fence_match:
            content = fence_match.group(1).strip()

        try:
            result = json.loads(content)
            if not isinstance(result, dict):
                return {
                    "ok": False,
                    "error": f"LLM returned non-object JSON: {type(result).__name__}",
                    "metrics": self._response_metrics(llm_response),
                }
        except (json.JSONDecodeError, ValueError) as exc:
            return {
                "ok": False,
                "error": f"non-JSON response: {content[:200]}",
                "metrics": self._response_metrics(llm_response),
            }

        return {"ok": True, "result": result,
                "metrics": self._response_metrics(llm_response)}

    def _response_metrics(self, llm_response: LLMResponse) -> dict[str, Any]:
        return {
            "model_id": getattr(llm_response, "model_id", "unknown"),
            "prompt_tokens": getattr(llm_response, "prompt_tokens", 0),
            "completion_tokens": getattr(llm_response, "completion_tokens", 0),
            "total_tokens": getattr(llm_response, "total_tokens", 0),
            "latency_ms": 0.0,
        }

    # ------------------------------------------------------------------
    # Internal: Idempotency
    # ------------------------------------------------------------------

    def _find_existing_outcome(self, chat_set_id: str) -> Optional[Any]:
        """Find a pre-existing OutcomeNode for this ChatSet.

        Outcome nodes are definitive and immutable — we reuse them.
        """
        for node in self._soma.query_by_type("OutcomeNode"):
            if node.properties.get("chat_set_id") == chat_set_id:
                return node
        return None

    # ------------------------------------------------------------------
    # Internal: Node writers
    # ------------------------------------------------------------------

    def _write_outcome_node(
        self, chat_set_id: str, session_id: str, outcome_text: str
    ) -> Optional[str]:
        """Write the OutcomeNode. Returns node_id or None on failure."""
        if self._cached_outcome_id:
            return self._cached_outcome_id
        existing = self._find_existing_outcome(chat_set_id)
        if existing is not None:
            return existing.node_id

        node = self._soma.create_node("OutcomeNode", {
            "id": f"outcome-{chat_set_id}",
            "outcome_text": outcome_text,
            "session_id": session_id,
            "chat_set_id": chat_set_id,
            "immutable": True,
            "created_at": time.time(),
        })
        self._cached_outcome_id = node.node_id
        return node.node_id

    def _write_deliverable_nodes(
        self,
        chat_set_id: str,
        session_id: str,
        deliverables: list[dict[str, Any]],
    ) -> tuple[list[str], list[str]]:
        """Write DeliverableNode records. Returns (all_ids, created_ids)."""
        ids: list[str] = []
        created: list[str] = []
        for idx, d in enumerate(deliverables):
            err = validate_deliverable(d)
            if err:
                logger.warning("Skipping invalid deliverable: %s", err)
                continue
            node = self._soma.create_node("DeliverableNode", {
                "id": f"deliverable-{chat_set_id}-{idx}",
                "deliverable_text": str(d["deliverable_text"]),
                "source_outcome_id": f"outcome-{chat_set_id}",
                "session_id": session_id,
                "chat_set_id": chat_set_id,
            })
            ids.append(node.node_id)
            created.append(node.node_id)
        return ids, created

    def _write_lesson_nodes(
        self,
        chat_set_id: str,
        session_id: str,
        lessons: list[dict[str, Any]],
    ) -> tuple[list[str], list[str]]:
        """Write LessonNode records. Returns (all_ids, created_ids)."""
        ids: list[str] = []
        created: list[str] = []
        for idx, l in enumerate(lessons):
            err = validate_lesson(l)
            if err:
                logger.warning("Skipping invalid lesson: %s", err)
                continue
            node = self._soma.create_node("LessonNode", {
                "id": f"lesson-{chat_set_id}-{idx}",
                "lesson_text": str(l["lesson_text"]),
                "source_outcome_id": f"outcome-{chat_set_id}",
                "session_id": session_id,
                "chat_set_id": chat_set_id,
            })
            ids.append(node.node_id)
            created.append(node.node_id)
        return ids, created

    def _write_drift_nodes(
        self,
        chat_set_id: str,
        session_id: str,
        drifts: list[dict[str, Any]],
    ) -> tuple[list[str], list[str]]:
        """Write DriftNode records. Returns (all_ids, created_ids)."""
        ids: list[str] = []
        created: list[str] = []
        for idx, d in enumerate(drifts):
            err = validate_drift(d)
            if err:
                logger.warning("Skipping invalid drift: %s", err)
                continue
            drift_type = str(d.get("drift_type", "unknown"))
            node = self._soma.create_node("DriftNode", {
                "id": f"drift-{chat_set_id}-{idx}",
                "drift_description": str(d["drift_description"]),
                "from_node": str(d["from_node"]),
                "to_node": str(d["to_node"]),
                "drift_type": drift_type,
                "session_id": session_id,
                "chat_set_id": chat_set_id,
            })
            ids.append(node.node_id)
            created.append(node.node_id)
        return ids, created

    def _write_action_nodes(
        self,
        chat_set_id: str,
        session_id: str,
        actions: list[dict[str, Any]],
    ) -> tuple[list[str], list[str]]:
        """Write ActionNode records. Returns (all_ids, created_ids)."""
        ids: list[str] = []
        created: list[str] = []
        for idx, a in enumerate(actions):
            err = validate_action(a)
            if err:
                logger.warning("Skipping invalid action: %s", err)
                continue
            node = self._soma.create_node("ActionNode", {
                "id": f"action-{chat_set_id}-{idx}",
                "action_text": str(a["action_text"]),
                "assigned_to": str(a["assigned_to"]),
                "status": "open",
                "session_id": session_id,
                "chat_set_id": chat_set_id,
            })
            ids.append(node.node_id)
            created.append(node.node_id)
        return ids, created

    # ------------------------------------------------------------------
    # Internal: Edge creation
    # ------------------------------------------------------------------

    def _create_closure_edges(
        self,
        chat_set_id: str,
        outcome_id: str,
        created_deliverable_ids: list[str],
        created_lesson_ids: list[str],
        created_drift_ids: list[str],
        created_action_ids: list[str],
    ) -> None:
        """Create physical edges in the Soma graph."""
        # OutcomeNode -> TRIGGERED_BY -> ChatSet
        self._soma.create_edge(outcome_id, "TRIGGERED_BY", chat_set_id)

        # OutcomeNode -> PRODUCES -> each DeliverableNode
        for did in created_deliverable_ids:
            self._soma.create_edge(outcome_id, "PRODUCES", did)

        # OutcomeNode -> LEARNS -> each LessonNode
        for lid in created_lesson_ids:
            self._soma.create_edge(outcome_id, "LEARNS", lid)

        # DriftNode -> DRIFTS_FROM -> from_node
        for node in self._soma.query_by_type("DriftNode"):
            if node.properties.get("chat_set_id") == chat_set_id:
                from_node_id = node.properties.get("from_node", "")
                if from_node_id:
                    self._soma.create_edge(node.node_id, "DRIFTS_FROM", from_node_id)

        # ActionNode -> ASSIGNED_TO -> assigned_to target
        for node in self._soma.query_by_type("ActionNode"):
            if node.properties.get("chat_set_id") == chat_set_id:
                assigned = node.properties.get("assigned_to", "")
                if assigned:
                    self._soma.create_edge(node.node_id, "ASSIGNED_TO", assigned)

    # ------------------------------------------------------------------
    # Result helpers
    # ------------------------------------------------------------------

    def _cached_result(
        self, chat_set_id: str, session_id: str, outcome_id: str, start: float
    ) -> dict[str, Any]:
        """Return cached result when OutcomeNode already exists."""
        deliverables = [n for n in self._soma.query_by_type("DeliverableNode")
                        if n.properties.get("source_outcome_id") == outcome_id]
        lessons = [n for n in self._soma.query_by_type("LessonNode")
                   if n.properties.get("source_outcome_id") == outcome_id]
        drifts = [n for n in self._soma.query_by_type("DriftNode")
                  if n.properties.get("chat_set_id") == chat_set_id]
        actions = [n for n in self._soma.query_by_type("ActionNode")
                   if n.properties.get("chat_set_id") == chat_set_id]

        return {
            "chat_set_id": chat_set_id,
            "session_id": session_id,
            "outcome_node_id": outcome_id,
            "deliverable_node_ids": [n.node_id for n in deliverables],
            "lesson_node_ids": [n.node_id for n in lessons],
            "drift_node_ids": [n.node_id for n in drifts],
            "action_node_ids": [n.node_id for n in actions],
            "cached": True,
            "metrics": {
                "model_id": "unknown", "prompt_tokens": 0,
                "completion_tokens": 0, "total_tokens": 0,
                "latency_ms": (time.monotonic() - start) * 1000,
            },
        }

    def _failure_result(
        self,
        chat_set_id: str,
        session_id: str,
        stage_result: dict[str, Any],
        start: float,
    ) -> dict[str, Any]:
        return {
            "error": stage_result.get("error", "LLM call failed"),
            "chat_set_id": chat_set_id,
            "session_id": session_id,
            "outcome_node_id": None,
            "deliverable_node_ids": [],
            "lesson_node_ids": [],
            "drift_node_ids": [],
            "action_node_ids": [],
            "metrics": stage_result.get("metrics", {}),
        }
