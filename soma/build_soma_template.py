"""Generate the Soma SQLite database template with schema, views,
placeholder data, and all 14 stage instructions loaded from machine-talk/*.v2.md."""

import re
import sqlite3
import json
from pathlib import Path
from datetime import datetime, timezone

# ── Paths ───────────────────────────────────────────────────────────────
BASE = Path("/home/flintx/soma-10-14/soma")
MACHINETALK = BASE / "machine-talk"
OUTPUT = BASE / "soma_template.sql"

# ── Stage instruction loading ──────────────────────────────────────────
STAGE_CONFIG = [
    ("tb-001-distiller.v2.md",      "distiller",   "tb-001", None,    True),
    ("tb-002-pipeline-protocol.v2.md","pipeline_protocol","tb-002", None, True),
    ("tb-003-system-base.v2.md",    "system_base", "tb-003", None, True),
    ("tb-004-introbeaver.v2.md",    "introbeaver", "tb-004", None, True),
    ("tb-005-planbeaver.v2.md",     "planbeaver",  "tb-005", None, True),
    ("tb-006-outrobeaver.v2.md",    "outrobeaver", "tb-006", None, True),
    ("tb-007-nexus.v2.md",          "nexus",       "tb-007", None, True),
    ("tb-008-spark.v2.md",          "spark",       "tb-008", None, True),
    ("tb-009-falcon.v2.md",         "falcon",      "tb-009", None, True),
    ("tb-010-eagle.v2.md",          "eagle",       "tb-010", None, True),
    ("tb-011-drafter.v2.md",        "drafter",     "tb-011", None, True),
    ("tb-012-scout.v2.md",          "scout",       "tb-012", None, True),
    ("tb-013-oc.v2.md",             "oc",          "tb-013", None, True),
    ("tb-014-olc.v2.md",            "olc",         "tb-014", None, True),
]

def load_stage_instructions():
    """Read each .v2.md file and return (stage_name, tb_number, body) tuples."""
    instructions = []
    for filename, stage_name, tb_number, _, handoff in STAGE_CONFIG:
        fpath = MACHINETALK / filename
        if not fpath.exists():
            raise FileNotFoundError(f"Missing: {fpath}")
        body = fpath.read_text(encoding="utf-8")
        # Strip leading markdown headers (version/classification lines)
        body = re.sub(r'^#\s+#?\s*VERSION:\s+.*?\n', '', body, flags=re.M)
        body = re.sub(r'^#\s+#?\s*CLASSIFICATION:\s+.*?\n', '', body, flags=re.M)
        body = re.sub(r'^#\s+#?\s*SUPERSEDES:\s+.*?\n', '', body, flags=re.M)
        body = re.sub(r'^#\s+#?\s*TOKEN_CEILING:\s+.*?\n', '', body, flags=re.M)
        instructions.append((stage_name, tb_number, body.strip()))
    return instructions

