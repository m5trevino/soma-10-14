# truth-inference patches

`/media/storage/dendritic123/truth-inference` is not a git repository, so the
fixes applied on 2026-11-01 exist only as working files. This directory records
exactly what changed so the patches can be reapplied if that tree is lost.

Original file: `src/truth_inference/inference.py` (250 lines, dated 2026-07-03).

The two scripts beside this file (`rebuild_truth.py`, `load_truth.py`) are
copies of the code that rebuilds the corpus from the `anchors` table and loads
it into `truth` / `truth_fts`. They are versioned here for the same reason.

---

## 1. Chunk rescan inside the group loop

**Where:** `TruthInferenceEngine.run`, originally line 136.

**Problem:** the loop that collected `typed_relations` rescanned every chunk
for every group:

```python
for key, anchors in groups.items():        # ~604,000 groups
    ...
    for chunk in chunks:                   # ~375,243 chunks
        if chunk.chunk_id in {s.chunk_id for s in sources}:
            relations.extend(chunk.typed_relations)
```

604,000 x 375,243 is roughly 226 trillion iterations. The engine never
returned. It was never observed because the package had never been run — the
forensic report of 2026-10-22 records it as not importable, with the `.pth`
pointing at `/media/storage/dendritic/truth-inference/src` (missing the `123`).

**Fix:** materialise `chunks` once and index relations by chunk id before the
group loop, then look up per source.

---

## 2. Quadratic conflict detection

**Where:** `TruthInferenceEngine.run`, phase 2.

**Problem:** every pair of records inside a `repo:family` scope was compared.
The largest scope holds ~78,470 records:

```
ClickHouse|DATA_INVARIANTS     78,470
ClickHouse|STATE_TRANSITIONS   39,707
ClickHouse|API_CONTRACTS       35,145
```

78,470^2 / 2 is about 3.1 billion comparisons, each normalizing two statements.
Days, not minutes.

**Fix (two parts):**

- `run(..., detect_conflicts=False)` skips phase 2 entirely. Collapse and
  scoring are linear.
- When conflicts are requested, candidates are bucketed by
  `_contradiction_bucket()` — the statement with negators removed, reduced to
  its two most identifying words. The pairwise test still decides; the bucket
  only narrows who is compared.

Result on the full corpus: 611,172 records, 6 with conflicts, in a few minutes.

---

## 3. `model_names` rejected `None`

**Where:** `TruthInferenceEngine._score`, originally line 80.

**Problem:** some anchors carry `extraction_model: null` and the pydantic
`TruthScore.model_names: list[str]` rejects it:

```
ValidationError: model_names.0  Input should be a valid string
  [input_value=None]
```

**Fix:**

```python
model_names=sorted({
    (a.provenance.extraction_model or "unknown")
    for a in anchors if a.provenance
}),
```

---

## 4. Repository path

`/media/storage/dendritic123/truth-inference/.venv` has no packages installed
and its `.pth` points at a path that does not exist. The package is usable by
putting `src` on `PYTHONPATH`:

```bash
cd /media/storage/dendritic123/truth-inference
PYTHONPATH=src ./.venv/bin/python rebuild_truth.py
```

No install is required.

---

## Rebuild procedure

```bash
cd /media/storage/dendritic123/truth-inference

# 1. reconstruct ExtractedChunk objects from the anchors table and collapse
PYTHONPATH=src ./.venv/bin/python rebuild_truth.py --conflicts \
    --out /media/storage/invariants/truth_records.jsonl

# 2. load into a queryable table with FTS
./.venv/bin/python load_truth.py
```

Expected output of step 1:

```
chunks 375,243   anchors 611,299
truth records 611,172
records with conflicts 6
composite  min 0.198  avg 0.590  max 0.762
```

Step 2 additionally builds `truth` and `truth_fts` in
`/media/storage/invariants/invariants.db`, which `LawCorpus` reads.
