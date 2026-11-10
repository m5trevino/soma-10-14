#!/usr/bin/env python3
"""Distiller — ingest session, run pipeline stages one-by-one with Enter-to-continue.

Usage:
    python distiller.py --path /media/storage/dendritic123/chat-logs/sessions/SESSION_DIR
    python distiller.py --picker          # interactive session picker UI
    python distiller.py --load-chunk      # S01: DB chat -> chatset JSON, then stop

Flow:
  1. Load session (from --path or from session picker)
  2. Init fresh SQLite DB from soma_template.sql
  3. Ingest ALL chat sets into Soma (each JSON file = one node)
  4. Run each pipeline stage one-by-one, PAUSED, waiting for Enter:
       Stage 1: Distiller (TB-001)
       Stage 2: IntroBeaver (TB-002)
       Stage 3: PlanBeaver (TB-003)
       ...etc...

Uses:
  - session_picker for session selection
  - source.py (load_source) for loading sessions/chatsets
  - TurnKey SDK EngineClient for LLM calls
  - soma_bridge for writing pipeline results to Soma
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time as _time
import threading
from pathlib import Path
from typing import Dict

# ── Paths ──────────────────────────────────────────────────────────────────
SOMA_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SOMA_DIR))
sys.path.insert(0, "/workspace/artifacts/turn-key")

from store import Soma
from machinetalk.session_picker import run_session_picker
from machinetalk.source import load_source
from machinetalk.soma_bridge import SomaBridge
from machinetalk.client import EngineClient
from machinetalk.debug_dashboard_skeu import (
    start_dashboard,
    set_current_session,
    append_event,
)


# ── Pipeline stages ────────────────────────────────────────────────────────
PIPELINE_STAGES = [
    ("distiller", "TB-001: Distiller"),
    ("classifier", "TB-002: IntroBeaver"),
    ("integrator", "TB-003: PlanBeaver"),
    ("retrograde", "TB-004: Outrobeaver"),
    ("nexus", "TB-005: Nexus"),
    ("spark", "TB-006: Spark"),
    ("falcon", "TB-007: Falcon"),
    ("drafter", "TB-008: Drafter"),
    ("scout", "TB-009: Scout"),
    ("ax_hillock", "TB-010: OC"),
    ("myelinator", "TB-011: OLC"),
    ("terminal", "TB-012: Terminal"),
]


# ── Debug dashboard directory ────────────────────────────────────────────────
DASHBOARD_DIR = Path("/tmp/soma_debug")

# ── Slice S01: raw chat -> chatset ───────────────────────────────────────────
REPO_ROOT = SOMA_DIR.parent
SESSION_ID_FILE = Path("/tmp/soma_test_session_id.txt")
CHATSET_PATH = Path("/tmp/soma_distiller_chatset.json")


def read_session_id(path: Path = SESSION_ID_FILE) -> str | None:
    """Read the session id from disk, or None when the file is absent/empty."""
    try:
        value = path.read_text().strip()
    except OSError:
        return None
    return value or None


def _candidate_soma_paths(session_id: str) -> list[Path]:
    """Places a session's SOMA graph may live, most specific first."""
    return [
        REPO_ROOT / "somas" / session_id / "soma.db",
        REPO_ROOT / "somas" / session_id / "soma.json",
        SOMA_DIR / "somas" / session_id / "soma.db",
        SOMA_DIR / "somas" / session_id / "soma.json",
        REPO_ROOT / "soma" / "output" / "sessions" / session_id / "soma.json",
        SOMA_DIR / "output" / "sessions" / session_id / "soma.json",
        REPO_ROOT / "soma.db",
        SOMA_DIR / "soma.db",
    ]


def _open_soma_readonly(path: Path):
    """Open a SOMA graph without writing next to the source file.

    JSON graphs load in memory. SQLite databases are copied to /tmp first so
    opening them cannot create WAL/journal sidecars in the repository.
    """
    import shutil
    import tempfile

    if path.suffix.lower() == ".json":
        return Soma(str(path))

    fd, tmp_name = tempfile.mkstemp(prefix="soma_s01_", suffix=".db")
    os.close(fd)
    shutil.copyfile(path, tmp_name)
    for sidecar in (f"{path}-wal", f"{path}-shm"):
        side = Path(sidecar)
        if side.exists():
            shutil.copyfile(side, tmp_name + side.name[len(path.name):])
    return Soma(tmp_name)


