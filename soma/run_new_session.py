"""Full pipeline run on 25-12-14-permis.python.script session.

Usage: python3 run_full_pipeline.py
"""
import json, sys
from pathlib import Path

sys.path.insert(0, str(Path("/home/flintx/soma")))

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

# NEW SESSION PATH
SESSION_DIR = Path("/media/storage/dendritic123/chat-logs/sessions/25-12-14-permis.python.script")


def load_chatsets(d):
    recs = []
    for fp in sorted(d.glob("*.json")):
        try:
            data = json.load(open(fp))
        except:
            continue
        if isinstance(data, dict) and all(k in data for k in ("chat_set_id", "session_id", "set_number", "user_text")):
            try:
                recs.append(ChatSetRecord(
                    chat_set_id=str(data["chat_set_id"]),
                    session_id=str(data["session_id"]),
                    set_number=int(data.get("set_number", 0)),
                    user_text=str(data.get("user_text", "")),
                    assistant_text=str(data.get("assistant_text", "")),
                ))
            except:
                pass
    recs.sort(key=lambda r: r.set_number)
    return recs


def print_node_summary(soma):
    types = {}
    for n in soma._nodes.values():
        types.setdefault(n.node_type, []).append(n.id)
    print("\n  NODE TYPES:")
    for t, ids in sorted(types.items()):
        print(f"    {t}: {len(ids)}")
    print(f"  Edges: {soma.edge_count()}")


def main():
    print("=" * 70)
    print("FULL PIPELINE — 25-12-14-permis.python.script")
    print("=" * 70)

    # Load ChatSets
    all_data = []
    for fp in sorted(SESSION_DIR.glob("*.json")):
        try:
            data = json.load(open(fp))
            if isinstance(data, dict) and "chat_set_id" in data:
                all_data.append(data)
        except:
            pass
    all_data.sort(key=lambda r: r.get("set_number", 0))
    session_id = str(all_data[0]["session_id"])
    print(f"\nLoaded {len(all_data)} ChatSets")
    print(f"Session: {session_id[:80]}...")

    # Seed Soma
    soma = Soma()
    chatsets = [ChatSetRecord(
        chat_set_id=str(d["chat_set_id"]),
        session_id=str(d["session_id"]),
        set_number=int(d.get("set_number", 0)),
        user_text=str(d.get("user_text", "")),
        assistant_text=str(d.get("assistant_text", "")),
    ) for d in all_data]
    seed_session(soma, chatsets, session_id=session_id)
    print(f"\nSeeded: {soma.node_count()} nodes\n")

    # Real LLM client
    llm = TurnKeyClient()

    # ─── STAGE 1: Classifier ───
    print("── STAGE 1: CLASSIFIER ──")
    c = ClassifierDendrite(soma, llm, None)
    for cs in chatsets[:5]:  # First 5 to keep it manageable
        c.run(f"cs-{cs.chat_set_id}")
    print(f"  → {soma.node_count()} nodes")

    # ─── STAGE 2: Nexus ───
    print("\n── STAGE 2: NEXUS ──")
    NexusDendrite(soma, llm, None).run(session_id)
    print(f"  → {soma.node_count()} nodes")

    # ─── STAGE 3: Spark ───
    print("\n── STAGE 3: SPARK ──")
    SparkDendrite(soma, llm, None).run(session_id)
    print(f"  → {soma.node_count()} nodes")

    # ─── STAGE 4: Falcon ───
    print("\n── STAGE 4: FALCON ──")
    FalconDendrite(soma, llm, None).run(session_id)
    print(f"  → {soma.node_count()} nodes")

    # ─── STAGE 5: Drafter ───
    print("\n── STAGE 5: DRAFTER ──")
    d_llm = TurnKeyClient()
    from pipeline.drafter_dendrite import LLMClient as DrafterLLM
    from drafter_dendrite import ModelRotator as DrafterRot
    d_rot = DrafterRot(["mock-model"])
    DrafterDendrite(soma, d_llm, d_rot).run(session_id)
    print(f"  → {soma.node_count()} nodes")

    # ─── STAGE 6: Scout ───
    print("\n── STAGE 6: SCOUT ──")
    scout = ScoutDendrite(soma, llm, None)
    scout_result = scout.run(session_id)
    print(f"  Scout: {scout_result.get('file_nodes_scanned')} files scanned")
    print(f"  Invariant nodes: {len(scout_result.get('invariant_nodes_created', []))}")
    print(f"  → {soma.node_count()} nodes")

    # ─── STAGE 7: AxonHillock ───
    print("\n── STAGE 7: AXONHILLOCK ──")
    axon = AxonHillockSlicer(soma, llm, None)
    axon_result = axon.run(session_id)
    print(f"  Scanned: {axon_result.get('scanned_count')}")
    print(f"  Sliced: {axon_result.get('sliced_count')}")
    print(f"  → {soma.node_count()} nodes")

    # ─── STAGE 8: Myelinator ───
    print("\n── STAGE 8: MYELINATOR ──")
    myel = MyelinatorOptimizer(soma, llm, None)
    myel_result = myel.run(session_id)
    print(f"  Optimized: {myel_result.get('slot_count')} slots")
    print(f"  → {soma.node_count()} nodes")

    # ─── FINAL SUMMARY ───
    print("\n" + "=" * 70)
    print("FINAL STATE")
    print("=" * 70)
    print_node_summary(soma)
    print("\nFULL PIPELINE COMPLETE")


if __name__ == "__main__":
    main()