"""TB-007 Runner — Falcon Dendrite (Architecture + Contract).

Usage: python3 run_tb007.py <session_dir>
"""
from __future__ import annotations

import sys
from pathlib import Path

# No hardcoded workspace path insert

from store import Soma
from pipeline.llm_sdk import TurnKeyClient
from pipeline.chat_log_adapter import ChatSetRecord
from session_seeder import seed_session
from classifier_dendrite import ClassifierDendrite
from nexus_dendrite import NexusDendrite
from spark_dendrite import SparkDendrite
from falcon_dendrite import FalconDendrite
from session_loader import load_session


class _SimpleRotator:
    """Minimal stand-in — no ModelRotator import allowed."""
    def __init__(self, models):
        self._models = models
    def next_model(self, role=""):
        return self._models[0] if self._models else "mock-model"



def main(path: Path) -> int:
    print("=" * 70)
    print("TB-007: Falcon Dendrite — Architecture + Contract")
    print("=" * 70)

    # Load session using the loader
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

    anchor_id, _ = seed_session(soma, chatsets, session_id=session_id)

    llm = TurnKeyClient()
    rotator = _SimpleRotator(["mock-model"])

    # Classifier → Nexus → Spark → Falcon
    print("Running Classifier on all ChatSets...")
    classifier = ClassifierDendrite(soma, llm, rotator)
    for cs in chatsets:
        classifier.run(f"cs-{cs.chat_set_id}")
    print(f"  → {soma.node_count()} nodes")

    print("Running Nexus...")
    nexus = NexusDendrite(soma, llm, rotator)
    nexus.run(session_id)
    print(f"  → {soma.node_count()} nodes")

    print("Running Spark...")
    spark = SparkDendrite(soma, llm, rotator)
    spark.run(session_id)
    print(f"  → {soma.node_count()} nodes")

    print("\n" + "=" * 70)
    print("Running Falcon...")
    falcon = FalconDendrite(soma, llm, rotator)
    falcon_result = falcon.run(session_id)

    print(f"\nFalcon result:")
    for k, v in falcon_result.items():
        if k != "metrics":
            print(f"  {k}: {v}")

    # Show ArchitectureNode
    arch_nodes = [n for n in soma._nodes.values() if n.node_type == "ArchitectureNode"]
    if arch_nodes:
        arch = arch_nodes[0]
        print(f"\nArchitectureNode:")
        print(f"  id: {arch.id}")
        print(f"  session_id: {arch.properties.get('session_id')}")
        print(f"  architecture_text (first 300 chars): {arch.properties.get('architecture_text', '')[:300]}")

    # Show ArchitectureContractNode
    contract_nodes = [n for n in soma._nodes.values() if n.node_type == "ArchitectureContractNode"]
    if contract_nodes:
        contract = contract_nodes[0]
        print(f"\nArchitectureContractNode:")
        print(f"  id: {contract.id}")
        print(f"  contract_text: {contract.properties.get('contract_text', '')}")
    else:
        print("\nNo ArchitectureContractNode created (Falcon contract path errored or no constraints)")

    # Show edges
    print(f"\nEdges involving ArchitectureNode:")
    for edge in soma._edges:
        if edge.source.startswith("arch-") or edge.target.startswith("arch-"):
            print(f"  {edge.source} --[{edge.rel_type}]--> {edge.target}")

    # Final summary
    print(f"\n{'='*70}")
    print("FINAL STATE")
    node_types = {}
    for n in soma._nodes.values():
        node_types.setdefault(n.node_type, []).append(n.id)
    for ntype, nids in sorted(node_types.items()):
        print(f"  {ntype}: {len(nids)}")
    print(f"  Edges: {soma.edge_count()}")
    print(f"\nTB-007 COMPLETE")

    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 run_tb007.py <session_dir>")
        sys.exit(1)
    session_dir = Path(sys.argv[1])
    sys.exit(main(session_dir))