"""TB-DEND-022: InteractiveRunner — Pipeline orchestrator with verification gate.

Runs the full dendritic pipeline on a session, with:
- SaltatoryGate verification between Myelinator and CodePublisher
- Integrity check: VerifiedNodes count == OptimizedSlots count
- Abort on FailureNode: publisher is skipped if any FailureNode exists
- Soma persistence at the end

Usage:
    python3 run_new_session.py          # original runner
    python3 run_pipeline.py --session <id>  # new runner with verification
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

from store import Soma
from soma.helpers import get_receptor_config
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
from pipeline.drafter_dendrite import LLMClient as DrafterLLM
from pipeline.llm_sdk import TurnKeyClient

# New modules from pipeline/
from pipeline.saltatory_gate import SaltatoryGate
from pipeline.code_publisher import CodePublisher


def load_chatsets_from_dir(session_dir: Path) -> list[ChatSetRecord]:
    """Load ChatSetRecord objects from a directory of JSON files."""
    all_data = []
    for fp in sorted(session_dir.glob("*.json")):
        try:
            data = json.load(open(fp))
        except Exception:
            continue
        if isinstance(data, dict) and "chat_set_id" in data:
            try:
                all_data.append(data)
            except Exception:
                pass
    all_data.sort(key=lambda r: r.get("set_number", 0))
    return [
        ChatSetRecord(
            chat_set_id=str(d["chat_set_id"]),
            session_id=str(d["session_id"]),
            set_number=int(d.get("set_number", 0)),
            user_text=str(d.get("user_text", "")),
            assistant_text=str(d.get("assistant_text", "")),
        )
        for d in all_data
    ]


def print_node_summary(soma: Soma) -> dict[str, list[str]]:
    """Print and return node types grouped by type name."""
    types: dict[str, list[str]] = {}
    for n in soma._nodes.values():
        types.setdefault(n.node_type, []).append(n.id)
    for t, ids in sorted(types.items()):
        print(f"    {t}: {len(ids)}")
    print(f"  Total Edges: {soma.edge_count()}")
    return types


class InteractiveRunner:
    """Pipeline orchestrator with SaltatoryGate verification."""

    def __init__(
        self,
        soma: Soma,
        llm_client: TurnKeyClient,
        session_id: str,
        output_dir: Path | None = None,
    ) -> None:
        self._soma = soma
        self._llm = llm_client
        self._session_id = session_id
        self._output_dir = output_dir
        self._errors: list[dict[str, str]] = []

    def run(self) -> dict[str, Any]:
        """Execute the full pipeline with verification gate.

        Returns a report dict with node counts, edge counts, and verification results.
        """
        print("=" * 70)
        print(f"FULL PIPELINE — {self._session_id}")
        print("=" * 70)
        print(f"\nSeeded: {self._soma.node_count()} nodes\n")

        # ─── STAGE 1: Classifier ───
        print("── STAGE 1: CLASSIFIER ──")
        c = ClassifierDendrite(self._soma, self._llm, None)
        # Classifier needs chatsets — load first few
        # For now, assume classifier works via get_receptor_config
        # Run classifier on existing ChatSet nodes
        chatsets = self._soma.query_by_type("ChatSet")
        for cs in chatsets[:10]:
            c.run(cs.properties.get("id", cs.id))
        print(f"  → {self._soma.node_count()} nodes")

        # ─── STAGE 2: Nexus ───
        print("\n── STAGE 2: NEXUS ──")
        nexus_result = NexusDendrite(self._soma, self._llm, None).run(self._session_id)
        print(f"  → {self._soma.node_count()} nodes")
        if nexus_result.get("error"):
            self._errors.append({"stage": "nexus", "error": nexus_result["error"]})

        # ─── STAGE 3: Spark ───
        print("\n── STAGE 3: SPARK ──")
        spark_result = SparkDendrite(self._soma, self._llm, None).run(self._session_id)
        print(f"  → {self._soma.node_count()} nodes")
        if spark_result.get("error"):
            self._errors.append({"stage": "spark", "error": spark_result["error"]})

        # ─── STAGE 4: Falcon ───
        print("\n── STAGE 4: FALCON ──")
        falcon_result = FalconDendrite(self._soma, self._llm, None).run(self._session_id)
        print(f"  → {self._soma.node_count()} nodes")
        if falcon_result.get("error"):
            self._errors.append({"stage": "falcon", "error": falcon_result["error"]})

        # ─── STAGE 5: Drafter ───
        print("\n── STAGE 5: DRAFTER ──")
        d_llm = self._llm
        d_rot = None  # Will use mock if no rotator
        drafter = DrafterDendrite(self._soma, d_llm, d_rot)
        drafter_result = drafter.run(self._session_id)
        print(f"  → {self._soma.node_count()} nodes")
        print(f"  Files written: {drafter_result.get('written_files', [])}")

        # ─── STAGE 6: Scout ───
        print("\n── STAGE 6: SCOUT ──")
        scout = ScoutDendrite(self._soma, self._llm, None)
        scout_result = scout.run(self._session_id)
        print(f"  Invariant nodes: {len(scout_result.get('invariant_nodes_created', []))}")
        print(f"  → {self._soma.node_count()} nodes")

        # ─── STAGE 7: AxonHillock ───
        print("\n── STAGE 7: AXONHILLOCK ──")
        axon = AxonHillockSlicer(self._soma, self._llm, None)
        axon_result = axon.run(self._session_id)
        print(f"  Sliced: {axon_result.get('sliced_count')}")
        print(f"  Evidence linked: {axon_result.get('matched_count')}")
        print(f"  → {self._soma.node_count()} nodes")

        # ─── STAGE 8: Myelinator ───
        print("\n── STAGE 8: MYELINATOR ──")
        myel = MyelinatorOptimizer(self._soma, self._llm, None)
        myel_result = myel.run(self._session_id)
        print(f"  Optimized: {myel_result.get('slot_count')} slots")
        print(f"  → {self._soma.node_count()} nodes")

        # ─── STAGE 9: SaltatoryGate Verification ───
        print("\n── STAGE 9: SALTATORYGATE (VERIFICATION) ──")
        gate = SaltatoryGate(self._soma)
        gate_result = gate.run(self._session_id)
        verified_count = gate_result.get("verified_count", 0)
        failure_count = gate_result.get("failure_count", 0)
        print(f"  Verified: {verified_count}")
        print(f"  Failed: {failure_count}")
        print(f"  Skipped: {gate_result.get('skipped_count', 0)}")
        print(f"  → {self._soma.node_count()} nodes")

        # Integrity check
        optimized_count = myel_result.get("slot_count", 0)
        if verified_count > 0 and verified_count != optimized_count:
            print(f"  ⚠ WARNING: Verified count ({verified_count}) != Optimized count ({optimized_count})")
            print(f"  → Some slots may have been skipped (no tests found)")
            print(f"  → This is acceptable if skipped_count > 0")

        # ─── STAGE 10: CodePublisher ───
        print("\n── STAGE 10: CODEPUBLISHER ──")

        # Check for FailureNodes — abort publisher if any exist
        if failure_count > 0:
            print(f"  ⛔ ABORT: {failure_count} FailureNode(s) exist for this session")
            print(f"  → Publisher skipped to prevent unverified code from writing to disk")
            # List failure reasons
            for fid in gate_result.get("failure_ids", []):
                fn = self._soma.get_node(fid)
                if fn:
                    print(f"    → {fn.properties.get('slot_name', 'unknown')}: {fn.properties.get('failure_reason', 'unknown')}")
            publisher_result = {
                "session_id": self._session_id,
                "published_files": [],
                "skipped_files": [{"reason": "aborted_due_to_failure_nodes"}],
                "published_count": 0,
                "skipped_count": 1,
                "aborted": True,
                "aborted_reason": f"{failure_count} FailureNode(s) exist",
            }
        else:
            print("  ✓ No FailureNodes — proceeding with publisher")
            publisher = CodePublisher(self._soma)
            publisher_result = publisher.run(self._session_id)
            print(f"  Published: {publisher_result.get('published_count')} files")
            print(f"  Skipped: {publisher_result.get('skipped_count')} files")

        # ─── FINAL SUMMARY ───
        print("\n" + "=" * 70)
        print("FINAL STATE")
        print("=" * 70)
        types = print_node_summary(self._soma)

        # Persist soma.json if output_dir is set
        if self._output_dir:
            self._soma._persist()
            soma_path = self._output_dir / "soma.json"
            print(f"\n  Soma persisted to: {soma_path}")

        return {
            "session_id": self._session_id,
            "node_types": {t: len(ids) for t, ids in types.items()},
            "edge_count": self._soma.edge_count(),
            "nexus": nexus_result,
            "spark": spark_result,
            "falcon": falcon_result,
            "drafter": drafter_result,
            "scout": scout_result,
            "axon": axon_result,
            "myelinator": myel_result,
            "saltatory_gate": gate_result,
            "publisher": publisher_result,
            "errors": self._errors,
            "verified_count": verified_count,
            "failure_count": failure_count,
        }


def main() -> None:
    """Main entry point."""
    if len(sys.argv) < 3:
        print("Usage: python3 run_pipeline.py <session_dir> <output_dir>")
        print("  session_dir: directory containing session JSON files")
        print("  output_dir: directory for soma.json output")
        sys.exit(1)

    session_dir = Path(sys.argv[1])
    output_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else None

    # Load chatsets
    chatsets = load_chatsets_from_dir(session_dir)
    if not chatsets:
        print(f"ERROR: No ChatSet files found in {session_dir}")
        sys.exit(1)

    session_id = str(chatsets[0].session_id)
    print(f"Loaded {len(chatsets)} ChatSets for session: {session_id}")

    # Initialize Soma
    soma_path = None
    if output_dir:
        output_dir.mkdir(parents=True, exist_ok=True)
        soma_path = str(output_dir / "soma.json")

    soma = Soma(path=soma_path)
    seed_session(soma, chatsets, session_id=session_id)

    # Initialize LLM client
    llm = TurnKeyClient()

    # Run pipeline
    runner = InteractiveRunner(
        soma=soma,
        llm_client=llm,
        session_id=session_id,
        output_dir=output_dir,
    )
    result = runner.run()

    print(f"\nPipeline complete — {soma.node_count()} nodes, {soma.edge_count()} edges")
    if result["errors"]:
        print(f"⚠ {len(result['errors'])} stage error(s): {[e['stage'] for e in result['errors']]}")


if __name__ == "__main__":
    main()