# ── SQL Schema ──────────────────────────────────────────────────────────
SCHEMA = """\
-- ═══════════════════════════════════════════════════════════════════
-- SOMA SQLITE DATABASE TEMPLATE
-- Per-session graph store with stage instructions and controlled projections
-- Generated: {generated_at}
-- ═══════════════════════════════════════════════════════════════════

PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
PRAGMA encoding='UTF-8';
PRAGMA page_size=4096;

-- ── Sessions table ──────────────────────────────────────────────────
CREATE TABLE sessions (
    session_id        TEXT PRIMARY KEY,
    project_context   TEXT DEFAULT 'Dendritic',
    total_sets        INTEGER DEFAULT 0,
    total_session_chars INTEGER DEFAULT 0,
    created_at        TEXT DEFAULT (datetime('now'))
);

-- ── Nodes table ─────────────────────────────────────────────────────
CREATE TABLE nodes (
    node_id     TEXT PRIMARY KEY,
    node_type   TEXT NOT NULL CHECK(node_type IN (
        'SessionAnchor', 'ChatSet', 'Message', 'ReceptorLog',
        'DistilledChatSet', 'Directive', 'Constraint', 'Artifact',
        'Stack', 'Chronology', 'NoiseSignature', 'Entity',
        'Chunk', 'ChatSetGroup', 'IntentEntry', 'IntentNode'
    )),
    properties  TEXT NOT NULL,
    created_at  TEXT DEFAULT (datetime('now'))
);
CREATE INDEX idx_nodes_type   ON nodes(node_type);
CREATE INDEX idx_nodes_sid    ON nodes(properties->>'$.session_id');
CREATE INDEX idx_nodes_csid   ON nodes(properties->>'$.chat_set_id');

-- ── Edges table ─────────────────────────────────────────────────────
CREATE TABLE edges (
    edge_id   TEXT PRIMARY KEY,
    source    TEXT NOT NULL REFERENCES nodes(node_id),
    rel_type  TEXT NOT NULL CHECK(rel_type IN (
        'CONTAINS', 'HAS_MESSAGE', 'PROCESSED_BY', 'DISTILLED_TO',
        'HAS_DIRECTIVE', 'HAS_CONSTRAINT', 'HAS_ARTIFACT',
        'HAS_STACK', 'HAS_CHRONOLOGY', 'HAS_NOISE',
        'HAS_CHATSET_GROUP', 'HAS_CHUNK', 'NEXT_CHUNK', 'NEXT_GROUP',
        'YIELDS', 'GOVERNS', 'LINKED_TO', 'SLICED_FROM', 'TRACES_TO'
    )),
    target    TEXT NOT NULL REFERENCES nodes(node_id)
);
CREATE INDEX idx_edges_source ON edges(source);
CREATE INDEX idx_edges_target ON edges(target);
CREATE INDEX idx_edges_rel    ON edges(rel_type);

-- ── Stage Instructions table ────────────────────────────────────────
CREATE TABLE stage_instructions (
    stage_name  TEXT PRIMARY KEY,
    tb_number   TEXT,
    body        TEXT NOT NULL,
    handoff     INTEGER DEFAULT 0,
    loaded_from TEXT,
    version     INTEGER DEFAULT 1
);
"""

