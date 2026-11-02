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
import statistics
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


# A dropped connection says nothing about the model. These are retried so
# the score reflects the model rather than the network.
_TRANSPORT = ("RemoteDisconnected", "ConnectionError", "TimeoutError",
              "ConnectionResetError", "IncompleteRead", "TIMEOUT",
              "CONNECTION_ERROR")


def _is_transport(why: str) -> bool:
    return any(tok in why for tok in _TRANSPORT)


def run_once(model: str, transcript: str, raw: list[dict],
             run_index: int, transport_retries: int = 2,
             temperature: float | None = 0.0) -> dict:
    """One model call. ``run_index`` only names the temp profile."""
    prof = json.loads((ROOT / "turn-key-profile" /
                       "turnkey-profile_2026-11-02T08-40-12.json").read_text())
    prof["deck"] = [{"uid": "b", "modelId": model,
                     "modelName": model, "provider": "gw"}]
    prof.setdefault("pipeline", {})["maxRetries"] = 0
    # A pinned stage would override the single-card deck and measure the pin
    # instead of the model under test.
    for st in prof.get("stages") or []:
        st["pinnedModels"] = []
        st["useDeck"] = True
    tmp = Path(f"/tmp/bench_{abs(hash(model))}_{run_index}.json")
    tmp.write_text(json.dumps(prof))

    msgs = [{"role": "system", "content": PROMPT},
            {"role": "user", "content": transcript}]
    text = ""
    last_why = ""
    t0 = time.monotonic()
    try:
        client = EngineClient(str(tmp))
        for attempt in range(transport_retries + 1):
            try:
                res = client._call_with_retry("distiller", msgs, attempts=1,
                                              temperature=temperature)
                text = res.content
                break
            except Exception as exc:
                last_why = f"{type(exc).__name__}: {str(exc)[:60]}"
                if not _is_transport(last_why) or attempt >= transport_retries:
                    raise
                time.sleep(2 + attempt * 3)
        else:
            raise RuntimeError(last_why)
    except Exception as exc:
        return {"ok": False, "why": f"{type(exc).__name__}: "
                f"{str(exc)[:60]}", "secs": time.monotonic() - t0,
                "transport": _is_transport(str(exc)) or _is_transport(last_why)}
    finally:
        tmp.unlink(missing_ok=True)
    elapsed = time.monotonic() - t0

    warnings: list[str] = []
    obj, errs = _extract_json_object(text, warnings)
    if obj is None:
        return {"ok": False, "why": (errs or ["parse_failed"])[0][:60],
                "secs": elapsed, "chars": len(text)}

    body = obj.get("distiller_output") if isinstance(
        obj.get("distiller_output"), dict) else obj
    counted = sum(len(body.get(k) or []) for k in
                  ("directives", "constraints", "preferences",
                   "questions", "corrections"))

    prov = verify_distiller(obj, raw)
    return {"ok": True, "secs": elapsed, "chars": len(text),
            "entries": counted, "verified": prov.verified,
            "rejected": len(prov.issues),
            "prose": any(w.startswith("prose") for w in warnings),
            "repaired": any(w.startswith("repaired") for w in warnings),
            "usable": prov.verified > 0,
            "errs": [str(i) for i in prov.issues[:2]]}


