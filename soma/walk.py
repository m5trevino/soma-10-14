"""Pipeline — one walk from session to verified code.

TurnKey is the middleware. This script and the dendrites do not pick models,
do not know the engine URL, and do not talk to any API. They hand a stage
name and messages to the client. The client is the only thing that imports
TurnKey.

Usage:
    python3 pipeline.py --session /path/to/session --profile /path/to/profile.json
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from store import Soma
from pipeline.chat_log_adapter import parse_directory, ChatSetRecord
from session_seeder import seed_session
from machinetalk.client import TurnKeyClient

from classifier_dendrite import ClassifierDendrite
from integrator_dendrite import IntegratorDendrite
from retrograde_dendrite import RetrogradeDendrite
from nexus_dendrite import NexusDendrite
from spark_dendrite import SparkDendrite
from falcon_dendrite import FalconDendrite
from drafter_dendrite import DrafterDendrite
from scout_dendrite import ScoutDendrite
from axon_hillock_oc import AxonHillockSlicer
from myelinator_olc import MyelinatorOptimizer
from pipeline.saltatory_gate import SaltatoryGate
from pipeline.code_publisher import CodePublisher


# Stage 1 runs once per ChatSet.
STAGE1 = [
    ("classifier", ClassifierDendrite),
    ("integrator", IntegratorDendrite),
    ("retrograde", RetrogradeDendrite),
]

# Crystallization runs once per session, after every ChatSet is ingested.
CRYSTALLIZE = [
    ("nexus", NexusDendrite),
    ("spark", SparkDendrite),
    ("falcon", FalconDendrite),
    ("drafter", DrafterDendrite),
    ("scout", ScoutDendrite),
    ("axon_hillock", AxonHillockSlicer),
    ("myelinator", MyelinatorOptimizer),
]


def _print(state: str, stage: str, detail: str = "") -> None:
    line = f"[{state}] {stage}"
    if detail:
        line += f" — {detail}"
    print(line, flush=True)


def _run_stage(name: str, cls: type, soma: Soma, client: TurnKeyClient, target: str) -> dict:
    """Run one stage. target is a chat_set_id for stage 1, a session_id for crystallize."""
    _print("WORKING", name)
    start = time.monotonic()
    try:
        dendrite = cls(soma, client)
        result = dendrite.run(target)
    except Exception as exc:
        _print("KILL", name, str(exc))
        return {"error": str(exc)}
    elapsed = (time.monotonic() - start) * 1000
    if isinstance(result, dict) and result.get("error"):
        _print("KILL", name, result["error"])
        return result
    metrics = result.get("metrics", {}) if isinstance(result, dict) else {}
    model = metrics.get("model_id", "")
    tokens = metrics.get("total_tokens", "")
    _print("NEXT", name, f"{elapsed:.0f}ms model={model} tokens={tokens}")
    return result if isinstance(result, dict) else {}


def run(session_path: Path, profile_path: Path, soma_path: Path) -> int:
    if not session_path.exists():
        print(f"session not found: {session_path}", file=sys.stderr)
        return 1
    if not profile_path.exists():
        print(f"profile not found: {profile_path}", file=sys.stderr)
        return 1

    client = TurnKeyClient(str(profile_path))
    soma = Soma(str(soma_path))

    records_by_session = parse_directory(session_path)
    if not records_by_session:
        print(f"no chat sets in {session_path}", file=sys.stderr)
        return 1

    session_id = next(iter(records_by_session))
    records: list[ChatSetRecord] = records_by_session[session_id]
    _print("WORKING", "seed", f"{len(records)} chat sets")
    seed_session(soma, records)
    _print("NEXT", "seed")

    for i, record in enumerate(records, start=1):
        chat_set_id = f"cs-{record.chat_set_id}"
        print(f"\n--- chat set {i}/{len(records)} ({chat_set_id}) ---", flush=True)
        for name, cls in STAGE1:
            result = _run_stage(name, cls, soma, client, chat_set_id)
            if result.get("error"):
                return 1

    print(f"\n--- crystallize session {session_id} ---", flush=True)
    for name, cls in CRYSTALLIZE:
        result = _run_stage(name, cls, soma, client, session_id)
        if result.get("error"):
            return 1

    _print("WORKING", "saltatory_gate")
    gate = SaltatoryGate(soma)
    gate_result = gate.run(session_id)
    if isinstance(gate_result, dict) and gate_result.get("error"):
        _print("KILL", "saltatory_gate", gate_result["error"])
        return 1
    _print("NEXT", "saltatory_gate")

    _print("WORKING", "code_publisher")
    publisher = CodePublisher(soma)
    pub_result = publisher.run(session_id)
    if isinstance(pub_result, dict) and pub_result.get("errors"):
        _print("KILL", "code_publisher", str(pub_result["errors"]))
        return 1
    _print("NEXT", "code_publisher", str(pub_result.get("published_files", [])))

    print("\nDONE", flush=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Walk one session through the full pipeline.")
    parser.add_argument("--session", required=True, type=Path, help="Path to a session directory")
    parser.add_argument("--profile", required=True, type=Path, help="Path to a TurnKey profile JSON")
    parser.add_argument("--soma", type=Path, default=Path("/tmp/soma.json"), help="Path for the Soma store")
    args = parser.parse_args(argv)
    return run(args.session, args.profile, args.soma)


if __name__ == "__main__":
    sys.exit(main())