def _messages_from_node(node) -> dict | None:
    props = node.properties
    content = props.get("content")
    if content is None:
        return None
    return {
        "role": str(props.get("role") or ""),
        "content": str(content),
        "timestamp": str(
            props.get("timestamp")
            or props.get("created_at")
            or props.get("timestamp_utc")
            or ""
        ),
    }


def _messages_from_chatsets(chatsets, anchor_ts: str) -> list[dict]:
    """Fallback when a graph stores text on ChatSet nodes instead of Messages."""
    out: list[dict] = []
    for node in chatsets:
        props = node.properties
        ts = str(props.get("timestamp") or props.get("created_at") or anchor_ts)
        for role, key in (("USER", "user_text"), ("AGENT", "assistant_text")):
            text = props.get(key) or ""
            if str(text).strip():
                out.append({"role": role, "content": str(text), "timestamp": ts})
    return out


def load_raw_messages(session_id: str, db_path: str | None = None,
                      ) -> tuple[list[dict], str]:
    """Load one session's raw chat from a SOMA graph.

    Returns ``(messages, source)`` where each message is a dict with
    ``role``, ``content`` and ``timestamp``. This is the DB query result the
    written chatset must match one-for-one.
    """
    candidates: list[Path] = []
    if db_path:
        candidates.append(Path(db_path).expanduser())
    candidates.extend(_candidate_soma_paths(session_id))

    fallback: tuple[list[dict], str] | None = None
    for path in candidates:
        if not path.exists():
            continue
        try:
            if path.suffix.lower() != ".json" and path.stat().st_size == 0:
                continue
        except OSError:
            continue
        try:
            soma = _open_soma_readonly(path)
        except Exception as exc:  # unreadable/corrupt candidate -> next
            print(f"  [WARN] cannot open {path}: {exc}", file=sys.stderr)
            continue
        try:
            anchor = soma.get_session_anchor(session_id)
            anchor_ts = ""
            if anchor is not None:
                anchor_ts = str(
                    anchor.properties.get("created_at")
                    or anchor.properties.get("timestamp")
                    or ""
                )

            messages = [
                msg for msg in (
                    _messages_from_node(n) for n in soma.get_messages(session_id)
                ) if msg is not None
            ]
            if messages:
                for msg in messages:
                    if not msg["timestamp"]:
                        msg["timestamp"] = anchor_ts
                return messages, str(path)

            if fallback is None:
                built = _messages_from_chatsets(
                    soma.get_chatsets(session_id), anchor_ts)
                if built:
                    fallback = (built, str(path))
        finally:
            soma.close()

    if fallback is not None:
        return fallback
    return [], ""


def build_chatset(messages: list[dict]) -> list[dict]:
    """Chunk raw messages into one chatset, preserving conversation order.

    One chatset entry per message; every entry always carries role, content
    and timestamp keys.
    """
    chatset: list[dict] = []
    for msg in messages:
        chatset.append({
            "role": str(msg.get("role") or ""),
            "content": str(msg.get("content") or ""),
            "timestamp": str(msg.get("timestamp") or ""),
        })
    return chatset


