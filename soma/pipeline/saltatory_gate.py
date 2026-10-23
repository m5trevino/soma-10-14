"""TB-DEND-022: SaltatoryGate — Verification gate for FunctionSlots.

Creates VerifiedNode (or FailureNode) for each FunctionSlot after test
execution, linked back to the parent FunctionSlot via a VERIFIED edge.

Hard gates:
  - VerifiedNode exists ONLY if all tests pass for that slot
  - FailureNode created if any test fails
  - Must not modify FunctionSlot or OptimizedSlot nodes
  - All edge modifications go through Soma.create_edge()
"""
from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Any

from store import Soma


class SaltatoryGate:
    """Active verification gate — runs tests and creates VerifiedNode/FailureNode."""

    def __init__(self, soma: Soma, workspace_root: str | None = None) -> None:
        self._soma = soma
        self._workspace_root = workspace_root

    def run(self, session_id: str) -> dict[str, Any]:
        """Run verification for all FunctionSlots in the session.

        1. Query all FunctionSlot nodes for the session.
        2. For each slot, run tests (if test files exist for the slot's file).
        3. Create VerifiedNode if tests pass, FailureNode if they fail.
        4. Create VERIFIED edge from FunctionSlot → VerifiedNode/FailureNode.

        Returns report with verified_ids, failure_ids, and metrics.
        """
        start = time.monotonic()

        slots = [
            n for n in self._soma.query_by_type("FunctionSlot")
            if n.properties.get("session_id") == session_id
        ]

        verified_ids: list[str] = []
        failure_ids: list[str] = []
        skipped: list[str] = []

        for slot in slots:
            slot_id = slot.id
            slot_name = slot.properties.get("name", "unknown")
            file_path = slot.properties.get("file_path", "")

            print(f"  [saltatory] Verifying {slot_name} ({file_path})...")

            # Determine if tests exist for this file
            test_result = self._run_slot_tests(session_id, file_path)

            if test_result.get("skipped"):
                skipped.append(slot_id)
                print(f"    → SKIPPED (no test files)")
                continue

            if test_result.get("passed"):
                # Create VerifiedNode
                verified_id = self._create_verified_node(
                    session_id, slot_id, slot_name, file_path
                )
                # Create VERIFIED edge: FunctionSlot → VerifiedNode
                self._soma.create_edge(slot_id, "VERIFIED", verified_id)
                verified_ids.append(verified_id)
                print(f"    → VERIFIED")
            else:
                # Create FailureNode
                failure_id = self._create_failure_node(
                    session_id, slot_id, slot_name, file_path,
                    test_result.get("error", "unknown failure")
                )
                # Create VERIFIED edge (pointing to FailureNode)
                self._soma.create_edge(slot_id, "VERIFIED", failure_id)
                failure_ids.append(failure_id)
                print(f"    → FAILURE: {test_result.get('error')}")

        elapsed_ms = (time.monotonic() - start) * 1000

        return {
            "session_id": session_id,
            "verified_ids": verified_ids,
            "failure_ids": failure_ids,
            "skipped_ids": skipped,
            "verified_count": len(verified_ids),
            "failure_count": len(failure_ids),
            "skipped_count": len(skipped),
            "metrics": {
                "latency_ms": elapsed_ms,
            },
        }

    def _run_slot_tests(
        self, session_id: str, file_path: str
    ) -> dict[str, Any]:
        """Run tests for a specific file_path in the session workspace.

        Returns {"passed": True/False, "error": str, "skipped": bool}.
        """
        workspace = self._get_workspace_path(session_id)
        if not workspace or not workspace.exists():
            return {"passed": False, "error": "workspace not found", "skipped": False}

        # Check if there are test files in the workspace
        test_files = list(workspace.rglob("test_*"))
        if not test_files:
            return {"passed": False, "error": "no test files", "skipped": True}

        # Build test command
        target = workspace / file_path
        if not target.exists():
            return {"passed": False, "error": "file not in workspace", "skipped": False}

        # Try running pytest on test files — use system Python that has pytest
        import shutil
        _PYTHON_BIN = "/usr/bin/python3"
        try:
            result = subprocess.run(
                [_PYTHON_BIN, "-m", "pytest", "-x", "--tb=short"] + [str(tf) for tf in test_files],
                cwd=str(workspace),
                capture_output=True,
                text=True,
                timeout=60,
            )
            if result.returncode == 0:
                return {"passed": True, "error": "", "skipped": False}
            else:
                return {"passed": False, "error": result.stderr[:500], "skipped": False}
        except subprocess.TimeoutExpired:
            return {"passed": False, "error": "test timeout", "skipped": False}
        except FileNotFoundError:
            # pytest not available, mark as skipped
            return {"passed": False, "error": "pytest not available", "skipped": True}

    def _get_workspace_path(self, session_id: str) -> Path | None:
        """Get workspace path for the session."""
        safe_id = re.sub(r"[^\w.-]", "_", session_id)
        # Try the standard workspace location
        candidate = Path.home() / "soma" / "chats" / safe_id / "workspace"
        if candidate.exists():
            return candidate
        return None

    def _create_verified_node(
        self, session_id: str, slot_id: str, slot_name: str, file_path: str
    ) -> str:
        """Create a VerifiedNode for a passing FunctionSlot."""
        verified_id = f"verified-{slot_id}"
        existing = self._soma.get_node(verified_id)
        if existing:
            self._soma.delete_node(verified_id)

        self._soma.create_node("VerifiedNode", {
            "id": verified_id,
            "session_id": session_id,
            "slot_id": slot_id,
            "slot_name": slot_name,
            "file_path": file_path,
            "status": "verified",
            "verification_method": "test_suite",
        })
        return verified_id

    def _create_failure_node(
        self, session_id: str, slot_id: str, slot_name: str,
        file_path: str, error: str
    ) -> str:
        """Create a FailureNode for a failing FunctionSlot."""
        failure_id = f"failure-{slot_id}"
        existing = self._soma.get_node(failure_id)
        if existing:
            self._soma.delete_node(failure_id)

        self._soma.create_node("FailureNode", {
            "id": failure_id,
            "session_id": session_id,
            "slot_id": slot_id,
            "slot_name": slot_name,
            "file_path": file_path,
            "status": "failed",
            "failure_reason": error,
        })
        return failure_id


import re