# ── Views ─────────────────────────────────────────────────────────────
VIEWS = """\
-- ═══════════════════════════════════════════════════════════════════
-- CONTROLLED PROJECTIONS (per-stage views)
-- Each stage queries its view, never the base tables directly.
-- ═══════════════════════════════════════════════════════════════════

-- Stage 1: Distiller — raw chatsets only
CREATE VIEW stage1_distiller_input AS
  SELECT n.node_id, n.properties
  FROM nodes n
  WHERE n.node_type = 'ChatSet';

-- Stage 1: IntroBeaver — raw chatsets (all messages)
CREATE VIEW stage1_introbeaver_input AS
  SELECT n.node_id, n.properties,
         e.source AS chatset_ref
  FROM nodes n
  JOIN edges e ON n.node_id = e.target
  WHERE e.rel_type = 'HAS_MESSAGE';

-- Stage 1: IntroBeaver — distilled output from distiller
CREATE VIEW stage1_distiller_output AS
  SELECT n.node_id, n.properties
  FROM nodes n
  WHERE n.node_type = 'DistilledChatSet';

-- Stage 1: PlanBeaver — distilled + directives + constraints
CREATE VIEW stage1_planbeaver_input AS
  SELECT n.node_id, n.properties, e.rel_type
  FROM nodes n
  JOIN edges e ON n.node_id = e.target
  WHERE n.node_type IN ('DistilledChatSet', 'Directive', 'Constraint');

-- Stage 1: OutroBeaver — all stage 1 outputs for session
CREATE VIEW stage1_outrobeaver_input AS
  SELECT n.node_id, n.properties, n.node_type
  FROM nodes n
  WHERE n.node_type IN ('DistilledChatSet', 'Directive', 'Constraint', 'Artifact', 'Stack', 'Chronology', 'NoiseSignature');

-- Stage 2: Nexus — all distilled chatsets for session
CREATE VIEW stage2_nexus_input AS
  SELECT n.node_id, n.properties
  FROM nodes n
  WHERE n.node_type = 'DistilledChatSet'
  ORDER BY CAST(json_extract(n.properties, '$.set_number') AS INTEGER);

-- Stage 2: Spark — blueprint from nexus
CREATE VIEW stage2_spark_input AS
  SELECT n.node_id, n.properties
  FROM nodes n
  WHERE n.node_type = 'StrategicBlueprintNode'
     OR n.node_type = 'SessionAnchor';

-- Stage 2: Falcon — spark requirements
CREATE VIEW stage2_falcon_input AS
  SELECT n.node_id, n.properties
  FROM nodes n
  WHERE n.node_type = 'RequirementsNode'
     OR n.node_type = 'StrategicBlueprintNode';

-- Stage 3: Eagle — falcon execution plan
CREATE VIEW stage3_eagle_input AS
  SELECT n.node_id, n.properties
  FROM nodes n
  WHERE n.node_type = 'ArchitectureNode'
     OR n.node_type = 'ArchitectureContractNode'
     OR n.node_type = 'RequirementsNode';

-- Stage 3: Drafter — eagle architecture
CREATE VIEW stage3_drafter_input AS
  SELECT n.node_id, n.properties
  FROM nodes n
  WHERE n.node_type IN ('ArchitectureNode', 'FileNode', 'ReferenceArtifactNode')
     OR n.node_type = 'ArchitectureContractNode';

-- Stage 3: Scout — draft artifacts
CREATE VIEW stage3_scout_input AS
  SELECT n.node_id, n.properties
  FROM nodes n
  WHERE n.node_type IN ('FileNode', 'ReferenceArtifactNode', 'ArchitectureContractNode');

-- Stage 4: OC (AxonHillock) — scout report
CREATE VIEW stage4_oc_input AS
  SELECT n.node_id, n.properties
  FROM nodes n
  WHERE n.node_type IN ('InvariantQueryNode', 'FunctionSlotNode');

-- Stage 4: OLC (Myelinator) — approved drafts
CREATE VIEW stage4_olc_input AS
  SELECT n.node_id, n.properties
  FROM nodes n
  WHERE n.node_type IN ('ImplementationNode', 'SmokeTestNode', 'OptimizedSlotNode', 'SessionManifestNode');

-- Universal read views (for debugging / introspection)
CREATE VIEW node_types AS
  SELECT node_type, COUNT(*) AS count
  FROM nodes
  GROUP BY node_type;

CREATE VIEW edge_types AS
  SELECT rel_type, COUNT(*) AS count
  FROM edges
  GROUP BY rel_type;

-- Session summary view
CREATE VIEW session_summary AS
  SELECT
    s.session_id,
    s.project_context,
    s.total_sets,
    s.total_session_chars,
    COUNT(DISTINCT CASE WHEN n.node_type = 'ChatSet' THEN n.node_id END) AS chatset_count,
    COUNT(DISTINCT CASE WHEN n.node_type = 'DistilledChatSet' THEN n.node_id END) AS distilled_count,
    COUNT(DISTINCT CASE WHEN e.rel_type = 'HAS_DIRECTIVE' THEN e.edge_id END) AS directive_count,
    COUNT(DISTINCT CASE WHEN e.rel_type = 'HAS_CONSTRAINT' THEN e.edge_id END) AS constraint_count,
    COUNT(DISTINCT CASE WHEN e.rel_type = 'HAS_ARTIFACT' THEN e.edge_id END) AS artifact_count
  FROM sessions s
  LEFT JOIN nodes n ON s.session_id = json_extract(n.properties, '$.session_id')
  LEFT JOIN edges e ON n.node_id = e.source
  GROUP BY s.session_id;
"""

# ── Placeholder Data ──────────────────────────────────────────────────
def sql_json(obj):
    """Convert Python dict to SQL-safe compact JSON string."""
    raw = json.dumps(obj, separators=(",", ":"))
    return raw.replace("'", "''")


