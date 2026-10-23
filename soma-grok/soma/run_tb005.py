"""TB-005 Runner — Nexus Dendrite on real session data (FIXED mock cycling).

Usage: python3 run_tb005.py <session_dir>
"""
from __future__ import annotations

import sys
from pathlib import Path

# No hardcoded workspace path insert

from store import Soma
from nexus_dendrite import NexusDendrite
from pipeline.chat_log_adapter import ChatSetRecord
from session_seeder import seed_session
from session_loader import load_session


class _SimpleRotator:
    """Minimal stand-in — no ModelRotator import allowed."""
    def __init__(self, models):
        self._models = models
    def next_model(self, role=""):
        return self._models[0] if self._models else "mock-model"



def main(path: Path) -> int:
    print("=" * 70)
    print("TB-005: Nexus Dendrite — Blueprint Extraction")
    print("=" * 70)

    # Load session using the loader (do this FIRST, before importing turnkey)
    all_data, reason = load_session(path)
    if reason != "ok":
        print(f"NO RECORDS {reason}")
        return 2

    # Now it's safe to import TurnKeyClient (after empty check)
    from pipeline.llm_sdk import TurnKeyClient
    
    session_id = str(all_data[0]["session_id"])

    soma = Soma()
    print(f"\nLoaded {len(all_data)} ChatSets, seeding Soma...")

    chatsets = [ChatSetRecord(
        chat_set_id=str(d["chat_set_id"]),
        session_id=str(d["session_id"]),
        set_number=int(d.get("set_number", 0)),
        user_text=str(d.get("user_text", "")),
        assistant_text=str(d.get("assistant_text", "")),
    ) for d in all_data]

    anchor_id, stats = seed_session(soma, chatsets, session_id=session_id)
    print(f"Soma: {soma.node_count()} nodes, {soma.edge_count()} edges")

    # 2. Run Classifier on ALL ChatSets
    print(f"\nRunning Classifier on all {len(chatsets)} ChatSets...")
    from classifier_dendrite import ClassifierDendrite
    llm = TurnKeyClient()
    rotator = _SimpleRotator(["mock-model"])
    classifier = ClassifierDendrite(soma, llm, rotator)

    sig_counts_by_cs = {}
    for cs in chatsets:
        cs_id = f"cs-{cs.chat_set_id}"
        cls_result = classifier.run(cs_id)
        sig_counts = cls_result.get("signal_counts", {})
        sig_counts_by_cs[cs.chat_set_id] = sig_counts

    print(f"\nClassifier results:")
    all_signal_types = {}
    for cs_id, sc in sorted(sig_counts_by_cs.items()):
        if sc:
            print(f"  {cs_id}: {sc}")
            for t, c in sc.items():
                all_signal_types[t] = all_signal_types.get(t, 0) + c

    print(f"\nSignal type totals: {all_signal_types}")
    print(f"Soma after Classifier: {soma.node_count()} nodes")

    # Show node type breakdown
    node_types = {}
    for nid, node in soma._nodes.items():
        node_types.setdefault(node.node_type, []).append(nid)
    print("\nNode types:")
    for ntype, nids in sorted(node_types.items()):
        print(f"  {ntype}: {len(nids)}")

    # 3. Run Nexus
    print(f"\n{'='*70}")
    print(f"Running Nexus on session '{session_id}'...")
    nexus = NexusDendrite(soma, llm, rotator)
    nexus_result = nexus.run(session_id)

    print(f"\nNexus result:")
    for k, v in nexus_result.items():
        if k != "metrics":
            print(f"  {k}: {v}")

    # 4. Show blueprint details
    blueprint_nodes = [n for n in soma._nodes.values() if n.node_type == "StrategicBlueprintNode"]
    if blueprint_nodes:
        bp = blueprint_nodes[0]
        bp_text = bp.properties.get('blueprint_text', '')
        print(f"\nStrategicBlueprintNode:")
        print(f"  id: {bp.id}")
        print(f"  session_id: {bp.properties.get('session_id')}")
        print(f"  directive_count: {bp.properties.get('directive_count')}")
        print(f"  constraint_count: {bp.properties.get('constraint_count')}")
        print(f"  blueprint_text (first 300 chars): {bp_text[:300]}")

    # 5. Final summary
    print(f"\n{'='*70}")
    print("FINAL STATE")
    print(f"{'='*70}")
    final_types = {}
    for n in soma._nodes.values():
        final_types.setdefault(n.node_type, []).append(n.id)
    for ntype, nids in sorted(final_types.items()):
        print(f"  {ntype}: {len(nids)}")
    print(f"  Edges: {soma.edge_count()}")

    print("\nTB-005 COMPLETE")

    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 run_tb005.py <session_dir>")
        sys.exit(1)
    session_dir = Path(sys.argv[1])
    sys.exit(main(session_dir))