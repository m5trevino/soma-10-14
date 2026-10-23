"""TB-OC-001: Active AxonHillock (OC) Multi-File Graph Slicer.

Slices all ReferenceArtifactNodes for a session into discrete FunctionSlot nodes,
linking each slot to its parent FileNode via SLICED_FROM edges.

Hard gates:
  - No filesystem access
  - No invariant rules applied in this stage
  - Only writes FunctionSlot nodes + SLICED_FROM edges to parent FileNodes
"""
from __future__ import annotations

import hashlib
import re
import time
from pathlib import Path
from typing import Any

from store import Soma
from workspace import workspace_for


CODE_STOPWORDS = {"def", "class", "import", "from", "json", "sys", "path", "return", "pass", "async", "await"}


# TB-FIN-002: Per-language top-level definition patterns. Named groups are
# used so the extractor can reliably pick the identifier for each language.
_PYTHON_PATTERN = re.compile(
    r"^\s*(?P<async>async\s+)?(?P<kind>def|class)\s+(?P<name>\w+)",
    re.MULTILINE,
)
_SHELL_PATTERN = re.compile(
    r"^\s*(?:function\s+)?(?P<name>\w+)\s*\(\s*\)\s*\{",
    re.MULTILINE,
)
_JS_PATTERN = re.compile(
    r"^\s*(?P<async>async\s+)?function\s+(?P<fname>\w+)\s*\("
    r"|^\s*(?:const|let|var)\s+(?P<arrow>\w+)\s*=\s*(?:async\s*)?\(.*\)\s*=>"
    r"|^\s*class\s+(?P<klass>\w+)",
    re.MULTILINE,
)


def _sanitize_session_id(session_id: str) -> str:
    """Make a session id safe to use in a filesystem path."""
    return re.sub(r"[^\w.-]", "_", session_id)


def _detect_language(rel_path: str) -> str:
    """TB-FIN-002: Pick a language heuristic from the file extension."""
    suffix = rel_path.lower().rsplit(".", 1)[-1] if "." in rel_path else ""
    if suffix in {"sh", "bash", "zsh", "ksh"}:
        return "shell"
    if suffix in {"js", "mjs", "cjs", "ts", "tsx"}:
        return "javascript"
    if suffix in {"py", "pyw"}:
        return "python"
    return "python"  # default for unknown / plain fixtures


def _extract_subtokens(name: str) -> list[str]:
    """TB-OC-006: Split identifier into sub-tokens for semantic matching.

    Handles snake_case and camelCase:
      execute_generators -> ["execute", "generators"]
      fetchData -> ["fetch", "data"]
    """
    # snake_case
    if "_" in name:
        return [t.lower() for t in name.split("_") if t]
    # camelCase / PascalCase: insert space before capitals, then split
    spaced = re.sub(r"([a-z])([A-Z])", r"\1 \2", name)
    return [t.lower() for t in spaced.split() if t]


def _extract_slot_spans(content: str, language: str) -> list[tuple[str, int, int]]:
    """TB-FIN-002: Return (name, start, end) for each real function/class.

    ``end`` is the start of the next top-level definition or EOF.
    """
    pattern = {
        "python": _PYTHON_PATTERN,
        "shell": _SHELL_PATTERN,
        "javascript": _JS_PATTERN,
    }.get(language)
    if pattern is None:
        return []

    matches = list(pattern.finditer(content))
    spans: list[tuple[str, int, int]] = []
    for i, m in enumerate(matches):
        if language == "python" or language == "shell":
            name = m.group("name")
        else:
            name = m.group("fname") or m.group("arrow") or m.group("klass")
        if not name:
            continue
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
        spans.append((name, start, end))
    return spans


