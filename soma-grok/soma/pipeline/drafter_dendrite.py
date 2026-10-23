"""Minimal stubs: LLMClient, LLMResponse, ModelRotator.

This is NOT the full 633-line Drafter. Only infrastructure stubs needed by
the 3 Stage-1 dendrites and stage_complete.py.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class LLMResponse:
    model_id: str
    content: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    latency_ms: float = 0.0
    tool_calls: list = field(default_factory=list)


class ModelRotator:
    """Round-robin model selector."""

    def __init__(self, models: list[str]) -> None:
        self._models = models
        self._idx = 0

    def next_model(self, stage_name: str = "") -> str:
        if not self._models:
            return "mock-model"
        m = self._models[self._idx % len(self._models)]
        self._idx += 1
        return m


class LLMClient:
    """Abstract base — subclasses must implement .chat()."""

    def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> LLMResponse:
        raise NotImplementedError("Subclasses must implement chat()")


# ------------------------------------------------------------------
# Mock implementations for tracer-bullet testing
# ------------------------------------------------------------------


class MockLLMClient(LLMClient):
    """Returns pre-programmed responses — no real LLM calls."""

    def __init__(self, responses: list[str] | None = None) -> None:
        """If responses is given, each call pops one. Otherwise cycles a default set."""
        if responses:
            self._responses = iter(responses)
        else:
            self._responses = iter(self._default_responses())

    @staticmethod
    def _default_responses() -> list[str]:
        return [
            # Classifier response (used per ChatSet)
            json.dumps([
                {"signal_type": "IntentNode", "confidence": 0.85, "source_text": "[from chat]", "rationale": "mock"},
                {"signal_type": "DirectiveNode", "confidence": 0.75, "source_text": "[from chat]", "rationale": "mock"},
                {"signal_type": "ConstraintNode", "confidence": 0.70, "source_text": "[from chat]", "rationale": "mock"},
            ]),
            # Integrator response
            json.dumps({
                "tasks": [{"task_text": "mock task", "priority": "MEDIUM"}],
                "risks": [{"risk_text": "mock risk", "severity": "LOW"}],
                "decisions": [{"decision_text": "mock decision", "rationale": "mock"}],
                "stack": [{"stack_text": "mock stack", "role": "mock"}],
            }),
            # Retrograde response
            json.dumps({
                "outcome": {"outcome_text": "mock outcome"},
                "deliverables": [{"deliverable_text": "mock deliverable"}],
                "lessons": [{"lesson_text": "mock lesson"}],
                "drifts": [],
                "actions": [],
                "unresolved": [],
            }),
            # Nexus response
            json.dumps({
                "blueprint_text": "mock blueprint synthesized from directives and constraints",
                "directives_used": 5,
                "constraints_used": 3,
            }),
            # Spark response
            json.dumps({
                "requirement_text": "mock requirement derived from blueprint",
                "source_blueprint_id": "blueprint-mock",
            }),
            # Falcon response
            json.dumps({
                "architecture_text": "mock architecture derived from requirements",
                "source_requirements_id": "req-mock",
            }),
        ]

    def __init__(self) -> None:
        self._call_count = 0

    def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> LLMResponse:
        # Detect which dendrite is calling from the system message
        system = ""
        for m in messages:
            if m.get("role") == "system":
                system = m.get("content", "").lower()
                break

        # Match response type to dendrite instruction
        if "classifier" in system:
            responses = [self._default_responses()[0]] * 6  # classifier response
        elif "integrator" in system:
            responses = [self._default_responses()[1]] * 6  # integrator response
        elif "retrograde" in system:
            responses = [self._default_responses()[2]] * 6  # retrograde response
        elif "nexus" in system:
            responses = [self._default_responses()[3]] * 6  # nexus response
        elif "spark" in system:
            responses = [self._default_responses()[4]] * 6  # spark response
        elif "falcon" in system:
            responses = [self._default_responses()[5]] * 6  # falcon response
        elif "drafter" in system or "architect" in system:
            responses = [json.dumps(["main.py", "config.py", "utils/helpers.py"])] * 6  # drafter: file list
        else:
            responses = self._default_responses()

        content = responses[self._call_count % len(responses)]
        self._call_count += 1
        return LLMResponse(
            model_id=kwargs.get("model", "mock-model"),
            content=content,
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            latency_ms=25.0,
        )


class StrictMockLLMClient(LLMClient):
    """Returns ONLY the responses given — raises on exhaustion."""

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self._idx = 0

    def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> LLMResponse:
        if self._idx >= len(self._responses):
            raise RuntimeError(f"StrictMockLLMClient exhausted: {self._idx}/{len(self._responses)} responses used")
        content = self._responses[self._idx]
        self._idx += 1
        return LLMResponse(
            model_id=kwargs.get("model", "mock-model"),
            content=content,
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            latency_ms=25.0,
        )

class LLMResponseStub:
    """Stub LLMResponse for imports."""
    def __init__(self, model_id="", content="", prompt_tokens=0, completion_tokens=0, total_tokens=0, latency_ms=0.0, tool_calls=None):
        self.model_id = model_id
        self.content = content
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.total_tokens = total_tokens
        self.latency_ms = latency_ms
        self.tool_calls = tool_calls or []


class ToolRegistry:
    """Minimal ToolRegistry for myelinator imports."""
    _SCHEMAS = []

    def __init__(self, soma):
        self._soma = soma

    @classmethod
    def schemas(cls):
        return []

    def call(self, name, arguments):
        return {"ok": False, "error": f"Tool {name} not implemented"}
