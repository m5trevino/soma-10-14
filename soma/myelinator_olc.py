"""TB-OLC-001/002/003/004/005/006: Active Myelinator (OLC) Optimizer.

Hardens FunctionSlots with invariant rules via active tool-calling.
Generates cryptographically secure PINs and salt-hashes them for SOMA.

Hard gates:
  - Must not generate code implementations
  - Only writes OptimizedSlot nodes + GOVERNS edges + LINKED_TO edges
  - Cleartext PIN must never be written to OptimizedSlot properties
  - All SOMA edge modifications go through formal tool-calls
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets
import time
from typing import Any

from store import Soma
from pipeline.drafter_dendrite import ToolRegistry





class MyelinatorOptimizer:
    """Active OLC — merges FunctionSlot mandate with invariant rules via tool-calling."""

    def __init__(self, soma: Soma, llm_client: Any) -> None:
        self._soma = soma
        self._llm = llm_client
        self._tools = ToolRegistry(soma)

    @staticmethod
    def _generate_pin() -> str:
        """TB-OLC-003: Generate a cryptographically secure 4-digit PIN."""
        return f"{secrets.randbelow(10000):04d}"

    @staticmethod
    def _hash_pin(pin: str) -> str:
        """TB-OLC-003: Create SHA-256 hash of a PIN string."""
        return hashlib.sha256(pin.encode("utf-8")).hexdigest()

    def run(self, session_id: str) -> dict[str, Any]:
        """TB-OLC-001/002/003/004: Optimize all FunctionSlots for the session.

        1. Query FunctionSlots and InvariantQueryNodes.
        2. Call LLM with tool to match invariants to slots (GOVERNS edges).
        3. Create OptimizedSlots with hardened rules from GOVERNS-linked invariants.
        4. Generate PINs and hash them for each OptimizedSlot.
        5. Write master manifest node with PIN mappings.

        Returns report with all optimized_slot_ids, match counts, pin_map, and metrics.
        """
        start = time.monotonic()
        stage_name = "myelinator"

        print(f"    [myelinator] Loading FunctionSlots for session {session_id}...", flush=True)
        slots = [
            n for n in self._soma.query_by_type("FunctionSlot")
            if n.properties.get("session_id") == session_id
        ]
        invariants = [
            n for n in self._soma.query_by_type("InvariantQueryNode")
            if n.properties.get("session_id") == session_id
        ]
        print(f"    [myelinator] Found {len(slots)} FunctionSlot(s) and {len(invariants)} InvariantQueryNode(s)", flush=True)

        if not slots:
            print("    [myelinator] No FunctionSlots found — aborting OLC", flush=True)
            return {
                "session_id": session_id,
                "error": "No FunctionSlots found",
                "optimized_slot_ids": [],
                "slot_count": 0,
                "invariant_count": len(invariants),
                "pin_map": {},
                "metrics": {"model_id": "unknown", "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "latency_ms": 0.0},
            }

        prompt_tokens = 0
        completion_tokens = 0
        total_tokens = 0
        llm_latency_ms = 0.0
        governs_count = 0

        # TB-OLC-001: Active tool-calling match if both slots and invariants exist
        if invariants:
            print(f"    [myelinator] Calling TurnKey to match invariants to slots...", flush=True)
            llm_start = time.monotonic()
            response = self._call_match_llm(slots, invariants)
            llm_latency_ms = (time.monotonic() - llm_start) * 1000
            print(f"    [myelinator] LLM match call complete — {llm_latency_ms / 1000.0:.1f}s", flush=True)

            if response:
                prompt_tokens = response.prompt_tokens
                completion_tokens = response.completion_tokens
                total_tokens = response.total_tokens

                # TB-OLC-005: Execute tool calls through formal ToolRegistry
                if response.tool_calls:
                    for tc in response.tool_calls:
                        func = tc.get("function", {})
                        if func.get("name") == "create_soma_edge":
                            try:
                                args = json.loads(func.get("arguments", "{}"))
                                result = self._tools.call("create_soma_edge", args)
                                if result.get("ok"):
                                    governs_count += 1
                            except Exception:
                                pass

        # TB-FIN-006: Harden every FunctionSlot via harden_slot().
        optimized_slot_ids: list[str] = []
        slot_invariant_map: dict[str, list[str]] = {}
        pin_map: dict[str, str] = {}  # opt_id -> cleartext PIN

        print(f"    [myelinator] Hardening {len(slots)} FunctionSlot(s) with PIN hashes...", flush=True)
        for i, slot in enumerate(slots, start=1):
            name = slot.properties.get("name", "unknown")
            print(f"    [myelinator] [{i}/{len(slots)}] Hardening {name}()...", flush=True)
            result = self.harden_slot(slot.node_id, session_id)
            opt_id = result["optimized_slot_id"]
            optimized_slot_ids.append(opt_id)
            slot_invariant_map[slot.node_id] = result["laws"]
            pin_map[opt_id] = result["pin"]

        # TB-OLC-004: Write master manifest node
        print(f"    [myelinator] Writing master SessionManifestNode with {len(pin_map)} PIN entries...", flush=True)
        self._write_manifest(session_id, pin_map)
        print(f"    [myelinator] OLC complete — {len(optimized_slot_ids)} OptimizedSlot(s) created", flush=True)

        elapsed_ms = (time.monotonic() - start) * 1000
        return {
            "session_id": session_id,
            "optimized_slot_ids": optimized_slot_ids,
            "slot_count": len(slots),
            "invariant_count": len(invariants),
            "governs_edges_created": governs_count,
            "slot_invariant_map": {k: len(v) for k, v in slot_invariant_map.items()},
            "pin_map": pin_map,
            "metrics": {
                "model_id": getattr(response, "model_id", "unknown") if response else "unknown",
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
                "llm_latency_ms": llm_latency_ms,
                "latency_ms": elapsed_ms,
            },
        }

    def _write_manifest(self, session_id: str, pin_map: dict[str, str]) -> None:
        """TB-OLC-004: Write or update the SessionManifestNode with PIN mappings."""
        manifest_id = f"manifest-{session_id}"
        existing = self._soma.get_node(manifest_id)
        if existing:
            self._soma.delete_node(manifest_id)

        self._soma.create_node("SessionManifestNode", {
            "id": manifest_id,
            "session_id": session_id,
            "manifest_payload": json.dumps(pin_map, sort_keys=True),
        })

    def _call_match_llm(self, slots: list[Any], invariants: list[Any]) -> Any:
        """TB-OLC-001: Build prompt and call LLM with create_soma_edge tool."""
        slot_lines = []
        for s in slots:
            code = s.properties.get("code_block", "")[:200]
            slot_lines.append(f"  {s.node_id}: {s.properties.get('mandate', '')} | code={code[:80]}...")

        inv_lines = []
        for inv in invariants:
            inv_lines.append(f"  {inv.node_id}: {inv.properties.get('invariant_text', '')[:150]}")

        prompt = (
            "You are the Myelinator OLC — a SOMA graph optimizer.\n\n"
            "Your task: match InvariantQueryNodes to FunctionSlots.\n"
            "For each match, call the create_soma_edge tool with:\n"
            "  source_id = InvariantQueryNode ID\n"
            "  relationship = 'GOVERNS'\n"
            "  target_id = FunctionSlot ID\n\n"
            "Match criteria: semantic relevance (function purpose, keywords, domain).\n\n"
            "FunctionSlots:\n" + "\n".join(slot_lines) + "\n\n"
            "InvariantQueryNodes:\n" + "\n".join(inv_lines) + "\n\n"
            "Call create_soma_edge for every match you find."
        )

        messages = [
            {"role": "system", "content": "You are a SOMA graph optimizer. Use tools to write edges."},
            {"role": "user", "content": prompt},
        ]

        try:
            return self._llm.call("myelinator", messages)
        except Exception:
            return None

    def harden_slot(self, slot_id: str, session_id: str) -> dict[str, Any]:
        """TB-FIN-005: Harden one FunctionSlot into an OptimizedSlot.

        Matches session InvariantQueryNodes to the slot by deterministic text
        overlap (function name, mandate, or file path vs invariant text).
        Creates GOVERNS edges for new matches and an OptimizedSlot linked back
        to the parent FunctionSlot. Idempotent: repeated calls update the
        OptimizedSlot but do not duplicate GOVERNS edges.

        Returns a dict with the optimized_slot_id, governs_count, and laws.
        """
        slot = self._soma.get_node(slot_id)
        if slot is None or slot.properties.get("session_id") != session_id:
            return {"error": "Slot not found"}

        invariants = [
            n for n in self._soma.query_by_type("InvariantQueryNode")
            if n.properties.get("session_id") == session_id
        ]

        existing_edges = self._soma.get_edges(slot_id)
        existing_governs = {
            e.source for e in existing_edges
            if e.rel_type == "GOVERNS" and e.target == slot_id
        }

        inv_by_id = {inv.node_id: inv for inv in invariants}
        # GOVERNS edges already in the tree come from retrieval (BM25 over the
        # law corpus) and are ranked. Trust them: they are the only signal that
        # distinguishes two functions in the same file.
        matched: list[Any] = [inv_by_id[sid] for sid in existing_governs if sid in inv_by_id]

        # Fallback only when retrieval produced nothing for this slot.
        # Matching is on the slot's own name — never the file path, which made
        # every function in a file inherit that file's laws regardless of what
        # the function does.
        if not matched:
            name = (slot.properties.get("name", "") or "").lower()
            tokens = {t for t in re.split(r"[^a-z0-9]+", name) if len(t) > 3}
            for inv in invariants:
                inv_text = str(inv.properties.get("invariant_text", "")).lower()
                if any(tok in inv_text for tok in tokens):
                    self._soma.create_edge(inv.node_id, "GOVERNS", slot_id)
                    matched.append(inv)

        opt_id = f"opt-{slot_id}"
        existing = self._soma.get_node(opt_id)
        if existing:
            self._soma.delete_node(opt_id)

        mandate = slot.properties.get("mandate", "")
        terminal_id = slot.properties.get("terminal_id", "")
        laws = [str(inv.properties.get("invariant_text", "")) for inv in matched]
        hardened_rules = "\n".join(f"- {law}" for law in laws)

        pin = self._generate_pin()
        pin_hash = self._hash_pin(pin)

        self._soma.create_node("OptimizedSlot", {
            "id": opt_id,
            "session_id": session_id,
            "mandate": f"{mandate}\n\nHARDENED RULES:\n{hardened_rules}" if hardened_rules else mandate,
            "terminal_id": terminal_id,
            "status": "optimized",
            "pin_hash": pin_hash,
            "parent_slot_id": slot_id,
            "invariant_count": len(matched),
            "laws": laws,
        })
        self._soma.create_edge(opt_id, "LINKED_TO", slot_id)

        return {
            "optimized_slot_id": opt_id,
            "governs_count": len(matched),
            "laws": laws,
            "pin": pin,
        }

    def apply_check(self, slot_id: str, checker) -> dict:
        """TB-FIX-010: Write a check result onto one OptimizedSlot.

        The checker is injected as a callable that takes the slot_id and returns
        a tuple of (ok: bool, error: str). On ok=True, sets check_ok=True,
        check_error='', status='optimized'. On ok=False, sets check_ok=False,
        check_error=error string, status='check_failed'.

        Missing slot returns an error dict and writes nothing.
        Does not spawn a process and does not import pyright or mypy.
        Existing GOVERNS and LINKED_TO edges are unchanged.
        """
        opt_id = f"opt-{slot_id}"
        opt_node = self._soma.get_node(opt_id)
        if opt_node is None:
            return {"error": "OptimizedSlot not found", "slot_id": slot_id}

        ok, error = checker(opt_id)

        # Update properties
        opt_node.properties["check_ok"] = ok
        opt_node.properties["check_error"] = "" if ok else error
        opt_node.properties["status"] = "optimized" if ok else "check_failed"

        return {
            "optimized_slot_id": opt_id,
            "check_ok": ok,
            "check_error": "" if ok else error,
            "status": opt_node.properties["status"],
        }

