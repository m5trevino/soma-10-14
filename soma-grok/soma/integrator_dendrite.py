"""TB-TK-REPLACE-003: Integrator Dendrite — synthesises sequenced TaskNodes from classified signals.

Reads signal nodes linked to a ChatSet, calls the LLM to produce tasks/risks/decisions/stack
items, writes TaskNode/RiskNode/DecisionNode/StackNode records into Soma, and links them
with physical edges (REQUIRES_ACTION, INTRODUCES_RISK, ADDRESSES).

Hard gates:
  - Must NOT access physical files on disk
  - Must consume signal nodes created by ClassifierDendrite, NOT raw chat logs
  - Must produce idempotent output (no duplicate TaskNode on retry)
"""
from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, Optional

from store import Soma
from pipeline.drafter_dendrite import LLMClient, LLMResponse, MockLLMClient

logger = logging.getLogger(__name__)

# Configure console output for token usage and latency metrics
if not logger.handlers:
    _console_handler = logging.StreamHandler()
    _console_handler.setLevel(logging.INFO)
    _console_handler.setFormatter(
        logging.Formatter("%(levelname)s [integrator_dendrite] %(message)s")
    )
    logger.addHandler(_console_handler)
logger.setLevel(logging.INFO)

# ---------------------------------------------------------------------------
# Output node types and their required / optional keys
# ---------------------------------------------------------------------------

_OUTPUT_NODE_TYPES = frozenset({
    "TaskNode",
    "RiskNode",
    "DecisionNode",
    "StackNode",
})

# ---------------------------------------------------------------------------
# Default LLM instruction
# ---------------------------------------------------------------------------

_INTEGRATOR_INSTRUCTION = (
    "You are the Integrator Dendrite. Given the classified signals below, "
    "synthesize an ordered plan of tasks, risks, decisions, and stack items. "
    "Return a JSON object with exactly these keys:\n"
    '  "tasks": [{ "task_text": str, "priority": "HIGH"|"MEDIUM"|"LOW" }]\n'
    '  "risks": [{ "risk_text": str, "severity": "HIGH"|"MEDIUM"|"LOW" }]\n'
    '  "decisions": [{ "decision_text": str, "rationale": str }]\n'
    '  "stack": [{ "stack_text": str, "role": str }]\n'
    "Return ONLY the JSON object. No prose, no markdown, no explanation."
)

# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

_VALID_PRIORITIES = frozenset({"HIGH", "MEDIUM", "LOW"})
_VALID_SEVERITIES = frozenset({"HIGH", "MEDIUM", "LOW"})


def _validate_task(task: dict[str, Any]) -> Optional[str]:
    """Return error string if task dict is malformed."""
    if "task_text" not in task:
        return "task missing task_text"
    priority = task.get("priority", "MEDIUM").upper()
    if priority not in _VALID_PRIORITIES:
        return f"invalid priority: {task.get('priority')!r}"
    return None


def _validate_risk(risk: dict[str, Any]) -> Optional[str]:
    if "risk_text" not in risk:
        return "risk missing risk_text"
    severity = risk.get("severity", "LOW").upper()
    if severity not in _VALID_SEVERITIES:
        return f"invalid severity: {risk.get('severity')!r}"
    return None


def _validate_decision(dec: dict[str, Any]) -> Optional[str]:
    if "decision_text" not in dec:
        return "decision missing decision_text"
    if "rationale" not in dec:
        return "decision missing rationale"
    return None


def _validate_stack_item(item: dict[str, Any]) -> Optional[str]:
    if "stack_text" not in item:
        return "stack item missing stack_text"
    if "role" not in item:
        return "stack item missing role"
    return None


# ---------------------------------------------------------------------------
# Core integration logic
# ---------------------------------------------------------------------------


