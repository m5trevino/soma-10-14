"""ATM Protocol — physical clean-room isolation for execution agents.

TB-ATM-001. When a code-generation or analysis slice runs an agent, the agent
must not be able to see anything outside its own sterile directory. This
module builds that room, copies in only the target file, exposes only
``read_file`` / ``write_file`` scoped to the room, and wipes the room when the
slice finishes.

Directory-scanning tools (``ls``, ``grep``, ``find``, and explorer subagents)
are never part of the exposed toolset, so a jailed agent has zero filesystem
visibility above its assigned ``/tmp`` directory.
"""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

# The ONLY tools an execution agent is handed. Directory scanning is stripped
# on purpose — there is deliberately no ls, grep, find, or explorer here.
AGENT_TOOLSET = ("read_file", "write_file")

# Tools that must never be exposed to a jailed agent.
STRIPPED_TOOLS = ("ls", "grep", "find", "explorer")

# Clean rooms live under the system temp dir.
ATM_ROOT = Path(tempfile.gettempdir())


class CleanRoomError(Exception):
    """Raised when an agent attempts to escape its clean room."""


class CleanRoom:
    """A sterile ``/tmp`` directory for one slice's execution.

    The room is created fresh on entry (any prior state is wiped, so nothing
    bleeds between runs), holds only the target file, and is removed on exit.

    Usage::

        with CleanRoom("TB-ATM-001", target="src/thing.py") as room:
            content = room.read_file("thing.py")
            room.write_file("thing.py", updated)
            result = room.result("thing.py")
        # room no longer exists here
    """

    def __init__(self, slice_id: str, target: str | Path | None = None,
                 stub: str = "", root: Path | None = None) -> None:
        self.slice_id = slice_id
        self.root = (root or ATM_ROOT) / f"dendritic_atm_{slice_id}"
        self.target = Path(target) if target else None
        self.stub = stub

    # ── lifecycle ──────────────────────────────────────────────────────
    def __enter__(self) -> "CleanRoom":
        # Sterile: wipe any residue from a prior aborted run, then create.
        shutil.rmtree(self.root, ignore_errors=True)
        self.root.mkdir(parents=True)
        self._seed()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        # Wipe the room so no state bleeds into the next slice.
        shutil.rmtree(self.root, ignore_errors=True)

    def _seed(self) -> None:
        if self.target is None:
            return
        if self.target.exists():
            # Copy only the target file. Nothing else from the repo comes in.
            shutil.copy2(self.target, self.root / self.target.name)
        else:
            # Target missing: write an empty stub so the agent has a file to
            # read and modify, without leaking any surrounding context.
            (self.root / self.target.name).write_text(self.stub)

    # ── jailed path resolution ─────────────────────────────────────────
    def _resolve(self, rel: str) -> Path:
        """Resolve a path inside the room; reject anything that escapes it."""
        if rel.startswith("/") or "\\" in rel or rel.startswith(".."):
            # Fast-reject the obvious escapes before any filesystem work.
            raise CleanRoomError(f"path escapes clean room: {rel!r}")
        candidate = (self.root / rel).resolve()
        if candidate != self.root and self.root not in candidate.parents:
            raise CleanRoomError(f"path escapes clean room: {rel!r}")
        return candidate

    # ── the only primitives an agent gets ──────────────────────────────
    def read_file(self, rel: str) -> str:
        p = self._resolve(rel)
        if not p.is_file():
            raise CleanRoomError(f"not a file in clean room: {rel!r}")
        return p.read_text(encoding="utf-8")

    def write_file(self, rel: str, content: str) -> None:
        p = self._resolve(rel)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")

    def result(self, rel: str) -> str:
        """Read the modified file back out before the room is wiped."""
        return self.read_file(rel)

    # ── toolset surface ────────────────────────────────────────────────
    def toolset(self) -> list[str]:
        """The tools this agent is allowed to see."""
        return list(AGENT_TOOLSET)

    def stripped(self) -> list[str]:
        """The tools that were removed from this agent's toolset."""
        return list(STRIPPED_TOOLS)
