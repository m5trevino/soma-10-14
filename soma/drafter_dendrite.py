"""TB-SOMA-004: Active Drafter Dendrite.

Generates a monolithic reference app and maps project FileNodes in the Soma
via active tool-calling. All Soma access goes through the tool interface.

TB-DRAFT-003: If the LLM returns no tool calls, the Drafter falls back to
extracting fenced markdown code blocks from the response content and
creates the ReferenceArtifactNode / FileNode pair programmatically.

TB-DRAFT-004: A successfully extracted code payload is written to a
deterministic temp file under /tmp/ and the absolute path is returned in the
report so the interactive runner can render a clickable file:// link.

Hard gates:
  - No physical files written to disk except workspace files under chats/<session_id>/
  - All Soma access via tool calls (fallback node creation is intentional)
  - Uses active model rotation
"""
from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from store import Soma
from workspace import workspace_for
from pipeline.atm_runner import CleanRoom


# ------------------------------------------------------------------
# LLM client abstraction (mockable / swappable)
# ------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class LLMResponse:
    """Structured LLM response with token metrics."""
    model_id: str
    content: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    latency_ms: float
    tool_calls: list[dict[str, Any]] | None = None


class LLMClient:
    """Abstract LLM client — subclass for real or mock."""

    def chat(
        self,
        messages: list[dict[str, str]],
        tools: list[dict] | None = None,
        tool_choice: str | None = None,
        model: str | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        raise NotImplementedError


class ModelRotator:
    """Rotate through a fixed list of model identifiers."""

    def __init__(self, models: list[str]) -> None:
        self._models = models
        self._idx = 0

    def next(self) -> str:
        model = self._models[self._idx]
        self._idx = (self._idx + 1) % len(self._models)
        return model


# ------------------------------------------------------------------
# Tool registry — the only surface the LLM touches
# ------------------------------------------------------------------

class ToolRegistry:
    """Callable tools backed by the Soma store."""

    _SCHEMAS: list[dict[str, Any]] = [
        {
            "type": "function",
            "function": {
                "name": "get_receptor_config",
                "description": "Fetch the ReceptorConfig for a given agent_id.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "agent_id": {"type": "string", "description": "Agent identifier"},
                    },
                    "required": ["agent_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_chatset",
                "description": "Retrieve a ChatSet node by its node_id.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "node_id": {"type": "string", "description": "ChatSet node id"},
                    },
                    "required": ["node_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "list_chatsets_for_session",
                "description": "List all ChatSet node ids for a session ordered by set_number.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "session_id": {"type": "string"},
                    },
                    "required": ["session_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "create_soma_node",
                "description": "Create a typed node in the Soma graph store.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "type_name": {"type": "string"},
                        "properties": {"type": "object"},
                    },
                    "required": ["type_name", "properties"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "create_soma_edge",
                "description": "Create a directed edge between two existing nodes.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "source_id": {"type": "string"},
                        "relationship": {"type": "string"},
                        "target_id": {"type": "string"},
                    },
                    "required": ["source_id", "relationship", "target_id"],
                },
            },
        },
    ]

    def __init__(self, soma: Soma) -> None:
        self._soma = soma
        self._handlers: dict[str, Callable] = {
            "get_receptor_config": self._get_receptor_config,
            "get_chatset": self._get_chatset,
            "list_chatsets_for_session": self._list_chatsets_for_session,
            "create_soma_node": self._create_soma_node,
            "create_soma_edge": self._create_soma_edge,
        }

    @classmethod
    def schemas(cls) -> list[dict[str, Any]]:
        return list(cls._SCHEMAS)

    def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name not in self._handlers:
            return {"ok": False, "error": f"Unknown tool: {name}"}
        try:
            result = self._handlers[name](**arguments)
            return {"ok": True, "result": result}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    # -- handlers ------------------------------------------------

    def _get_receptor_config(self, agent_id: str) -> dict | None:
        for node in self._soma.query_by_type("ReceptorConfig"):
            if node.properties.get("agent_id") == agent_id:
                return dict(node.properties)
        return None

    def _get_chatset(self, node_id: str) -> dict | None:
        node = self._soma.get_node(node_id)
        if node is None:
            return None
        return {"node_id": node.node_id, "node_type": node.node_type, "properties": dict(node.properties)}

    def _list_chatsets_for_session(self, session_id: str) -> list[dict]:
        chatsets = [
            n for n in self._soma.query_by_type("ChatSet")
            if n.properties.get("session_id") == session_id
        ]
        chatsets.sort(key=lambda n: n.properties.get("set_number", 0))
        return [
            {"node_id": n.node_id, "set_number": n.properties.get("set_number")}
            for n in chatsets
        ]

    def _create_soma_node(self, type_name: str, properties: dict[str, Any]) -> dict:
        if "id" not in properties:
            properties["id"] = uuid.uuid4().hex
        node = self._soma.create_node(type_name, properties)
        return {"node_id": node.node_id, "node_type": node.node_type}

    def _create_soma_edge(self, source_id: str, relationship: str, target_id: str) -> dict:
        edge_id = self._soma.create_edge(source_id, relationship, target_id)
        return {"edge_id": edge_id}


