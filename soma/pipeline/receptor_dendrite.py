"""TB-TK-REPLACE-001: ReceptorDendrite — Heuristic chatset cleaner.

A pure, stateless artifact-transformer.  Queries a ChatSet node from the
Soma graph, extracts the raw text (user_text + assistant_text), runs
deterministic whitespace stripping, and returns cleaned text with
compression metrics.

NO LLM calls. NO graph writes.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from store import Soma, Node


# ---------------------------------------------------------------------------
# Data shapes
# ---------------------------------------------------------------------------

@dataclass
class ReceptorOutput:
    """Return value from the ReceptorDendrite."""
    chatset_id: str
    cleaned_text: str
    compression_ratio: float          # chars_out / chars_in  (0.0 — 1.0)
    bytes_original: int
    bytes_cleaned: int
    whitespace_removed: int
    lines_original: int
    lines_cleaned: int


# ---------------------------------------------------------------------------
# Heuristic cleaners (deterministic, no LLM)
# ---------------------------------------------------------------------------

# Patterns that represent pure-whitespace-only lines or excessive blank lines.
_EXCESS_BLANK = re.compile(r"\n{4,}")   # 4+ consecutive newlines → collapse to 2


def strip_raw(raw: str) -> str:
    """Deterministic whitespace cleaning.

    Steps (applied in order):
      1. Collapse runs of 4+ blank lines to 2.
      2. Strip trailing whitespace from every line.
      3. Strip leading / trailing blank space on the whole string.
    """
    raw = _EXCESS_BLANK.sub("\n\n", raw)
    raw = "\n".join(line.rstrip() for line in raw.splitlines())
    raw = raw.strip()
    return raw


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


class ReceptorDendrite:
    """Read-only transformer for a single ChatSet node."""

    def __init__(self, soma: Soma) -> None:
        self._soma = soma

    def run(self, chatset_id: str) -> ReceptorOutput:
        """Process one ChatSet and return metrics + cleaned text.

        Parameters
        ----------
        chatset_id : str
            The node-id of the ChatSet (e.g. ``session_id:1`` or ``cs-...``).

        Returns
        -------
        ReceptorOutput

        Raises
        ------
        ValueError
            If the ChatSet node is not found in Soma.
        """
        node = self._soma.get_node(chatset_id)
        if node is None:
            raise ValueError(
                f"ChatSet node {chatset_id!r} not found in Soma graph"
            )

        # ------------------------------------------------------------------
        # 1. Extract raw text from node properties
        # ------------------------------------------------------------------
        user_text = node.properties.get("user_text", "") or ""
        asst_text = node.properties.get("assistant_text", "") or ""
        raw = user_text + asst_text

        # ------------------------------------------------------------------
        # 2. Calculate original metrics (before cleaning)
        # ------------------------------------------------------------------
        bytes_original = len(raw.encode("utf-8"))
        lines_original = len(raw.splitlines())

        # ------------------------------------------------------------------
        # 3. Clean deterministically
        # ------------------------------------------------------------------
        cleaned = strip_raw(raw)

        # ------------------------------------------------------------------
        # 4. Calculate post-clean metrics
        # ------------------------------------------------------------------
        bytes_cleaned = len(cleaned.encode("utf-8"))
        lines_cleaned = len(cleaned.splitlines())
        whitespace_removed = bytes_original - bytes_cleaned

        # Safety: ratio is 0.0 if original was empty
        if bytes_original == 0:
            compression_ratio = 0.0
        else:
            compression_ratio = bytes_cleaned / bytes_original

        return ReceptorOutput(
            chatset_id=chatset_id,
            cleaned_text=cleaned,
            compression_ratio=compression_ratio,
            bytes_original=bytes_original,
            bytes_cleaned=bytes_cleaned,
            whitespace_removed=whitespace_removed,
            lines_original=lines_original,
            lines_cleaned=lines_cleaned,
        )

    def get_compression_ratio(self, chatset_id: str) -> float:
        """Convenience: just the ratio for a given ChatSet."""
        return self.run(chatset_id).compression_ratio