class IntegratorDendrite:
    """Synthesises TaskNode, RiskNode, DecisionNode, StackNode from classified signal nodes."""

    def __init__(
        self,
        soma: Soma,
        llm_client: Optional[LLMClient] = None,
        instruction: Optional[str] = None,
    ) -> None:
        self._soma = soma
        self._llm = llm_client or MockLLMClient()
        self._instruction = (
            instruction
            if instruction is not None
            else _INTEGRATOR_INSTRUCTION
        )
        # Per-run metrics accumulator
        self._metrics: dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self, chat_set_id: str) -> dict[str, Any]:
        """Process one ChatSet: read signals, synthesize plan, write output nodes.

        Returns dict with:
          - chat_set_id
          - task_node_ids, risk_node_ids, decision_node_ids, stack_node_ids
          - metrics (tokens, latency)
        """
        start = time.monotonic()

        cs = self._soma.get_node(chat_set_id)
        if cs is None or cs.node_type != "ChatSet":
            return {"error": f"ChatSet not found: {chat_set_id}"}

        session_id = cs.properties.get("session_id", "")

        # Step 1: collect signal node IDs linked to this ChatSet
        signal_ids = self._collect_signal_ids(chat_set_id)
        if not signal_ids:
            # No signals — nothing to integrate. Return empty result.
            return self._empty_result(chat_set_id, session_id, start)

        # Step 2: fetch the source text for each signal (for the LLM prompt)
        signal_payload = self._build_signal_payload(signal_ids)

        # Step 3: LLM synthesis call
        stage_result = self._call_llm(chat_set_id, signal_payload)

        if not stage_result["ok"]:
            return self._failure_result(chat_set_id, session_id, stage_result, start)

        # Step 4: write output nodes and edges (only create for NEW nodes)
        result = stage_result["result"]
        task_ids, created_task_ids = self._write_task_nodes(
            chat_set_id, session_id, result.get("tasks", []), signal_ids)
        risk_ids, created_risk_ids = self._write_risk_nodes(
            chat_set_id, session_id, result.get("risks", []), signal_ids)
        decision_ids, created_decision_ids = self._write_decision_nodes(
            chat_set_id, session_id, result.get("decisions", []))
        stack_ids, created_stack_ids = self._write_stack_nodes(
            chat_set_id, session_id, result.get("stack", []))

        # Step 5: create linkage edges — only for newly created nodes
        self._create_linkage_edges(
            chat_set_id, session_id, created_task_ids, created_risk_ids,
            signal_ids, created_decision_ids, created_stack_ids,
        )

        elapsed_ms = (time.monotonic() - start) * 1000
        metrics = dict(stage_result.get("metrics", {}))
        metrics["latency_ms"] = elapsed_ms

        # Log token usage and latency to console
        self._log_metrics(metrics, len(task_ids), len(risk_ids),
                          len(decision_ids), len(stack_ids))

        return {
            "chat_set_id": chat_set_id,
            "session_id": session_id,
            "task_node_ids": task_ids,
            "risk_node_ids": risk_ids,
            "decision_node_ids": decision_ids,
            "stack_node_ids": stack_ids,
            "metrics": metrics,
        }

    def _log_metrics(
        self,
        metrics: dict[str, Any],
        task_count: int,
        risk_count: int,
        decision_count: int,
        stack_count: int,
    ) -> None:
        """Log token usage and latency to console."""
        prompt_tokens = metrics.get("prompt_tokens", 0)
        completion_tokens = metrics.get("completion_tokens", 0)
        total_tokens = metrics.get("total_tokens", 0)
        latency_ms = metrics.get("latency_ms", 0.0)
        model_id = metrics.get("model_id", "unknown")

        logger.info(
            "integrator_dendrite run complete — model=%s tokens(total=%d prompt=%d "
            "completion=%d) latency=%.1fms nodes(task=%d risk=%d decision=%d stack=%d)",
            model_id, total_tokens, prompt_tokens, completion_tokens,
            latency_ms, task_count, risk_count, decision_count, stack_count,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _collect_signal_ids(self, chat_set_id: str) -> list[str]:
        """Return signal node IDs linked to *chat_set_id* via EXTRACTED_FROM edges.

        Must NOT read raw chat logs — only signal nodes produced by ClassifierDendrite.
        """
        edges = self._soma.get_edges(chat_set_id)
        signal_ids: list[str] = []
        for edge in edges:
            if edge.rel_type == "EXTRACTED_FROM":
                target = edge.target
                node = self._soma.get_node(target)
                if node and node.node_type in (
                    "IntentNode", "DirectiveNode", "ConstraintNode",
                    "QuestionNode", "PreferenceNode", "CorrectionNode", "NoiseNode",
                ):
                    signal_ids.append(target)
        return signal_ids

    def _build_signal_payload(self, signal_ids: list[str]) -> str:
        """Assemble a JSON payload of signal summaries for the LLM prompt."""
        signals: list[dict[str, Any]] = []
        for nid in signal_ids:
            node = self._soma.get_node(nid)
            if node:
                signals.append({
                    "id": nid,
                    "type": node.node_type,
                    "source_text": node.properties.get("source_text", ""),
                    "confidence": node.properties.get("confidence", 0.0),
                    "rationale": node.properties.get("rationale", ""),
                })
        return json.dumps(signals, indent=2)

    def _call_llm(self, chat_set_id: str, signal_payload: str) -> dict[str, Any]:
        """Call the LLM and parse JSON response."""
        llm_response = self._llm.chat([
            {"role": "system", "content": self._instruction},
            {"role": "user", "content": signal_payload},
        ])

        content = (llm_response.content or "").strip()
        # Strip markdown fences if present
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

        return {"ok": True, "result": result, "metrics": self._response_metrics(llm_response)}

    def _response_metrics(self, llm_response: LLMResponse) -> dict[str, Any]:
        return {
            "model_id": getattr(llm_response, "model_id", "unknown"),
            "prompt_tokens": getattr(llm_response, "prompt_tokens", 0),
            "completion_tokens": getattr(llm_response, "completion_tokens", 0),
            "total_tokens": getattr(llm_response, "total_tokens", 0),
            "latency_ms": 0.0,
        }

    # ------------------------------------------------------------------
    # Node writers (idempotent)
    # ------------------------------------------------------------------

    def _write_task_nodes(
        self,
        chat_set_id: str,
        session_id: str,
        tasks: list[dict[str, Any]],
        source_signal_ids: list[str],
    ) -> tuple[list[str], list[str]]:
        """Write TaskNode records. Skips duplicates (idempotent).

        Returns (all_ids, created_ids) — created_ids are only those newly written.
        """
        ids: list[str] = []
        created: list[str] = []
        for seq, task in enumerate(tasks, start=1):
            err = _validate_task(task)
            if err:
                logger.warning("Skipping invalid task: %s", err)
                continue

            # Idempotency: skip if a TaskNode with this text already exists
            existing = self._find_existing_task(str(task["task_text"]))
            if existing is not None:
                ids.append(existing.node_id)
                continue

            priority = str(task.get("priority", "MEDIUM")).upper()

            node = self._soma.create_node("TaskNode", {
                "id": f"task-{chat_set_id}-{seq}",
                "task_text": str(task["task_text"]),
                "sequence_number": seq,
                "priority": priority,
                "source_signal_ids": json.dumps(source_signal_ids),
                "session_id": session_id,
                "chat_set_id": chat_set_id,
            })
            ids.append(node.node_id)
            created.append(node.node_id)

        return ids, created

    def _write_risk_nodes(
        self,
        chat_set_id: str,
        session_id: str,
        risks: list[dict[str, Any]],
        source_signal_ids: list[str],
    ) -> tuple[list[str], list[str]]:
        """Write RiskNode records. Skips duplicates (idempotent).

        Returns (all_ids, created_ids).
        """
        ids: list[str] = []
        created: list[str] = []
        for idx, risk in enumerate(risks):
            err = _validate_risk(risk)
            if err:
                logger.warning("Skipping invalid risk: %s", err)
                continue

            existing = self._find_existing_risk(str(risk["risk_text"]))
            if existing is not None:
                ids.append(existing.node_id)
                continue

            severity = str(risk.get("severity", "LOW")).upper()

            node = self._soma.create_node("RiskNode", {
                "id": f"risk-{chat_set_id}-{idx}",
                "risk_text": str(risk["risk_text"]),
                "severity": severity,
                "source_signal_ids": json.dumps(source_signal_ids),
                "session_id": session_id,
                "chat_set_id": chat_set_id,
            })
            ids.append(node.node_id)
            created.append(node.node_id)

        return ids, created

    def _write_decision_nodes(
        self,
        chat_set_id: str,
        session_id: str,
        decisions: list[dict[str, Any]],
    ) -> tuple[list[str], list[str]]:
        """Write DecisionNode records.

        Returns (all_ids, created_ids).
        """
        ids: list[str] = []
        created: list[str] = []
        for idx, dec in enumerate(decisions):
            err = _validate_decision(dec)
            if err:
                logger.warning("Skipping invalid decision: %s", err)
                continue

            existing = self._find_existing_decision(str(dec["decision_text"]))
            if existing is not None:
                ids.append(existing.node_id)
                continue

            node = self._soma.create_node("DecisionNode", {
                "id": f"decision-{chat_set_id}-{idx}",
                "decision_text": str(dec["decision_text"]),
                "rationale": str(dec.get("rationale", "")),
                "session_id": session_id,
                "chat_set_id": chat_set_id,
            })
            ids.append(node.node_id)
            created.append(node.node_id)

        return ids, created

    def _write_stack_nodes(
        self,
        chat_set_id: str,
        session_id: str,
        stack_items: list[dict[str, Any]],
    ) -> tuple[list[str], list[str]]:
        """Write StackNode records.

        Returns (all_ids, created_ids).
        """
        ids: list[str] = []
        created: list[str] = []
        for idx, item in enumerate(stack_items):
            err = _validate_stack_item(item)
            if err:
                logger.warning("Skipping invalid stack item: %s", err)
                continue

            existing = self._find_existing_stack(str(item["stack_text"]))
            if existing is not None:
                ids.append(existing.node_id)
                continue

            node = self._soma.create_node("StackNode", {
                "id": f"stack-{chat_set_id}-{idx}",
                "stack_text": str(item["stack_text"]),
                "role": str(item.get("role", "")),
                "dependencies": json.dumps(item.get("dependencies", [])),
                "session_id": session_id,
                "chat_set_id": chat_set_id,
            })
            ids.append(node.node_id)
            created.append(node.node_id)

        return ids, created

    # ------------------------------------------------------------------
    # Idempotency helpers — search by task_text field
    # ------------------------------------------------------------------

    def _find_existing_task(self, task_text: str) -> Optional[Any]:
        existing = self._soma.query_by_type("TaskNode")
        for node in existing:
            if node.properties.get("task_text") == task_text:
                return node
        return None

    def _find_existing_risk(self, risk_text: str) -> Optional[Any]:
        existing = self._soma.query_by_type("RiskNode")
        for node in existing:
            if node.properties.get("risk_text") == risk_text:
                return node
        return None

    def _find_existing_decision(self, decision_text: str) -> Optional[Any]:
        existing = self._soma.query_by_type("DecisionNode")
        for node in existing:
            if node.properties.get("decision_text") == decision_text:
                return node
        return None

    def _find_existing_stack(self, stack_text: str) -> Optional[Any]:
        existing = self._soma.query_by_type("StackNode")
        for node in existing:
            if node.properties.get("stack_text") == stack_text:
                return node
        return None

    # ------------------------------------------------------------------
    # Edge linkage
    # ------------------------------------------------------------------

    def _create_linkage_edges(
        self,
        chat_set_id: str,
        session_id: str,
        created_task_ids: list[str],
        created_risk_ids: list[str],
        signal_ids: list[str],
        created_decision_ids: list[str],
        created_stack_ids: list[str],
    ) -> None:
        """Create physical edges in the Soma graph — only for newly created nodes.

        Edge semantics:
          SessionNode -> REQUIRES_ACTION -> TaskNode (created only)
          SessionNode -> INTRODUCES_RISK -> RiskNode (created only)
          TaskNode -> ADDRESSES -> SignalNode (created only)
        """
        if not created_task_ids and not created_risk_ids:
            return

        # Ensure a SessionNode exists
        session_node_id = self._ensure_session_node(session_id)

        # REQUIRES_ACTION: Session -> each newly created TaskNode
        for task_id in created_task_ids:
            self._soma.create_edge(session_node_id, "REQUIRES_ACTION", task_id)

        # INTRODUCES_RISK: Session -> each newly created RiskNode
        for risk_id in created_risk_ids:
            self._soma.create_edge(session_node_id, "INTRODUCES_RISK", risk_id)

        # ADDRESSES: each newly created TaskNode -> its source signal nodes
        for task_id in created_task_ids:
            for signal_id in signal_ids:
                self._soma.create_edge(task_id, "ADDRESSES", signal_id)

    def _ensure_session_node(self, session_id: str) -> str:
        """Return the session node ID, creating a placeholder SessionNode if needed."""
        session_node = self._soma.get_node(f"session-{session_id}")
        if session_node is not None:
            return session_node.node_id

        self._soma.create_node("SessionNode", {
            "id": f"session-{session_id}",
            "session_id": session_id,
        })
        return f"session-{session_id}"

    # ------------------------------------------------------------------
    # Result helpers
    # ------------------------------------------------------------------

    def _empty_result(
        self, chat_set_id: str, session_id: str, start: float
    ) -> dict[str, Any]:
        return {
            "chat_set_id": chat_set_id,
            "session_id": session_id,
            "task_node_ids": [],
            "risk_node_ids": [],
            "decision_node_ids": [],
            "stack_node_ids": [],
            "metrics": {
                "model_id": "unknown",
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
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
            "task_node_ids": [],
            "risk_node_ids": [],
            "decision_node_ids": [],
            "stack_node_ids": [],
            "metrics": stage_result.get("metrics", {}),
        }