def run_model(model: str, transcript: str, raw: list[dict],
              runs: int, temperature: float | None = 0.0) -> dict:
    """Call one model ``runs`` times and summarise the distribution.

    A single call is not a measurement. The same prompt against the same
    model has returned 62 verified entries once and 3 on reruns, so a
    ranking built from one sample is noise. The median is the headline;
    ``floor`` and ``ceiling`` show how much the model can be trusted when
    the run that matters is the one that happens tonight.
    """
    samples: list[dict] = []
    for i in range(runs):
        samples.append(run_once(model, transcript, raw, i,
                                temperature=temperature))

    good = [s for s in samples if s.get("ok")]
    secs = [s["secs"] for s in samples]

    # A run that failed to return anything is a zero, not a gap. Dropping
    # transport failures from the sample list made a model that answered
    # once out of three look identical to one that answered three times,
    # which is the opposite of what the audit is for.
    verified = [s["verified"] if s.get("ok") else 0 for s in samples]
    failures = [s.get("why", "no response") for s in samples if not s.get("ok")]

    if not good:
        why = failures[0] if failures else "no run"
        return {"model": model, "runs": runs, "ok": False, "why": why,
                "median": 0, "floor": 0, "ceiling": 0, "mean": 0.0,
                "usable": False, "parsed_runs": 0, "failed_runs": runs,
                "empty_runs": runs, "samples": verified,
                "failures": failures[:2],
                "secs": statistics.median(secs) if secs else 0.0}

    return {
        "model": model, "runs": runs, "ok": True,
        "median": statistics.median(verified),
        "floor": min(verified), "ceiling": max(verified),
        "mean": statistics.fmean(verified),
        "usable": statistics.median(verified) > 0,
        "empty_runs": sum(1 for v in verified if v == 0),
        "parsed_runs": len(good),
        "failed_runs": len(samples) - len(good),
        "entries": max((s.get("entries", 0) for s in good), default=0),
        "rejected": max((s.get("rejected", 0) for s in good), default=0),
        "secs": statistics.median(secs) if secs else 0.0,
        "samples": verified,
        "failures": failures[:2],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--queue", default=str(ROOT / "data/soma_queue.json"))
    ap.add_argument("--session", default="trevino.war.room")
    ap.add_argument("--chatset", type=int, default=6)
    ap.add_argument("--models", default="")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--runs", type=int, default=3,
                    help="calls per model; the median is the score")
    ap.add_argument("--temperature", type=float, default=0.0,
                    help="sampling temperature; 0 makes runs comparable")
    ap.add_argument("--out", default="/tmp/distiller_bench.json")
    a = ap.parse_args()

    raw = load_chatset(Path(a.queue), a.session, a.chatset)
    transcript = render(raw)
    print(f"chatset {a.session}:{a.chatset}  {len(raw)} messages  "
          f"{len(transcript):,} chars")
    print(f"{a.runs} run(s) per model, temperature={a.temperature}, "
          f"scored on the median\n")

    if a.models:
        models = [m.strip() for m in a.models.split(",") if m.strip()]
    else:
        prof = json.loads((ROOT / "turn-key-profile" /
                           "turnkey-profile_2026-11-02T08-40-12.json").read_text())
        models = [c["modelId"] for c in prof["deck"]]
    print(f"{len(models)} models, {a.workers} workers, "
          f"{len(models) * a.runs} total calls\n")

    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=a.workers) as pool:
        futs = {pool.submit(run_model, m, transcript, raw, a.runs,
                            a.temperature): m
                for m in models}
        done = 0
        for f in as_completed(futs):
            done += 1
            r = f.result()
            results.append(r)
            if r.get("ok"):
                mark = "OK " if r["usable"] else "--  "
                fail = (f"  ({r['failed_runs']} failed)"
                        if r.get("failed_runs") else "")
                print(f"  [{done:2}/{len(models)}] {mark}{r['model'][:40]:42} "
                      f"med={r['median']:>5.0f} floor={r['floor']:>3} "
                      f"ceil={r['ceiling']:>4} {r['samples']} "
                      f"{r['secs']:.0f}s{fail}", flush=True)
            else:
                print(f"  [{done:2}/{len(models)}] ERR {r['model'][:40]:42} "
                      f"{r['why'][:40]}", flush=True)

    Path(a.out).write_text(json.dumps(results, indent=2))

    good = [r for r in results if r.get("usable")]
    good.sort(key=lambda r: (-r["median"], -r["floor"], r["secs"]))
    print(f"\n{'=' * 104}")
    print(f"STABLE FLOOR: {len(good)}/{len(results)} models with median > 0")
    print(f"{'=' * 104}")
    print(f"{'MODEL':42}{'MEDIAN':>8}{'FLOOR':>7}{'CEIL':>6}{'ZEROS':>7}"
          f"{'FAIL':>6}{'SECS':>7}  SAMPLES")
    for r in good:
        print(f"{r['model'][:40]:42}{r['median']:>8.0f}{r['floor']:>7}"
              f"{r['ceiling']:>6}{r['empty_runs']:>7}{r['failed_runs']:>6}"
              f"{r['secs']:>7.0f}  {r['samples']}")

    # A model whose floor is zero cannot be depended on for a single run,
    # which is how the pipeline actually uses it.
    unstable = [r for r in good if r["floor"] == 0]
    if unstable:
        print(f"\nUNSTABLE (median > 0 but at least one empty run): "
              f"{len(unstable)}")
        for r in unstable:
            print(f"  {r['model'][:40]:42} median={r['median']:.0f} "
                  f"samples={r['samples']}")

    bad = [r for r in results if not r.get("usable")]
    if bad:
        print(f"\nUNUSABLE ({len(bad)}):")
        for r in sorted(bad, key=lambda r: r["model"]):
            why = r.get("why") or "median 0"
            print(f"  {r['model'][:40]:42} {why[:56]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
