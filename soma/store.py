"""SQLite-backed graph store — drop-in replacement for JSON-backed Soma."""
from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator


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
    """SQLite-backed graph store. Same API as the old JSON-backed version."""

    def __init__(self, path: str | None = None, force_empty: bool = False) -> None:
        self._path = path
        self._conn: sqlite3.Connection | None = None
        self._batch_mode = False
        self._batch_dirty = False
        if path:
            self._load_or_init(Path(path), force=force_empty)
        else:
            self._conn = self._make_conn()
            self._init_schema()

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("Soma has no connection — call with a path")
        return self._conn

    # ── connection helpers ───────────────────────────────────────────────

    @staticmethod
    def _make_conn() -> sqlite3.Connection:
        c = sqlite3.connect(":memory:", check_same_thread=False)
        c.execute("PRAGMA journal_mode=WAL")
        # FK OFF — graph edges don't always reference existing nodes
        c.row_factory = sqlite3.Row
        return c

    def _load_or_init(self, path: Path, force: bool = False) -> None:
        self._path = str(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        # If force_empty, delete existing file and start fresh
        if force and Path(self._path).exists():
            Path(self._path).unlink()

        self._conn = sqlite3.connect(self._path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        # FK OFF — graph edges don't always reference existing nodes
        self._conn.row_factory = sqlite3.Row

        # Check if tables exist
        tables = self._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        if not tables:
            self._init_schema()

    def _init_schema(self) -> None:
        tpl = Path(__file__).parent / "soma_template.sql"
        if tpl.exists():
            sql = tpl.read_text()
            self._conn.executescript(sql)
        else:
            # Minimal inline schema (fallback)
            self._conn.executescript("""
                CREATE TABLE nodes (
                    node_id TEXT PRIMARY KEY,
                    node_type TEXT NOT NULL,
                    properties TEXT NOT NULL,
                    created_at TEXT DEFAULT (datetime('now'))
                );
                CREATE TABLE edges (
                    edge_id TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    rel_type TEXT NOT NULL,
                    target TEXT NOT NULL
                );
                CREATE INDEX idx_nodes_type ON nodes(node_type);
            """)
        # FK OFF — graph edges don't always reference existing nodes
        # (template.sql sets foreign_keys=ON, we override it)
        self._conn.execute("PRAGMA foreign_keys=OFF")

    # ── CRUD (same signatures as old store.py) ───────────────────────────

    def create_node(self, type_name: str, properties: dict[str, Any]) -> Node:
        node_id = properties.get("id", uuid.uuid4().hex)
        node = Node(node_id=node_id, node_type=type_name, properties=dict(properties))
        self._ensure_node(node)
        self._batch_dirty = True
        if not self._batch_mode:
            self._persist_node(node)
        return node

    def get_node(self, node_id: str) -> Node | None:
        row = self.conn.execute(
            "SELECT node_id, node_type, properties FROM nodes WHERE node_id=?",
            (node_id,),
        ).fetchone()
        if row is None:
            return None
        props = json.loads(row["properties"]) if row["properties"] else {}
        return Node(node_id=row["node_id"], node_type=row["node_type"], properties=props)

    def delete_node(self, node_id: str) -> None:
        self.conn.execute("DELETE FROM nodes WHERE node_id=?", (node_id,))
        self.conn.execute("DELETE FROM edges WHERE source=? OR target=?", (node_id, node_id))
        self.conn.commit()
        self._batch_dirty = True
        if not self._batch_mode:
            self._persist()

    # ── edges ────────────────────────────────────────────────────────────

    def create_edge(self, source: str, rel_type: str, target: str) -> str:
        eid = str(uuid.uuid4())[:8]
        self.conn.execute(
            "INSERT INTO edges (edge_id, source, rel_type, target) VALUES (?,?,?,?)",
            (eid, source, rel_type, target),
        )
        self.conn.commit()
        self._batch_dirty = True
        if not self._batch_mode:
            self._persist()
        return eid

    def get_edges_for(self, node_id: str) -> list[Edge]:
        return self.get_edges(node_id)

    def get_edges(self, node_id: str) -> list[Edge]:
        rows = self.conn.execute(
            "SELECT edge_id, source, rel_type, target FROM edges "
            "WHERE source=? OR target=?",
            (node_id, node_id),
        ).fetchall()
        return [Edge(edge_id=r["edge_id"], source=r["source"],
                      rel_type=r["rel_type"], target=r["target"]) for r in rows]

    def get_all_edges(self) -> list[Edge]:
        rows = self.conn.execute(
            "SELECT edge_id, source, rel_type, target FROM edges"
        ).fetchall()
        return [Edge(edge_id=r["edge_id"], source=r["source"],
                      rel_type=r["rel_type"], target=r["target"]) for r in rows]

    # ── queries (same API as old store.py) ───────────────────────────────

    def query_by_type(self, type_name: str) -> list[Node]:
        rows = self.conn.execute(
            "SELECT node_id, node_type, properties FROM nodes WHERE node_type=?",
            (type_name,),
        ).fetchall()
        result = []
        for r in rows:
            props = json.loads(r["properties"]) if r["properties"] else {}
            result.append(Node(node_id=r["node_id"], node_type=r["node_type"], properties=props))
        return result

    # ── batch mode ───────────────────────────────────────────────────────

    def start_batch(self) -> None:
        self._batch_mode = True
        self._batch_dirty = False

    def commit_batch(self) -> None:
        self._batch_mode = False
        if self._batch_dirty:
            self._persist()
            self._batch_dirty = False

    # ── counts ───────────────────────────────────────────────────────────

    def node_count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]

    def edge_count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]

    # ── internal helpers ─────────────────────────────────────────────────

    def _persist_node(self, node: Node) -> None:
        props_json = json.dumps(node.properties, separators=(',', ':'))
        self.conn.execute(
            "INSERT OR REPLACE INTO nodes (node_id, node_type, properties) VALUES (?,?,?)",
            (node.node_id, node.node_type, props_json),
        )
        self.conn.commit()

    def _ensure_node(self, node: Node) -> None:
        """Ensure node exists in DB (insert or update)."""
        existing = self.conn.execute(
            "SELECT node_id FROM nodes WHERE node_id=?",
            (node.node_id,),
        ).fetchone()
        if existing:
            self._persist_node(node)
        else:
            self._persist_node(node)

    def _persist(self) -> None:
        """No-op for SQLite — changes are persistent immediately."""
        pass

    # ── cleanup ──────────────────────────────────────────────────────────

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> "Soma":
        return self

    def __exit__(self, *args) -> None:
        if self._conn is not None:
            try:
                self._conn.commit()
            except Exception:
                pass
            self._conn.close()
            self._conn = None
