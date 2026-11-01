"""Truth inference engine: composite scoring and conflict detection."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
from uuid import uuid5

import structlog
from tqdm import tqdm

from truth_inference.models import (
    AnchorRecord,
    ConflictRecord,
    ExtractedChunk,
    SourceReference,
    TruthRecord,
    TruthScore,
)
from truth_inference.normalizer import NAMESPACE_INFERENCE, NormalizedKey, StatementNormalizer

logger = structlog.get_logger()


class TruthInferenceEngine:
    """Collapse repo-scoped anchors into truth records with composite scores."""

    def __init__(
        self,
        normalizer: StatementNormalizer | None = None,
        confidence_weight: float = 0.35,
        model_weight: float = 0.25,
        evidence_weight: float = 0.25,
        provenance_weight: float = 0.15,
        contradiction_threshold: float = 0.6,
    ) -> None:
        self.normalizer = normalizer or StatementNormalizer()
        self.confidence_weight = confidence_weight
        self.model_weight = model_weight
        self.evidence_weight = evidence_weight
        self.provenance_weight = provenance_weight
        self.contradiction_threshold = contradiction_threshold

    def _truth_id(self, key: NormalizedKey) -> str:
        return str(uuid5(NAMESPACE_INFERENCE, key.repo + key.family + key.canonical_statement))

    def _score(self, anchors: list[AnchorRecord]) -> TruthScore:
        if not anchors:
            raise ValueError("Cannot score empty anchor list")

        confidences = [a.confidence for a in anchors]
        model_strengths = [a.model_strength() for a in anchors]
        evidence_counts = [len(a.evidence_spans) for a in anchors]
        provenance_counts = [
            len(a.provenance.input_shard_ids) if a.provenance else 0 for a in anchors
        ]

        confidence_component = sum(confidences) / len(confidences)
        model_strength_component = sum(model_strengths) / len(model_strengths)
        evidence_richness_component = min(1.0, (sum(evidence_counts) / max(1, len(anchors))) / 3.0)
        provenance_richness_component = min(1.0, (sum(provenance_counts) / max(1, len(anchors))) / 4.0)

        composite = round(
            self.confidence_weight * confidence_component
            + self.model_weight * model_strength_component
            + self.evidence_weight * evidence_richness_component
            + self.provenance_weight * provenance_richness_component,
            4,
        )

        return TruthScore(
            composite=composite,
            confidence_component=round(confidence_component, 4),
            model_strength_component=round(model_strength_component, 4),
            evidence_richness_component=round(evidence_richness_component, 4),
            provenance_richness_component=round(provenance_richness_component, 4),
            instance_count=len(anchors),
            model_names=sorted({
                (a.provenance.extraction_model or "unknown")
                for a in anchors if a.provenance
            }),
        )

    def _source_reference(self, anchor: AnchorRecord) -> SourceReference:
        best_span = anchor.evidence_spans[0] if anchor.evidence_spans else None
        return SourceReference(
            chunk_id=anchor.chunk_id,
            repo=anchor.repo,
            lens=anchor.lens,
            anchor_id=anchor.anchor_id,
            file_path=best_span.file_path if best_span else None,
            lines=best_span.lines if best_span else [],
            evidence_quote=best_span.quote if best_span else None,
            provenance=anchor.provenance,
        )

    _NEGATORS = ("does not", "is not", "cannot", "never", "not", "no")

    def _contradiction_bucket(self, statement: str) -> str:
        """Bucket key for conflict candidates: statement with negators removed.

        Two statements can only be direct contradictions if their negator-free
        cores are equal or one contains the other. Bucketing on a coarse
        projection of that core means the pairwise scan only runs inside small
        buckets instead of across an entire repo:family scope.
        """
        base = self.normalizer.normalize(statement)
        for n in self._NEGATORS:
            base = base.replace(n, " ")
        words = sorted({w for w in base.split() if len(w) > 2})
        # Bucket on the two most identifying words; the exact containment test
        # still decides, this only narrows the candidate set.
        return " ".join(words[:2]) if words else ""

    def _is_direct_contradiction(self, left: str, right: str) -> bool:
        """Detect direct contradictions using a lightweight heuristic."""
        left_norm = self.normalizer.normalize(left)
        right_norm = self.normalizer.normalize(right)
        if left_norm == right_norm:
            return False

        # Polar opposites.
        negators = set(self._NEGATORS)
        left_has_neg = any(n in left_norm for n in negators)
        right_has_neg = any(n in right_norm for n in negators)
        if left_has_neg != right_has_neg:
            base_left = left_norm
            base_right = right_norm
            for n in negators:
                base_left = base_left.replace(n, "").strip()
                base_right = base_right.replace(n, "").strip()
            # If the core action is identical, treat as contradictory.
            if base_left and base_right and (base_left in base_right or base_right in base_left):
                return True
        return False

    def run(self, chunks: Iterable[ExtractedChunk],
            detect_conflicts: bool = True) -> list[TruthRecord]:
        """Collapse anchors into truth records and detect conflicts.

        ``detect_conflicts=False`` skips phase 2. Conflict detection compares
        every pair of records inside a repo:family scope, which is quadratic:
        the ClickHouse/DATA_INVARIANTS scope alone holds ~78k records, i.e.
        ~3 billion comparisons. Run collapse first, then conflicts separately.
        """
        # Materialise the chunks once. ``chunks`` may be a generator, and the
        # relation lookup below needs the whole set.
        chunk_list = list(chunks)

        # Index relations by chunk id once. The original inner loop rescanned
        # every chunk for every group, which is O(groups x chunks) — with
        # ~600k groups and ~375k chunks that never returns.
        rel_by_chunk: dict[str, list] = defaultdict(list)
        for chunk in chunk_list:
            if chunk.typed_relations:
                rel_by_chunk[chunk.chunk_id].extend(chunk.typed_relations)

        groups: dict[NormalizedKey, list[AnchorRecord]] = defaultdict(list)
        for chunk in chunk_list:
            for anchor in chunk.semantic_anchors:
                key = self.normalizer.key(anchor.repo, anchor.family, anchor.statement)
                groups[key].append(anchor)

        truth_records: list[TruthRecord] = []
        key_to_truth: dict[NormalizedKey, str] = {}

        for key, anchors in groups.items():
            truth_id = self._truth_id(key)
            key_to_truth[key] = truth_id
            score = self._score(anchors)
            sources = [self._source_reference(a) for a in anchors]

            relations = []
            for s in sources:
                relations.extend(rel_by_chunk.get(s.chunk_id, ()))

            # De-duplicate by relation_id.
            seen_relations = set()
            unique_relations = []
            for rel in relations:
                if rel.relation_id not in seen_relations:
                    seen_relations.add(rel.relation_id)
                    unique_relations.append(rel)

            truth_records.append(
                TruthRecord(
                    truth_id=truth_id,
                    statement=anchors[0].statement,
                    family=anchors[0].family,
                    repo=anchors[0].repo,
                    scope=f"{anchors[0].repo}:{anchors[0].family}",
                    types=[anchors[0].type],
                    score=score,
                    sources=sources,
                    conflicts=[],
                    relations=unique_relations,
                    valid_from=min(
                        (a.valid_from or datetime.now(timezone.utc)) for a in anchors
                    ),
                    assumptions=sorted({assumption for anchor in anchors for assumption in anchor.assumptions}),
                    limitations=sorted({limitation for anchor in anchors for limitation in anchor.limitations}),
                )
            )

        if not detect_conflicts:
            return truth_records

        # Detect conflicts across records in the same repo+family scope.
        # Candidates are bucketed by their negator-free core so the pairwise
        # test only runs inside small buckets, not across an entire scope
        # (ClickHouse/DATA_INVARIANTS alone holds ~78k records).
        by_scope: dict[str, dict[str, list[TruthRecord]]] = defaultdict(
            lambda: defaultdict(list))
        for record in truth_records:
            bucket = self._contradiction_bucket(record.statement)
            if bucket:
                by_scope[record.scope][bucket].append(record)

        for scope_buckets in by_scope.values():
            for records in scope_buckets.values():
                if len(records) < 2:
                    continue
                for i, left in enumerate(records):
                    for right in records[i + 1 :]:
                        if self._is_direct_contradiction(left.statement, right.statement):
                            conflict_id = str(
                                uuid5(
                                    NAMESPACE_INFERENCE,
                                    f"conflict:{left.truth_id}:{right.truth_id}",
                                )
                            )
                            conflict = ConflictRecord(
                                conflict_id=conflict_id,
                                left_truth_id=left.truth_id,
                                right_truth_id=right.truth_id,
                                left_statement=left.statement,
                                right_statement=right.statement,
                                relation_type="CONTRADICTS",
                                severity=self.contradiction_threshold,
                                scope=left.scope,
                                reason="Detected direct contradiction via negation heuristic.",
                                left_sources=left.sources[:3],
                                right_sources=right.sources[:3],
                            )
                            left.conflicts.append(conflict)
                            right.conflicts.append(conflict)

        return truth_records


def run_inference(
    extracted_dir: Path,
    output_path: Path,
    limit: int | None = None,
) -> list[TruthRecord]:
    """Convenience runner that reads all extracted files and writes truth records."""
    from truth_inference.reader import read_extracted_file

    extracted_dir = Path(extracted_dir)
    output_path = Path(output_path)
    files = sorted(extracted_dir.glob("*.extracted.json"))
    if limit:
        files = files[:limit]

    chunks: list[ExtractedChunk] = []
    for path in tqdm(files, desc="Reading extracted chunks"):
        try:
            chunks.append(read_extracted_file(path))
        except Exception as e:
            logger.warning("Failed to read file", path=str(path), error=str(e))

    engine = TruthInferenceEngine()
    records = engine.run(chunks)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(record.model_dump_json() + "\n")

    logger.info(
        "Inference complete",
        chunks=len(chunks),
        truth_records=len(records),
        output=str(output_path),
    )
    return records


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 3:
        print("Usage: python inference.py <extracted_dir> <output_path> [limit]")
        sys.exit(1)
    run_inference(
        Path(sys.argv[1]),
        Path(sys.argv[2]),
        int(sys.argv[3]) if len(sys.argv) > 3 else None,
    )
