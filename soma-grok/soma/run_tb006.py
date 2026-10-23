"""TB-006 Runner — Spark Dendrite (Requirements from Blueprint).

Usage: python3 run_tb006.py <session_dir>
"""
from __future__ import annotations

import sys
from pathlib import Path

# No hardcoded workspace path insert

from store import Soma
from pipeline.llm_sdk import TurnKeyClient
from pipeline.chat_log_adapter import ChatSetRecord
from session_seeder import seed_session


class _SimpleRotator:
    """Minimal stand-in — no ModelRotator import allowed (TB-FIX-004)."""
    def __init__(self, models: list[str]) -> None:
        self._models = models
    def next_model(self, role: str = "") -> str:
        return self._models[0] if self._models else "mock-model"
from classifier_dendrite import ClassifierDendrite
from nexus_dendrite import NexusDendrite
from spark_dendrite import SparkDendrite
from session_loader import load_session


def main(path: Path) -> int:
    print("=" * 70)
    print("TB-006: Spark Dendrite — Requirements Derivation")
    print("=" * 70)

    # 1. Load session using the loader
    all_data, reason = load_session(path)
    if reason != "ok":
        print(f"NO RECORDS {reason}")
        return 2

    session_id = str(all_data[0]["session_id"])

    soma = Soma()
    print(f"\nLoaded {len(all_data)} ChatSets...")

    chatsets = [ChatSetRecord(
        chat_set_id=str(d["chat_set_id"]),
        session_id=str(d["session_id"]),
        set_number=int(d.get("set_number", 0)),
        user_text=str(d.get("user_text", "")),
        assistant_text=str(d.get("assistant_text", "")),
    ) for d in all_data]

    anchor_id, stats = seed_session(soma, chatsets, session_id=session_id)
    print(f"Soma seeded: {soma.node_count()} nodes, {soma.edge_count()} edges")

    # 2. Run Classifier
    print(f"\nRunning Classifier on {len(chatsets)} ChatSets...")
    llm = TurnKeyClient()
    rotator = _SimpleRotator(["mock-model"])
    classifier = ClassifierDendrite(soma, llm, rotator)

    for cs in chatsets:
        classifier.run(f"cs-{cs.chat_set_id}")
    print(f"  → {soma.node_count()} nodes")

    # 3. Run Nexus
    print(f"Running Nexus...")
    nexus = NexusDendrite(soma, llm, rotator)
    nexus_result = nexus.run(session_id)
    bp_id = nexus_result.get("blueprint_id", "N/A")
    print(f"  → Blueprint: {bp_id}")
    print(f"  → {soma.node_count()} nodes")

    # 4. Run Spark
    print(f"\n{'='*70}")
    print(f"Running Spark on session '{session_id}'...")
    spark = SparkDendrite(soma, llm, rotator)
    spark_result = spark.run(session_id)

    print(f"\nSpark result:")
    for k, v in spark_result.items():
        if k != "metrics":
            print(f"  {k}: {v}")

    # 5. Show RequirementsNode details
    req_nodes = [n for n in soma._nodes.values() if n.node_type == "RequirementsNode"]
    if req_nodes:
        req = req_nodes[0]
        req_text = req.properties.get('requirement_text', '')
        print(f"\nRequirementsNode:")
        print(f"  id: {req.id}")
        print(f"  session_id: {req.properties.get('session_id')}")
        print(f"  requirement_text (first 500 chars): {req_text[:500]}")

    # 6. Final summary
    print(f"\n{'='*70}")
    print("FINAL STATE")
    node_types = {}
    for n in soma._nodes.values():
        node_types.setdefault(n.node_type, []).append(n.id)
    for ntype, nids in sorted(node_types.items()):
        print(f"  {ntype}: {len(nids)}")
    print(f"  Edges: {soma.edge_count()}")
    print(f"\nTB-006 COMPLETE")

    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 run_tb006.py <session_dir>")
        sys.exit(1)
    session_dir = Path(sys.argv[1])
    sys.exit(main(session_dir))