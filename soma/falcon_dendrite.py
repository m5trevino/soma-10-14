"""TB-DEND-021: FALCON Dendrite.

Derives an ArchitectureNode from the session's RequirementsNode via LLM,
then builds the ArchitectureContractNode from ConstraintNode signals.

The run() path uses get_receptor_config + complete_stage (TB-009).
Hard gates from TB-FAL-001/002/003 are preserved:
  - ids arch-{session_id} and arch-contract-{session_id}
  - DERIVED_FROM and LOCKS edges
  - CHOSEN/FORBIDDEN keys store/navigation/backend
  - freeze-or-fail if contract cannot lock
  - error if no RequirementsNode
  - metrics tokens not hardcoded 0
  - drafter_dendrite.py untouched
"""
from __future__ import annotations

import re
import time
from typing import Any

from store import Soma
from soma.helpers import get_receptor_config
from pipeline.stage_complete import complete_stage


_DEFAULT_FALCON_INSTRUCTION = (
    "You are the Falcon Dendrite. Review the requirements below and derive "
    "the system architecture. Return a JSON object:\n"
    '  {"architecture_text": str, "source_requirements_id": str}\n'
    "Return ONLY the JSON object. No prose, no markdown, no explanation."
)


class FalconDendrite:
    """Active FALCON — architecture derivation."""

    # Valid keys for CHOSEN lines
    _CHOSEN_KEYS = frozenset(("store", "navigation", "backend"))

    def __init__(self, soma: Soma, llm_client: Any, rotator: Any = None) -> None:
        self._soma = soma
        self._llm = llm_client

    def run(self, session_id: str) -> dict[str, Any]:
        """Create an ArchitectureNode + ArchitectureContractNode.

        Uses get_receptor_config + complete_stage (TB-009).
        Preserves TB-FAL-001/002/003 contract behaviour.
        Returns report with architecture_id, contract_id, and metrics.
        """
        start = time.monotonic()
        stage_name = "falcon"

        requirements = [
            n for n in self._soma.query_by_type("RequirementsNode")
            if n.properties.get("session_id") == session_id
        ]
        if not requirements:
            elapsed_ms = (time.monotonic() - start) * 1000
            return {
                "session_id": session_id,
                "error": "No RequirementsNode found",
                "metrics": {
                    "model_id": "unknown",
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                    "latency_ms": elapsed_ms,
                },
            }

        req = requirements[0]
        payload = req.properties.get("requirement_text", "")

        # TB-009: Load ReceptorConfig instruction body
        config = get_receptor_config(self._soma, "falcon")
        instruction_body = (
            config.get("instruction_body", _DEFAULT_FALCON_INSTRUCTION)
            if config else _DEFAULT_FALCON_INSTRUCTION
        )

        # TB-009: Call complete_stage
        stage_result = complete_stage(
            self._llm, stage_name, instruction_body, payload,
        )

        if not stage_result["ok"]:
            elapsed_ms = (time.monotonic() - start) * 1000
            return {
                "session_id": session_id,
                "error": stage_result["error"],
                "metrics": stage_result["metrics"],
            }

        result = stage_result["result"]
        architecture_text = result.get("architecture_text", "")
        if not architecture_text:
            architecture_text = payload

        architecture_id = f"arch-{session_id}"
        # Overwrite: delete existing architecture before creating fresh one
        existing = self._soma.get_node(architecture_id)
        if existing:
            self._soma.delete_node(existing.node_id)
        self._soma.create_node("ArchitectureNode", {
            "id": architecture_id,
            "session_id": session_id,
            "architecture_text": architecture_text,
            "source_requirements_id": result.get("source_requirements_id", req.node_id),
        })

        # TB-FAL-001: DERIVED_FROM edge Architecture -> Requirements (idempotent)
        for edge in list(self._soma._edges):
            if edge.source == architecture_id and edge.rel_type == "DERIVED_FROM":
                self._soma._edges.remove(edge)
        self._soma.create_edge(architecture_id, "DERIVED_FROM", req.node_id)

        # TB-FIX-001: CONSTRAINED_BY edges Architecture -> ConstraintNode (idempotent)
        self.create_constrained_by(architecture_id, session_id)

        # TB-FAL-003: Build contract from ConstraintNode.source_text
        # (preserved from original implementation — contract is NOT LLM-generated)
        contract_result = self._build_contract_from_constraints(session_id)
        if contract_result.get("error"):
            # Error: do not write contract, do not write LOCKS
            elapsed_ms = (time.monotonic() - start) * 1000
            return {
                "session_id": session_id,
                "architecture_id": architecture_id,
                "source_requirements_id": req.node_id,
                "error": contract_result["error"],
                "metrics": stage_result["metrics"],
            }

        contract_text = contract_result["contract_text"]
        contract_id = f"arch-contract-{session_id}"

        # TB-FAL-002: ArchitectureContractNode + LOCKS edge (idempotent)
        existing_contract = self._soma.get_node(contract_id)
        if existing_contract:
            self._soma.delete_node(contract_id)
        self._soma.create_node("ArchitectureContractNode", {
            "id": contract_id,
            "session_id": session_id,
            "contract_text": contract_text,
        })
        for edge in list(self._soma._edges):
            if edge.source == architecture_id and edge.rel_type == "LOCKS":
                self._soma._edges.remove(edge)
        self._soma.create_edge(architecture_id, "LOCKS", contract_id)

        return {
            "session_id": session_id,
            "architecture_id": architecture_id,
            "source_requirements_id": req.node_id,
            "contract_id": contract_id,
            "metrics": stage_result["metrics"],
        }

    def create_constrained_by(self, architecture_id: str, session_id: str) -> list[str]:
        """Create CONSTRAINED_BY edges from ArchitectureNode to each ConstraintNode in session.

        Idempotent: running twice does not duplicate edges.
        Returns list of created edge IDs.
        """
        # Verify ArchitectureNode exists
        arch_node = self._soma.get_node(architecture_id)
        if not arch_node:
            return []

        # Find all ConstraintNodes for this session
        constraints = [
            n for n in self._soma.query_by_type("ConstraintNode")
            if n.properties.get("session_id") == session_id
        ]

        created_edges = []
        for constraint in constraints:
            # Check if edge already exists
            edge_exists = False
            for edge in self._soma._edges:
                if (edge.source == architecture_id
                    and edge.rel_type == "CONSTRAINED_BY"
                    and edge.target == constraint.node_id):
                    edge_exists = True
                    break
            if not edge_exists:
                edge_id = self._soma.create_edge(architecture_id, "CONSTRAINED_BY", constraint.node_id)
                created_edges.append(edge_id)

        return created_edges

    def _build_contract_from_constraints(self, session_id: str) -> dict[str, Any]:
        """Build contract_text from ConstraintNode.source_text for this session.

        Preserved from original implementation (TB-FAL-003).
        Returns {"contract_text": str} on success, or {"error": str} on failure.
        """
        constraints = [
            n for n in self._soma.query_by_type("ConstraintNode")
            if n.properties.get("session_id") == session_id
        ]
        if not constraints:
            # No constraints stated. Write a default contract and continue.
            # Absence is not an error. A conflict is.
            lines = [f"CHOSEN: {key}=none" for key in ("store", "navigation", "backend")]
            return {"contract_text": "\n".join(lines)}

        # Accumulate CHOSEN and FORBIDDEN from all constraints
        chosen: dict[str, str] = {}  # key -> token
        forbidden: set[str] = set()
        any_signal = False

        # Token pattern: words (alphanumeric + hyphen/underscore)
        token_re = re.compile(r"[A-Za-z0-9_-]+")

        for c in constraints:
            source_text = c.properties.get("source_text", "")
            if not source_text:
                continue

            # Find all words in source_text that could be tokens
            tokens_in_text = set(token_re.findall(source_text))

            # Parse CHOSEN: lines
            for line in source_text.splitlines():
                line = line.strip()
                if line.startswith("CHOSEN:"):
                    any_signal = True
                    rest = line.split(":", 1)[1].strip()
                    # rest is like "store=postgresql"
                    if "=" in rest:
                        key, value = rest.split("=", 1)
                        key = key.strip()
                        value = value.strip()
                        if key in self._CHOSEN_KEYS:
                            # Validate token appears in source_text
                            if value in tokens_in_text or value == "none":
                                if key in chosen and chosen[key] != value:
                                    return {"error": f"Conflicting CHOSEN for {key}: {chosen[key]} vs {value}"}
                                chosen[key] = value
                elif line.startswith("FORBIDDEN:"):
                    any_signal = True
                    parts = line.split(":", 1)
                    if len(parts) >= 2:
                        for token in parts[1].split():
                            token = token.strip()
                            if token in tokens_in_text:
                                forbidden.add(token)

        # Build contract_text lines (defaults to "none" if no CHOSEN/FORBIDDEN found)
        # TB-FAL-003: Make CHOSEN/FORBIDDEN optional with defaults
        lines = []
        for key in ("store", "navigation", "backend"):
            value = chosen.get(key, "none")
            lines.append(f"CHOSEN: {key}={value}")
        if forbidden:
            lines.append(f"FORBIDDEN: {' '.join(sorted(forbidden))}")

        return {"contract_text": "\n".join(lines)}