def make_placeholder_data():
    """Generate realistic placeholder node/edge data for a demo session."""
    now = datetime.now(timezone.utc).isoformat()
    nodes = []
    edges = []
    edge_counter = [0]  # mutable counter for unique IDs

    def next_edge_id():
        eid = f"edge-{edge_counter[0]:03d}"
        edge_counter[0] += 1
        return eid

    # Session row (one SessionAnchor node)
    anchor_id = "anchor-demo-001"
    props = {"id": anchor_id, "session_id": "demo-001",
             "project_context": "Dendritic", "total_sets": 5,
             "total_session_chars": 12500, "created_at": now}
    nodes.append((anchor_id, "SessionAnchor", f"'{sql_json(props)}'"))

    # Create a few ChatSets with messages
    cs_ids = [
        "demo-001:0001.1", "demo-001:0002.1", "demo-001:0003.1"
    ]
    for i, cs_id in enumerate(cs_ids):
        props = {"id": cs_id, "session_id": "demo-001",
                 "set_number": i + 1, "chars": 800 + i * 400,
                 "provider": "kimi-og", "models_used": '["openai/gpt-oss-20b"]',
                 "chatset_hash": f"a{16+i:064x}"}
        nodes.append((cs_id, "ChatSet", f"'{sql_json(props)}'"))
        edges.append((next_edge_id(), anchor_id, "CONTAINS", cs_id))

        # Messages
        props = {"id": f"msg-{cs_id}-0", "session_id": "demo-001",
                 "chat_set_id": cs_id, "turn_index": 0,
                 "role": "USER", "chars": 500,
                 "content": f"USER message {i+1}: Build a Python CLI tool that processes clipboard data. Must run as user, never as root. Prefer asyncio."}
        nodes.append((f"msg-{cs_id}-0", "Message", f"'{sql_json(props)}'"))
        edges.append((next_edge_id(), cs_id, "HAS_MESSAGE", f"msg-{cs_id}-0"))

        props = {"id": f"msg-{cs_id}-1", "session_id": "demo-001",
                 "chat_set_id": cs_id, "turn_index": 1,
                 "role": "AGENT", "chars": 700 + i * 200,
                 "content": f"AGENT response {i+1}: Drafting the specification with asyncio-based architecture."}
        nodes.append((f"msg-{cs_id}-1", "Message", f"'{sql_json(props)}'"))
        edges.append((next_edge_id(), cs_id, "HAS_MESSAGE", f"msg-{cs_id}-1"))

        # Distilled ChatSet
        dist_id = f"distilled-{cs_id}"
        props = {"id": dist_id, "session_id": "demo-001",
                 "chat_set_id": cs_id, "set_number": i + 1,
                 "chatset_hash": f"a{16+i:064x}",
                 "intent": f"Build CLI tool with asyncio processing for {i+1}'s clipboard data requirements",
                 "signal_quality": 0.75 + i * 0.05,
                 "bytes_original": 800 + i * 400, "bytes_distilled": 300 + i * 50,
                 "skip": False, "skip_reason": None, "exfil_type": None,
                 "model_id": "deepseek/deepseek-v4.1-flash", "latency_ms": 25000,
                 "processed_at": now}
        nodes.append((dist_id, "DistilledChatSet", f"'{sql_json(props)}'"))
        edges.append((next_edge_id(), cs_id, "DISTILLED_TO", dist_id))

        # Directives
        for j in range(2):
            dir_id = f"directive-{cs_id}-{j}"
            props = {"id": dir_id, "session_id": "demo-001",
                     "chat_set_id": cs_id,
                     "text": f"Process clipboard data using asyncio pattern {j+1}",
                     "index": j}
            nodes.append((dir_id, "Directive", f"'{sql_json(props)}'"))
            edges.append((next_edge_id(), dist_id, "HAS_DIRECTIVE", dir_id))

        # Constraints
        for j in range(2):
            con_id = f"constraint-{cs_id}-{j}"
            props = {"id": con_id, "session_id": "demo-001",
                     "chat_set_id": cs_id,
                     "text": ["Never run as root", "Must use asyncio for I/O"][j],
                     "index": j}
            nodes.append((con_id, "Constraint", f"'{sql_json(props)}'"))
            edges.append((next_edge_id(), dist_id, "HAS_CONSTRAINT", con_id))

        # Artifacts
        for j in range(1):
            art_id = f"artifact-{cs_id}-{j}"
            props = {"id": art_id, "session_id": "demo-001",
                     "chat_set_id": cs_id,
                     "path": f"/home/flintx/project/clipboard_tool_{i+1}.py",
                     "index": j}
            nodes.append((art_id, "Artifact", f"'{sql_json(props)}'"))
            edges.append((next_edge_id(), dist_id, "HAS_ARTIFACT", art_id))

        # Receptor Log
        rec_id = f"receptor-{cs_id}"
        props = {"id": rec_id, "session_id": "demo-001",
                 "chat_set_id": cs_id, "set_number": i + 1,
                 "model_id": "deepseek/deepseek-v4.1-flash",
                 "latency_ms": 30000, "verdict": "false",
                 "skipped": False, "timestamp": now}
        nodes.append((rec_id, "ReceptorLog", f"'{sql_json(props)}'"))
        edges.append((next_edge_id(), cs_id, "PROCESSED_BY", rec_id))

    return nodes, edges


