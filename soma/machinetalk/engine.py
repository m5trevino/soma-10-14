"""Pipeline engine: runs the 4-stage machine-talk pipeline.

Run modes
---------
single session : --source <session_dir>  (or --source <proj> --session <id>)
project        : --source <proj_dir>     (all sessions under it)

Stage 1 (INGESTION) -- per ChatSet, parallel (1 worker = 1 ChatSet, workers
never cross sessions):
    distiller -> introbeaver -> planbeaver -> outrobeaver
    distiller SKIP -> skip vault, downstream stages for that ChatSet = SKIPPED

Stage 2-4 (MAPPING / CREATION / FINALIZING) -- run ONCE per build unit,
sequentially. A build unit is the session (single-session mode) or ALL
sessions merged chronologically (project mode). Chronological supremacy
inside nexus means the newest session's intent wins conflicts -- that is how
"N sessions -> 1 blueprint -> 1 codebase" happens.
    nexus -> spark -> falcon -> eagle -> drafter -> scout -> oc -> olc
    oc REWORK -> build BLOCKED (rework_order saved; operator drives --redo)

State: checkpoints/ (resume), artifacts/ (machine-readable chain),
stage1|stage2|... markdown (evidence), codebase/ (final files),
run_manifest.md (proof of every call).

Soma integration (NEW): Every successful stage writes corresponding nodes
and edges to the per-session Soma graph store, preserving
the same node types and edge types used by the legacy pipeline dendrites.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from . import fleet
from .checkpoint import (CheckpointStore, DONE, FAILED, RUNNING, SKIPPED,
                         BLOCKED, PENDING)
from .client import EngineClient as MachineTalkClient
from .gate import is_done, is_hard_block
from .hashes import canonical_json, chatset_hash_for
from .report import (Manifest, card_session_stage, write_artifact,
                     write_skip_vault)
from .source import ChatSet, Session
from .logger import StageLogger
from . import progress

# ── Stage-1 stages that drive the one-line spinner ───────────────────────
_LIVE_STAGES = ("distiller", "introbeaver", "planbeaver", "outrobeaver")

# Per-session SOMA databases: <repo>/somas/<session_id>/soma.json
SOMAS_DIR = Path(__file__).resolve().parents[2] / "somas"

# ── Dividers ──────────────────────────────────────────────────────────────
_DIVIDER = ("■□■□■□■□■□■□■□■■□■□■□■□■□■□■□■■□■□■□■□■□■□■□"
            "■■□■□■□■□■□■□■□■■□■□■□■□■□■□■□■■□■□■□■□■□■□■□"
            "■■□■□■□■□■□■□■□■■□■□■□■□■□■□■□■■□■□■□■□■□■□■□■")

# -- Soma integration (NEW) ---------------------------------------------
import os as _os
from pathlib import Path as _Path
import json as _json
import threading as _threading
try:
    from ..store import Soma
except ImportError:
    from store import Soma


class AtomicSoma:
    """Soma with atomic persistence (write to .tmp, then rename)."""

    def __init__(self, path: str):
        self._path = _Path(path)
        self._soma = Soma(str(self._path))
        self._lock = _threading.Lock()

    def __getattr__(self, name):
        return getattr(self._soma, name)

    @property
    def path(self) -> _Path:
        """On-disk location of the persisted SOMA database."""
        return self._path

    def _persist(self) -> None:
        """Atomic write: dump to .tmp, then rename."""
        with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            # Handle both old in-memory Soma (_nodes dict) and new SQLite-backed Soma
            if hasattr(self._soma, "_nodes"):
                nodes = {
                    nid: {"type": n.node_type, "properties": n.properties}
                    for nid, n in self._soma._nodes.items()
                }
                edges = [
                    {"source": e.source, "rel_type": e.rel_type,
                     "target": e.target, "id": getattr(e, "id", "")}
                    for e in self._soma._edges
                ]
            else:
                # SQLite-backed Soma — query the database
                rows = self._soma._conn.execute(
                    "SELECT node_id, node_type, properties FROM nodes ORDER BY node_id"
                ).fetchall()
                nodes = {row[0]: {"type": row[1], "properties": json.loads(row[2])} for row in rows}
                edge_rows = self._soma._conn.execute(
                    "SELECT edge_id, source, rel_type, target FROM edges ORDER BY edge_id"
                ).fetchall()
                edges = [{"id": r[0], "source": r[1], "rel_type": r[2], "target": r[3]} for r in edge_rows]
            data = {"nodes": nodes, "edges": edges}
            tmp_path = self._path.with_suffix(self._path.suffix + ".tmp")
            with open(tmp_path, "w", encoding="utf-8") as f:
                _json.dump(data, f, indent=2)
            _os.rename(tmp_path, self._path)


from .soma_bridge import SomaBridge

GROUP_OF = {
    "distiller": "stage1", "introbeaver": "stage1", "planbeaver": "stage1",
    "outrobeaver": "stage1", "nexus": "stage2", "spark": "stage2",
    "falcon": "stage2", "eagle": "stage3", "drafter": "stage3",
    "scout": "stage3", "oc": "stage4", "olc": "stage4",
}

_PATH_RE = re.compile(r"(?:^|[\s`'(])(/[\w.\-/]+\.(?:py|js|ts|go|sh|json|md|html|css|ya?ml|toml|txt|c|cpp|h))")

# ---------------------------------------------------------------------------
# Scout text report -> structured (best-effort, Python side)
# ---------------------------------------------------------------------------

def parse_scout_report(raw: str, verdict: str) -> dict:
    violations = []
    blocks = re.split(r"^\[(PASS|FAIL|WARN|SKIP)\]\s+(\S+)[—-]\s*(.*)$",
                      raw, flags=re.M)
    # blocks: [pre, kind, id, title, body, kind, id, title, body, ...]
    for i in range(1, len(blocks) - 3, 4):
        kind, cid, title, body = blocks[i], blocks[i + 1], blocks[i + 2], blocks[i + 3]
        sev_m = re.search(r"Severity:\s*(\w+)", body)
        type_m = re.search(r"Type:\s*(\w+)", body)
        msg_m = re.search(r"Message:\s*(.+)", body)
        violations.append({
            "contract_id": cid.strip(),
            "status": kind.lower(),
            "severity": (sev_m.group(1).lower() if sev_m else
                         ("high" if kind == "FAIL" else "info")),
            "type": (type_m.group(1).lower() if type_m else ""),
            "message": (msg_m.group(1).strip() if msg_m else title.strip()),
        })
    criticals = [v for v in violations
                 if v["severity"] == "critical" and v["status"] == "fail"]
    fails = [v for v in violations if v["status"] == "fail"]
    total = len(violations)
    health = 0.0 if (criticals or verdict == "REWORK") else (
        0.9 if not fails else max(0.5, 1 - 0.15 * len(fails)))
    return {
        "analysis_id": f"SCOUT-{verdict}",
        "scout_verdict": verdict,
        "violations": violations,
        "blockers": [v["contract_id"] for v in criticals],
        "aggregate_health": round(health, 2),
    }


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class Engine:
    def __init__(self, *, out_dir: Path, client: MachineTalkClient,
                 workers: int = 4, quiet: bool = False,
                 force: bool = False,
                 gateway_map: dict | None = None,
                 debug_dir: str | None = None,
                 max_chatsets: int | None = None,
                 step_mode: bool = False,
                 soma_path: Path | None = None) -> None:
        self.out = Path(out_dir)
        self.client = client
        self.workers = max(1, workers)
        self.force = force
        self.max_chatsets = max_chatsets
        self.step_mode = step_mode
        self.granular = False
        self.gateway_map = gateway_map
        self.ck = CheckpointStore(self.out, layout="chunk")
        self.manifest = Manifest(self.out)
        self.art_dir = self.out / "artifacts"
        self.log = StageLogger(cwd=Path.cwd(), out_dir=self.out, quiet=quiet)
        self._print = (lambda *a: None) if quiet else progress.emit
        self._debug_dir = Path(debug_dir) if debug_dir else None
        if self._debug_dir:
            self._debug_dir.mkdir(parents=True, exist_ok=True)
        self._manifest_lock = threading.Lock()

        # Soma graph store (per-session by default)
        soma_file = Path(soma_path) if soma_path else self.out / "soma.json"
        self._soma = AtomicSoma(str(soma_file))
        self._bridge = SomaBridge(self._soma)
        self._soma_lock = threading.Lock()
        self._print_lock = threading.Lock()

    # -- logging helpers (NEW) ---------------------------------------------

    def _log_summary(self, stage: str, session: str, counts: dict[str, int],
                    chatset: int | None = None) -> None:
        """Print per-task summary from SomaBridge return dict."""
        if not counts:
            return
        parts = [f"{k}={v}" for k, v in counts.items() if v > 0]
        if not parts:
            return
        # Suppress output for Stage 1 — we print clean tables, not interleaved logs
        if stage in ("distiller", "introbeaver", "planbeaver", "outrobeaver"):
            return
        detail = "  → " + ", ".join(parts)
        self._print(detail)
        self.log.info(stage, f"session={session}" +
                      (f" chatset={chatset}" if chatset else "") +
                      f" | {', '.join(parts)}")

    def _with_spinner(self, label: str, fn, *args,
                      live_stage: str = "", **kwargs):
        """Run ``fn`` behind the one-line stage progress printer.

        Only the four Stage-1 beaver stages own the live line. Other stages
        keep printing normally so their timeout warnings stay visible.
        """
        if live_stage in _LIVE_STAGES:
            return progress.spin(label, fn, *args, **kwargs)
        return fn(*args, **kwargs)

    def _timeout_watcher(self, label: str, timeout: float,
                          stop: threading.Event) -> None:
        """Background thread that prints warnings at 50/75/90% of timeout."""
        thresholds = [
            (0.50, "[⚠ SLOW]"),
            (0.75, "[⚠ SLOW]"),
            (0.90, "[⚠ TIMEOUT IMMINENT]"),
        ]
        for pct, prefix in thresholds:
            wait = timeout * pct
            if stop.wait(timeout=wait):
                return
            if not stop.is_set():
                elapsed = time.monotonic() - self._watch_start
                remaining = timeout - elapsed
                self._print(f"  {prefix} {label} elapsed={elapsed:.0f}s/{timeout:.0f}s "
                            f"remaining={remaining:.0f}s")

    def _print_dashboard(self, sessions: list[Session]) -> None:
        """Print compact status board for all sessions and their stages."""
        from .checkpoint import STAGE1, STAGE234
        # Symbols
        SYM = {"DONE": "✓", "SKIPPED": "≋", "RUNNING": "→RUN", "BLOCKED": "⊘",
               "FAILED": "✗", "PENDING": "-"}
        lines = []
        lines.append("  " + "═" * 70)
        # Header
        all_stages = STAGE1 + STAGE234
        hdr = "  SESSION        " + "".join(f"{s[:6]:<7}" for s in all_stages)
        lines.append(hdr)
        lines.append("  " + "─" * 70)
        # Per session rows
        for s in sessions:
            sid = s.session_id
            data = self.ck.load(sid)
            cs_rows = data.get("chatsets", {})
            row = f"  {sid:<14} "
            # Stage 1: aggregate across chatsets
            for stg in STAGE1:
                statuses = [cs["stages"].get(stg, {}).get("status", "PENDING")
                            for cs in cs_rows.values()]
                if any(st == "RUNNING" for st in statuses):
                    sym = SYM["RUNNING"]
                elif any(st == "FAILED" for st in statuses):
                    sym = SYM["FAILED"]
                elif any(st == "BLOCKED" for st in statuses):
                    sym = SYM["BLOCKED"]
                elif all(st in ("DONE", "SKIPPED") for st in statuses):
                    sym = SYM["DONE"]
                elif any(st == "SKIPPED" for st in statuses):
                    sym = SYM["SKIPPED"]
                else:
                    sym = SYM["PENDING"]
                row += f"{sym:<7}"
            # Stage 2-4: per session
            for stg in STAGE234:
                st = data.get("session_stages", {}).get(stg, {}).get("status", "PENDING")
                row += f"{SYM.get(st, '?'):<7}"
            lines.append(row)
        lines.append("  " + "═" * 70)
        for line in lines:
            self._print(line)

    # -- artifact helpers ----------------------------------------------------

    # -- artifact helpers ----------------------------------------------------

    def _save_artifact(self, build: str, stage: str, obj) -> Path:
        p = self.art_dir / build / f"{stage}.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(canonical_json(obj) if isinstance(obj, (dict, list))
                       else str(obj))
        tmp.replace(p)
        return p

    def _load_artifact(self, build: str, stage: str):
        p = self.art_dir / build / f"{stage}.json"
        if p.exists():
            return json.loads(p.read_text())
        return None

    # -- stage 1: one chatset, all 4 beaver stages in order ------------------

    def _beaver_payload(self, cs: ChatSet, *, extra: dict | None = None) -> dict:
        payload = {
            "session_id": cs.session_id,
            "chatset_id": cs.chatset_id,
            "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "chatset_hash": cs.chatset_hash,
            "raw_chat_set": cs.raw_chat_set,
        }
        if extra:
            payload.update(extra)
        return payload

    def _run_chatset_stage(self, cs: ChatSet, stage: str,
                           worker: int, payload: dict | None = None,
                           chunk: str = "", contracts: str = "") -> bool:
        """Run one stage for one chatset; checkpoint + artifact + card.

        Returns True when the stage is DONE (or cleanly SKIPPED).
        """
        sid, n = cs.session_id, cs.set_number
        cur = self.ck.cs_stage(sid, n, stage)
        if cur["status"] == DONE:
            if self.force:
                self._print(f"  [W{worker}] {n}:{stage} forced re-run (was DONE)")
            else:
                self._print(f"  … [W{worker}] {n}:{stage} already DONE (resume skip)")
                self.log.info(stage, f"{sid} CS{n} already DONE (resume)")
                return True
        if cur["status"] == SKIPPED:
            if not self.force:
                return True

        self.ck.cs_mark(sid, n, stage, RUNNING)
        model = self.client.model_for(stage)
        self.log.start(stage, session=sid, chatset=n, model=model,
                       detail=f"chars={cs.chars} hash={cs.chatset_hash[:16]}…")

        t0 = time.monotonic()
        spinner_label = f"{stage} {sid} CS{cs.source_chunk_id or n} {model}"
        is_stage1 = stage in _LIVE_STAGES
        if stage == "distiller" and self._print is progress.emit:
            # Show the distiller's processing steps on a ~30 s cadence while
            # the single LLM call runs underneath.
            prog = progress.DistillerProgress(target=30.0)
            prog.start()
            try:
                res = self.client.call_stage(
                    stage, session_id=sid, chatset_id=cs.chatset_id,
                    chunk=chunk, contracts=contracts, payload=payload,
                    expected_hash=cs.chatset_hash,
                )
            finally:
                prog.finish()
        elif is_stage1:
            res = self._with_spinner(
                spinner_label,
                self.client.call_stage,
                stage, session_id=sid, chatset_id=cs.chatset_id,
                chunk=chunk, contracts=contracts, payload=payload,
                expected_hash=cs.chatset_hash if stage in
                ("distiller", "introbeaver") else None,
                live_stage=stage,
            )
        else:
            # Timeout watcher for non-stage1
            self._watch_start = t0
            stop_event = threading.Event()
            watcher = threading.Thread(
                target=self._timeout_watcher,
                args=(spinner_label, self.client.timeout, stop_event),
                daemon=True,
            )
            watcher.start()
            try:
                res = self._with_spinner(
                    spinner_label,
                    self.client.call_stage,
                    stage, session_id=sid, chatset_id=cs.chatset_id,
                    chunk=chunk, contracts=contracts, payload=payload,
                    expected_hash=cs.chatset_hash if stage in
                    ("distiller", "introbeaver") else None,
                    live_stage=stage,
                )
            finally:
                stop_event.set()
                watcher.join(timeout=0.5)
        rec, gate = res.record, res.record.gate or GateResult(skipped=False, verdict="UNKNOWN", reasons=["Stage exhausted"], errors=[], parsed=None)
        latency = (time.monotonic() - t0) * 1000
        with self._manifest_lock:
            self.manifest.add(rec, gate)
        p = write_artifact(self.out, sid, stage, n, rec, gate,
                           group=GROUP_OF[stage])
        
        # ── Debug event writing ─────────────────────────
        if self._debug_dir:
            try:
                from .debug_dashboard_skeu import write_event
                import traceback

                status = rec.status
                status_map = {"pass": "done", "fail": "failed", "blocked": "failed", "": "running"}

                # Convert non-serializable values to string (safe fallback)
                def safe(val):
                    try:
                        json.dumps(val)
                        return val
                    except (TypeError, ValueError):
                        return str(val)[:500]

                ev = {
                    "stage": stage,
                    "status": status_map.get(status, status),
                    "session_id": sid,
                    "chatset_number": n,
                    "chatset_id": cs.chatset_id,
                    "chars_in": cs.chars,
                    "model": rec.model or "unknown",
                    "tokens": rec.total_tokens,
                    "prompt_tokens": rec.prompt_tokens,
                    "completion_tokens": rec.completion_tokens,
                    "latency_ms": round(rec.latency_ms, 1),
                    "attempts": safe(rec.attempts if rec.attempts else [{"attempt": 1, "model": rec.model or "unknown"}]),
                    "errors": rec.error or (gate.errors if gate.errors else gate.reasons) if not is_done(gate) else "",
                    "verdict": gate.verdict or "",
                    "raw_response": rec.raw_response or "",
                    "sys_prompt": rec.sys_prompt or "",
                    "user_msg": rec.user_msg or "",
                    "payload": safe(gate.parsed) if gate.parsed else {},
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                }
                write_event(self._debug_dir, ev)
            except Exception as e:
                traceback.print_exc()
                # Route through _print so this never writes to stdout while a
                # stage spinner owns the live line (progress.emit defers it).
                self._print(f"WARNING: debug event write failed: {e}")
        if is_done(gate):
            self.ck.cs_mark(sid, n, stage, DONE,
                            verdict=gate.verdict or None,
                            model=rec.model, tokens=rec.total_tokens,
                            chars_in=cs.chars,
                            latency_ms=round(rec.latency_ms, 1),
                            artifact=str(p.relative_to(self.out)),
                            raw_response=rec.raw_response,
                            sys_prompt=rec.sys_prompt,
                            user_msg=rec.user_msg,
                            errors=rec.error or (gate.errors if gate.errors else gate.reasons) if not is_done(gate) else "",)
            if gate.skipped and stage == "distiller":
                write_skip_vault(self.out, sid, n, gate, rec,
                                 transcript_head=cs.transcript())
                self.ck.cs_downstream_skipped(sid, n, "distiller")
            if gate.skipped:
                self.log.skip(stage, session=sid, chatset=n,
                              detail=f"tokens={rec.total_tokens} ms={latency:.0f} model={rec.model}")
                self._print(f"  -[{stage.upper()}]- [SKIPPED]")
                self._print(f"  model={rec.model or 'N/A'} chars_in={cs.chars} kept={rec.completion_tokens} dropped={rec.prompt_tokens}")
                elapsed_s = latency / 1000
                self._print(f"  Done in {elapsed_s:.0f}s")
            else:
                self.log.done(stage, session=sid, chatset=n,
                               detail=f"tokens={rec.total_tokens} ms={latency:.0f} model={rec.model} verdict={gate.verdict}")
                self._print(f"  -[{stage.upper()}]- [SUCCESS]")
                self._print(f"  model={rec.model or 'N/A'} chars_in={cs.chars} kept={rec.completion_tokens} dropped={rec.prompt_tokens}")
                elapsed_s = latency / 1000
                self._print(f"  Done in {elapsed_s:.0f}s")
            if gate.parsed is not None:
                self._save_artifact(cs.chatset_id, stage, gate.parsed)
            # ---- Soma graph writes (NEW: legacy pipeline compatibility) ----
            with self._soma_lock:
                if stage == "distiller":
                    self._bridge.write_receptor(
                        sid, cs.chatset_id, n, gate, rec.model, latency)
                    dcounts = self._bridge.write_distilled(
                        sid, cs.chatset_id, n, gate, rec.model, latency)
                    self._log_summary(stage, sid, dcounts, chatset=n)
                elif stage in ("introbeaver", "planbeaver", "outrobeaver"):
                    counts = self._bridge.write_intro_plan_outrobeaver(
                        sid, cs.chatset_id, stage, gate, rec.model, latency)
                    self._log_summary(stage, sid, counts, chatset=n)
                self._soma._persist()
            if stage == "distiller":
                self._print(progress.distiller_summary(
                    self._soma.path, gate.parsed))
            return True
        if is_hard_block(gate):
            self.ck.cs_mark(sid, n, stage, BLOCKED,
                            verdict=gate.verdict, model=rec.model,
                            artifact=str(p.relative_to(self.out)))
            self.log.block(stage, session=sid, chatset=n,
                           detail=f"verdict={gate.verdict} models={len(rec.attempts)}")
            self._print(f"  -[{stage.upper()}]- [BLOCKED]")
            self._print(f"  model={rec.model or 'N/A'} chars_in={cs.chars} reason={gate.verdict or 'BLOCKED'}")
            elapsed_s = latency / 1000
            self._print(f"  Done in {elapsed_s:.0f}s")
        else:
            self.ck.cs_mark(sid, n, stage, FAILED, model=rec.model,
                            errors=gate.reasons[:300],
                            artifact=str(p.relative_to(self.out)))
            self.log.fail(stage, session=sid, chatset=n,
                          detail=f"models={len(rec.attempts)} errors={gate.reasons[:80]}")
            self._print(f"  -[{stage.upper()}]- [FAILED]")
            self._print(f"  model={rec.model or 'N/A'} chars_in={cs.chars} reason={gate.reasons[0] if gate.reasons else 'UNKNOWN'}")
            elapsed_s = latency / 1000
            self._print(f"  Done in {elapsed_s:.0f}s")
        return False

    def run_chatset(self, cs: ChatSet, worker: int = 0) -> dict:
        """All of stage 1 for one chatset, in order. Returns per-stage dict."""
        sid, n = cs.session_id, cs.set_number
        self.ck.ensure_chatset(sid, n, cs.chatset_id, cs.chatset_hash, cs.chars)

        # Print current chatset character count before each stage
        with self._print_lock:
            self._print(
                f"  [{n}] {cs.chars:,} character(s) in this chatset")

        # ---- Soma: SessionAnchor + ChatSet + raw Messages ----
        totals = getattr(self, "_session_totals", {}).get(sid, (1, cs.chars))
        with self._soma_lock:
            self._bridge.write_session_anchor(
                sid, project_name="Dendritic",
                total_sets=totals[0],
                total_chars=totals[1])
            self._bridge.write_chatset(
                sid, cs.chatset_id, n, cs.chars,
                chatset_hash=cs.chatset_hash,
                provider=cs.provider, models_used=list(cs.models))
            self._bridge.write_raw_messages(cs)
            self._soma._persist()

        result: dict[str, str] = {}

        # Each beaver reads the raw ChatSet directly. No cross-dependencies.
        _all_stages = ("distiller", "introbeaver", "planbeaver", "outrobeaver")
        _run_stages = (getattr(self, "_stage", None) or "distiller")
        _run_stages = (_run_stages,) if isinstance(_run_stages, str) else _run_stages

        if self.granular:
            self._print("\n  [Step: write SessionAnchor+ChatSet to Soma]")
            self._print("  Enter to run, Ctrl+C to skip")
            try:
                input()
            except EOFError:
                pass

        for stage in _all_stages:
            if stage not in _run_stages:
                continue
            if self.granular:
                self._print(f"\n  [Step: {stage.upper()}]")
                self._print("  Enter to run, Ctrl+C to skip")
                try:
                    answer = input().strip().lower()
                    if answer == "n" or answer == "no":
                        self._print(f"  Skipping {stage}.")
                        result[stage] = SKIPPED
                        continue
                except EOFError:
                    pass
                pass  # no input, will proceed
            extra = {}
            if stage == "planbeaver":
                extra = {"codebase_context": {"existing_files": [],
                                              "language": None,
                                              "framework": None,
                                              "conventions": []},
                         "invariant_rules": []}
            if stage == "outrobeaver":
                paths = sorted(set(_PATH_RE.findall(
                    cs.user_text + "\n" + cs.assistant_text)))
                extra = {"final_artifact_state": {
                    "files_created": paths, "files_modified": [],
                    "lines_of_code": None, "functions_implemented": [],
                    "functions_planned": [],
                    "session_outcome": "PARTIAL"},
                    "user_feedback": []}
            chunk = cs.transcript() if stage == "distiller" else ""
            try:
                ok = self._run_chatset_stage(
                    cs, stage, worker,
                    payload=self._beaver_payload(cs, extra=extra),
                    chunk=chunk)
            except Exception as exc:
                detail = f"{type(exc).__name__}: {exc}"
                self.ck.cs_mark(sid, n, stage, FAILED,
                                model=None, chars_in=cs.chars, errors=detail)
                self.log.fail(stage, session=sid, chatset=n, detail=detail)
                self._print(f"  -[{stage.upper()}]- [FAILED]")
                self._print(f"  model=N/A chars_in={cs.chars} reason={detail}")
                result[stage] = FAILED
                ok = False
            else:
                result[stage] = self.ck.cs_stage(sid, n, stage)["status"]
            if not ok and stage == "distiller":
                # Distiller skip still marks the rest SKIPPED.
                if self.ck.cs_stage(sid, n, "distiller")["status"] == SKIPPED:
                    for s in ("introbeaver", "planbeaver", "outrobeaver"):
                        result[s] = "SKIPPED"
                    return result

        return result

    # -- stage 1 across chatsets (parallel, workers never cross sessions) ----

    def run_stage1(self, sessions: list[Session],
                   only: tuple[str, int] | list[tuple[str, int]] | None = None) -> bool:
        """Run stage1 for all chatsets, or only the selected (sid, set) pairs."""
        # Determine which stages to run: stage="distiller" means only distiller
        stages_to_run = ("distiller", "introbeaver", "planbeaver", "outrobeaver")
        selected = (getattr(self, "_stage", None)
                    or getattr(self, "_selected_stage", None))
        if selected:
            stages_to_run = (selected,)

        # Normalise ``only`` to a set of (session_id, set_number) tuples.
        wanted: set[tuple[str, int]] | None = None
        if only:
            if (isinstance(only, tuple) and len(only) == 2
                    and isinstance(only[0], str)):
                wanted = {only}
            else:
                wanted = set(only)

        jobs = []
        for s in sessions:
            for cs in s.chatsets:
                if wanted is not None and (cs.session_id, cs.set_number) not in wanted:
                    continue
                if not self.force:
                    last = stages_to_run[-1]
                    if self.ck.cs_stage(cs.session_id, cs.set_number,
                                        last)["status"] in (DONE, SKIPPED):
                        continue  # fully done, resume
                jobs.append(cs)

        # Accurate per-session totals for the SessionAnchor (not per chatset).
        self._session_totals = {
            s.session_id: (len(s.chatsets), sum(c.chars for c in s.chatsets))
            for s in sessions
        }

        # Apply max_chatsets limit
        if self.max_chatsets is not None and self.max_chatsets > 0 and self.max_chatsets < len(jobs):
            jobs = jobs[:self.max_chatsets]
        if not jobs:
            if self.force:
                self._print("  Nothing to do.")
            else:
                self._print("  Stage 1: nothing to do (all DONE or SKIPPED).")
            return True

        # Group jobs by session for header output
        session_jobs: dict[str, list[ChatSet]] = {}
        for cs in jobs:
            session_jobs.setdefault(cs.session_id, []).append(cs)

        # Print total session character count before the first chatset
        total_chars = sum(cs.chars for cs in jobs)
        self._print(
            f"  Total session: {total_chars:,} character(s) across "
            f"{len(jobs)} chatset(s)")

        # Print session headers
        for sid in sorted(session_jobs.keys()):
            s_jobs = session_jobs[sid]
            cs0 = s_jobs[0]
            total_sets = cs0.total_sets or len(s_jobs)
            self._print(progress.session_header(sid, total_sets))

        label = "STAGE 1 (FORCE)" if self.force else "STAGE 1: INGESTION"
        # Print session name, total chatsets, current index before first stage
        session_id = session_jobs.get(
            next(iter(session_jobs)), [None])[0].session_id if session_jobs else "unknown"
        total_sets = len(jobs)
        self._print(f"\n  Session: {session_id} | {total_sets} total chatset(s) | "
                    f"Worker(s): {self.workers}")
        self._print(f"\n=== {label} -- {total_sets} chatset(s), "
                    f"{self.workers} worker(s) ===")

        # Print individual chatset character counts before starting ingestion
        for i, cs in enumerate(jobs, 1):
            self._print(f"  Chatset {i}/{total_sets} character count: {cs.chars:,}")

        ok = True
        counts = {"done": 0, "failed": 0, "skipped": 0}
        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            futs = {}
            for i, cs in enumerate(jobs, 1):
                f = pool.submit(self.run_chatset, cs, i)
                futs[f] = cs
            completed = 0
            for f in as_completed(futs):
                cs = futs[f]
                completed += 1
                self._print(f"Chatset {cs.source_chunk_id or cs.set_number} finished. Total characters: {cs.chars:,}")
                try:
                    r = f.result()
                except Exception as e:
                    ok = False
                    self._print(f"  ✗ chatset {cs.chatset_id} crashed: {e}")
                    continue
                # Count chatset by actual outcome: DONE only when all stages pass
                r_d = r.get("distiller", "")
                if r_d == SKIPPED:
                    counts["skipped"] += 1
                elif any(r.get(s) in (FAILED, BLOCKED) for s in (
                        "distiller", "introbeaver", "planbeaver", "outrobeaver")):
                    counts["failed"] += 1
                    ok = False
                elif all(r.get(s) == DONE for s in (
                        "distiller", "introbeaver", "planbeaver", "outrobeaver")):
                    counts["done"] += 1

                # ── Debug event writing ─────────────────────────
                if self._debug_dir:
                    try:
                        from .debug_dashboard_skeu import write_event
                        # Read checkpoint data for this chatset
                        ck_data = {}
                        for sn in ("distiller", "introbeaver", "planbeaver", "outrobeaver"):
                            sd = self.ck.cs_stage(sid, n, sn)
                            if sd.get("status") not in ("PENDING", "RUNNING"):
                                ck_data[sn] = sd
                        # Build debug event
                        ev = {
                            "session_id": sid,
                            "chatset_number": n,
                            "chatset_id": cs.chatset_id,
                            "chars_in": cs.chars,
                            "chatset_hash": cs.chatset_hash[:12] + "…",
                            "stages": ck_data,
                            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                        }
                        write_event(self._debug_dir, ev)
                    except Exception:
                        pass  # debug failure doesn't break pipeline

                # ── Print clean table after chatset completes ─
                sid, n = cs.session_id, cs.set_number
                stages_data: dict[str, Any] = {}
                for sn in ("distiller", "introbeaver", "planbeaver", "outrobeaver"):
                    sd = self.ck.cs_stage(sid, n, sn)
                    if sd.get("status") not in ("PENDING", "RUNNING"):
                        stages_data[sn] = sd
                self._print(progress.chatset_table(n, cs.total_sets or len(cs.chatsets),
                                                   stages_data,
                                                   gateway_map=self.gateway_map))
                self._print(_DIVIDER)
                self._print()
        # Print overall summary
        self._print(progress.session_summary(
            counts["done"], counts["failed"], counts["skipped"], len(jobs)))
        return ok

    # -- stages 2-4: one build unit (session or merged project) --------------

    def _merged_raw(self, sessions: list[Session]) -> list[dict]:
        """All chatsets of the build unit, chronological, deduped by hash."""
        seen: set[str] = set()
        merged: list[dict] = []
        for s in sorted(sessions, key=lambda x: x.sort_key):
            for cs in s.chatsets:
                if cs.chatset_hash in seen:
                    continue
                seen.add(cs.chatset_hash)
                merged.extend(cs.raw_chat_set)
        return merged

    def _run_build_stage(self, build: str, stage: str, *,
                         chunk: str = "", contracts: str = "",
                         payload: dict | None = None,
                         expected_hash: str | None = None) -> bool:
        cur = self.ck.ss_stage(build, stage)
        if cur["status"] in (DONE, SKIPPED):
            self.log.info(stage, f"{build} already {cur['status']} (resume)")
            return True
        self.ck.ss_mark(build, stage, RUNNING)
        model = self.client.model_for(stage)
        self.log.start(stage, session=build, model=model,
                       detail=f"build_unit={build}")
        t0 = time.monotonic()
        # ---- Spinner + timeout watcher (NEW) ----
        spinner_label = f"{stage} {build} {model}"
        self._watch_start = t0
        stop_event = threading.Event()
        watcher = threading.Thread(
            target=self._timeout_watcher,
            args=(spinner_label, self.client.timeout, stop_event),
            daemon=True,
        )
        watcher.start()
        try:
            res = self._with_spinner(
                spinner_label,
                self.client.call_stage,
                stage, session_id=build, chatset_id=build,
                chunk=chunk, contracts=contracts, payload=payload,
                expected_hash=expected_hash,
                live_stage=stage,
            )
        finally:
            stop_event.set()
            watcher.join(timeout=0.5)
        rec, gate = res.record, res.record.gate or GateResult(skipped=False, verdict="UNKNOWN", reasons=["Stage exhausted"], errors=[], parsed=None)
        latency = (time.monotonic() - t0) * 1000
        with self._manifest_lock:
            self.manifest.add(rec, gate)
        p = write_artifact(self.out, build, stage, None, rec, gate,
                           group=GROUP_OF[stage])
        if is_done(gate):
            self.ck.ss_mark(build, stage, DONE, verdict=gate.verdict or None,
                            model=rec.model, tokens=rec.total_tokens,
                            latency_ms=round(rec.latency_ms, 1),
                            artifact=str(p.relative_to(self.out)))
            if gate.parsed is not None:
                self._save_artifact(build, stage, gate.parsed)
            self.log.done(stage, session=build,
                          detail=f"tokens={rec.total_tokens} ms={latency:.0f} model={rec.model} verdict={gate.verdict}")
            # ---- Soma graph writes (NEW: legacy pipeline compatibility) ----
            # Stats line: model, chars_in, kept, dropped
            chars_in = self.ck.load(build).get("chatsets", {}).get("1", {}).get("chars", 0)
            self._print(f"  model={rec.model or 'N/A'} chars_in={chars_in} kept={rec.completion_tokens} dropped={rec.prompt_tokens}")
            with self._soma_lock:
                if stage == "nexus":
                    counts = self._bridge.write_nexus(build, gate, rec.model, latency)
                elif stage == "spark":
                    counts = self._bridge.write_spark(build, gate, rec.model, latency)
                elif stage == "falcon":
                    counts = self._bridge.write_falcon(build, gate, rec.model, latency)
                elif stage == "drafter":
                    counts = self._bridge.write_drafter(build, gate, rec.model, latency)
                elif stage == "scout":
                    counts = self._bridge.write_scout(build, gate, rec.model, latency)
                elif stage == "oc":
                    counts = self._bridge.write_oc(build, gate, rec.model, latency)
                elif stage == "olc":
                    counts = self._bridge.write_olc(build, gate, rec.model, latency)
                    t_counts = self._bridge.write_terminal(build, rec.model, latency)
                    counts.update(t_counts)
                    g_counts = self._bridge.write_gate(build)
                    counts.update(g_counts)
                else:
                    counts = {}
                self._soma._persist()
            self._log_summary(stage, build, counts)
            return True
        if is_hard_block(gate):
            self.ck.ss_mark(build, stage, BLOCKED, verdict=gate.verdict,
                            model=rec.model,
                            artifact=str(p.relative_to(self.out)))
            self.log.block(stage, session=build,
                           detail=f"verdict={gate.verdict} models={len(rec.attempts)}")
            self._print(f"  model={rec.model or 'N/A'} chars_in=0 kept={rec.completion_tokens} dropped={rec.prompt_tokens}")
        else:
            self.ck.ss_mark(build, stage, FAILED, model=rec.model,
                            errors=gate.reasons[:300],
                            artifact=str(p.relative_to(self.out)))
            self.log.fail(stage, session=build,
                          detail=f"models={len(rec.attempts)} errors={gate.reasons[:80]}")
            self._print(f"  model={rec.model or 'N/A'} chars_in=0 kept={rec.completion_tokens} dropped={rec.prompt_tokens}")
        return False

    def _merged_plan(self, sessions: list[Session]) -> dict | None:
        """Merge all chatsets' planbeaver outputs; newest file wins."""
        plans = []
        for s in sorted(sessions, key=lambda x: x.sort_key):
            for cs in s.chatsets:
                p = self._load_artifact(cs.chatset_id, "planbeaver")
                if p:
                    plans.append(p)
        if not plans:
            return None
        by_path: dict[str, dict] = {}
        contracts: dict[str, dict] = {}
        for p in plans:  # chronological -> later overwrites
            inner = p.get("planbeaver_output", p)
            for f in inner.get("files", []) or []:
                if f.get("path"):
                    by_path[f["path"]] = f
            for c in inner.get("data_contracts", []) or []:
                cid = c.get("contract_id")
                if cid:
                    contracts[cid] = c
        merged = {
            "plan_id": "PLAN-MERGED",
            "session_id": "merged",
            "version": "1.0.0",
            "files": list(by_path.values()),
            "data_contracts": list(contracts.values()),
            "execution_sequence": [f.get("file_id") for f in by_path.values()
                                   if f.get("file_id")],
        }
        return merged

    def run_stages_2_4(self, build: str, sessions: list[Session],
                       from_stage: str | None = None,
                       step_mode: bool = False,
                       granular: bool = False) -> bool:
        if granular:
            self._print("\n  [Step: Stages 2-4 build. Enter to run, Ctrl+C to skip]")
            try: input()
            except EOFError: pass
        merged_raw = self._merged_raw(sessions)
        h = chatset_hash_for(merged_raw)
        ctx = {"session_id": build, "chatset_id": build, "chatset_hash": h}
        skip_to = 0
        order = ["nexus", "spark", "falcon", "eagle", "drafter", "scout",
                 "oc", "olc"]
        if from_stage:
            if from_stage not in order:
                raise ValueError(f"--from: unknown build stage {from_stage!r}")
            skip_to = order.index(from_stage)

        # up front: load upstream artifacts for payload assembly
        def upstream(stage):
            return self._load_artifact(build, stage)

        stages = order[skip_to:]
        for stage in stages:
            if self.granular:
                self._print(f"\n  [Step: {stage.upper()} build stage]")
                self._print("  Enter to run, Ctrl+C to skip")
                try:
                    answer = input().strip().lower()
                    if answer == "n" or answer == "no":
                        self._print(f"  Skipping {stage}.")
                        st_status = SKIPPED
                    else:
                        st_status = None
                except EOFError:
                    st_status = None
                if st_status == SKIPPED:
                    self.ck.ss_stage(build, stage, st_status)
                    self._print(f"  {stage.upper()} [SKIPPED]")
                    continue
            self._print(f"\n=== {stage.upper()} ({build}) ===")
            if stage == "nexus":
                payload = {"session_id": build, "chatset_id": build,
                           "timestamp_utc": time.strftime(
                               "%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                           "chatset_hash": h, "raw_chat_set": merged_raw}
                ok = self._run_build_stage(build, "nexus", payload=payload,
                                           expected_hash=h)
            elif stage == "spark":
                nexus_out = upstream("nexus")
                if not ok if False else nexus_out is None:
                    self._print("  cannot run spark: nexus artifact missing")
                    return False
                payload = {"plan_context": ctx, "nexus_output": nexus_out}
                self._run_build_stage(build, "spark", payload=payload,
                                      expected_hash=h)
            elif stage == "falcon":
                spark_out = upstream("spark")
                if spark_out is None:
                    self._print("  cannot run falcon: spark artifact missing")
                    return False
                payload = {"plan_context": ctx,
                           "spark_specification_payload": spark_out}
                self._run_build_stage(build, "falcon", payload=payload,
                                      expected_hash=h)
            elif stage == "eagle":
                falcon_out = upstream("falcon")
                if falcon_out is None:
                    self._print("  cannot run eagle: falcon artifact missing")
                    return False
                self._run_build_stage(build, "eagle",
                                      chunk=canonical_json(falcon_out),
                                      expected_hash=h)
            elif stage == "drafter":
                plan = self._merged_plan(sessions)
                if plan is None:
                    self._print("  cannot run drafter: no planbeaver "
                                "artifacts in stage1")
                    return False
                payload = {"session_id": build,
                           "planbeaver_output": plan,
                           "template_library": {"language": None},
                           "style_guide": {"indent": "4 spaces",
                                            "naming": {"functions": "snake_case",
                                                       "files": "kebab-or_snake"},
                                            "docstring_format": "google"}}
                self._run_build_stage(build, "drafter", payload=payload)
            elif stage == "scout":
                draft = upstream("drafter")
                files = (draft.get("draft_artifact", {}) or {}).get("files", [])
                if not files:
                    self._print("  cannot run scout: no draft artifact")
                    return False
                code = "\n\n".join(
                    f"### {f.get('path')}\n{f.get('content', '')}" for f in files)
                # Scout queries the invariant registry. Eagle does not supply rules.
                from .invariants import InvariantRegistry
                exts = [Path(f.get("path", "")).suffix for f in files if f.get("path")]
                rules = InvariantRegistry().query(exts)
                contracts_txt = "\n".join(
                    f"{r['rule_id']}: {r['statement']} (severity {r['severity']})"
                    for r in rules) or "NONE"
                self._run_build_stage(build, "scout", chunk=code,
                                      contracts=contracts_txt)
                # parse scout text report into a JSON artifact for OC
                sc_raw = ""
                sc_verdict = ""
                sp = self.art_dir / build / "scout.json"
                if sp.exists():
                    sc_verdict = (json.loads(sp.read_text())
                                  .get("scout_verdict", ""))
                if sc_verdict:
                    # re-read raw from last stage2-4 artifact md is overkill;
                    # keep the parsed structure we just built
                    pass
                sc = self._load_artifact(build, "scout") or {}
                if not sc.get("violations"):
                    # rebuild from the markdown raw section
                    mdp = (self.out / "stage3" / f"{build}_scout.md")
                    raw_txt = mdp.read_text() if mdp.exists() else ""
                    m = re.search(r"## Raw Response\n```\n(.*?)\n```",
                                  raw_txt, re.S)
                    if m:
                        sc = parse_scout_report(m.group(1), sc_verdict)
                        self._save_artifact(build, "scout", sc)
            elif stage == "oc":
                draft = upstream("drafter")
                plan = self._merged_plan(sessions)
                sc = self._load_artifact(build, "scout") or {
                    "analysis_id": "SCOUT-UNKNOWN", "violations": [],
                    "blockers": [], "aggregate_health": 0.0}
                payload = {"session_id": build,
                           "draft_artifact": (draft or {}).get(
                               "draft_artifact", {}),
                           "scout_output": sc,
                           "planbeaver_output": plan or {}}
                ok2 = self._run_build_stage(build, "oc", payload=payload)
                if ok2:
                    oc = self._load_artifact(build, "oc") or {}
                    v = (oc.get("oc_decision", {}) or {}).get("verdict", "")
                    if v == "REWORK":
                        self.ck.ss_mark(build, "oc", BLOCKED, verdict="REWORK")
                        self._print("  ⊘ OC verdict REWORK -- build BLOCKED."
                                    " See rework_order; --redo drafter when"
                                    " ready.")
                        return False
            elif stage == "olc":
                oc = upstream("oc")
                sc = self._load_artifact(build, "scout") or {}
                # OLC reads the laws Scout wrote, not Eagle's output.
                violations = sc.get("violations", []) or []
                rules = [{"rule_id": v.get("contract_id", ""),
                          "severity": v.get("severity", "MEDIUM"),
                          "guard_template": v.get("message", "")} for v in violations]
                payload = {"session_id": build,
                           "oc_decision": (oc or {}).get("oc_decision", {}),
                           "scout_output": sc,
                           "invariant_rules": rules}
                if self._run_build_stage(build, "olc", payload=payload):
                    if self.granular:
                        self._print("\n  [Step: write codebase. Enter to run, Ctrl+C to skip]")
                        try: input()
                        except EOFError: pass
                    self._write_codebase(build, upstream)
            if not ok if stage == "nexus" else True:
                pass
            # ---- Dashboard board (NEW) ----
            self._print_dashboard(sessions)
            # stop on any non-DONE above
            st = self.ck.ss_stage(build, stage)["status"]
            if st not in (DONE, SKIPPED):
                self._print(f"  halting build at {stage}: {st}")
                return False
            if self.step_mode:
                print(f"\n  [{stage.upper()} done. Press Enter for next stage...]")
                input()
        return True

    def _write_codebase(self, build: str, upstream) -> None:
        target = self.out / "codebase" / build
        olc = upstream("olc")
        files = []
        if olc:
            files = (olc.get("olc_output", {}) or {}).get("hardened_files", [])
        if not files:
            draft = upstream("drafter") or {}
            files = (draft.get("draft_artifact", {}) or {}).get("files", [])
        for f in files:
            path = str(f.get("path", "")).lstrip("/")
            if not path or ".." in path:
                continue
            dest = target / path
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(f.get("content", ""))
        self._print(f"  ▸ codebase written: {target} "
                    f"({len(files)} file(s), "
                    f"{'hardened' if olc else 'draft'})")
        # ---- Soma: CodePublisher writes VerifiedNodes (NEW) ----
        with self._soma_lock:
            self._bridge.write_publisher(build, len(files))
            self._soma._persist()


# ---------------------------------------------------------------------------
# Top-level run
# ---------------------------------------------------------------------------

def run(sessions: list[Session], *, out_dir: Path,
        client: MachineTask if False else MachineTalkClient,
        workers: int = 4, from_stage: str | None = None,
        only: tuple[str, int] | list[tuple[str, int]] | None = None,
        quiet: bool = False,
        force: bool = False,
        gateway_map: dict | None = None,
        debug_dir: str | None = None,
        max_chatsets: int | None = None,
        step_mode: bool = False,
        stage: str | None = None,
        granular: bool = False) -> int:
    # One SOMA database per chat session. If --only targets a single
    # session, use that session's database even when the queue has more.
    target_session = None
    if only:
        pairs = ([only] if (isinstance(only, tuple) and len(only) == 2
                            and isinstance(only[0], str)) else list(only))
        sids = {p[0] for p in pairs}
        if len(sids) == 1:
            target_session = next(iter(sids))
    if target_session:
        soma_file = SOMAS_DIR / target_session / "soma.json"
    elif len(sessions) == 1:
        soma_file = SOMAS_DIR / sessions[0].session_id / "soma.json"
    else:
        soma_file = Path(out_dir) / "soma.json"

    eng = Engine(out_dir=out_dir, client=client, workers=workers,
                 quiet=quiet, force=force, gateway_map=gateway_map,
                 debug_dir=debug_dir, max_chatsets=max_chatsets,
                 step_mode=step_mode, soma_path=soma_file)
    if stage:
        eng._stage = stage
    eng.granular = granular
    if len(sessions) == 1:
        build = sessions[0].session_id
    else:
        # A readable concatenation of 18 session ids exceeds NAME_MAX and
        # turns every checkpoint stat into ENAMETOOLONG. Keep it stable but
        # short.
        names = "|".join(s.session_id for s in sessions)
        build = "project-" + hashlib.sha1(names.encode("utf-8")).hexdigest()[:16]

    # --- stage 1 -----------------------------------------------------------
    if from_stage in (None, "distiller"):
        if not eng.run_stage1(sessions, only=only):
            return 1
    elif from_stage in ("introbeaver", "planbeaver", "outrobeaver"):
        # start mid-stage1: ensure upstream DONE for the selected chatset(s)
        pass  # run_stage1 still walks all; checkpoint guards upstream

    if only or (max_chatsets is not None and max_chatsets > 0):
        # A bounded stage-1 run is a chunk batch. Stages 2-4 are project-wide
        # and must not run after one chunk.
        return 0

    if step_mode:
        print("\n  [Press Enter to continue to stages 2-4...]")
        input()

    if stage and stage != "distiller":
        return 0

    # --- stages 2-4 ----------------------------------------------------------
    if from_stage is None:
        build_from = None
    elif from_stage in ("nexus", "spark", "falcon", "eagle", "drafter",
                        "scout", "oc", "olc"):
        build_from = from_stage
    else:
        build_from = None

    if build_from or from_stage is None:
        ok = eng.run_stages_2_4(build, sessions, from_stage=build_from,
                                granular=granular)
    else:
        ok = True

    # final manifest
    if granular:
        eng._print("\n  [Step: manifest. Enter to run, Ctrl+C to skip]")
        try: input()
        except EOFError: pass
    header = {
        "build": build,
        "sessions": ", ".join(s.session_id for s in sessions),
        "finished": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "workers": workers,
    }
    mp = eng.manifest.render(header)
    eng._print(f"\nManifest: {mp}")
    return 0 if ok else 1
