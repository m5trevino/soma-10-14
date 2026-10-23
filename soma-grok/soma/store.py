"""Minimal in-memory JSON-backed graph store."""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class Node:
    node_id: str
    node_type: str
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass
class Edge:
    source: str
    rel_type: str
    target: str
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])


class Soma:
    """Simple JSON-backed graph store."""

    def __init__(self, path: str | None = None, force_empty: bool = False) -> None:
        self._path = path
        self._nodes: dict[str, Node] = {}
        self._edges: list[Edge] = []
        self._batch_mode = False
        self._batch_dirty = False
        if path and not force_empty and Path(path).exists():
            self._load()

    def _load(self) -> None:
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for nid, ndata in data.get("nodes", {}).items():
                self._nodes[nid] = Node(
                    node_id=nid,
                    node_type=ndata["type"],
                    properties=ndata.get("properties", {}),
                )
            for edata in data.get("edges", []):
                self._edges.append(Edge(
                    source=edata["source"],
                    rel_type=edata["rel_type"],
                    target=edata["target"],
                    id=edata.get("id", ""),
                ))
        except Exception:
            pass

    def _persist(self) -> None:
        if self._path is None:
            return
        data = {
            "nodes": {
                nid: {"type": n.node_type, "properties": n.properties}
                for nid, n in self._nodes.items()
            },
            "edges": [
                {"source": e.source, "rel_type": e.rel_type, "target": e.target, "id": e.id}
                for e in self._edges
            ],
        }
        Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def create_node(self, type_name: str, properties: dict[str, Any]) -> Node:
        node_id = properties.get("id", uuid.uuid4().hex)
        node = Node(node_id=node_id, node_type=type_name, properties=dict(properties))
        self._nodes[node_id] = node
        self._batch_dirty = True
        if not self._batch_mode:
            self._persist()
        return node

    def get_node(self, node_id: str) -> Node | None:
        return self._nodes.get(node_id)

    def delete_node(self, node_id: str) -> None:
        if node_id in self._nodes:
            del self._nodes[node_id]
        self._edges = [
            e for e in self._edges
            if e.source != node_id and e.target != node_id
        ]
        self._batch_dirty = True
        if not self._batch_mode:
            self._persist()

    def query_by_type(self, type_name: str) -> list[Node]:
        return [n for n in self._nodes.values() if n.node_type == type_name]

    def create_edge(self, source: str, rel_type: str, target: str) -> str:
        self._edges.append(Edge(source=source, rel_type=rel_type, target=target))
        self._batch_dirty = True
        if not self._batch_mode:
            self._persist()
        return self._edges[-1].id

    def get_edges_for(self, node_id: str) -> list[Edge]:
        """Alias for get_edges — required by production code (run_tb004, test_tb_fix_010)."""
        return self.get_edges(node_id)

    def get_edges(self, node_id: str) -> list[Edge]:
        return [
            e for e in self._edges
            if e.source == node_id or e.target == node_id
        ]

    def start_batch(self) -> None:
        self._batch_mode = True
        self._batch_dirty = False

    def commit_batch(self) -> None:
        self._batch_mode = False
        if self._batch_dirty:
            self._persist()
            self._batch_dirty = False

    def node_count(self) -> int:
        return len(self._nodes)

    def edge_count(self) -> int:
        return len(self._edges)

    def get_all_edges(self) -> list[Edge]:
        return self._edges
