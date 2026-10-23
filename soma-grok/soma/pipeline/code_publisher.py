"""TB-DEND-022: CodePublisher — Writes verified code to disk.

Queries ONLY VerifiedNodes, follows the full verification chain to get
the exact code payload, and writes to the original file path recorded
in the FileNode. Skips any slot that has a FailureNode.

Hard gates:
  - Only publishes from VerifiedNodes (never from unverified slots)
  - If a FailureNode exists for a slot, that slot is skipped
  - Uses the FileNode path from the full chain, not the FunctionSlot path
  - Never modifies SOMA graph state
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from store import Soma


class CodePublisher:
    """Active publisher — writes verified code to workspace."""

    def __init__(self, soma: Soma) -> None:
        self._soma = soma

    def run(self, session_id: str) -> dict[str, Any]:
        """Publish all verified FunctionSlots to disk.

        For each VerifiedNode:
        1. Get the VERIFIED edge target (VerifiedNode)
        2. Follow VERIFIED edge back to source (FunctionSlot)
        3. Query the FunctionSlot's code_block
        4. Resolve the file path from the SLICED_FROM chain back to FileNode
        5. Write code to disk at that path

        Skips any slot where a FailureNode exists.

        Returns report with written_files, skipped_files, and metrics.
        """
        start = time.monotonic()

        # Get all VerifiedNodes for this session
        verified_nodes = [
            n for n in self._soma.query_by_type("VerifiedNode")
            if n.properties.get("session_id") == session_id
        ]

        published: list[dict[str, Any]] = []
        skipped: list[dict[str, str]] = []

        for verified_node in verified_nodes:
            verified_id = verified_node.id
            slot_id = verified_node.properties.get("slot_id", "")
            slot_name = verified_node.properties.get("slot_name", "unknown")
            file_path = verified_node.properties.get("file_path", "")

            # Check if there's a FailureNode for this slot
            failure_node = self._soma.get_node(f"failure-{slot_id}")
            if failure_node and failure_node.node_type == "FailureNode":
                skipped.append({
                    "verified_id": verified_id,
                    "slot_id": slot_id,
                    "reason": "failure_node_exists",
                })
                print(f"    [publisher] SKIPPED {slot_name}: FailureNode exists")
                continue

            # Get the FunctionSlot to read code_block
            slot = self._soma.get_node(slot_id)
            if not slot:
                skipped.append({
                    "verified_id": verified_id,
                    "slot_id": slot_id,
                    "reason": "slot_not_found",
                })
                print(f"    [publisher] SKIPPED {slot_name}: FunctionSlot not found")
                continue

            code_block = slot.properties.get("code_block", "")
            if not code_block:
                skipped.append({
                    "verified_id": verified_id,
                    "slot_id": slot_id,
                    "reason": "no_code_block",
                })
                print(f"    [publisher] SKIPPED {slot_name}: no code_block")
                continue

            # Resolve the file path via SLICED_FROM chain to FileNode
            # The FileNode has the authoritative path
            resolved_path = self._resolve_file_path(session_id, slot_id, file_path)

            if not resolved_path:
                skipped.append({
                    "verified_id": verified_id,
                    "slot_id": slot_id,
                    "reason": "path_resolution_failed",
                })
                print(f"    [publisher] SKIPPED {slot_name}: path resolution failed")
                continue

            # Write the code to disk
            written = self._write_code(resolved_path, code_block, session_id)
            if written:
                published.append({
                    "verified_id": verified_id,
                    "slot_id": slot_id,
                    "slot_name": slot_name,
                    "file_path": resolved_path,
                })
                print(f"    [publisher] WRITTEN {slot_name} → {resolved_path}")
            else:
                skipped.append({
                    "verified_id": verified_id,
                    "slot_id": slot_id,
                    "reason": "write_failed",
                })
                print(f"    [publisher] FAILED to write {slot_name}")

        elapsed_ms = (time.monotonic() - start) * 1000

        return {
            "session_id": session_id,
            "published_files": published,
            "skipped_files": skipped,
            "published_count": len(published),
            "skipped_count": len(skipped),
            "metrics": {
                "latency_ms": elapsed_ms,
            },
        }

    def _resolve_file_path(
        self, session_id: str, slot_id: str, fallback_path: str
    ) -> str | None:
        """Resolve the file path via SLICED_FROM chain to FileNode.

        Follows: FunctionSlot →(SLICED_FROM)→ FileNode → get path property.
        Falls back to the FileNode's file_path property if SLICED_FROM doesn't exist.
        Falls back to the slot's file_path property.
        """
        slot = self._soma.get_node(slot_id)
        if not slot:
            return None

        # Try SLICED_FROM edge to FileNode
        edges = self._soma.get_edges(slot_id)
        for edge in edges:
            if edge.rel_type == "SLICED_FROM":
                file_node = self._soma.get_node(edge.target)
                if file_node and file_node.node_type == "FileNode":
                    path = file_node.properties.get("path") or file_node.properties.get("file_path", "")
                    if path:
                        return path

        # Fallback to slot's file_path
        return slot.properties.get("file_path", fallback_path)

    def _write_code(self, file_path: str, code: str, session_id: str) -> bool:
        """Write code to disk at the resolved file_path."""
        try:
            workspace = self._get_workspace_path(session_id)
            if not workspace:
                print(f"    [publisher] ERROR: workspace not found for {session_id}")
                return False

            target = workspace / file_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(code, encoding="utf-8")
            return True
        except Exception as e:
            print(f"    [publisher] ERROR writing {file_path}: {e}")
            return False

    def _get_workspace_path(self, session_id: str) -> Path | None:
        """Get workspace path for the session."""
        import re
        safe_id = re.sub(r"[^\w.-]", "_", session_id)
        candidate = Path.home() / "soma" / "chats" / safe_id / "workspace"
        if candidate.exists():
            return candidate
        return None