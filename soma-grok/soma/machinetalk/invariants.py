"""Local invariant registry.

Scout queries this. Eagle does not write to it.
The registry is the source of truth for laws.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


_DEFAULT_RULES = [
    {
        "rule_id": "INV-001",
        "family": "security",
        "statement": "No secrets or credentials in source.",
        "severity": "CRITICAL",
        "applies_to": ["py", "js", "ts", "go", "sh"],
    },
    {
        "rule_id": "INV-002",
        "family": "correctness",
        "statement": "Every public function must have a clear input and output.",
        "severity": "HIGH",
        "applies_to": ["py", "js", "ts", "go"],
    },
    {
        "rule_id": "INV-003",
        "family": "safety",
        "statement": "No unbounded recursion or loops without an exit condition.",
        "severity": "HIGH",
        "applies_to": ["py", "js", "ts", "go"],
    },
    {
        "rule_id": "INV-004",
        "family": "style",
        "statement": "No TODO or placeholder in committed code.",
        "severity": "MEDIUM",
        "applies_to": ["py", "js", "ts", "go", "md"],
    },
]


class InvariantRegistry:
    """Read-only store of laws. Scout is the only caller."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path
        self._rules = list(_DEFAULT_RULES)
        if path and path.exists():
            data = json.loads(path.read_text())
            if isinstance(data, list):
                self._rules = data

    def query(self, extensions: list[str] | None = None) -> list[dict[str, Any]]:
        """Return rules that apply to the given file extensions."""
        if not extensions:
            return list(self._rules)
        wanted = {e.lower().lstrip(".") for e in extensions}
        out = []
        for rule in self._rules:
            applies = {a.lower() for a in rule.get("applies_to", [])}
            if not applies or applies & wanted:
                out.append(rule)
        return out
