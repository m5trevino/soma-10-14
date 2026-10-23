"""Re-run Scout/Axon/Myelinator for 25-12-14-permis.python.script with fixed workspace."""
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

SESSION_DIR = Path("/media/storage/dendritic123/chat-logs/sessions/25-12-14-permis.python.script")
SESSION_ID = "251214-bumpabeezy@gmail.com/25-12-14-permis.python.script.json"

def main():
    print("=" * 70)
    print("RE-RUN: Scout + AxonHillock + Myelinator — permis.python.script")
    print("=" * 70)

    # Load and seed
    all_data = []
    for fp in sorted(SESSION_DIR.glob("*.json")):
        try:
            data = json.load(open(fp))
            if isinstance(data, dict) and "chat_set_id" in data:
                all_data.append(data)
        except: pass
    all_data.sort(key=lambda r: r.get("set_number", 0))
    session_id = all_data[0]["session_id"]

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

    llm = TurnKeyClient()

    # Full pipeline
    print("── CLASSIFIER ──")
    c = ClassifierDendrite(soma, llm, None)
    for cs in chatsets[:5]:
        c.run(f"cs-{cs.chat_set_id}")
    print(f"  → {soma.node_count()} nodes")

    print("\n── NEXUS ──")
    NexusDendrite(soma, llm, None).run(session_id)
    print(f"  → {soma.node_count()} nodes")

    print("\n── SPARK ──")
    SparkDendrite(soma, llm, None).run(session_id)
    print(f"  → {soma.node_count()} nodes")

    print("\n── FALCON ──")
    FalconDendrite(soma, llm, None).run(session_id)
    print(f"  → {soma.node_count()} nodes")

    print("\n── DRAFTER ──")
    d_llm = TurnKeyClient()
    from drafter_dendrite import ModelRotator
    d_rot = ModelRotator(["mock-model"])
    DrafterDendrite(soma, d_llm, d_rot).run(session_id)
    print(f"  → {soma.node_count()} nodes")

    # Scout
    print("\n── SCOUT ──")
    scout = ScoutDendrite(soma, llm, None)
    scout_result = scout.run(session_id)
    print(f"  Files scanned: {scout_result.get('file_nodes_scanned')}")
    inv = scout_result.get('invariant_nodes_created', [])
    print(f"  Invariant nodes: {len(inv)}")

    # AxonHillock
    print("\n── AXONHILLOCK ──")
    axon = AxonHillockSlicer(soma, llm, None)
    axon_result = axon.run(session_id)
    print(f"  Scanned: {axon_result.get('scanned_count')}")
    print(f"  Sliced: {axon_result.get('sliced_count')}")
    print(f"  Slot IDs: {axon_result.get('slot_ids', [])}")

    # Myelinator
    print("\n── MYELINATOR ──")
    myel = MyelinatorOptimizer(soma, llm, None)
    myel_result = myel.run(session_id)
    print(f"  Optimized: {myel_result.get('slot_count')} slots")

    # Summary
    print("\n" + "=" * 70)
    print("FINAL STATE")
    types = {}
    for n in soma._nodes.values():
        types.setdefault(n.node_type, []).append(n.id)
    for t, ids in sorted(types.items()):
        print(f"  {t}: {len(ids)}")
    print(f"  Edges: {soma.edge_count()}")

    # Show some node details
    print("\n── SAMPLE NODES ──")
    for node_type in ["IntentNode", "DirectiveNode", "InvariantQueryNode", "FunctionSlot", "OptimizedSlot"]:
        nodes = [n for n in soma._nodes.values() if n.node_type == node_type]
        if nodes:
            print(f"\n  {node_type} examples:")
            for n in nodes[:3]:
                props = {k: v[:80] if isinstance(v, str) and len(v) > 80 else v 
                         for k, v in n.properties.items()}
                print(f"    [{n.id}] {props}")

    # Save to disk
    session_name = "25-12-14-permis.python.script"
    output_dir = Path("/home/flintx/soma/output") / session_name
    output_dir.mkdir(parents=True, exist_ok=True)
    store_path = output_dir / "soma.json"
    # Also save the workspace files
    workspace_src = Path("/home/flintx/soma/chats/251214-bumpabeezy_gmail.com_25-12-14-permis.python.script.json/workspace")
    workspace_dst = output_dir / "workspace"
    import shutil
    if workspace_src.exists() and not workspace_dst.exists():
        shutil.copytree(str(workspace_src), str(workspace_dst))
    print(f"Workspace copied to: {workspace_dst}")
    store_path.parent.mkdir(parents=True, exist_ok=True)
    soma._path = str(store_path)
    soma._persist()
    print(f"\nSaved Soma store to: {store_path}")
    print(f"Store size: {store_path.stat().st_size:,} bytes")
    print(f"Nodes in store: {len(soma._nodes)}")
    print(f"Edges in store: {len(soma._edges)}")
    
    print("\nRE-RUN COMPLETE")

if __name__ == "__main__":
    main()