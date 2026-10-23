"""TB-009: Scout + AxonHillock + Myelinator.

Usage: python3 run_tb009.py <session_dir>
"""
from __future__ import annotations

import sys
from pathlib import Path

# No hardcoded workspace path insert

from store import Soma
from pipeline.chat_log_adapter import ChatSetRecord
from session_seeder import seed_session
from classifier_dendrite import ClassifierDendrite
from nexus_dendrite import NexusDendrite
from spark_dendrite import SparkDendrite
from falcon_dendrite import FalconDendrite
from drafter_dendrite import DrafterDendrite
from scout_dendrite import ScoutDendrite
from axon_hillock_oc import AxonHillockSlicer
from myelinator_olc import MyelinatorOptimizer
from pipeline.llm_sdk import TurnKeyClient
from session_loader import load_session


def main(path: Path) -> int:
    print("=" * 70)
    print("TB-009: Scout + AxonHillock + Myelinator")
    print("=" * 70)

    # Load session using the loader
    all_data, reason = load_session(path)
    if reason != "ok":
        print(f"NO RECORDS {reason}")
        return 2

    session_id = str(all_data[0]["session_id"])
    print(f"Loaded {len(all_data)} ChatSets, session={session_id[:60]}...")

    soma = Soma()
    chatsets = [ChatSetRecord(
        chat_set_id=str(d["chat_set_id"]),
        session_id=str(d["session_id"]),
        set_number=int(d.get("set_number", 0)),
        user_text=str(d.get("user_text", "")),
        assistant_text=str(d.get("assistant_text", "")),
    ) for d in all_data]
    seed_session(soma, chatsets, session_id=session_id)
    print(f"Seeded: {soma.node_count()} nodes")

    llm = TurnKeyClient()

    # Full pipeline
    print("Running Classifier...")
    c = ClassifierDendrite(soma, llm, None)
    for cs in chatsets:
        c.run(f"cs-{cs.chat_set_id}")
    print(f"  → {soma.node_count()} nodes")

    print("Running Nexus...")
    NexusDendrite(soma, llm, None).run(session_id)
    print(f"  → {soma.node_count()} nodes")

    print("Running Spark...")
    SparkDendrite(soma, llm, None).run(session_id)
    print(f"  → {soma.node_count()} nodes")

    print("Running Falcon...")
    FalconDendrite(soma, llm, None).run(session_id)
    print(f"  → {soma.node_count()} nodes")

    print("Running Drafter...")
    from drafter_dendrite import LLMClient as DrafterLLM, ModelRotator as DrafterRot
    d_llm = TurnKeyClient()
    d_rot = DrafterRot(["mock-model"])
    DrafterDendrite(soma, d_llm, None).run(session_id)
    print(f"  → {soma.node_count()} nodes")

    # TB-009: Scout
    print(f"\n{'='*70}")
    print("Running Scout...")
    scout = ScoutDendrite(soma, llm, None)
    scout_result = scout.run(session_id)
    print(f"  Scout: {scout_result.get('file_nodes_scanned')} files scanned")
    print(f"  Invariant nodes: {len(scout_result.get('invariant_nodes_created', []))}")
    print(f"  → {soma.node_count()} nodes")

    # TB-009: AxonHillock
    print(f"\nRunning AxonHillock...")
    axon = AxonHillockSlicer(soma, llm, None)
    axon_result = axon.run(session_id)
    print(f"  Scanned: {axon_result.get('scanned_count')}")
    print(f"  Sliced: {axon_result.get('sliced_count')}")
    print(f"  → {soma.node_count()} nodes")

    # TB-009: Myelinator
    print(f"\nRunning Myelinator...")
    myel = MyelinatorOptimizer(soma, llm, None)
    myel_result = myel.run(session_id)
    print(f"  Optimized: {myel_result.get('slot_count')} slots")
    print(f"  → {soma.node_count()} nodes")

    # Summary
    print(f"\n{'='*70}")
    print("FINAL STATE")
    types = {}
    for n in soma._nodes.values():
        types.setdefault(n.node_type, []).append(n.id)
    for t, ids in sorted(types.items()):
        print(f"  {t}: {len(ids)}")
    print(f"  Edges: {soma.edge_count()}")
    print("\nTB-009 COMPLETE")

    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 run_tb009.py <session_dir>")
        sys.exit(1)
    session_dir = Path(sys.argv[1])
    sys.exit(main(session_dir))