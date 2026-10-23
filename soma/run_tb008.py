"""TB-008 Runner — Drafter Dendrite (Architecture/Requirements).

Usage: python3 run_tb008.py <session_dir>

Runs the Drafter on a session that has gone through Classifier → Nexus → Spark → Falcon.
Prints RequirementsNode, ArchitectureNode, StrategicBlueprintNode details.
NOTE: Drafter writes files to disk (chats/<session_id>/workspace/) — this is
documented, not an error.
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
from session_loader import load_session


class _SimpleRotator:
    """Minimal stand-in — no ModelRotator import allowed."""
    def __init__(self, models):
        self._models = models
    def next_model(self, role=""):
        return self._models[0] if self._models else "mock-model"



def main(path: Path) -> int:
    print("=" * 70)
    print("TB-008: Drafter Dendrite — Architecture/Requirements")
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

    from pipeline.llm_sdk import TurnKeyClient
    llm = TurnKeyClient()
    rotator = _SimpleRotator(["mock-model"])

    # Full pipeline up to Falcon
    print("Running Classifier → Nexus → Spark → Falcon...")
    classifier = ClassifierDendrite(soma, llm, rotator)
    for cs in chatsets:
        classifier.run(f"cs-{cs.chat_set_id}")

    nexus = NexusDendrite(soma, llm, rotator)
    nexus.run(session_id)

    spark = SparkDendrite(soma, llm, rotator)
    spark.run(session_id)

    falcon = FalconDendrite(soma, llm, rotator)
    falcon.run(session_id)
    print(f"  → {soma.node_count()} nodes, {soma.edge_count()} edges")

    # Show existing nodes
    node_types = {}
    for n in soma._nodes.values():
        node_types.setdefault(n.node_type, []).append(n.id)

    print("\nExisting node types:")
    for ntype, nids in sorted(node_types.items()):
        print(f"  {ntype}: {len(nids)}")

    # Run Drafter — this is where things get interesting
    # The Drafter defines its own LLMClient/ModelRotator internally
    # But we pass our MockLLMClient (which it accepts since it's a subclass)
    # The drafter uses its own ModelRotator from the flat file

    print(f"\n{'='*70}")
    print("Running Drafter...")

    # Create drafter with its own internal classes
    from drafter_dendrite import LLMClient as DrafterLLMClient, ModelRotator as DrafterRotator

    # The MockLLMClient we have works with DrafterLLMClient (same interface)
    drafter_llm = TurnKeyClient()
    drafter_rotator = DrafterRotator(["mock-model"])
    drafter = DrafterDendrite(soma, drafter_llm, drafter_rotator)

    drafter_result = drafter.run(session_id)

    print(f"\nDrafter result:")
    for k in ("session_id", "file_paths", "file_nodes_created", "structure", "workspace_path", "written_files"):
        if k in drafter_result:
            v = drafter_result[k]
            if isinstance(v, list):
                print(f"  {k}: [{len(v)} items]")
                for item in v[:5]:
                    print(f"    - {item}")
                if len(v) > 5:
                    print(f"    ... and {len(v)-5} more")
            else:
                print(f"  {k}: {v}")

    # Show LLM metrics
    if "metrics" in drafter_result:
        m = drafter_result["metrics"]
        print(f"\nDrafter LLM metrics:")
        print(f"  model_id: {m.get('model_id')}")
        print(f"  prompt_tokens: {m.get('prompt_tokens')}")
        print(f"  completion_tokens: {m.get('completion_tokens')}")
        print(f"  total_tokens: {m.get('total_tokens')}")
        print(f"  overall_elapsed_ms: {m.get('overall_elapsed_ms'):.1f}")

    # Final summary
    final_types = {}
    for n in soma._nodes.values():
        final_types.setdefault(n.node_type, []).append(n.id)
    print(f"\n{'='*70}")
    print("FINAL STATE")
    for ntype, nids in sorted(final_types.items()):
        print(f"  {ntype}: {len(nids)}")
    print(f"  Edges: {soma.edge_count()}")

    print("\nTB-008 COMPLETE")

    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 run_tb008.py <session_dir>")
        sys.exit(1)
    session_dir = Path(sys.argv[1])
    sys.exit(main(session_dir))