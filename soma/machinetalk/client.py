"""TurnKey client — the only place that talks to models.

Dendrites and Soma call this with a stage name and messages.
They do not pick a model. They do not know the engine URL.
TurnKey SDK does rotation, retry, gateway, and the HTTP call.
"""
from __future__ import annotations

import http.client
import inspect
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# Stage 1 extracts. There is exactly one right answer to "which sentence is
# the directive", so sampling a distribution over answers is wrong: the same
# prompt against the same model returned 0, 7 and 0 verified entries on three
# consecutive calls. Later stages compose plans and journals, where some
# latitude is legitimate.
_EXTRACTIVE_STAGES = frozenset({
    "distiller", "introbeaver", "planbeaver", "outrobeaver",
    "scout", "oc", "olc",
})
DEFAULT_EXTRACTIVE_TEMPERATURE = 0.0


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
        self._pea_kw = self._supports_pea_session(self._sdk.run_stage)

    @staticmethod
    def _supports_pea_session(fn) -> bool:
        """True when the installed SDK accepts pea_session."""
        try:
            params = inspect.signature(fn).parameters
        except (TypeError, ValueError):
            return True
        if "pea_session" in params:
            return True
        return any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values())

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
             pea_session: str | None = None,
             temperature: float | None = None) -> StageResult:
        mapped = _STAGE_MAP.get(stage, stage)
        start = time.monotonic()
        kwargs = {"pea_session": pea_session} if self._pea_kw else {}
        # run_stage only sends temperature when it is not None, so passing it
        # unconditionally is safe and makes unset the explicit default.
        if temperature is not None:
            kwargs["temperature"] = temperature
        raw = self._sdk.run_stage(mapped, messages, **kwargs)
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
        """Name the model the next call will use.

        This used to return the literal string "turnkey", which appeared in
        every progress line and summary table as though it were a model. The
        rotator can say which card it is about to serve without consuming it.
        """
        try:
            info = self._tk._sdk.rotator.peek_model(stage)
            return info.get("model_id") or "unknown"
        except Exception:
            # A profile with no deck is a configuration error the call itself
            # will surface; the display should not crash first.
            return "unknown"

    # A DNS failure cannot be fixed by waiting: the host does not resolve at
    # all, so every retry fails the same way. Give it one quick second chance
    # and then surface it instead of burning the whole retry budget.
    _UNRECOVERABLE = ("Name or service not known",
                      "nodename nor servname",
                      "Temporary failure in name resolution")

    def _call_with_retry(self, stage: str, messages: list[dict[str, str]],
                         attempts: int = 10,
                         pea_session: str | None = None,
                         temperature: float | None = None) -> Any:
        """Retry transport failures that escape the TurnKey SDK.

        The SDK converts URLError/TimeoutError to SDKError and retries those,
        but ``http.client.RemoteDisconnected`` is a ConnectionError/BadStatusLine
        and is not a URLError, so it propagates out of ``run_stage`` and kills
        the chatset. Retrying here also advances the SDK's deck rotator, so a
        bad model is skipped instead of being hit again.

        Failures that cannot improve with time (DNS resolution) abort after the
        first retry, because retrying them only multiplies the wait by the
        attempt count.
        """
        last: Exception | None = None
        dns_failures = 0
        for attempt in range(attempts):
            try:
                return self._tk.call(stage, messages, pea_session=pea_session,
                                     temperature=temperature)
            except TypeError:
                # A signature mismatch is a code bug, not a transport failure.
                # Retrying it ten times only burns the deck.
                raise
            except (ConnectionError, TimeoutError, http.client.HTTPException) as exc:
                last = exc
                text = f"{type(exc).__name__}: {exc}"
                print(f"\n[retry] {stage} attempt {attempt + 1}/{attempts} "
                      f"failed: {text}", file=sys.stderr, flush=True)
                if any(tok in text for tok in self._UNRECOVERABLE):
                    dns_failures += 1
                    if dns_failures >= 2:
                        print(f"[retry] {stage}: DNS failure will not recover, "
                              f"stopping after {attempt + 1} attempt(s)",
                              file=sys.stderr, flush=True)
                        raise
                if attempt + 1 < attempts:
                    time.sleep(1.5 * (attempt + 1))
            except Exception as exc:
                # SDKError and anything else — also retry to rotate the deck
                last = exc
                text = f"{type(exc).__name__}: {exc}"
                print(f"\n[retry] {stage} attempt {attempt + 1}/{attempts} "
                      f"failed: {text}", file=sys.stderr, flush=True)
                if any(tok in text for tok in self._UNRECOVERABLE):
                    dns_failures += 1
                    if dns_failures >= 2:
                        print(f"[retry] {stage}: DNS failure will not recover, "
                              f"stopping after {attempt + 1} attempt(s)",
                              file=sys.stderr, flush=True)
                        raise
                if attempt + 1 < attempts:
                    time.sleep(1.5 * (attempt + 1))
        assert last is not None
        raise last

    def call_stage(self, stage: str, *, session_id: str, chatset_id: str,
                   chunk: str = "", contracts: str = "",
                   payload: dict | None = None,
                   expected_hash: str | None = None,
                   temperature: float | None = None,
                   soma: Any = None,
                   raw_chat_set: list[dict] | None = None) -> Any:
        """Call one stage and verify its output before it is trusted.

        Instructions come from the ``stage_instructions`` row for this stage,
        never from the markdown files on disk. A stage is told its own job and
        nothing about the other stages, so it has no pipeline to reason about.

        When ``raw_chat_set`` is supplied (distiller and introbeaver), every
        emitted entry must match the source text at the offsets it claims.
        A provenance failure fails the stage: the model's claim is not
        allowed into the graph unverified.
        """
        from .fleet import assemble
        from .gate import validate, is_done, is_hard_block
        from .provenance import (verify_distiller, verify_introbeaver)

        pea_session = session_id

        instruction = None
        if soma is not None:
            instruction = soma.get_stage_instruction(stage)
        if instruction is None:
            raise RuntimeError(
                f"stage {stage!r} has no row in stage_instructions. "
                f"Instructions are read from the database, not from disk; "
                f"build the store from soma_template.sql first.")

        sys_prompt = instruction["body"]
        _, user_msg = assemble(stage, sys_prompt, chunk=chunk,
                               contracts=contracts, payload=payload)
        messages = [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": user_msg},
        ]
        if temperature is None:
            temperature = (DEFAULT_EXTRACTIVE_TEMPERATURE
                           if stage in _EXTRACTIVE_STAGES else None)
        result = self._call_with_retry(stage, messages, pea_session=pea_session,
                                       temperature=temperature)
        gate = validate(stage, result.content, expected_hash=expected_hash)

        # ── provenance: the claim must exist in the source ──────────────
        if raw_chat_set is not None and gate.parsed and is_done(gate):
            if stage == "distiller":
                prov = verify_distiller(gate.parsed, raw_chat_set)
            elif stage == "introbeaver":
                prov = verify_introbeaver(gate.parsed, raw_chat_set)
            else:
                prov = None
            if prov is not None and not prov.ok:
                gate.errors.extend(str(i) for i in prov.issues)
                gate.ok = False
                gate.provenance = prov.summary()

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
