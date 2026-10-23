"""TurnKey LLM SDK — wraps the TurnKey SDK (Novita/Xkiro deck rotation).

Usage:
    from pipeline.llm_sdk import TurnKeyClient
    
    client = TurnKeyClient()  # uses default profile path
    response = client.chat(messages=[...])
"""
import time
from typing import Any
from pathlib import Path

from pipeline.drafter_dendrite import LLMClient, LLMResponse

# Ensure turn-key SDK is on path (must come after dendritic imports above)
sys = __import__("sys")
if "/home/flintx/turn-key" not in sys.path:
    sys.path.insert(0, "/home/flintx/turn-key")


_STAGE_MAP = {
    "classifier": "distiller",
    "nexus": "nexus",
    "spark": "spark",
    "falcon": "falcon",
    "drafter": "drafter",
    "scout": "scout",
    "axon_hillock": "oc",
    "myelinator": "olc",
}


class TurnKeyClient(LLMClient):
    """Wraps the TurnKey SDK to implement the dendrite LLMClient interface.
    
    Calls the TurnKey engine at engine.save-aichats.com:3099 with
    deck-based model rotation (Novita + Xkiro providers).
    """
    
    def __init__(self, profile_path: str | None = None):
        if not profile_path:
            profile_path = str(Path("/home/flintx/soma/123_2026-10-08T10-20-18.json"))
        self._profile_path = profile_path
        
        from turnkey.profile_integration import initialize_sdk_with_profile
        self._sdk = initialize_sdk_with_profile(profile_path)
    
    def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> LLMResponse:
        system_msg = ""
        for m in messages:
            if m.get("role") == "system":
                system_msg = m.get("content", "").lower()
                break
        
        stage_name = "distiller"
        for key, val in _STAGE_MAP.items():
            if key in system_msg:
                stage_name = val
                break
        
        start = time.monotonic()
        result = self._sdk.run_stage(stage_name, messages)
        elapsed_ms = (time.monotonic() - start) * 1000
        
        choices = result.get("choices", [])
        content = ""
        if choices:
            msg = choices[0].get("message", {})
            content = msg.get("content", "")
        
        usage = result.get("usage", {})
        prompt_tokens = usage.get("prompt_tokens", 0)
        completion_tokens = usage.get("completion_tokens", 0)
        
        return LLMResponse(
            model_id=result.get("model", "unknown"),
            content=content,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            latency_ms=elapsed_ms,
        )