# ------------------------------------------------------------------
# Mock LLM client for testing
# ------------------------------------------------------------------

class MockLLMClient(LLMClient):
    """Pre-programmed LLM that returns specific tool_calls and content."""

    def __init__(self, planned_responses: list[LLMResponse] | None = None) -> None:
        self._planned = planned_responses or []
        self._idx = 0
        self.history: list[dict[str, Any]] = []

    def chat(
        self,
        messages: list[dict[str, str]],
        tools: list[dict] | None = None,
        tool_choice: str | None = None,
        model: str | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        self.history.append({"messages": messages, "tools": tools, "model": model})
        if self._idx < len(self._planned):
            response = self._planned[self._idx]
            self._idx += 1
            return response
        return LLMResponse(
            model_id=model or "mock-default",
            content="",
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
            latency_ms=0.0,
            tool_calls=[],
        )


# ------------------------------------------------------------------
# Path normalization
# ------------------------------------------------------------------

def normalize_draft_relpath(file_path: str) -> str | None:
    """Return a safe relative path under a draft workspace, or None if it escapes.

    TB-DRAFT-WRITE-001: absolute mapped paths must be forced back under the
    workspace root. Leading slashes and drive letters are dropped; any ``..``
    component that would escape the workspace results in ``None``.
    """
    p = Path(file_path)
    parts = list(p.parts)

    # Drop absolute root or Windows drive letter so the path becomes relative.
    if parts and (parts[0] == "/" or parts[0] == "\\" or parts[0].endswith(":")):
        parts = parts[1:]

    if not parts:
        parts = ["."]

    # Reject upward escapes that would leave the workspace.
    if any(part == ".." for part in parts):
        return None

    rel = Path(*parts)
    return rel.as_posix()


# ------------------------------------------------------------------
# Drafter Dendrite
# ------------------------------------------------------------------

class DrafterDendrite:
    """Active Drafter — generates reference app + FileNodes via tool-calling."""

    # Token ceiling used to warn when the model may have hit its output limit.
    COMPLETION_TOKEN_CEILING = 16000

    # Matches triple-backtick or triple-tilde fenced code blocks.
    # Captures the fence character in group 1 and the payload in group 2.
    _CODE_FENCE_RE = re.compile(
        r"(?:^|\n)(```|~~~)(?:\w+)?\n(.*?)\1(?:\n|$)",
        re.DOTALL,
    )

    def __init__(self, soma: Soma, llm_client: LLMClient, model_rotator: ModelRotator | None = None) -> None:
        self._soma = soma
        self._llm = llm_client
        self._tools = ToolRegistry(soma)
        self._rotator = model_rotator or ModelRotator(["mock-model"])
        self._metrics: list[dict[str, Any]] = []

    def _parse_code_structure(self, code: str) -> dict[str, int]:
        """TB-DRAFT-001: Parse code payload and count structural elements.
        
        Returns dict with functions, classes, imports, and character counts.
        Gracefully returns zeros if code is empty or None.
        """
        if not code:
            return {
                "functions_count": 0,
                "classes_count": 0,
                "imports_count": 0,
                "code_chars": 0,
            }
        
        # Count functions (Python def, JavaScript function)
        func_count = len(re.findall(r"^\s*(def\s+|function\s+)", code, re.MULTILINE))
        
        # Count classes
        class_count = len(re.findall(r"^\s*class\s+", code, re.MULTILINE))
        
        # Count external imports (Python import/from, JavaScript require)
        import_count = len(re.findall(r"^\s*(import\s+|from\s+[\w.]+\s+import|require\()", code, re.MULTILINE))
        
        return {
            "functions_count": func_count,
            "classes_count": class_count,
            "imports_count": import_count,
            "code_chars": len(code),
        }

    def _extract_largest_code_block(self, content: str) -> str | None:
        """TB-DRAFT-003: Extract the largest fenced code block from text.

        Supports triple-backtick and triple-tilde fences with optional
        language tags. Returns the largest payload by character count.
        """
        matches = self._CODE_FENCE_RE.findall(content)
        if not matches:
            return None
        largest = max(matches, key=lambda match: len(match[1]))
        return largest[1].strip()

    def _create_fallback_nodes(self, session_id: str, code_payload: str) -> tuple[str, str]:
        """TB-DRAFT-003: Create ReferenceArtifactNode + FileNode from fallback code.

        Returns (reference_artifact_id, file_node_id).
        """
        ref_props: dict[str, Any] = {
            "session_id": session_id,
            "code_payload": code_payload,
        }
        ref_node = self._soma.create_node("ReferenceArtifactNode", ref_props)

        # Anchor the fallback FileNode to the first ChatSet for this session.
        chatsets = self._tools.call("list_chatsets_for_session", {"session_id": session_id})
        chat_set_id = "fallback"
        if chatsets.get("ok") and chatsets["result"]:
            chat_set_id = chatsets["result"][0]["node_id"]

        file_props: dict[str, Any] = {
            "session_id": session_id,
            "chat_set_id": chat_set_id,
            "file_path": "main.py",
        }
        file_node = self._soma.create_node("FileNode", file_props)
        self._soma.create_edge(ref_node.node_id, "PRODUCES", file_node.node_id)

        return ref_node.node_id, file_node.node_id

    def _get_last_chatset_id(self, session_id: str) -> str:
        """TB-DRAFT-006: Fetch the last ChatSet node ID for schema compliance."""
        chatsets = self._tools.call("list_chatsets_for_session", {"session_id": session_id})
        if chatsets.get("ok") and chatsets["result"]:
            last = max(chatsets["result"], key=lambda x: x.get("set_number", 0))
            return last["node_id"]
        return "fallback"

    def _phase1_map_files(self, session_id: str, task_plan: str) -> list[str]:
        """TB-DRAFT-006: Make a planning call to get the list of target file paths."""
        model_id = self._rotator.next_model("drafter")
        print(f"    [drafter] Phase 1: Mapping architecture with {model_id}...", flush=True)
        messages = [
            {
                "role": "system",
                "content": (
                    "You are the Drafter Dendrite — Architectural Mapper. "
                    "Given the task plan below, output a flat JSON list of file paths "
                    "that the implementation will need. No code, no explanation, "
                    "just a JSON array of strings like [\"app.py\", \"utils/helpers.py\"]."
                ),
            },
            {"role": "user", "content": f"Task plan:\n{task_plan}"},
        ]

        llm_start = time.monotonic()
        response = self._llm.chat(messages=messages, model=model_id)
        llm_latency_ms = (time.monotonic() - llm_start) * 1000
        print(f"    [drafter] Phase 1 complete — {llm_latency_ms / 1000.0:.1f}s | "
              f"{response.prompt_tokens} prompt / {response.completion_tokens} completion tokens", flush=True)

        self._metrics.append({
            "phase": "planning",
            "model_id": model_id,
            "prompt_tokens": response.prompt_tokens,
            "completion_tokens": response.completion_tokens,
            "total_tokens": response.total_tokens,
            "latency_ms": llm_latency_ms,
        })

        file_paths: list[str] = []
        try:
            content = response.content.strip()
            start = content.find("[")
            end = content.rfind("]")
            if start != -1 and end != -1 and end > start:
                file_paths = json.loads(content[start:end + 1])
            if not isinstance(file_paths, list):
                file_paths = []
        except Exception:
            file_paths = []

        if not file_paths:
            file_paths = ["main.py"]
        print(f"    [drafter] Mapped {len(file_paths)} file(s):", flush=True)
        for i, path in enumerate(file_paths, start=1):
            print(f"      [{i}/{len(file_paths)}] {path}", flush=True)
        return file_paths

    def _phase2_generate_file(
        self,
        session_id: str,
        file_path: str,
        file_node_id: str,
        task_plan: str,
        index: int = 1,
        total: int = 1,
    ) -> tuple[str, dict[str, Any]]:
        """TB-DRAFT-007: Make exactly one LLM call to generate code for a specific file."""
        model_id = self._rotator.next_model("drafter")
        print(f"    [drafter] [{index}/{total}] Generating {file_path} with {model_id}...", flush=True)
        messages = [
            {
                "role": "system",
                "content": (
                    "You are the Drafter Dendrite — Code Generator. "
                    "Generate the complete, working implementation for the specified file. "
                    "Output only the code, no explanations."
                ),
            },
            {
                "role": "user",
                "content": f"Task plan:\n{task_plan}\n\nGenerate code for file: {file_path}",
            },
        ]

        llm_start = time.monotonic()
        response = self._llm.chat(messages=messages, model=model_id)
        llm_latency_ms = (time.monotonic() - llm_start) * 1000
        print(f"    [drafter] [{index}/{total}] {file_path} complete — {llm_latency_ms / 1000.0:.1f}s | "
              f"{response.prompt_tokens} prompt / {response.completion_tokens} completion tokens", flush=True)

        code_payload = response.content

        ref_props: dict[str, Any] = {
            "session_id": session_id,
            "code_payload": code_payload,
            "file_path": file_path,
        }
        ref_node = self._soma.create_node("ReferenceArtifactNode", ref_props)
        self._soma.create_edge(ref_node.node_id, "PRODUCES", file_node_id)

        metrics: dict[str, Any] = {
            "phase": "generation",
            "file_path": file_path,
            "model_id": model_id,
            "prompt_tokens": response.prompt_tokens,
            "completion_tokens": response.completion_tokens,
            "total_tokens": response.total_tokens,
            "latency_ms": llm_latency_ms,
        }
        self._metrics.append(metrics)

        return ref_node.node_id, metrics

    def _sanitize_session_id(self, session_id: str) -> str:
        """Make a session id safe to use in a filesystem path."""
        return re.sub(r"[^\w.-]", "_", session_id)

    def _get_workspace_path(self, session_id: str) -> Path:
        """Get the workspace directory for this session."""
        return workspace_for(session_id)

    def _write_draft_file(self, session_id: str, file_path: str, code_payload: str) -> str | None:
        """TB-DRAFT-009/WRITE-001: Write a generated file to the workspace."""
        workspace = self._get_workspace_path(session_id)
        rel_path = normalize_draft_relpath(file_path)
        if rel_path is None:
            return None

        target = workspace / rel_path
        try:
            resolved = target.resolve()
            workspace_resolved = workspace.resolve()
            # Hard gate: refuse any path that escapes the workspace.
            if not str(resolved).startswith(str(workspace_resolved) + "/"):
                return None

            # ATM protocol (TB-ATM-001): generated code is staged inside a
            # sterile clean room where only this file is reachable and no
            # directory-scanning tool exists, then read back out and the room
            # is wiped. The agent that produced this payload therefore never
            # touches the workspace or the repo directly.
            room_id = f"drafter-{self._sanitize_session_id(session_id)}"
            with CleanRoom(slice_id=room_id) as room:
                room.write_file(rel_path, code_payload)
                draft = room.result(rel_path)

            resolved.parent.mkdir(parents=True, exist_ok=True)
            resolved.write_text(draft, encoding="utf-8")
            return str(resolved)
        except Exception:
            return None

    def run(self, session_id: str) -> dict[str, Any]:
        """Execute the drafter workflow for *session_id*.

        Phase 1: Map architecture -> file paths.
        Phase 2: Generate code for each file.
        Returns a report dict with file paths, nodes, metrics, and structure.
        """
        overall_start = time.monotonic()

        # Gather context
        chatsets = self._tools.call("list_chatsets_for_session", {"session_id": session_id})
        task_plan = self._build_task_plan(session_id, chatsets)

        # Phase 1: Map files
        file_paths = self._phase1_map_files(session_id, task_plan)

        # TB-DRAFT-006: Get last ChatSet ID for schema compliance
        last_chatset_id = self._get_last_chatset_id(session_id)

        # Create FileNodes programmatically
        file_node_ids: list[str] = []
        for path in file_paths:
            file_id = f"file-{session_id}-{path}"
            existing = self._soma.get_node(file_id)
            if existing:
                file_node_ids.append(existing.node_id)
            else:
                node = self._soma.create_node("FileNode", {
                    "id": file_id,
                    "session_id": session_id,
                    "chat_set_id": last_chatset_id,
                    "path": path,
                    "file_path": path,
                    "source_text": "",
                })
                file_node_ids.append(node.node_id)

        # Phase 2: Generate code for each file (exactly 1 call per file)
        ref_artifact_ids: list[str] = []
        per_file_metrics: list[dict[str, Any]] = []
        for i, (path, file_node_id) in enumerate(zip(file_paths, file_node_ids), start=1):
            ref_id, metrics = self._phase2_generate_file(
                session_id, path, file_node_id, task_plan, index=i, total=len(file_paths)
            )
            ref_artifact_ids.append(ref_id)
            per_file_metrics.append(metrics)

        # TB-DRAFT-009: Write files to workspace
        workspace_path = str(self._get_workspace_path(session_id))
        print(f"    [drafter] Workspace: {workspace_path}")
        written_files: list[str] = []
        for i, path in enumerate(file_paths):
            ref_node = self._soma.get_node(ref_artifact_ids[i])
            if ref_node:
                code = ref_node.properties.get("code_payload", "")
                written_path = self._write_draft_file(session_id, path, code)
                if written_path:
                    written_files.append(written_path)

        # TB-DRAFT-008: Aggregate structural stats
        total_code = ""
        for ref_id in ref_artifact_ids:
            ref_node = self._soma.get_node(ref_id)
            if ref_node:
                total_code += ref_node.properties.get("code_payload", "")
        structure = self._parse_code_structure(total_code)
        structure["file_count"] = len(file_paths)

        overall_ms = (time.monotonic() - overall_start) * 1000

        # Overall metrics include Phase 1 (planning) + Phase 2 (generation)
        all_llm_metrics = [m for m in self._metrics if m.get("phase") in ("planning", "generation")]
        total_prompt = sum(m["prompt_tokens"] for m in all_llm_metrics)
        total_completion = sum(m["completion_tokens"] for m in all_llm_metrics)
        total_tokens = sum(m["total_tokens"] for m in all_llm_metrics)

        report: dict[str, Any] = {
            "session_id": session_id,
            "file_paths": file_paths,
            "file_nodes_created": file_node_ids,
            "reference_artifact_ids": ref_artifact_ids,
            "structure": structure,
            "workspace_path": workspace_path,
            "written_files": written_files,
            "per_file_metrics": per_file_metrics,
            "metrics": {
                "model_id": per_file_metrics[0]["model_id"] if per_file_metrics else "n/a",
                "prompt_tokens": total_prompt,
                "completion_tokens": total_completion,
                "total_tokens": total_tokens,
                "llm_latency_ms": sum(m["latency_ms"] for m in all_llm_metrics),
                "overall_elapsed_ms": overall_ms,
            },
        }
        # Backward compatibility fields
        if ref_artifact_ids:
            report["reference_artifact_id"] = ref_artifact_ids[-1]
        if written_files:
            report["draft_file_path"] = written_files[-1]

        return report

    def _build_task_plan(self, session_id: str, chatsets_resp: dict) -> str:
        """Concatenate user_text from ChatSet nodes to form the task plan."""
        lines: list[str] = []
        if chatsets_resp.get("ok"):
            for entry in chatsets_resp["result"]:
                node = self._soma.get_node(entry["node_id"])
                if node:
                    text = node.properties.get("user_text", "")
                    if text:
                        lines.append(text[:500])
        return "\n---\n".join(lines) or f"Session: {session_id}"