def main():
    print("Loading stage instructions...")
    instructions = load_stage_instructions()
    total_bytes = sum(len(b) for _, _, b in instructions)
    print(f"  {len(instructions)} instructions loaded, {total_bytes:,} bytes total")

    # Escape SQL strings
    def sql_str(s):
        return s.replace("'", "''")

    # Build SQL
    sql_parts = []
    sql_parts.append(SCHEMA.format(generated_at=datetime.now(timezone.utc).isoformat()))

    # Insert stage instructions
    sql_parts.append("-- ═══════════════════════════════════════════════════════════════════\n-- STAGE INSTRUCTIONS (loaded from machine-talk/*.v2.md)\n-- ═══════════════════════════════════════════════════════════════════\n")
    for stage_name, tb_number, body in instructions:
        tb_num = f"'{tb_number}'"
        handoff_val = 1 if tb_number in ("tb-002",) else 0
        loaded_from = f"'machine-talk/{stage_name}.v2.md'"
        sql_parts.append(
            f"INSERT INTO stage_instructions (stage_name, tb_number, body, handoff, loaded_from, version) "
            f"VALUES ('{stage_name}', {tb_num}, '{sql_str(body)}', {handoff_val}, {loaded_from}, 1);\n"
        )

    sql_parts.append("\n" + VIEWS)

    # Placeholder data
    sql_parts.append("\n-- ═══════════════════════════════════════════════════════════════════\n"
                     "-- PLACEHOLDER DATA (demo session — remove before production)\n"
                     "-- ═══════════════════════════════════════════════════════════════════\n")

    nodes, edges = make_placeholder_data()
    for nid, ntype, props in nodes:
        sql_parts.append(
            f"INSERT INTO nodes (node_id, node_type, properties) VALUES ('{nid}', '{ntype}', {props});\n"
        )
    for eid, src, rtype, tgt in edges:
        sql_parts.append(
            f"INSERT INTO edges (edge_id, source, rel_type, target) VALUES ('{eid}', '{src}', '{rtype}', '{tgt}');\n"
        )

    sql_parts.append("\n-- ═══════════════════════════════════════════════════════════════════\n"
                     "-- END OF TEMPLATE\n"
                     "-- To initialize: sqlite3 somas/<session_id>/soma.db < soma_template.sql\n"
                     "-- ═══════════════════════════════════════════════════════════════════\n")

    # Write
    sql = "\n".join(sql_parts)
    OUTPUT.write_text(sql, encoding="utf-8")
    print(f"\nWritten: {OUTPUT}")
    print(f"Size: {OUTPUT.stat().st_size:,} bytes")
    print(f"Statements: {sql.count(';')}")

if __name__ == "__main__":
    main()
