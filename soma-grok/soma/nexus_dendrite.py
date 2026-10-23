"""TB-DEND-021: NEXUS Dendrite (FIXED — stage_name → "nexus").

Synthesises a StrategicBlueprintNode from the session's DirectiveNode and
ConstraintNode signals via LLM.
"""
from __future__ import annotations

import time
from typing import Any

from store import Soma
from soma.helpers import get_receptor_config
from pipeline.stage_complete import complete_stage


_DEFAULT_NEXUS_INSTRUCTION = (
    "You are the Nexus Dendrite. Review the directives and constraints "
    "below and synthesise a strategic blueprint. Return a JSON object:\n"
    '  {"blueprint_text": str, "directives_used": int, "constraints_used": int}\n'
    "Return ONLY the JSON object. No prose, no markdown, no explanation."
)


class NexusDendrite:
    """Active NEXUS — strategic blueprint synthesis."""

    def __init__(self, soma: Soma, llm_client: Any) -> None:
        self._soma = soma
        self._llm = llm_client

    def run(self, session_id: str) -> dict[str, Any]:
        """Create a StrategicBlueprintNode via LLM."""
        start = time.monotonic()
        # FIXED: "nexus" instead of undefined stage_name
        stage_name = "nexus"

        directives = [
            n for n in self._soma.query_by_type("DirectiveNode")
            if n.properties.get("session_id") == session_id
        ]
        constraints = [
            n for n in self._soma.query_by_type("ConstraintNode")
            if n.properties.get("session_id") == session_id
        ]

        # Build payload from signal source text
        parts: list[str] = []
        for d in directives:
            parts.append(d.properties.get("source_text", ""))
        for c in constraints:
            parts.append(c.properties.get("source_text", ""))
        payload = "\n".join(p for p in parts if p) or f"Session {session_id}: no directive or constraint signals"

        # Load ReceptorConfig instruction body
        config = get_receptor_config(self._soma, "nexus")
        instruction_body = (
            config.get("instruction_body", _DEFAULT_NEXUS_INSTRUCTION)
            if config else _DEFAULT_NEXUS_INSTRUCTION
        )

        # Call complete_stage
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
        blueprint_text = result.get("blueprint_text", "")
        if not blueprint_text:
            blueprint_text = payload

        blueprint_id = f"blueprint-{session_id}"
        # Overwrite: delete existing blueprint before creating fresh one
        existing = self._soma.get_node(blueprint_id)
        if existing:
            self._soma.delete_node(blueprint_id)
        self._soma.create_node("StrategicBlueprintNode", {
            "id": blueprint_id,
            "session_id": session_id,
            "blueprint_text": blueprint_text,
            "directive_count": result.get("directives_used", len(directives)),
            "constraint_count": result.get("constraints_used", len(constraints)),
        })
        # LINEAGE: link blueprint back to its input signals
        for d in directives:
            self._soma.create_edge(blueprint_id, "STRATEGIC_PLAN", d.id)
        for c in constraints:
            self._soma.create_edge(blueprint_id, "CONSTRAINED_BY", c.id)

        return {
            "session_id": session_id,
            "blueprint_id": blueprint_id,
            "directive_count": len(directives),
            "constraint_count": len(constraints),
            "metrics": stage_result["metrics"],
        }