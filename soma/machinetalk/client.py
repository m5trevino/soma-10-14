"""TurnKey client — the only place that talks to models.

Dendrites and Soma call this with a stage name and messages.
They do not pick a model. They do not know the engine URL.
TurnKey SDK does rotation, retry, gateway, and the HTTP call.
"""
from __future__ import annotations

import http.client
import sys
import time
from dataclasses import dataclass, field
from typing import Any


_STAGE_MAP = {
    "receptor": "distiller",
    "distiller": "distiller",
    "classifier": "introbeaver",
    "introbeaver": "introbeaver",
    "integrator": "planbeaver",
    "planbeaver": "planbeaver",
    "retrograde": "outrobeaver",
    "outrobeaver": "outrobeaver",
    "nexus": "nexus",
    "spark": "spark",
    "falcon": "falcon",
    "drafter": "drafter",
    "eagle": "drafter",
    "scout": "scout",
    "axon_hillock": "oc",
    "oc": "oc",
    "myelinator": "olc",
    "olc": "olc",
    "terminal": "terminal",
    "saltatory_gate": "saltatory_gate",
}


@dataclass
class CallRecord:
    stage: str = ""
    session_id: str = ""
    chatset_id: str = ""
    model: str = ""
    status: str = ""
    attempt: int = 0
    attempts: list = field(default_factory=list)
    gate: Any = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    latency_ms: float = 0.0
    error: str = ""
    raw_response: str = ""
    sys_prompt: str = ""
    user_msg: str = ""


class StageResult:
    """What a dendrite gets back. No model selection happened on their side."""

    def __init__(
        self,
        content: str,
        model_id: str = "unknown",
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        total_tokens: int = 0,
        latency_ms: float = 0.0,
    ) -> None:
        self.content = content
        self.model_id = model_id
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.total_tokens = total_tokens
        self.latency_ms = latency_ms


class TurnKeyClient:
    """Middleware. Takes a stage name. Hands it to TurnKey. Returns the text."""

    def __init__(self, profile_path: str) -> None:
        self._profile_path = profile_path
        self._sdk = self._load_sdk(profile_path)

    @staticmethod
    def _load_sdk(profile_path: str):
        try:
            from turnkey.profile_integration import initialize_sdk_with_profile
        except ImportError as exc:
            raise RuntimeError(
                "TurnKey SDK is not importable. It is the only middleware "
                "for model calls. Install or path it before running."
            ) from exc
        return initialize_sdk_with_profile(profile_path)

    def call(self, stage: str, messages: list[dict[str, str]],
             pea_session: str | None = None) -> StageResult:
        mapped = _STAGE_MAP.get(stage, stage)
        start = time.monotonic()
        raw = self._sdk.run_stage(mapped, messages, pea_session=pea_session)
        elapsed = (time.monotonic() - start) * 1000

        choices = raw.get("choices", []) if isinstance(raw, dict) else []
        content = ""
        if choices:
            content = choices[0].get("message", {}).get("content", "") or ""

        usage = raw.get("usage", {}) if isinstance(raw, dict) else {}
        return StageResult(
            content=content,
            model_id=raw.get("model", "unknown") if isinstance(raw, dict) else "unknown",
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            total_tokens=usage.get("total_tokens", 0),
            latency_ms=elapsed,
        )

    def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> StageResult:
        stage = kwargs.get("stage") or kwargs.get("model") or "distiller"
        return self.call(stage, messages)


class EngineClient:
    """Adapter so the engine can call TurnKey with the old call_stage shape.

    TurnKey still picks the model. The engine never sees a model id until
    the response comes back.
    """

    def __init__(self, profile_path: str) -> None:
        self._tk = TurnKeyClient(profile_path)
        self.timeout = 180.0

    def model_for(self, stage: str) -> str:
        return "turnkey"

    def _call_with_retry(self, stage: str, messages: list[dict[str, str]],
                         attempts: int = 10,
                         pea_session: str | None = None) -> Any:
        """Retry transport failures that escape the TurnKey SDK.

        The SDK converts URLError/TimeoutError to SDKError and retries those,
        but ``http.client.RemoteDisconnected`` is a ConnectionError/BadStatusLine
        and is not a URLError, so it propagates out of ``run_stage`` and kills
        the chatset. Retrying here also advances the SDK's deck rotator, so a
        bad model is skipped instead of being hit again.
        """
        last: Exception | None = None
        for attempt in range(attempts):
            try:
                return self._tk.call(stage, messages, pea_session=pea_session)
            except (ConnectionError, TimeoutError, http.client.HTTPException) as exc:
                last = exc
                print(f"\n[retry] {stage} attempt {attempt + 1}/{attempts} "
                      f"failed: {type(exc).__name__}: {exc}",
                      file=sys.stderr, flush=True)
            except Exception as exc:
                # SDKError and anything else — also retry to rotate the deck
                last = exc
                print(f"\n[retry] {stage} attempt {attempt + 1}/{attempts} "
                      f"failed: {type(exc).__name__}: {exc}",
                      file=sys.stderr, flush=True)
                if attempt + 1 < attempts:
                    time.sleep(1.5 * (attempt + 1))
        assert last is not None
        raise last

    def call_stage(self, stage: str, *, session_id: str, chatset_id: str,
                   chunk: str = "", contracts: str = "",
                   payload: dict | None = None,
                   expected_hash: str | None = None,
                   temperature: float | None = None) -> Any:
        from .fleet import assemble, load_system_prompt
        from .gate import validate, is_done, is_hard_block

        # Derive pea_session from session_id: use the session_id as-is.
        # The engine appends <WW>-<D><L>- to create a unique dir per day/week.
        # If the same session_id is reused across days, new dirs are created
        # automatically — no collision possible.
        pea_session = session_id

        sys_prompt = load_system_prompt(stage, strip_injection=True)
        _, user_msg = assemble(stage, sys_prompt, chunk=chunk,
                               contracts=contracts, payload=payload)
        messages = [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": user_msg},
        ]
        result = self._call_with_retry(stage, messages, pea_session=pea_session)
        gate = validate(stage, result.content, expected_hash=expected_hash)

        rec = CallRecord(
            stage=stage,
            session_id=session_id,
            chatset_id=chatset_id,
            model=result.model_id,
            status="pass" if is_done(gate) else ("blocked" if is_hard_block(gate) else "fail"),
            attempt=1,
            attempts=[{"attempt": 1, "model": result.model_id}],
            gate=gate,
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            total_tokens=result.total_tokens,
            latency_ms=result.latency_ms,
            raw_response=result.content,
            sys_prompt=sys_prompt,
            user_msg=user_msg,
        )

        class _Res:
            pass
        res = _Res()
        res.ok = is_done(gate)
        res.record = rec
        res.payload = gate.parsed
        res.skipped = gate.skipped
        res.verdict = gate.verdict
        return res