def discover_session_id() -> str | None:
    """Fallback: pick the session with the most Message nodes in repo graphs."""
    counts: dict[str, int] = {}
    for graph in list(REPO_ROOT.glob("somas/*/soma.json")) + list(
            REPO_ROOT.glob("soma/output/sessions/*/soma.json")):
        try:
            data = json.loads(graph.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        for ndata in (data.get("nodes") or {}).values():
            if (ndata.get("type") or ndata.get("node_type")) != "Message":
                continue
            sid = (ndata.get("properties") or {}).get("session_id")
            if sid:
                counts[str(sid)] = counts.get(str(sid), 0) + 1
    if not counts:
        return None
    return max(sorted(counts), key=lambda sid: counts[sid])


def run_load_and_chunk(session_file: Path = SESSION_ID_FILE,
                       db_path: str | None = None) -> int:
    """S01 — load, chunk, write, print count. No hash, checkpoint or engine."""
    session_id = read_session_id(session_file)
    if not session_id:
        session_id = discover_session_id()
        if not session_id:
            print("No session_id found and no SOMA graph to discover it from.",
                  file=sys.stderr)
            return 1
        session_file.write_text(session_id + "\n")
        print(f"  [WARN] {session_file} was missing; using {session_id}",
              file=sys.stderr)

    print(f"  Session: {session_id}", file=sys.stderr)
    messages, source = load_raw_messages(session_id, db_path=db_path)
    if source:
        print(f"  SOMA graph: {source}", file=sys.stderr)
    else:
        print("  [WARN] no SOMA graph found for this session", file=sys.stderr)

    chatset = build_chatset(messages)
    CHATSET_PATH.write_text(json.dumps(chatset, indent=2) + "\n")

    print(f"MESSAGE_COUNT: {len(chatset)}")
    print(f"CHATSET_PATH: {CHATSET_PATH}")
    print("NONCE: d8a4f7a0-0e8d-47ca-85c5-538dadb3dff8")
    return 0


def _write_checkpoint_event(dash_dir: Path, event: Dict) -> None:
    """Write a per-chatset checkpoint entry for the dashboard /progress endpoint."""
    cp_dir = dash_dir / "checkpoints"
    cp_dir.mkdir(parents=True, exist_ok=True)
    sid = event.get("session_id", "unknown")
    cp_file = cp_dir / f"{sid}.checkpoint.json"

    # Load or create checkpoint structure
    if cp_file.exists():
        try:
            data = json.loads(cp_file.read_text())
        except Exception:
            data = {"session_id": sid, "chatsets": {}}
    else:
        data = {"session_id": sid, "chatsets": {}}

    cs_num = str(event.get("chatset_number", "0"))
    if cs_num not in data["chatsets"]:
        data["chatsets"][cs_num] = {
            "chatset_id": event.get("chatset_id", ""),
            "stages": {},
            "chars": int(event.get("chars_in", 0)),
        }

    cs_data = data["chatsets"][cs_num]
    stage_name = event.get("stage", "")
    cs_data["stages"][stage_name] = {
        "status": event.get("status", ""),
        "model": event.get("model", ""),
        "timestamp": event.get("timestamp", ""),
    }

    cp_file.write_text(json.dumps(data, indent=2))


def _prompt_enter(prompt: str = "Press Enter to continue (Ctrl+C to skip)") -> bool:
    """Wait for Enter key. Return False on Ctrl+C."""
    print(f"\n  [{prompt}]", flush=True)
    try:
        input()
        return True
    except (EOFError, KeyboardInterrupt):
        return False


def _run_stage(client: EngineClient, soma: Soma, bridge: SomaBridge,
               session, chatset, stage_name: str, stage_label: str,
               dashboard_dir: Path | None = None):
    """Run one pipeline stage on one chatset. Emits dashboard events."""

    # ── Emit RUNNING event ─────────────────────────────────────────
    run_event = {
        "session_id": session.session_id,
        "session_title": session_path.name if "session_path" in dir() else None,
        "chatset_id": chatset.chatset_id,
        "chatset_number": chatset.set_number,
        "stage": stage_name,
        "status": "running",
        "chars_in": str(chatset.chars),
        "timestamp": _time.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    append_event(run_event)
    if dashboard_dir:
        _write_checkpoint_event(dashboard_dir, run_event)

    print(f"\n{'='*60}")
    print(f"  STAGE: {stage_label}")
    print(f"  ChatSet: {chatset.chatset_id}  ({chatset.chars} chars)")
    print(f"{'='*60}", flush=True)

    chunk = chatset.transcript()

    res = client.call_stage(
        stage_name,
        session_id=session.session_id,
        chatset_id=chatset.chatset_id,
        chunk=chunk,
        payload={
            "session_id": session.session_id,
            "chatset_id": chatset.chatset_id,
            "timestamp_utc": _time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "raw_chat_set": chatset.raw_chat_set,
        },
    )

    # Write result to Soma via bridge
    if stage_name == "distiller":
        bridge.write_receptor(
            session.session_id,
            chatset.chatset_id,
            chatset.set_number,
            res.record.gate,
            res.record.model,
            res.record.latency_ms,
        )
    # Future: other stages write their own nodes via bridge

    print(f"  Verdict: {res.verdict}")
    print(f"  OK: {res.ok}")
    print(f"  Model: {res.record.model}")
    print(f"  Latency: {res.record.latency_ms:.0f}ms")

    # ── Emit DONE / FAILED event ───────────────────────────────────
    status = "done" if res.ok else "failed"
    done_event = {
        "session_id": session.session_id,
        "session_title": session_path.name if "session_path" in dir() else None,
        "chatset_id": chatset.chatset_id,
        "chatset_number": chatset.set_number,
        "stage": stage_name,
        "status": status,
        "model": res.record.model,
        "chars_in": str(chatset.chars),
        "latency_ms": round(res.record.latency_ms, 1),
        "verdict": str(res.verdict),
        "raw_response": res.record.response if hasattr(res.record, 'response') else None,
        "prompt_tokens": getattr(res.record, 'prompt_tokens', None),
        "completion_tokens": getattr(res.record, 'completion_tokens', None),
        "errors": str(res.record.error) if hasattr(res.record, 'error') and res.record.error else None,
        "timestamp": _time.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    append_event(done_event)
    if dashboard_dir:
        _write_checkpoint_event(dashboard_dir, done_event)

    return res.ok


def main() -> int:
    ap = argparse.ArgumentParser(description="SOMA Distiller Pipeline")
    ap.add_argument("--path", default=None, help="session directory path")
    ap.add_argument("--picker", action="store_true",
                    help="use interactive session picker")
    ap.add_argument("--profile", default=None,
                    help="TurnKey profile JSON path")
    ap.add_argument("--max-stages", type=int, default=None,
                    help="max stages to run (default=all)")
    ap.add_argument("--debug-port", type=int, default=9876,
                    help="dashboard HTTP port (default 9876)")
    ap.add_argument("--load-chunk", action="store_true",
                    help="load raw chat from the SOMA graph, chunk into a "
                         "chatset, write /tmp/soma_distiller_chatset.json, "
                         "print the message count, and stop")
    ap.add_argument("--session-file", default=str(SESSION_ID_FILE),
                    help="file holding the session id (default %(default)s)")
    ap.add_argument("--db", default=None,
                    help="explicit SOMA graph/DB path for --load-chunk")
    args = ap.parse_args()

    if args.load_chunk:
        return run_load_and_chunk(Path(args.session_file), db_path=args.db)

    # ── Step 0: Start dashboard in background thread ───────────────────
    DASHBOARD_DIR.mkdir(parents=True, exist_ok=True)
    dash_thread = threading.Thread(
        target=start_dashboard,
        kwargs={
            "debug_dir": str(DASHBOARD_DIR),
            "port": args.debug_port,
            "auto_open": True,
            "soma_dir": str(SOMA_DIR),
        },
        daemon=True,
    )
    dash_thread.start()
    _time.sleep(0.8)  # let server bind
    print(f"\n  [DASH] Dashboard: http://127.0.0.1:{args.debug_port}", flush=True)

    # ── Step 1: Select session ─────────────────────────────────────────
    if args.picker:
        paths = run_session_picker()
        if not paths:
            print("No sessions selected. Exiting.")
            return 0
        session_path = Path(paths[0])
    elif args.path:
        session_path = Path(args.path).expanduser().resolve()
    else:
        print("Error: provide --path or --picker")
        return 1

    if not session_path.is_dir():
        print(f"Session dir not found: {session_path}")
        return 1

    print(f"\n  Session: {session_path.name}")
    print(f"  Path: {session_path}")

    # ── Step 2: Load session ───────────────────────────────────────────
    print("\n  Loading session...", flush=True)
    sessions = load_source(session_path)
    if not sessions:
        print("  No sessions loaded.")
        return 1

    session = sessions[0]
    print(f"  Chat sets: {len(session.chatsets)}")
    print(f"  Total chars: {sum(cs.chars for cs in session.chatsets)}")

    # ── Set dashboard session context ──────────────────────────────────
    set_current_session(
        session_id=session.session_id,
        title=session_path.name,
        chars=sum(cs.chars for cs in session.chatsets),
    )
    append_event({
        "session_id": session.session_id,
        "session_title": session_path.name,
        "status": "loaded",
        "total_sets": len(session.chatsets),
        "total_chars": sum(cs.chars for cs in session.chatsets),
        "timestamp": _time.strftime("%Y-%m-%dT%H:%M:%SZ"),
    })

    # ── Step 3: Init SQLite DB ─────────────────────────────────────────
    db_path = str(SOMA_DIR / "soma.db")
    print(f"\n  Soma DB: {db_path}")

    if _prompt_enter("Init SQLite DB?"):
        print("  [INIT] Writing soma_template.sql to DB...", flush=True)
        soma = Soma(path=db_path, force_empty=True)
        print(f"  [INIT] Tables created, nodes: {soma.node_count()}")
        _prompt_enter("Continue to ingestion?")

        # ── Step 4: Ingest all chat sets ───────────────────────────
        print(f"\n{'='*60}")
        print(f"  INGESTING {len(session.chatsets)} CHAT SETS")
        print(f"{'='*60}", flush=True)

        bridge = SomaBridge(soma)

        # Write SessionAnchor
        anchor = bridge.write_session_anchor(
            session.session_id,
            project_name="Dendritic",
            total_sets=len(session.chatsets),
            total_chars=sum(cs.chars for cs in session.chatsets),
        )
        print(f"  [Node] SessionAnchor: {anchor}", flush=True)

        # Ingest each chat set
        for cs in session.chatsets:
            cs_node = bridge.write_chatset(
                session.session_id,
                cs.chatset_id,
                cs.set_number,
                cs.chars,
                provider=cs.provider,
                models_used=cs.models,
            )
            print(f"  [Node] ChatSet #{cs.set_number}: {cs_node}", flush=True)

        print(f"\n  [INGEST] Total nodes: {soma.node_count()}")
        print(f"  [INGEST] Total edges: {soma.edge_count()}")
        soma.commit_batch()  # ensure all batched writes are flushed

        # ── Step 5: Run pipeline stages ──────────────────────────────
        if not args.profile:
            print("\n  No --profile specified. Loading from defaults...")
            from run_engine import _default_profile
            args.profile = _default_profile()

        if not args.profile:
            print("  No TurnKey profile found. Stages will be skipped.")
            print("  Run with: python distiller.py --path <session> --profile <profile.json>")
        else:
            print(f"\n  Profile: {args.profile}")
            client = EngineClient(args.profile)
            max_stages = args.max_stages or len(PIPELINE_STAGES)
            chatsets = session.chatsets

            for i, (stage_name, stage_label) in enumerate(PIPELINE_STAGES[:max_stages]):
                print(f"\n{'#'*60}")
                print(f"  STAGE {i+1}/{max_stages}: {stage_label}")
                print(f"  Processing {len(chatsets)} chat sets")
                print(f"{'#'*60}", flush=True)

                # Wait for Enter before each stage
                if not _prompt_enter(f"Run stage {i+1}/{max_stages}: {stage_label}?"):
                    print(f"\n  [SKIP] Skipping stage {stage_label} and all remaining.")
                    break

                stage_ok_all = True
                for cs in chatsets:
                    success = _run_stage(
                        client, soma, bridge, session, cs,
                        stage_name, stage_label,
                        dashboard_dir=DASHBOARD_DIR,
                    )
                    if not success:
                        stage_ok_all = False
                        print(f"  [WARN] ChatSet #{cs.set_number} failed gate.")
                        cont = _prompt_enter("Continue to next chatset?")
                        if not cont:
                            break
                    else:
                        print(f"  [OK] ChatSet #{cs.set_number} completed.")

                if stage_ok_all:
                    print(f"  [OK] Stage {stage_label} — all chat sets passed.")
                else:
                    print(f"  [WARN] Stage {stage_label} — some chat sets failed.")

                cont = _prompt_enter("Continue to next stage?")
                if not cont:
                    print(f"\n  [DONE] Stopping after stage {i+1}.")
                    break

            print(f"\n  Soma DB after pipeline: nodes={soma.node_count()} edges={soma.edge_count()}")

        print(f"\n  [COMPLETE] DB written to {db_path}")
        soma.close()

    print("\n  Distiller done.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
