"""complete_stage() — orchestrate a single LLM call and parse JSON result.

Imports LLMClient and LLMResponse from pipeline.drafter_dendrite.
"""
from __future__ import annotations

import json
import re
import time
from typing import Any

from pipeline.drafter_dendrite import LLMClient, LLMResponse


# Pattern to extract JSON from prose (handles markdown code fences)
_JSON_START = re.compile(r"[\[{]")
_JSON_END = re.compile(r"[}\]]")


def complete_stage(
    llm: Any,
    stage: str,
    instruction_body: str,
    payload: str,
) -> dict[str, Any]:
    """Call the client for a stage. The client is TurnKey. No model is chosen here.

    Returns:
        {"ok": True, "result": parsed, "metrics": {...}}  on success
        {"ok": False, "error": ..., "metrics": {...}}      on failure
    """
    start = time.monotonic()

    try:
        response = llm.call(
            stage,
            [
                {"role": "system", "content": instruction_body},
                {"role": "user", "content": payload},
            ],
        )
    except Exception as exc:
        elapsed_ms = (time.monotonic() - start) * 1000
        return {
            "ok": False,
            "error": str(exc),
            "metrics": {
                "model_id": "unknown",
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "latency_ms": elapsed_ms,
            },
        }

    content = (response.content or "").strip()

    cleaned = content
    fence_match = re.match(r"^```(?:json)?\s*(.*?)```?\s*$", cleaned, re.DOTALL)
    if fence_match:
        cleaned = fence_match.group(1).strip()

    try:
        result = json.loads(cleaned)
    except (json.JSONDecodeError, ValueError):
        elapsed_ms = (time.monotonic() - start) * 1000
        return {
            "ok": False,
            "error": f"LLM returned prose, not JSON: {cleaned[:200]}",
            "metrics": {
                "model_id": getattr(response, "model_id", "unknown"),
                "prompt_tokens": getattr(response, "prompt_tokens", 0),
                "completion_tokens": getattr(response, "completion_tokens", 0),
                "total_tokens": getattr(response, "total_tokens", 0),
                "latency_ms": elapsed_ms,
            },
        }

    elapsed_ms = (time.monotonic() - start) * 1000
    metrics = {
        "model_id": getattr(response, "model_id", "unknown"),
        "prompt_tokens": getattr(response, "prompt_tokens", 0),
        "completion_tokens": getattr(response, "completion_tokens", 0),
        "total_tokens": getattr(response, "total_tokens", 0),
        "latency_ms": elapsed_ms,
    }

    return {"ok": True, "result": result, "metrics": metrics}