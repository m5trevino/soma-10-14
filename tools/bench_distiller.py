#!/usr/bin/env python3
"""Benchmark distiller candidates on one real chat set.

Score is not "did it return something". It is:
  json       the response parses to an object
  schema     distiller_output present
  entries    directives/constraints/preferences/questions emitted
  verified   entries whose quoted text actually exists in the transcript
  usable     verified > 0 and the gate would pass

``verified`` is the only number that matters. A model that emits twelve
directives it invented scores worse than one that emits two real ones,
because fabrication is the failure this pipeline exists to prevent.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path("/home/flintx/soma-10-14")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, "/home/flintx/turn-key")

from soma.machinetalk.client import EngineClient        # noqa: E402
from soma.machinetalk.gate import _extract_json_object  # noqa: E402
from soma.machinetalk.provenance import verify_distiller  # noqa: E402

PROMPT = """You are the Distiller. Read the chat set and return one JSON object.

Output the JSON object and nothing else. No preamble, no reasoning, no
markdown fences. The first character of your response must be '{' and the
last must be '}'.

Schema:
{"distiller_output": {"directives": [{"text": "<verbatim sentence>", "turn": <int>}],
                      "constraints": [], "preferences": [], "questions": [],
                      "verdict": false, "skip_reason": ""}}

Every "text" must be copied exactly from the message at "turn". Do not
summarise, paraphrase, or invent. If the chat has no signal, return the
schema with empty lists and "verdict": true.
"""


def load_chatset(queue: Path, session: str, number: int) -> list[dict]:
    """Resolve a session dir the way run_engine.py does, then take one chunk."""
    from soma.run_engine import load_queue
    from soma.machinetalk.source import load_session

    for path in load_queue(str(queue)):
        if path.name != session:
            continue
        sess = load_session(path)
        for cs in sess.chatsets:
            if cs.set_number == number:
                return cs.raw_chat_set
    raise SystemExit(f"{session}:{number} not found")


def render(raw: list[dict]) -> str:
    out = []
    for i, m in enumerate(raw):
        out.append(f"[{i}] {m.get('role','?')}: {m.get('content','')}")
    return "\n\n".join(out)


def run_one(model: str, transcript: str, raw: list[dict], extra: bool) -> dict:
    prof = json.loads((ROOT / "turn-key-profile" /
                       "turnkey-profile_2026-11-02T08-40-12.json").read_text())
    prof["deck"] = [{"uid": "b", "modelId": model,
                     "modelName": model, "provider": "gw"}]
    prof.setdefault("pipeline", {})["maxRetries"] = 0
    tmp = Path(f"/tmp/bench_{abs(hash(model))}.json")
    tmp.write_text(json.dumps(prof))

    msgs = [{"role": "system", "content": PROMPT},
            {"role": "user", "content": transcript}]
    t0 = time.monotonic()
    try:
        client = EngineClient(str(tmp))
        res = client._call_with_retry("distiller", msgs, attempts=1)
        elapsed = time.monotonic() - t0
        text = res.content
    except Exception as exc:
        return {"model": model, "ok": False, "why": f"{type(exc).__name__}: "
                f"{str(exc)[:60]}", "secs": time.monotonic() - t0}
    finally:
        tmp.unlink(missing_ok=True)

    warnings: list[str] = []
    obj, errs = _extract_json_object(text, warnings)
    if obj is None:
        return {"model": model, "ok": False,
                "why": (errs or ["parse_failed"])[0][:60], "secs": elapsed,
                "chars": len(text)}

    body = obj.get("distiller_output") if isinstance(
        obj.get("distiller_output"), dict) else obj
    counted = 0
    for key in ("directives", "constraints", "preferences",
                "questions", "corrections"):
        counted += len(body.get(key) or [])

    prov = verify_distiller(obj, raw)
    repaired = any(w.startswith("repaired") for w in warnings)
    prose = any(w.startswith("prose") for w in warnings)

    return {"model": model, "ok": True, "secs": elapsed, "chars": len(text),
            "entries": counted, "verified": prov.verified,
            "rejected": len(prov.issues), "prose": prose,
            "repaired": repaired,
            "usable": prov.verified > 0,
            "errs": [str(i) for i in prov.issues[:2]]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--queue", default=str(ROOT / "data/soma_queue.json"))
    ap.add_argument("--session", default="trevino.war.room")
    ap.add_argument("--chatset", type=int, default=6)
    ap.add_argument("--models", default="")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--out", default="/tmp/distiller_bench.json")
    a = ap.parse_args()

    raw = load_chatset(Path(a.queue), a.session, a.chatset)
    transcript = render(raw)
    print(f"chatset {a.session}:{a.chatset}  {len(raw)} messages  "
          f"{len(transcript):,} chars\n")

    if a.models:
        models = [m.strip() for m in a.models.split(",") if m.strip()]
    else:
        prof = json.loads((ROOT / "turn-key-profile" /
                           "turnkey-profile_2026-11-02T08-40-12.json").read_text())
        models = [c["modelId"] for c in prof["deck"]]
    print(f"{len(models)} models, {a.workers} workers\n")

    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=a.workers) as pool:
        futs = {pool.submit(run_one, m, transcript, raw, True): m
                for m in models}
        done = 0
        for f in as_completed(futs):
            done += 1
            r = f.result()
            results.append(r)
            mark = "OK " if r.get("usable") else ("--  " if r.get("ok") else "ERR ")
            print(f"  [{done:2}/{len(models)}] {mark}{r['model'][:44]:46} "
                  f"{r.get('secs',0):6.1f}s  {r.get('why','')}", flush=True)

    Path(a.out).write_text(json.dumps(results, indent=2))

    good = [r for r in results if r.get("usable")]
    print(f"\n{'='*96}\nUSABLE: {len(good)}/{len(results)}\n{'='*96}")
    good.sort(key=lambda r: (-r["verified"], r["secs"]))
    print(f"{'MODEL':46}{'VERIF':>7}{'ENTRIES':>9}{'REJECT':>8}{'SECS':>7}")
    for r in good:
        print(f"{r['model'][:44]:46}{r['verified']:>7}{r['entries']:>9}"
              f"{r['rejected']:>8}{r['secs']:>7.1f}")

    bad = [r for r in results if not r.get("usable")]
    if bad:
        print(f"\nREJECTED ({len(bad)}):")
        for r in sorted(bad, key=lambda r: r["model"]):
            why = r.get("why") or (r.get("errs") or ["no verified entries"])[0]
            print(f"  {r['model'][:44]:46} {why[:62]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
