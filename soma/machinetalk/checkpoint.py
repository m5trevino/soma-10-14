"""Checkpoint state: per-session .checkpoint.json, atomic writes.

Layout (one file per session, under the run's output dir):

    <out>/checkpoints/<session_id>.checkpoint.json
    {
      "session_id": "...",
      "chatsets": {
        "3": {
          "chatset_id": "sess:3",
          "chatset_hash": "sha256...",
          "chars": 12345,
          "stages": {
            "distiller":  {"status": "DONE", "verdict": "", "models": ["x"],
                            "tokens": 123, "latency_ms": 100, "ts": "...",
                            "artifact": "stage1/3_distiller.md"},
            "introbeaver": {"status": "PENDING"},
            ...
          }
        }
      },
      "session_stages": {
        "nexus":   {"status": "DONE", ...},
        ...
      },
      "updated_at": "..."
    }

Statuses: PENDING | RUNNING | DONE | FAILED | SKIPPED | BLOCKED
  * DONE    -- gate passed (artifact usable downstream)
  * SKIPPED -- distiller skip; the ChatSet is vaulted, downstream stages
               for it are marked SKIPPED automatically
  * BLOCKED -- hard-block verdict (REWORK/NO-GO/etc.); operator decision
  * FAILED  -- all retry models exhausted

`--from <stage>`: a stage may run if every upstream stage for the same
chatset (stage1) or session (stage2-4) is DONE/SKIPPED-appropriately.
`--redo <stage>`: clears that stage's state (and, for stage1, everything
downstream within the same chatset) before running.
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

PENDING, RUNNING, DONE, FAILED, SKIPPED, BLOCKED = (
    "PENDING", "RUNNING", "DONE", "FAILED", "SKIPPED", "BLOCKED")

STAGE1 = ["distiller", "introbeaver", "planbeaver", "outrobeaver"]
STAGE234 = ["nexus", "spark", "falcon", "eagle", "drafter", "scout", "oc", "olc"]

_UPSTREAM = {
    "distiller": [],
    "introbeaver": ["distiller"],
    "planbeaver": ["introbeaver"],
    "outrobeaver": ["planbeaver"],
    "nexus": STAGE1,                      # needs all chatsets' stage1 done
    "spark": ["nexus"],
    "falcon": ["spark"],
    "eagle": ["falcon"],
    "drafter": ["eagle"],
    "scout": ["drafter"],
    "oc": ["scout", "drafter"],
    "olc": ["oc"],
}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _atomic_write(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(obj, f, indent=2, ensure_ascii=False)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


class CheckpointStore:
    def __init__(self, out_dir: Path) -> None:
        self.out_dir = Path(out_dir)
        self.dir = self.out_dir / "checkpoints"
        self._cache: dict[str, dict] = {}

    # -- io ----------------------------------------------------------------

    def _path(self, session_id: str) -> Path:
        return self.dir / f"{session_id}.checkpoint.json"

    def load(self, session_id: str) -> dict:
        if session_id in self._cache:
            return self._cache[session_id]
        p = self._path(session_id)
        if p.exists():
            data = json.loads(p.read_text())
        else:
            data = {"session_id": session_id, "chatsets": {},
                    "session_stages": {}, "updated_at": _now()}
        self._cache[session_id] = data
        return data

    def _save(self, session_id: str) -> None:
        data = self._cache[session_id]
        data["updated_at"] = _now()
        _atomic_write(self._path(session_id), data)

    # -- chatset (stage 1) ---------------------------------------------------

    def ensure_chatset(self, session_id: str, set_number: int,
                       chatset_id: str, chatset_hash: str, chars: int) -> dict:
        data = self.load(session_id)
        key = str(set_number)
        cs = data["chatsets"].get(key)
        if cs is None:
            cs = {"chatset_id": chatset_id, "chatset_hash": chatset_hash,
                  "chars": chars, "stages": {s: {"status": PENDING}
                                             for s in STAGE1}}
            data["chatsets"][key] = cs
        return cs

    def cs_stage(self, session_id: str, set_number: int, stage: str) -> dict:
        cs = self.load(session_id)["chatsets"].get(str(set_number))
        if cs is None:
            return {"status": PENDING}
        return cs["stages"].get(stage, {"status": PENDING})

    def cs_mark(self, session_id: str, set_number: int, stage: str, status: str,
                **info) -> None:
        cs = self.ensure_chatset(session_id, set_number, "", "", 0)
        st = cs["stages"].setdefault(stage, {"status": PENDING})
        st["status"] = status
        # Store verbose CallRecord fields only when not PENDING
        for k in ("raw_response", "sys_prompt", "user_msg"):
            if k in info:
                val = info[k]
                if val is not None:
                    # Truncate to prevent checkpoint bloat
                    if k == "sys_prompt":
                        val = val[:5000]
                    else:
                        val = val[:10000]
                st[k] = val
        st.update({k: v for k, v in info.items() if k not in ("raw_response", "sys_prompt", "user_msg") and v is not None})
        st["ts"] = _now()
        self._save(session_id)

    def cs_is_done(self, session_id: str, set_number: int, stage: str) -> bool:
        return self.cs_stage(session_id, set_number, stage)["status"] in (DONE, SKIPPED)

    def cs_downstream_skipped(self, session_id: str, set_number: int, from_stage: str) -> None:
        """After a distiller SKIP: mark the remaining stage1 stages SKIPPED."""
        cs = self.ensure_chatset(session_id, set_number, "", "", 0)
        started = False
        for s in STAGE1:
            if s == from_stage:
                started = True
            if started:
                st = cs["stages"].setdefault(s, {"status": PENDING})
                if st["status"] in (PENDING, RUNNING):
                    st["status"] = SKIPPED
                    st["ts"] = _now()
        self._save(session_id)

    def cs_redo(self, session_id: str, set_number: int, stage: str) -> None:
        """Clear stage + all downstream stage1 stages for this chatset."""
        cs = self.ensure_chatset(session_id, set_number, "", "", 0)
        started = False
        for s in STAGE1:
            if s == stage:
                started = True
            if started:
                cs["stages"][s] = {"status": PENDING}
        self._save(session_id)

    # -- session stages (2-4) --------------------------------------------------

    def ss_stage(self, session_id: str, stage: str) -> dict:
        return self.load(session_id)["session_stages"].get(stage,
                                                           {"status": PENDING})

    def ss_mark(self, session_id: str, stage: str, status: str, **info) -> None:
        data = self.load(session_id)
        st = data["session_stages"].setdefault(stage, {"status": PENDING})
        st["status"] = status
        st.update({k: v for k, v in info.items() if v is not None})
        st["ts"] = _now()
        self._save(session_id)

    def ss_is_done(self, session_id: str, stage: str) -> bool:
        return self.ss_stage(session_id, stage)["status"] == DONE

    def ss_redo(self, session_id: str, stage: str) -> None:
        data = self.load(session_id)
        for s in STAGE234:
            if s == stage:
                data["session_stages"][s] = {"status": PENDING}
                for later in STAGE234[STAGE234.index(s) + 1:]:
                    data["session_stages"][later] = {"status": PENDING}
        self._save(session_id)

    # -- readiness -----------------------------------------------------------

    def can_run_chatset_stage(self, session_id: str, set_number: int,
                              stage: str) -> tuple[bool, str]:
        """Upstream stage1 stages must be DONE (or SKIPPED at the skip point)."""
        cs = self.load(session_id)["chatsets"].get(str(set_number))
        if cs is None:
            return False, "chatset not initialized"
        for up in _UPSTREAM.get(stage, []):
            if up in STAGE1:
                st = cs["stages"].get(up, {}).get("status", PENDING)
                if st not in (DONE, SKIPPED):
                    return False, f"upstream {up} is {st}"
        return True, ""

    def can_run_session_stage(self, session_id: str, stage: str,
                              sessions: list) -> tuple[bool, str]:
        """nexus needs this session's stage1 fully done; others chain."""
        for up in _UPSTREAM.get(stage, []):
            if up in STAGE1:
                for cs in self.load(session_id)["chatsets"].values():
                    if cs["stages"].get(up, {}).get("status") not in (DONE, SKIPPED):
                        return False, f"upstream {up} incomplete for chatset {cs['chatset_id']}"
                continue
            if self.ss_stage(session_id, up)["status"] not in (DONE, SKIPPED):
                return False, f"upstream {up} is {self.ss_stage(session_id, up)['status']}"
        return True, ""

    def delete_soma(self) -> bool:
        """Delete the soma.json file for the output directory.
        Returns True if file was deleted, False if it didn't exist.
        """
        soma_path = self.out_dir / "soma.json"
        if soma_path.exists():
            soma_path.unlink()
            return True
        return False

    def force_clear_chatset(self, session_id: str, set_number: int) -> None:
        """Reset ALL stage1 steps for a chatset to PENDING (force re-run)."""
        cs = self.ensure_chatset(session_id, set_number, "", "", 0)
        for stg in STAGE1:
            cs["stages"][stg] = {"status": PENDING}
        self._save(session_id)

    def force_clear_session(self, session_id: str) -> None:
        """Reset ALL stages for a session to PENDING (full force re-run)."""
        data = self.load(session_id)
        # Stage 1 steps
        for cs_id, cs_data in data.get("chatsets", {}).items():
            for stg in STAGE1:
                cs_data["stages"][stg] = {"status": PENDING}
        # Build/processing stages
        for stg in STAGE234:
            data["session_stages"][stg] = {"status": PENDING}
        self._save(session_id)
