"""TB-SOMA-005: Active Scout Dendrite.

Queries FileNodes and RequirementsNodes, looks up invariants in a mock DB,
and writes InvariantQueryNode records linked via GOVERNS edges.

Hard gates:
  - No physical file reads/writes
  - No access to monolithic code payload
  - Only writes InvariantQueryNodes + connecting edges
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from typing import Any, Callable

from store import Soma


# ------------------------------------------------------------------
# Mock invariants database
# ------------------------------------------------------------------

class InvariantsDB:
    """Simulated corpus of invariant rules keyed by file pattern."""

    _RULES: dict[str, list[str]] = {
        "*.py": [
            "All functions must have type hints",
            "No mutable module-level variables",
            "All public functions must have docstrings",
        ],
        "*.json": [
            "Must be valid JSON",
            "Must have a root object or array",
        ],
        "*.md": [
            "Must have a top-level heading",
        ],
        "*test*.py": [
            "Must use pytest fixtures for Soma setup",
            "Must not write to production paths",
        ],
        "default": [
            "Must not contain hardcoded secrets",
            "Must handle errors explicitly",
        ],
    }

    def query(self, file_path: str, repo: str | None = None) -> list[str]:
        """Return invariant rules matching *file_path*."""
        results: list[str] = []
        for pattern, rules in self._RULES.items():
            if pattern == "default":
                continue
            if self._match(pattern, file_path):
                results.extend(rules)
        if not results:
            results.extend(self._RULES["default"])
        return results

    @staticmethod
    def _match(pattern: str, path: str) -> bool:
        import fnmatch
        return fnmatch.fnmatch(path, pattern)


# ------------------------------------------------------------------
# Scout Dendrite
# ------------------------------------------------------------------

class ScoutDendrite:
    """Active Scout — maps invariant laws to FileNodes via tool-calling."""

    def __init__(self, soma: Soma, llm_client: Any, repo: str | None = None, invariants_client: Any | None = None) -> None:
        self._soma = soma
        self._llm = llm_client
        self._db = invariants_client or InvariantsDB()
        self._repo = repo

    def run(self, session_id: str) -> dict[str, Any]:
        """Execute scout workflow for *session_id*.

        Returns:
            Report dict with invariant_nodes_created, metrics.
        """
        start = time.monotonic()
        stage_name = "scout"

        # 1. Query FileNodes for this session
        file_nodes = [
            n for n in self._soma.query_by_type("FileNode")
            if n.properties.get("session_id") == session_id
        ]

        # 2. Query RequirementsNodes
        req_nodes = [
            n for n in self._soma.query_by_type("RequirementsNode")
            if n.properties.get("session_id") == session_id
        ]

        # 3. Resolve repo from SessionAnchor if not provided
        repo = self._repo or ""
        if not repo:
            anchors = [
                n for n in self._soma.query_by_type("SessionAnchor")
                if n.properties.get("session_id") == session_id
            ]
            if anchors:
                repo = anchors[0].properties.get("repo", "")

        # 4. For each FileNode, query DB and write InvariantQueryNode
        invariant_ids: list[str] = []
        for fn in file_nodes:
            file_path = fn.properties.get("file_path", fn.id)
            rules = self._db.query(file_path, repo)
            for rule_text in rules:
                node_id = f"inv-{fn.id}-{uuid.uuid4().hex[:8]}"
                self._soma.create_node("InvariantQueryNode", {
                    "id": node_id,
                    "session_id": session_id,
                    "invariant_text": rule_text,
                    "target_file_node_id": fn.id,
                })
                self._soma.create_edge(fn.id, "GOVERNS", node_id)
                invariant_ids.append(node_id)

        elapsed_ms = (time.monotonic() - start) * 1000
        return {
            "session_id": session_id,
            "file_nodes_scanned": len(file_nodes),
            "requirements_found": len(req_nodes),
            "invariant_nodes_created": invariant_ids,
            "search_summary": {
                "repo_queried": repo or "auto",
                "total_invariants_found": len(invariant_ids),
                "by_family": {},
            },
            "metrics": {
                "model_id": "unknown",
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "latency_ms": elapsed_ms,
            },
        }