class AxonHillockSlicer:
    """Active OC — deconstructs monolith into FunctionSlot unit cells."""

    def __init__(self, soma: Soma, llm_client: Any, rotator: Any = None) -> None:
        self._soma = soma
        self._llm = llm_client

    def run(self, session_id: str) -> dict[str, Any]:
        """TB-FIN-004: Walk the drafter workspace and slice every written file.

        Returns report with all slot_ids created, grouped by parent file.
        """
        start = time.monotonic()
        stage_name = "axon_hillock"

        workspace = workspace_for(session_id)
        if not workspace.exists():
            return {"session_id": session_id, "slot_ids": [], "error": "No workspace found"}

        # Pre-run cleanup: delete existing FunctionSlots for this session so reruns overwrite
        existing_slots = [
            n for n in self._soma.query_by_type("FunctionSlot")
            if n.properties.get("session_id") == session_id
        ]
        for slot in existing_slots:
            self._soma.delete_node(slot.node_id)

        all_slots: list[dict[str, Any]] = []
        scanned_count = 0
        skipped_count = 0
        for file_path in sorted(workspace.rglob("*")):
            if file_path.is_dir():
                continue
            rel_path = str(file_path.relative_to(workspace))
            try:
                content = file_path.read_text(encoding="utf-8")
            except Exception:
                skipped_count += 1
                continue

            scanned_count += 1
            parent_file_id = self._find_or_create_file_node(session_id, rel_path)
            slots = self.process_file(session_id, rel_path, content, parent_file_id)
            all_slots.extend(slots)

        # TB-FIN-003: Link evidence to the new slots.
        linked = self.link_evidence_to_slots(session_id)
        matched_count = sum(1 for ids in linked.values() if ids)

        elapsed_ms = (time.monotonic() - start) * 1000

        by_file: dict[str, list[str]] = {}
        for s in all_slots:
            fp = s.get("file_path", "unknown")
            by_file.setdefault(fp, []).append(s["node_id"])

        return {
            "session_id": session_id,
            "reference_count": 0,
            "scanned_count": scanned_count,
            "skipped_count": skipped_count,
            "sliced_count": len(all_slots),
            "function_slots_created": len(all_slots),
            "matched_count": matched_count,
            "slot_ids": [s["node_id"] for s in all_slots],
            "slots_by_file": by_file,
            "metrics": {
                "model_id": "unknown",
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "latency_ms": elapsed_ms,
            },
        }

    def _find_or_create_file_node(self, session_id: str, rel_path: str) -> str:
        """Return an existing FileNode id for *rel_path*, or create one."""
        for node in self._soma.query_by_type("FileNode"):
            if node.properties.get("session_id") != session_id:
                continue
            path = node.properties.get("path", node.properties.get("file_path", ""))
            if path.lstrip("/") == rel_path or path == rel_path:
                return node.node_id

        chatsets = [
            n for n in self._soma.query_by_type("ChatSet")
            if n.properties.get("session_id") == session_id
        ]
        chat_set_id = chatsets[-1].properties.get("id") if chatsets else f"cs-{session_id}"
        file_id = f"file-{session_id}-{rel_path.replace('/', '-')}"
        node = self._soma.create_node("FileNode", {
            "id": file_id,
            "session_id": session_id,
            "chat_set_id": chat_set_id,
            "path": rel_path,
            "source_text": "",
        })
        return node.node_id

    def _slice(
        self,
        code: str,
        session_id: str,
        ref_id: str,
        parent_file_id: str,
        file_path: str,
    ) -> list[dict[str, Any]]:
        """Heuristic slice: create one FunctionSlot per top-level function/class.

        TB-OC-001: Writes parent_file_node_id and file_path to each slot.
        SLICED_FROM edge links FunctionSlot to parent FileNode (not ref).
        """
        import re
        # TB-OC-004: async-aware, indentation-resilient pattern
        pattern = re.compile(r"^\s*(async\s+)?(def\s+(\w+)|class\s+(\w+))", re.MULTILINE)
        matches = pattern.finditer(code)
        slots: list[dict[str, Any]] = []

        for i, m in enumerate(matches):
            name = m.group(3) or m.group(4)
            start = m.start()
            # naive extraction: grab until next top-level or EOF
            end_match = pattern.search(code, m.end())
            end = end_match.start() if end_match else len(code)
            block = code[start:end].strip()

            slot_id = f"slot-{session_id}-{ref_id[-6:]}-{i}"
            self._soma.create_node("FunctionSlot", {
                "id": slot_id,
                "session_id": session_id,
                "parent_file_node_id": parent_file_id,
                "file_path": file_path,
                "mandate": f"Implement {name} from reference monolith",
                "terminal_id": f"T-{i}",
                "status": "draft",
                "pin_hash": "pending",
                "code_block": block,
                "inputs": ["data"],
                "outputs": ["result"],
            })
            # TB-OC-001: SLICED_FROM links to parent FileNode, not ReferenceArtifactNode
            target_id = parent_file_id if parent_file_id else ref_id
            self._soma.create_edge(slot_id, "SLICED_FROM", target_id)
            slots.append({"node_id": slot_id, "name": name, "file_path": file_path})

        # Fallback: at least one slot even if no functions/classes found
        if not slots:
            slot_id = f"slot-{session_id}-{ref_id[-6:]}-0"
            self._soma.create_node("FunctionSlot", {
                "id": slot_id,
                "session_id": session_id,
                "parent_file_node_id": parent_file_id,
                "file_path": file_path,
                "mandate": "Implement the full monolithic reference",
                "terminal_id": "T-0",
                "status": "draft",
                "pin_hash": "pending",
                "code_block": code,
                "inputs": ["data"],
                "outputs": ["result"],
            })
            target_id = parent_file_id if parent_file_id else ref_id
            self._soma.create_edge(slot_id, "SLICED_FROM", target_id)
            slots.append({"node_id": slot_id, "name": "monolith", "file_path": file_path})

        return slots

    def process_file(
        self,
        session_id: str,
        rel_path: str,
        content: str,
        parent_file_id: str = "",
    ) -> list[dict[str, Any]]:
        """TB-FIN-002: Slice one draft file into FunctionSlots for real defs only.

        Creates one FunctionSlot per top-level Python/shell/JavaScript function
        or class. No fallback monolith slot is created when no definitions are
        found. When *parent_file_id* is provided, a SLICED_FROM edge links the
        new slot to that FileNode.

        Returns the created slot descriptors as ``{"node_id": ...,
        "name": ..., "file_path": ...}`` dicts.
        """
        language = _detect_language(rel_path)
        spans = _extract_slot_spans(content, language)
        if not spans:
            return []

        file_hash = hashlib.md5(rel_path.encode("utf-8")).hexdigest()[:8]
        slots: list[dict[str, Any]] = []
        for i, (name, start, end) in enumerate(spans):
            block = content[start:end].strip()
            slot_id = f"slot-{session_id}-{file_hash}-{i}"
            self._soma.create_node("FunctionSlot", {
                "id": slot_id,
                "session_id": session_id,
                "parent_file_node_id": parent_file_id,
                "file_path": rel_path,
                "name": name,
                "mandate": f"Implement {name} from {rel_path}",
                "terminal_id": f"T-{i}",
                "status": "draft",
                "pin_hash": "pending",
                "code_block": block,
                "inputs": [],
                "outputs": [],
                "evidence_ids": [],
            })
            if parent_file_id:
                self._soma.create_edge(slot_id, "SLICED_FROM", parent_file_id)
            slots.append({"node_id": slot_id, "name": name, "file_path": rel_path})
        return slots

    def link_evidence_to_slots(self, session_id: str) -> dict[str, list[str]]:
        """TB-FIN-003 / TB-DEND-022: Attach session signal/task evidence to FunctionSlots.

        For each FunctionSlot in the session, collect the ids of DirectiveNode,
        ConstraintNode, and TaskNode whose text mentions the function name or
        the file basename. Creates actual Soma ``TRACES_TO`` edges from each
        FunctionSlot → matched evidence node (not just property storage).

        Idempotent: calling twice does not duplicate TRACES_TO edges.

        Returns a mapping from slot_id to the list of matched evidence node ids.
        """
        slots = [
            n for n in self._soma.query_by_type("FunctionSlot")
            if n.properties.get("session_id") == session_id
        ]

        evidence_nodes: list[tuple[Any, str]] = []
        for node_type in ("DirectiveNode", "ConstraintNode", "TaskNode"):
            text_key = "source_text" if node_type in ("DirectiveNode", "ConstraintNode") else "task_text"
            for node in self._soma.query_by_type(node_type):
                if node.properties.get("session_id") != session_id:
                    continue
                evidence_nodes.append((node, str(node.properties.get(text_key, "")).lower()))

        linked: dict[str, list[str]] = {}
        for slot in slots:
            name = slot.properties.get("name", "")
            file_path = slot.properties.get("file_path", "")
            file_stem = Path(file_path).stem if file_path else ""
            needles = {n.lower() for n in (name, file_stem) if n}

            matched: list[str] = []
            for node, text in evidence_nodes:
                if any(needle in text for needle in needles):
                    matched.append(node.node_id)
                    # TB-DEND-022: create actual TRACES_TO edge for graph traversal (idempotent)
                    edge_exists = False
                    for edge in self._soma._edges:
                        if (edge.source == slot.node_id
                            and edge.rel_type == "TRACES_TO"
                            and edge.target == node.node_id):
                            edge_exists = True
                            break
                    if not edge_exists:
                        self._soma.create_edge(slot.node_id, "TRACES_TO", node.node_id)

            slot.properties["evidence_ids"] = matched
            linked[slot.node_id] = matched
        return linked

