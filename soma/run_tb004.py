"""TB-004 Runner — Stage 1 Dendrites on real session data.

Usage: python3 run_tb004.py <session_dir>

Picks ChatSets from the session and runs Classifier → Integrator →
Retrograde with a MockLLMClient. Prints node types, counts, edges to stdout.
"""
from __future__ import annotations

import sys
from pathlib import Path

# No hardcoded workspace path insert

from store import Soma
from session_seeder import seed_session
from classifier_dendrite import ClassifierDendrite
from integrator_dendrite import IntegratorDendrite
from retrograde_dendrite import RetrogradeDendrite
from pipeline.chat_log_adapter import ChatSetRecord
from pipeline.llm_sdk import TurnKeyClient
from session_loader import load_session


class _SimpleRotator:
    """Minimal stand-in — no ModelRotator import allowed."""
    def __init__(self, models):
        self._models = models
    def next_model(self, role=""):
        return self._models[0] if self._models else "mock-model"



def main(path: Path) -> int:
    print("=" * 70)
    print("TB-004: Stage 1 Dendrites — Real Session")
    print("=" * 70)

    # Load session using the loader
    all_data, reason = load_session(path)
    if reason != "ok":
        print(f"NO RECORDS {reason}")
        return 2

    # Convert to ChatSetRecord
    all_cs = [ChatSetRecord(
        chat_set_id=str(d["chat_set_id"]),
        session_id=str(d["session_id"]),
        set_number=int(d.get("set_number", 0)),
        user_text=str(d.get("user_text", "")),
        assistant_text=str(d.get("assistant_text", "")),
    ) for d in all_data]

    all_cs.sort(key=lambda r: r.set_number)

    print(f"\nLoaded {len(all_cs)} ChatSets from {path}")

    if not all_cs:
        print("ERROR: No ChatSets loaded. Check session directory.")
        return 2

    # Pick 3 representative ChatSets (first 3)
    pick = all_cs[:3]
    print(f"\nRunning on {len(pick)} ChatSets: {[cs.chat_set_id for cs in pick]}")
    for i, cs in enumerate(pick):
        ut = cs.user_text[:80].replace("\n", " ")
        at = cs.assistant_text[:80].replace("\n", " ")
        print(f"  [{i+1}] set#{cs.set_number} | user: '{ut}...' | assistant: '{at}...'")

    # 2. Seed Soma
    session_id = str(all_cs[0].session_id) if all_cs else "250523-peacock-project"
    soma = Soma(path=None)  # in-memory only
    anchor_id, stats = seed_session(soma, pick, session_id=session_id)
    print(f"\nSoma seeded: {soma.node_count()} nodes, {soma.edge_count()} edges")
    print(f"  Anchor: {anchor_id}")

    # 3. Wire dendrites with MockLLMClient
    llm = TurnKeyClient()
    rotator = _SimpleRotator(["mock-model"])

    classifier = ClassifierDendrite(soma, llm, rotator)
    integrator = IntegratorDendrite(soma, llm, rotator)
    retrograde = RetrogradeDendrite(soma, llm, rotator)

    # 4. Run each stage on each ChatSet
    all_nodes: dict[str, list[str]] = {}  # type -> [node_ids]
    all_edges: dict[str, int] = {}        # rel_type -> count
    chatset_nodes: dict[str, list[str]] = {}  # chat_set_id -> [node_ids]

    for cs in pick:
        cs_id = f"cs-{cs.chat_set_id}"
        chatset_nodes[cs_id] = []

        # --- Classifier ---
        cls_result = classifier.run(cs_id)
        print(f"\n  [{cs.chat_set_id}] Classifier →")
        if "error" in cls_result:
            print(f"    ERROR: {cls_result['error']}")
        else:
            sig_ids = cls_result.get("signal_node_ids", [])
            sig_counts = cls_result.get("signal_counts", {})
            print(f"    Signal nodes: {len(sig_ids)}")
            print(f"    Signal counts: {sig_counts}")
            print(f"    Node IDs: {sig_ids}")
            chatset_nodes[cs_id].extend(sig_ids)
            for sid in sig_ids:
                node = soma.get_node(sid)
                if node:
                    all_nodes.setdefault(node.node_type, []).append(sid)
            for edge in soma.get_edges_for(cs_id):
                if edge.source == cs_id:
                    all_edges[edge.rel_type] = all_edges.get(edge.rel_type, 0) + 1

        # --- Integrator ---
        int_result = integrator.run(cs_id)
        print(f"\n  [{cs.chat_set_id}] Integrator →")
        if "error" in int_result:
            print(f"    ERROR: {int_result['error']}")
        else:
            for field_name in ("task_node_ids", "risk_node_ids", "decision_node_ids", "stack_node_ids"):
                ids = int_result.get(field_name, [])
                prefix = field_name.replace("_node_ids", "")
                print(f"    {prefix} nodes: {len(ids)}")
                print(f"    Node IDs: {ids}")
                chatset_nodes[cs_id].extend(ids)
                for nid in ids:
                    node = soma.get_node(nid)
                    if node:
                        all_nodes.setdefault(node.node_type, []).append(nid)
            for edge in soma.get_edges_for(cs_id):
                if edge.source == cs_id:
                    all_edges[edge.rel_type] = all_edges.get(edge.rel_type, 0) + 1

        # --- Retrograde ---
        ret_result = retrograde.run(cs_id)
        print(f"\n  [{cs.chat_set_id}] Retrograde →")
        if "error" in ret_result:
            print(f"    ERROR: {ret_result['error']}")
        else:
            outcome_id = ret_result.get("outcome_node_id", "")
            if outcome_id:
                chatset_nodes[cs_id].append(outcome_id)
                node = soma.get_node(outcome_id)
                if node:
                    all_nodes.setdefault(node.node_type, []).append(outcome_id)
            print(f"    Outcome: {outcome_id}")
            print(f"    Deliverables: {ret_result.get('deliverable_count', 0)}")
            print(f"    Lessons: {ret_result.get('lessons_promoted', 0)}")
            # Check edges
            for edge in soma.get_edges_for(cs_id):
                if edge.source == cs_id:
                    all_edges[edge.rel_type] = all_edges.get(edge.rel_type, 0) + 1
            if outcome_id:
                for edge in soma.get_edges_for(outcome_id):
                    if edge.source == outcome_id:
                        all_edges[edge.rel_type] = all_edges.get(edge.rel_type, 0) + 1

    # 5. Summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)

    print("\nNode types created:")
    for ntype, nids in sorted(all_nodes.items()):
        # Show sample properties
        sample = soma.get_node(nids[0]).properties if nids else {}
        short = {k: v for k, v in list(sample.items()) if k in ("confidence", "source_text", "rationale", "task_text", "outcome_text")}
        print(f"  {ntype}: {len(nids)} nodes")
        if short:
            print(f"    sample: {short}")

    print("\nEdge types:")
    for rel, count in sorted(all_edges.items()):
        print(f"  {rel}: {count}")

    print("\nChatSet → nodes:")
    for cs_id, nids in sorted(chatset_nodes.items()):
        print(f"  {cs_id}: {len(nids)} nodes")

    print(f"\nTotal Soma: {soma.node_count()} nodes, {soma.edge_count()} edges")
    print("\nTB-004 COMPLETE")

    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 run_tb004.py <session_dir>")
        sys.exit(1)
    session_dir = Path(sys.argv[1])
    sys.exit(main(session_dir))