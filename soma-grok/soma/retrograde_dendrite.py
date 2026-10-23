"""TB-DEND-020: Retrograde Dendrite (FIXED — stage_name → "retrograde").

Logs deliverables, drift, next actions, and lessons learned for a single
ChatSet as OutcomeNode plus closure nodes via LLM.
"""
from __future__ import annotations

import time
from typing import Any

from store import Soma
from soma.helpers import get_receptor_config
from pipeline.stage_complete import complete_stage


_DEFAULT_RETROGRADE_INSTRUCTION = (
    "You are the Retrograde Dendrite. Review the assistant response below "
    "and return a JSON object with these optional keys:\n"
    '  "outcome": {"outcome_text": str}\n'
    '  "deliverables": array of {"deliverable_text": str}\n'
    '  "unresolved": array of {"unresolved_text": str}\n'
    '  "lessons": array of {"lesson_text": str}\n'
    '  "drifts": array of {"drift_text": str, "from_node": str, "to_node": str}\n'
    '  "actions": array of {"action_text": str, "assignee": str}\n'
    "Return ONLY the JSON object. No prose, no markdown, no explanation."
)


class RetrogradeDendrite:
    """Active Retrograde — outcome logging for one ChatSet."""

    def __init__(self, soma: Soma, llm_client: Any) -> None:
        self._soma = soma
        self._llm = llm_client

    def _extract_text(self, item: Any, key: str) -> str:
        """Extract text from item which may be a string or a dict with *key*."""
        if isinstance(item, str):
            return item
        if isinstance(item, dict):
            return str(item.get(key, ""))
        return ""

    def run(self, chat_set_id: str) -> dict[str, Any]:
        """Create an OutcomeNode summarising the turn via LLM."""
        start = time.monotonic()
        # FIXED: "retrograde" instead of undefined stage_name
        stage_name = "retrograde"

        cs = self._soma.get_node(chat_set_id)
        if cs is None or cs.node_type != "ChatSet":
            return {"error": f"ChatSet not found: {chat_set_id}"}

        session_id = cs.properties.get("session_id", "")

        # Idempotent: if outcome already exists, short-circuit
        outcome_id = f"outcome-{chat_set_id}"
        existing = self._soma.get_node(outcome_id)
        if existing:
            elapsed_ms = (time.monotonic() - start) * 1000
            return {
                "chat_set_id": chat_set_id,
                "outcome_node_id": outcome_id,
                "task_count": 0,
                "deliverable_count": 0,
                "lessons_promoted": 0,
                "metrics": {
                    "model_id": "unknown",
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                    "latency_ms": elapsed_ms,
                },
            }

        # Payload is assistant_text
        assistant_text = str(cs.properties.get("assistant_text", "")).strip()
        payload = assistant_text or "(no assistant response)"

        # Load ReceptorConfig instruction body
        config = get_receptor_config(self._soma, "retrograde")
        instruction_body = (
            config.get("instruction_body", _DEFAULT_RETROGRADE_INSTRUCTION)
            if config else _DEFAULT_RETROGRADE_INSTRUCTION
        )

        # Call complete_stage
        stage_result = complete_stage(
            self._llm, stage_name, instruction_body, payload,
        )

        if not stage_result["ok"]:
            # Fallback: create a minimal OutcomeNode
            outcome_text = assistant_text[:500] if assistant_text else "No outcome extracted"
            self._soma.create_node("OutcomeNode", {
                "id": outcome_id,
                "session_id": session_id,
                "chat_set_id": chat_set_id,
                "outcome_text": outcome_text,
            })
            self._soma.create_edge(chat_set_id, "TRIGGERED_BY", outcome_id)
            return {
                "chat_set_id": chat_set_id,
                "outcome_node_id": outcome_id,
                "task_count": 0,
                "deliverable_count": 0,
                "lessons_promoted": 0,
                "metrics": stage_result["metrics"],
            }

        result = stage_result["result"]
        outcome_data = result.get("outcome", {})
        if not isinstance(outcome_data, dict):
            outcome_data = {"outcome_text": str(outcome_data)}

        outcome_text = outcome_data.get("outcome_text", "")
        if not outcome_text:
            outcome_text = assistant_text[:500] if assistant_text else "No outcome extracted"

        self._soma.create_node("OutcomeNode", {
            "id": outcome_id,
            "session_id": session_id,
            "chat_set_id": chat_set_id,
            "outcome_text": outcome_text,
        })
        self._soma.create_edge(chat_set_id, "TRIGGERED_BY", outcome_id)

        deliverable_count = 0
        lessons_promoted = 0

        # -- DeliverableNodes --
        deliverables = result.get("deliverables", [])
        if isinstance(deliverables, dict):
            deliverables = [deliverables]
        for i, d in enumerate(deliverables):
            del_id = f"deliverable-{chat_set_id}-{i}"
            existing_d = self._soma.get_node(del_id)
            if existing_d:
                continue
            self._soma.create_node("DeliverableNode", {
                "id": del_id,
                "session_id": session_id,
                "chat_set_id": chat_set_id,
                "deliverable_text": self._extract_text(d, "deliverable_text"),
            })
            self._soma.create_edge(outcome_id, "PRODUCES", del_id)
            deliverable_count += 1

        # -- LessonNodes --
        lessons = result.get("lessons", [])
        if isinstance(lessons, dict):
            lessons = [lessons]
        for i, l in enumerate(lessons):
            lesson_id = f"lesson-{chat_set_id}-{i}"
            existing_l = self._soma.get_node(lesson_id)
            if existing_l:
                continue
            self._soma.create_node("LessonNode", {
                "id": lesson_id,
                "session_id": session_id,
                "chat_set_id": chat_set_id,
                "lesson_text": self._extract_text(l, "lesson_text"),
            })
            self._soma.create_edge(outcome_id, "LEARNS", lesson_id)
            lessons_promoted += 1

        # -- DriftNodes --
        drifts = result.get("drifts", [])
        if isinstance(drifts, dict):
            drifts = [drifts]
        for i, d in enumerate(drifts):
            drift_id = f"drift-{chat_set_id}-{i}"
            existing_d = self._soma.get_node(drift_id)
            if existing_d:
                continue
            self._soma.create_node("DriftNode", {
                "id": drift_id,
                "session_id": session_id,
                "chat_set_id": chat_set_id,
                "drift_text": self._extract_text(d, "drift_text"),
            })
            from_node = d.get("from_node") if isinstance(d, dict) else None
            to_node = d.get("to_node") if isinstance(d, dict) else None
            if from_node and self._soma.get_node(from_node):
                self._soma.create_edge(drift_id, "DRIFTS_FROM", from_node)
            if to_node and self._soma.get_node(to_node):
                self._soma.create_edge(drift_id, "DRIFTS_TO", to_node)

        # -- ActionNodes --
        actions = result.get("actions", [])
        if isinstance(actions, dict):
            actions = [actions]
        for i, a in enumerate(actions):
            action_id = f"action-{chat_set_id}-{i}"
            existing_a = self._soma.get_node(action_id)
            if existing_a:
                continue
            self._soma.create_node("ActionNode", {
                "id": action_id,
                "session_id": session_id,
                "chat_set_id": chat_set_id,
                "action_text": self._extract_text(a, "action_text"),
                "assignee": a.get("assignee", "") if isinstance(a, dict) else "",
            })
            self._soma.create_edge(outcome_id, "ASSIGNED_TO", action_id)

        # -- UnresolvedNodes --
        unresolved = result.get("unresolved", [])
        if isinstance(unresolved, dict):
            unresolved = [unresolved]
        for i, u in enumerate(unresolved):
            unres_id = f"unresolved-{chat_set_id}-{i}"
            existing_u = self._soma.get_node(unres_id)
            if existing_u:
                continue
            self._soma.create_node("UnresolvedNode", {
                "id": unres_id,
                "session_id": session_id,
                "chat_set_id": chat_set_id,
                "unresolved_text": self._extract_text(u, "unresolved_text"),
            })

        return {
            "chat_set_id": chat_set_id,
            "outcome_node_id": outcome_id,
            "task_count": 0,
            "deliverable_count": deliverable_count,
            "lessons_promoted": lessons_promoted,
            "metrics": stage_result["metrics"],
        }