"""TB-DEND-021: SPARK Dendrite (FIXED — stage_name → "spark").

Derives a RequirementsNode from the session's StrategicBlueprintNode via LLM.
"""
from __future__ import annotations

import time
from typing import Any

from store import Soma
from soma.helpers import get_receptor_config
from pipeline.stage_complete import complete_stage


_DEFAULT_SPARK_INSTRUCTION = (
    "You are the Spark Dendrite. Review the blueprint below and derive "
    "concrete requirements. Return a JSON object:\n"
    '  {"requirement_text": str, "source_blueprint_id": str}\n'
    "Return ONLY the JSON object. No prose, no markdown, no explanation."
)


class SparkDendrite:
    """Active SPARK — requirements derivation."""

    def __init__(self, soma: Soma, llm_client: Any) -> None:
        self._soma = soma
        self._llm = llm_client

    def run(self, session_id: str) -> dict[str, Any]:
        """Create a RequirementsNode via LLM."""
        start = time.monotonic()
        # FIXED: "spark" instead of undefined stage_name
        stage_name = "spark"

        blueprints = [
            n for n in self._soma.query_by_type("StrategicBlueprintNode")
            if n.properties.get("session_id") == session_id
        ]
        if not blueprints:
            elapsed_ms = (time.monotonic() - start) * 1000
            return {
                "session_id": session_id,
                "error": "No StrategicBlueprintNode found",
                "metrics": {
                    "model_id": "unknown",
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                    "latency_ms": elapsed_ms,
                },
            }

        blueprint = blueprints[0]
        payload = blueprint.properties.get("blueprint_text", "")

        # Load ReceptorConfig instruction body
        config = get_receptor_config(self._soma, "spark")
        instruction_body = (
            config.get("instruction_body", _DEFAULT_SPARK_INSTRUCTION)
            if config else _DEFAULT_SPARK_INSTRUCTION
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
        requirement_text = result.get("requirement_text", "")
        if not requirement_text:
            requirement_text = payload

        requirements_id = f"req-{session_id}"
        # Overwrite: delete existing requirements before creating fresh one
        existing = self._soma.get_node(requirements_id)
        if existing:
            self._soma.delete_node(requirements_id)
        self._soma.create_node("RequirementsNode", {
            "id": requirements_id,
            "session_id": session_id,
            "requirement_text": requirement_text,
            "source_blueprint_id": result.get("source_blueprint_id", blueprint.id),
        })
        # LINEAGE: link requirements back to blueprint
        self._soma.create_edge(requirements_id, "DERIVED_FROM", blueprint.id)

        return {
            "session_id": session_id,
            "requirements_id": requirements_id,
            "source_blueprint_id": blueprint.id,
            "metrics": stage_result["metrics"],
        }